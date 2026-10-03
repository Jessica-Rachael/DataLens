"""Reading uploaded CSV files and working out what each column contains.

Steps performed on every upload:
1. Decode the bytes (UTF-8, UTF-8 with BOM, UTF-16, Windows-1252, Latin-1).
2. Detect the delimiter (comma, semicolon, tab or pipe).
3. Parse the file, skipping malformed rows and reporting how many were skipped.
4. Clean headers, trim whitespace, normalise missing-value markers.
5. Detect each column's type: numeric, datetime, categorical, text or identifier.
"""
import csv
import io
import re
import warnings

import numpy as np
import pandas as pd

MAX_FILE_MB = 50
ALLOWED_EXTENSIONS = {".csv", ".tsv", ".txt"}

# Text markers that mean "no value". Pandas already knows NA, N/A, NULL, NaN, None, etc.
EXTRA_MISSING = ["?", "-", "--", "missing", "Missing", "MISSING", "#VALUE!", "#DIV/0!", "#REF!", "nil", "Nil"]
MISSING_SET = set(EXTRA_MISSING) | {
    "", "NA", "N/A", "n/a", "na", "NaN", "nan", "NULL", "null", "None", "none", "#N/A", "<NA>",
}

DELIMITER_NAMES = {",": "comma", ";": "semicolon", "\t": "tab", "|": "pipe"}

ID_NAME = re.compile(
    r"(^|[_\s\-.])(id|uuid|guid|code|key|no|num|number)$|^(id|uuid)([_\s\-.]|$)|^(s\.?\s?no|sr\.?\s?no|serial)",
    re.IGNORECASE,
)
NUMERIC_JUNK = re.compile(r"[\s₹$€£¥%]")

DATE_FORMATS = [
    "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M",
    "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%m-%d-%Y", "%d.%m.%Y", "%Y/%m/%d",
    "%d/%m/%Y %H:%M", "%m/%d/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S",
    "%d-%m-%Y %H:%M", "%d-%m-%Y %H:%M:%S",
    "%d-%b-%Y", "%d %b %Y", "%b %d, %Y", "%d %B %Y", "%B %d, %Y", "%b %d %Y",
    "%Y-%m", "%b-%Y", "%b %Y", "%B %Y",
]


class DataLoadError(Exception):
    """Raised with a user-friendly message when a file cannot be analysed."""


# ---------------------------------------------------------------------------
# Decoding and delimiter detection
# ---------------------------------------------------------------------------
def decode_bytes(raw):
    if raw.startswith(b"PK\x03\x04"):
        raise DataLoadError(
            "This looks like an Excel (.xlsx) file, not a CSV. In Excel choose "
            "File > Save As > CSV (Comma delimited) and upload that file."
        )
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16"), "UTF-16"
    if raw[:2048].count(b"\x00") > 10:
        raise DataLoadError("This file contains binary data and is not a readable CSV text file.")
    for encoding, name in (("utf-8-sig", "UTF-8"), ("cp1252", "Windows-1252")):
        try:
            return raw.decode(encoding), name
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1"), "Latin-1"


def detect_delimiter(text):
    """Pick the delimiter that splits the first lines into the most consistent column count."""
    lines = [line for line in text.splitlines()[:200] if line.strip()]
    if not lines:
        return ","
    best, best_score = ",", -1.0
    for delim in (",", ";", "\t", "|"):
        try:
            counts = [len(row) for row in csv.reader(lines, delimiter=delim)]
        except csv.Error:
            continue
        if not counts:
            continue
        mode = max(set(counts), key=counts.count)
        if mode < 2:
            continue
        consistency = counts.count(mode) / len(counts)
        score = consistency * 1000 + mode
        if score > best_score:
            best, best_score = delim, score
    return best


def _read(text, sep, header="infer"):
    """Parse text into a DataFrame of strings. Returns (df, skipped_row_count)."""
    options = dict(
        sep=sep, dtype=str, header=0 if header == "infer" else header,
        na_values=EXTRA_MISSING, keep_default_na=True,
        skip_blank_lines=True, skipinitialspace=True,
    )
    try:
        return pd.read_csv(io.StringIO(text), engine="c", **options), 0
    except pd.errors.ParserError:
        bad_lines = []

        def keep_track(line):
            bad_lines.append(line)
            return None

        df = pd.read_csv(io.StringIO(text), engine="python", on_bad_lines=keep_track, **options)
        return df, len(bad_lines)


def _looks_numeric(value):
    try:
        float(str(value).replace(",", ""))
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Column cleaning
# ---------------------------------------------------------------------------
def _clean_headers(columns):
    names, seen = [], {}
    for i, col in enumerate(columns):
        name = str(col).strip()
        if not name or name.lower().startswith("unnamed:") or name.lower() == "nan":
            name = f"column_{i + 1}"
        name = re.sub(r"\s+", " ", name)
        base = name
        if base in seen:
            seen[base] += 1
            name = f"{base}_{seen[base]}"
        else:
            seen[base] = 1
        names.append(name)
    return names


def _to_numeric(values, decimal_comma):
    cleaned = values.astype(str).str.replace(NUMERIC_JUNK, "", regex=True)
    if decimal_comma:
        cleaned = cleaned.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    else:
        cleaned = cleaned.str.replace(",", "", regex=False)
    cleaned = cleaned.str.replace(r"^\((.*)\)$", r"-\1", regex=True)  # (500) -> -500
    parsed = pd.to_numeric(cleaned, errors="coerce").astype("float64")
    return parsed.where(np.isfinite(parsed))  # "inf" / "-inf" count as invalid


def _to_datetime(values):
    """Try to parse values as dates. Returns (parsed, format_used, ambiguous_day_month)."""
    sample = values.sample(min(len(values), 500), random_state=0) if len(values) > 500 else values
    has_digit = sample.astype(str).str.contains(r"\d", regex=True).mean()
    lengths = sample.astype(str).str.len()
    if has_digit < 0.9 or lengths.quantile(0.95) > 40 or lengths.quantile(0.05) < 4:
        return None, None, False

    scores = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for fmt in DATE_FORMATS:
            parsed = pd.to_datetime(sample, format=fmt, errors="coerce")
            scores[fmt] = parsed.notna().mean()
    best_fmt = max(DATE_FORMATS, key=lambda f: scores[f])  # ties keep list order (day-first)
    if scores[best_fmt] >= 0.9:
        ambiguous = False
        pairs = [("%d/%m/%Y", "%m/%d/%Y"), ("%d-%m-%Y", "%m-%d-%Y"),
                 ("%d/%m/%Y %H:%M", "%m/%d/%Y %H:%M"), ("%d/%m/%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S")]
        for day_first, month_first in pairs:
            if best_fmt in (day_first, month_first) and scores[day_first] >= 0.9 and scores[month_first] >= 0.9:
                ambiguous = True
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            parsed = pd.to_datetime(values, format=best_fmt, errors="coerce")
        return parsed, best_fmt, ambiguous

    # Fall back to pandas' own parser (handles ISO strings with time zones, etc.)
    parsed_sample = _fallback_parse(sample)
    if parsed_sample is None or parsed_sample.notna().mean() < 0.9:
        return None, None, False
    parsed = _fallback_parse(values)
    if parsed is None:
        return None, None, False
    try:
        if getattr(parsed.dt, "tz", None) is not None:
            parsed = parsed.dt.tz_convert(None)
    except (AttributeError, TypeError):
        return None, None, False
    return parsed, "auto-detected", False


def _fallback_parse(values):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for kwargs in ({"format": "mixed", "utc": True}, {"utc": True}, {}):
            try:
                return pd.to_datetime(values, errors="coerce", **kwargs)
            except (TypeError, ValueError, OverflowError):
                continue
    return None


def _case_variants(values):
    """Find categories that differ only by upper/lower case, e.g. Male / male / MALE."""
    groups = {}
    for raw in values.dropna().unique():
        groups.setdefault(str(raw).lower(), set()).add(str(raw))
    return [sorted(v) for v in groups.values() if len(v) > 1][:10]


def _abbreviation_candidates(values):
    """Flag short values that look like abbreviations of longer ones, e.g. M / Male."""
    uniques = [str(v) for v in values.dropna().unique()]
    if len(uniques) > 50:
        return []
    short = [u for u in uniques if 1 <= len(u) <= 2]
    longer = [u for u in uniques if len(u) > 2]
    found = []
    for s in short:
        matches = [l for l in longer if l.lower().startswith(s.lower())]
        if len(matches) == 1:
            found.append([s, matches[0]])
    return found[:10]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def load_csv(raw_bytes, filename):
    if not raw_bytes or not raw_bytes.strip():
        raise DataLoadError("The file is empty.")

    text, encoding = decode_bytes(raw_bytes)
    sep = "\t" if filename.lower().endswith(".tsv") else detect_delimiter(text)

    try:
        df, skipped = _read(text, sep)
    except pd.errors.EmptyDataError:
        raise DataLoadError("The file has no readable rows or columns.")
    except Exception as exc:  # any other parser failure
        raise DataLoadError(f"The file could not be parsed as CSV ({exc}).")

    notes = []
    header_generated = False
    if len(df.columns) > 1 and all(_looks_numeric(c) for c in df.columns):
        df, skipped = _read(text, sep, header=None)
        header_generated = True
        notes.append("The first row contained only numbers, so it was treated as data and column names were generated.")

    df.columns = [f"column_{i + 1}" for i in range(df.shape[1])] if header_generated else _clean_headers(df.columns)
    total_rows_read = len(df)

    # Trim whitespace and treat leftover missing markers as missing.
    whitespace_fixed = {}
    for col in df.columns:
        s = df[col]
        present = s.notna()
        stripped = s.where(~present, s.astype(str).str.strip())
        changed = int((present & (stripped != s)).sum())
        if changed:
            whitespace_fixed[col] = changed
        stripped = stripped.where(~stripped.isin(list(MISSING_SET)), np.nan)
        df[col] = stripped

    empty_rows = int(df.isna().all(axis=1).sum())
    df = df.loc[~df.isna().all(axis=1)]
    empty_cols = [c for c in df.columns if df[c].isna().all()]
    df = df.drop(columns=empty_cols)

    if df.shape[1] == 0 or df.shape[0] == 0:
        raise DataLoadError("The file does not contain any data rows. Check that it has a header row and at least one row of values.")

    if skipped:
        notes.append(f"{skipped} malformed row(s) with the wrong number of fields were skipped.")
    if empty_rows:
        notes.append(f"{empty_rows} completely empty row(s) were removed.")
    if empty_cols:
        notes.append(f"{len(empty_cols)} completely empty column(s) were removed: {', '.join(empty_cols[:8])}.")
    if whitespace_fixed:
        notes.append(f"Leading/trailing spaces were trimmed in {len(whitespace_fixed)} column(s).")

    decimal_comma = False
    if sep == ";":
        sample = pd.concat([df[c].dropna().head(50) for c in df.columns]).astype(str)
        if len(sample) and sample.str.match(r"^-?\d+,\d+$").mean() > 0.2:
            decimal_comma = True
            notes.append("Commas were read as decimal separators (e.g. 3,5 = 3.5).")

    converted = pd.DataFrame(index=df.index)
    schema = []
    for col in df.columns:
        info, series = _detect_column(col, df[col], decimal_comma)
        converted[col] = series
        info["whitespace_fixed"] = whitespace_fixed.get(col, 0)
        schema.append(info)

    load_report = {
        "encoding": encoding,
        "delimiter": DELIMITER_NAMES.get(sep, repr(sep)),
        "rows_read": total_rows_read,
        "rows": int(converted.shape[0]),
        "columns": int(converted.shape[1]),
        "skipped_rows": skipped,
        "empty_rows_removed": empty_rows,
        "empty_columns_removed": empty_cols,
        "header_generated": header_generated,
        "missing_markers": sorted(m for m in MISSING_SET if m),
        "notes": notes,
    }
    return converted, schema, load_report


def _detect_column(name, s, decimal_comma):
    """Return (schema_info, converted_series) for one column of strings."""
    non_null = s.dropna()
    n = len(non_null)
    info = {
        "name": name, "type": "categorical", "non_null": int(n),
        "missing": int(s.isna().sum()), "missing_pct": float(s.isna().mean() * 100),
        "invalid": 0, "invalid_examples": [], "discrete": False, "notes": [],
        "case_variants": [], "abbreviations": [],
    }

    # 1) Numeric?
    parsed = _to_numeric(non_null, decimal_comma)
    ratio = parsed.notna().mean() if n else 0
    if n and ratio >= 0.95:
        bad = non_null[parsed.isna()]
        info["invalid"] = int(len(bad))
        info["invalid_examples"] = [str(v) for v in bad.unique()[:5]]
        series = pd.Series(np.nan, index=s.index, dtype="float64")
        series.loc[parsed.index] = parsed.astype("float64")
        info["type"] = "numeric"
        if non_null.astype(str).str.contains(r"[₹$€£¥%]", regex=True).any():
            info["notes"].append("Currency or % symbols were removed to read the numbers.")
        valid = series.dropna()
        uniq = valid.nunique()
        is_int = bool(len(valid) and np.all(np.mod(valid.values, 1) == 0))
        info["unique"] = int(uniq)
        info["unique_pct"] = float(uniq / len(valid) * 100) if len(valid) else 0.0
        looks_like_row_number = (
            is_int and len(valid) > 10 and uniq == len(valid)
            and (valid.diff().dropna() == 1).all()
        )
        if (ID_NAME.search(name) and len(valid) and uniq / len(valid) > 0.9) or looks_like_row_number:
            info["type"] = "identifier"
            info["notes"].append("Looks like an ID or row number, so it is excluded from statistics and correlations.")
        elif is_int and 2 <= uniq <= 10 and len(valid) >= 20:
            info["discrete"] = True
            info["notes"].append("Whole numbers with few distinct values; also usable as a grouping column.")
        info["dtype_label"] = "Integer" if is_int else "Decimal"
        info["samples"] = [str(v) for v in non_null.unique()[:5]]
        return info, series

    # 2) Date / time?
    if n:
        parsed_dates, fmt, ambiguous = _to_datetime(non_null)
        if parsed_dates is not None:
            bad = non_null[parsed_dates.isna()]
            info["invalid"] = int(len(bad))
            info["invalid_examples"] = [str(v) for v in bad.unique()[:5]]
            series = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
            series.loc[parsed_dates.index] = parsed_dates.astype("datetime64[ns]")
            info["type"] = "datetime"
            info["dtype_label"] = "Date/time"
            info["date_format"] = fmt
            info["unique"] = int(series.nunique())
            info["unique_pct"] = float(info["unique"] / max(n, 1) * 100)
            if ambiguous:
                info["notes"].append("Day and month order is ambiguous in this column; it was read as day/month/year.")
            valid = series.dropna()
            if len(valid):
                info["min_date"] = valid.min().isoformat()
                info["max_date"] = valid.max().isoformat()
            info["samples"] = [str(v) for v in non_null.unique()[:5]]
            return info, series

    # 3) Categorical, free text or identifier
    series = s.astype(object).where(s.notna(), np.nan)
    uniq = int(non_null.nunique())
    unique_ratio = uniq / n if n else 0
    info["unique"] = uniq
    info["unique_pct"] = float(unique_ratio * 100)
    info["samples"] = [str(v) for v in non_null.unique()[:5]]
    avg_len = non_null.astype(str).str.len().mean() if n else 0
    has_spaces = non_null.astype(str).str.contains(" ").mean() if n else 0

    if n > 20 and unique_ratio > 0.95 and (ID_NAME.search(name) or (avg_len < 40 and has_spaces < 0.2)):
        info["type"] = "identifier"
        info["dtype_label"] = "Text ID"
        info["notes"].append("Every value is (almost) unique, so it is treated as an identifier.")
    elif uniq > 50 and unique_ratio > 0.5:
        info["type"] = "text"
        info["dtype_label"] = "Free text"
        info["notes"].append("Too many distinct values to chart as categories; treated as free text.")
    else:
        info["type"] = "categorical"
        info["dtype_label"] = "Category"
        info["case_variants"] = _case_variants(non_null)
        info["abbreviations"] = _abbreviation_candidates(non_null)
    if n and ratio >= 0.5 and info["type"] in ("categorical", "text"):
        info["notes"].append(f"{ratio * 100:.0f}% of values are numbers but others are not, so the column was kept as text.")
    return info, series
