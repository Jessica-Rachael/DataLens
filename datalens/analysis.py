"""The EDA engine. Every number shown in the dashboard is computed here from the uploaded data."""
import math
import warnings

import numpy as np
import pandas as pd

from .utils import label, round_or_none, top_n_labels

try:  # SciPy is only used for p-values; everything else works without it.
    from scipy import stats as scipy_stats
except Exception:  # pragma: no cover
    scipy_stats = None

MAX_POINTS = 4000          # max points drawn in a scatter plot
MAX_CORR_COLUMNS = 25      # max columns in the correlation heatmap
TOP_CATEGORIES = 15        # categories shown before grouping into "Other"
MAX_PERIODS = 5000         # max points in a time-series chart


# ---------------------------------------------------------------------------
# Column helpers
# ---------------------------------------------------------------------------
def columns_of(schema, *types):
    return [c["name"] for c in schema if c["type"] in types]


def grouping_columns(schema):
    """Categorical columns plus whole-number columns with few values (e.g. rating 1-5)."""
    return [c["name"] for c in schema if c["type"] == "categorical" or (c["type"] == "numeric" and c.get("discrete"))]


def schema_map(schema):
    return {c["name"]: c for c in schema}


# ---------------------------------------------------------------------------
# Statistics and distributions
# ---------------------------------------------------------------------------
def skew_label(skew):
    if skew is None or (isinstance(skew, float) and math.isnan(skew)):
        return "not enough data"
    a = abs(skew)
    side = "right" if skew > 0 else "left"
    if a < 0.5:
        return "approximately symmetric"
    if a < 1:
        return f"moderately {side}-skewed"
    return f"highly {side}-skewed"


def describe_numeric(s):
    v = s.dropna().astype(float)
    n = len(v)
    result = {"count": n, "missing": int(s.isna().sum())}
    if n == 0:
        return result
    q = v.quantile([0.05, 0.25, 0.5, 0.75, 0.95])
    modes = v.mode()
    mode = float(modes.iloc[0]) if len(modes) else None
    mode_count = int((v == mode).sum()) if mode is not None else 0
    mean = float(v.mean())
    std = float(v.std()) if n > 1 else float("nan")
    skew = float(v.skew()) if n > 2 else float("nan")
    kurt = float(v.kurt()) if n > 3 else float("nan")
    result.update({
        "mean": mean, "median": float(q[0.5]),
        "mode": mode if mode_count > 1 else None, "mode_count": mode_count,
        "std": std, "variance": float(v.var()) if n > 1 else float("nan"),
        "min": float(v.min()), "p5": float(q[0.05]), "q1": float(q[0.25]),
        "q3": float(q[0.75]), "p95": float(q[0.95]), "max": float(v.max()),
        "iqr": float(q[0.75] - q[0.25]), "range": float(v.max() - v.min()),
        "skewness": skew, "kurtosis": kurt, "skew_label": skew_label(skew),
        "cv_pct": (std / abs(mean) * 100) if mean != 0 and not math.isnan(std) else None,
        "zeros": int((v == 0).sum()), "negatives": int((v < 0).sum()),
        "unique": int(v.nunique()), "sum": float(v.sum()),
    })
    return result


def histogram(s):
    v = s.dropna().astype(float).values
    if len(v) == 0:
        return None
    uniq = np.unique(v)
    if len(uniq) == 1 or (len(uniq) <= 25 and np.all(np.mod(uniq, 1) == 0)):
        counts = pd.Series(v).value_counts().sort_index()
        return {"kind": "discrete", "x": counts.index.tolist(), "y": counts.values.tolist()}
    n = len(v)
    q1, q3 = np.percentile(v, [25, 75])
    width = 2 * (q3 - q1) / (n ** (1 / 3))  # Freedman-Diaconis rule
    data_range = v.max() - v.min()
    bins = int(math.ceil(data_range / width)) if width > 0 else int(math.ceil(math.log2(n) + 1))
    bins = int(min(max(bins, 10), 60))
    counts, edges = np.histogram(v, bins=bins)
    return {
        "kind": "bins",
        "centers": ((edges[:-1] + edges[1:]) / 2).tolist(),
        "counts": counts.tolist(),
        "edges": edges.tolist(),
        "width": float(edges[1] - edges[0]),
    }


def box_stats(s, max_points=300):
    v = s.dropna().astype(float)
    if len(v) == 0:
        return None
    q1, med, q3 = v.quantile([0.25, 0.5, 0.75])
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    inside = v[(v >= lo) & (v <= hi)]
    out = v[(v < lo) | (v > hi)]
    shown = out
    if len(out) > max_points:
        extremes = pd.concat([out.nsmallest(5), out.nlargest(5)])
        shown = pd.concat([extremes, out.drop(extremes.index).sample(max_points - 10, random_state=0)])
    return {
        "q1": float(q1), "median": float(med), "q3": float(q3), "mean": float(v.mean()),
        "lowerfence": float(inside.min()) if len(inside) else float(q1),
        "upperfence": float(inside.max()) if len(inside) else float(q3),
        "outliers": shown.tolist(), "outlier_count": int(len(out)),
    }


def categorical_summary(s):
    labelled = s.dropna().map(label)
    vc = labelled.value_counts()
    total = int(vc.sum())
    top = vc.head(TOP_CATEGORIES)
    other = total - int(top.sum())
    labels = list(top.index) + ([f"Other ({len(vc) - TOP_CATEGORIES} more)"] if other > 0 else [])
    counts = [int(x) for x in top.values] + ([other] if other > 0 else [])
    result = {
        "total": total, "missing": int(s.isna().sum()), "unique": int(len(vc)),
        "labels": labels, "counts": counts,
        "percents": [c / total * 100 for c in counts] if total else [],
        "allow_pie": 2 <= len(vc) <= 8,
    }
    if total:
        result["mode"] = str(vc.index[0])
        result["mode_pct"] = float(vc.iloc[0] / total * 100)
        result["rarest"] = str(vc.index[-1])
        result["rarest_count"] = int(vc.iloc[-1])
        result["imbalanced"] = bool(len(vc) > 1 and vc.iloc[0] / total > 0.8)
    return result


# ---------------------------------------------------------------------------
# Data quality
# ---------------------------------------------------------------------------
def data_quality(df, schema):
    rows, cols = df.shape
    total_cells = rows * cols
    missing_cells = int(sum(c["missing"] for c in schema))
    dup_mask = df.duplicated(keep="first")
    dup_rows = int(dup_mask.sum())
    dup_examples = [int(i) + 1 for i in df.index[dup_mask][:10]]

    per_column = [{
        "name": c["name"], "type": c["type"], "missing": c["missing"], "missing_pct": c["missing_pct"],
        "invalid": c["invalid"], "invalid_examples": c["invalid_examples"],
    } for c in schema]

    issues = []
    for c in schema:
        if c["missing_pct"] >= 40:
            issues.append({"level": "warning", "column": c["name"],
                           "text": f"{c['missing_pct']:.1f}% of values are missing."})
        if c["invalid"]:
            examples = ", ".join(f'"{e}"' for e in c["invalid_examples"][:3])
            kind = "numbers" if c["type"] == "numeric" else "dates"
            issues.append({"level": "warning", "column": c["name"],
                           "text": f"{c['invalid']} value(s) could not be read as {kind} (e.g. {examples}). They are treated as missing."})
        for group in c.get("case_variants", []):
            issues.append({"level": "warning", "column": c["name"],
                           "text": "Same value written with different capitalisation: " + ", ".join(f'"{g}"' for g in group) + "."})
        for short, long_ in c.get("abbreviations", []):
            issues.append({"level": "info", "column": c["name"],
                           "text": f'"{short}" may be an abbreviation of "{long_}". Check whether they mean the same thing.'})
        if c.get("unique") == 1 and c["non_null"] > 1:
            issues.append({"level": "info", "column": c["name"],
                           "text": "Every row has the same value, so this column carries no information."})
        if c["type"] == "identifier":
            dup_ids = int(df[c["name"]].dropna().duplicated().sum())
            if dup_ids:
                issues.append({"level": "warning", "column": c["name"],
                               "text": f"{dup_ids} repeated value(s) in an ID column; IDs are usually unique."})
        if c.get("whitespace_fixed"):
            issues.append({"level": "info", "column": c["name"],
                           "text": f"{c['whitespace_fixed']} value(s) had extra spaces, which were trimmed."})

    return {
        "rows": rows, "columns": cols, "total_cells": total_cells, "missing_cells": missing_cells,
        "missing_pct": missing_cells / total_cells * 100 if total_cells else 0,
        "completeness_pct": 100 - (missing_cells / total_cells * 100 if total_cells else 0),
        "columns_with_missing": sum(1 for c in schema if c["missing"] > 0),
        "duplicate_rows": dup_rows, "duplicate_pct": dup_rows / rows * 100 if rows else 0,
        "duplicate_examples": dup_examples,
        "per_column": per_column, "issues": issues,
    }


# ---------------------------------------------------------------------------
# Outliers
# ---------------------------------------------------------------------------
def outliers(df, numeric):
    table = []
    for col in numeric:
        v = df[col].dropna().astype(float)
        if len(v) < 4:
            continue
        q1, q3 = v.quantile([0.25, 0.75])
        iqr = q3 - q1
        lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        iqr_mask = (v < lo) | (v > hi)
        std = v.std()
        z_mask = ((v - v.mean()).abs() / std > 3) if std > 0 else pd.Series(False, index=v.index)
        flagged = v[iqr_mask | z_mask]
        extremes = flagged.reindex(flagged.sub(v.median()).abs().sort_values(ascending=False).index).head(5)
        table.append({
            "column": col, "count": int(len(v)),
            "lower_bound": float(lo), "upper_bound": float(hi),
            "iqr_count": int(iqr_mask.sum()), "iqr_pct": float(iqr_mask.mean() * 100),
            "z_count": int(z_mask.sum()), "z_pct": float(z_mask.mean() * 100),
            "both_count": int((iqr_mask & z_mask).sum()),
            "extremes": [{"row": int(i) + 1, "value": float(val)} for i, val in extremes.items()],
        })
    return table


# ---------------------------------------------------------------------------
# Correlation
# ---------------------------------------------------------------------------
def strength(r):
    if r is None or math.isnan(r):
        return "undefined"
    a = abs(r)
    direction = "positive" if r > 0 else "negative"
    if a >= 0.7:
        return f"strong {direction}"
    if a >= 0.4:
        return f"moderate {direction}"
    if a >= 0.2:
        return f"weak {direction}"
    return "very weak / none"


def correlation(df, numeric, method="pearson"):
    usable = [c for c in numeric if df[c].notna().sum() >= 3 and (df[c].std(skipna=True) or 0) > 0]
    truncated = False
    if len(usable) > MAX_CORR_COLUMNS:
        keep = set(sorted(usable, key=lambda c: -df[c].notna().sum())[:MAX_CORR_COLUMNS])
        usable = [c for c in usable if c in keep]
        truncated = True
    if len(usable) < 2:
        return None
    matrix = df[usable].corr(method=method, min_periods=3)
    pairs = []
    for i, a in enumerate(usable):
        for b in usable[i + 1:]:
            r = matrix.loc[a, b]
            if pd.isna(r):
                continue
            n = int((df[a].notna() & df[b].notna()).sum())
            pairs.append({"a": a, "b": b, "r": float(r), "n": n, "strength": strength(float(r))})
    pairs.sort(key=lambda p: -abs(p["r"]))
    return {
        "method": method, "columns": usable,
        "matrix": [[round_or_none(x) for x in row] for row in matrix.values],
        "pairs": pairs[:30], "truncated": truncated,
    }


# ---------------------------------------------------------------------------
# Multivariate analysis
# ---------------------------------------------------------------------------
def scatter(df, x, y, color=None):
    cols = [x, y] + ([color] if color else [])
    d = df[cols].dropna(subset=[x, y])
    n = len(d)
    if n < 3:
        raise ValueError("Fewer than 3 rows have values in both columns.")
    xs, ys = d[x].astype(float), d[y].astype(float)
    r = xs.corr(ys)
    rho = xs.corr(ys, method="spearman")
    slope = intercept = p_value = None
    if xs.std() > 0 and ys.std() > 0:
        slope, intercept = np.polyfit(xs, ys, 1)
        if scipy_stats is not None:
            p_value = float(scipy_stats.pearsonr(xs, ys)[1])
    sampled = n > MAX_POINTS
    shown = d.sample(MAX_POINTS, random_state=42) if sampled else d

    groups = []
    if color:
        labelled, order = top_n_labels(shown[color], 10)
        for g in order:
            part = shown[labelled == g]
            if len(part):
                groups.append({"name": g, "x": part[x].tolist(), "y": part[y].tolist()})
    else:
        groups.append({"name": "Rows", "x": shown[x].tolist(), "y": shown[y].tolist()})

    trend = None
    if slope is not None:
        x0, x1 = float(xs.min()), float(xs.max())
        trend = {"x": [x0, x1], "y": [slope * x0 + intercept, slope * x1 + intercept]}
    return {
        "x": x, "y": y, "color": color, "n": n, "sampled": sampled, "shown": len(shown),
        "pearson": round_or_none(r), "spearman": round_or_none(rho),
        "r_squared": round_or_none(r * r if r is not None and not pd.isna(r) else None),
        "slope": round_or_none(slope, 6), "intercept": round_or_none(intercept, 6),
        "p_value": p_value, "strength": strength(float(r)) if not pd.isna(r) else "undefined",
        "groups": groups, "trend": trend,
    }


def scatter_matrix(df, columns, max_rows=1500):
    d = df[columns].dropna()
    if len(d) < 3:
        raise ValueError("Fewer than 3 rows have values in all selected columns.")
    sampled = len(d) > max_rows
    shown = d.sample(max_rows, random_state=42) if sampled else d
    return {
        "columns": columns, "n": int(len(d)), "shown": int(len(shown)), "sampled": sampled,
        "dimensions": [{"label": c, "values": shown[c].tolist()} for c in columns],
    }


def pivot(df, rows, cols=None, values=None, agg="mean"):
    if agg not in ("mean", "sum", "median", "min", "max", "count"):
        raise ValueError("Unknown aggregation.")
    work = pd.DataFrame(index=df.index)
    work["r"], row_order = top_n_labels(df[rows], 20)
    group_keys = ["r"]
    col_order = None
    if cols:
        work["c"], col_order = top_n_labels(df[cols], 10)
        group_keys.append("c")
    if values and agg != "count":
        work["v"] = df[values].astype(float)
        grouped = work.groupby(group_keys)["v"].agg(agg)
        counts = work.groupby(group_keys)["v"].count()
    else:
        grouped = work.groupby(group_keys).size()
        counts = grouped
        agg = "count"
    if cols:
        table = grouped.unstack("c").reindex(index=row_order, columns=col_order)
        count_table = counts.unstack("c").reindex(index=row_order, columns=col_order)
        return {
            "rows": rows, "cols": cols, "values": values, "agg": agg,
            "row_labels": row_order, "col_labels": col_order,
            "matrix": [[round_or_none(x) for x in r] for r in table.values],
            "counts": [[0 if pd.isna(x) else int(x) for x in r] for r in count_table.values],
        }
    series = grouped.reindex(row_order)
    count_series = counts.reindex(row_order)
    return {
        "rows": rows, "cols": None, "values": values, "agg": agg,
        "row_labels": row_order, "col_labels": None,
        "matrix": [[round_or_none(x)] for x in series.values],
        "counts": [[0 if pd.isna(x) else int(x)] for x in count_series.values],
    }


def crosstab(df, a, b):
    d = df[[a, b]].dropna()
    if len(d) == 0:
        raise ValueError("No rows have values in both columns.")
    la, order_a = top_n_labels(d[a], TOP_CATEGORIES)
    lb, order_b = top_n_labels(d[b], 12)
    ct = pd.crosstab(la, lb).reindex(index=order_a, columns=order_b, fill_value=0)
    observed = ct.values.astype(float)
    total = observed.sum()
    row_sum = observed.sum(axis=1, keepdims=True)
    col_sum = observed.sum(axis=0, keepdims=True)
    expected = row_sum @ col_sum / total
    result = {
        "a": a, "b": b, "n": int(total), "row_labels": order_a, "col_labels": order_b,
        "counts": ct.values.tolist(),
        "row_totals": row_sum.ravel().astype(int).tolist(),
        "col_totals": col_sum.ravel().astype(int).tolist(),
        "row_pct": (observed / np.where(row_sum == 0, 1, row_sum) * 100).round(2).tolist(),
        "chi2": None, "dof": None, "p_value": None, "cramers_v": None,
    }
    r, c = observed.shape
    if r >= 2 and c >= 2:
        with np.errstate(divide="ignore", invalid="ignore"):
            chi2 = float(np.nansum(np.where(expected > 0, (observed - expected) ** 2 / expected, 0)))
        dof = (r - 1) * (c - 1)
        result.update({
            "chi2": chi2, "dof": dof,
            "cramers_v": math.sqrt(chi2 / (total * (min(r, c) - 1))) if total else None,
            "low_expected_pct": float((expected < 5).mean() * 100),
        })
        if scipy_stats is not None:
            result["p_value"] = float(scipy_stats.chi2.sf(chi2, dof))
    return result


# ---------------------------------------------------------------------------
# Time series
# ---------------------------------------------------------------------------
FREQ_LABELS = {"D": "Daily", "W": "Weekly", "M": "Monthly", "Q": "Quarterly", "Y": "Yearly"}
MA_WINDOW = {"D": 7, "W": 4, "M": 3, "Q": 4, "Y": 3}
MA_UNIT = {"D": "day", "W": "week", "M": "month", "Q": "quarter", "Y": "year"}


def _freq_alias(code):
    """Pandas 2.2+ uses 'ME'/'QE'/'YE'; older versions use 'M'/'Q'/'A'."""
    new = {"D": "D", "W": "W", "M": "ME", "Q": "QE", "Y": "YE"}[code]
    old = {"D": "D", "W": "W", "M": "M", "Q": "Q", "Y": "A"}[code]
    try:
        pd.tseries.frequencies.to_offset(new)
        return new
    except ValueError:
        return old


def _auto_freq(span_days):
    if span_days <= 92:
        return "D"
    if span_days <= 730:
        return "W"
    if span_days <= 365 * 15:
        return "M"
    return "Y"


def _to_period_start(index, freq):
    """Label each resampled period by its first day (pandas labels months/weeks by their last day)."""
    if freq == "D":
        return index
    for code in ({"W": "W", "M": "M", "Q": "Q", "Y": "Y"}[freq], {"Y": "A"}.get(freq)):
        if not code:
            continue
        try:
            return index.to_period(code).start_time
        except (ValueError, TypeError):
            continue
    return index


def _resample(series, freq, agg):
    alias = _freq_alias(freq)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        counts = series.resample(alias).size() if agg == "count" else series.resample(alias).count()
        values = counts.astype(float) if agg == "count" else series.resample(alias).agg(agg)
    values = values.where(counts > 0) if agg != "count" else values
    values.index = _to_period_start(values.index, freq)
    counts.index = values.index
    return values, counts


AMOUNT_NAME = ("amount", "sales", "revenue", "total", "profit", "cost", "spend", "income", "units", "quantity", "qty", "count")


def default_timeseries_value(schema):
    """Pick a sensible default measure: an amount-like column is summed, otherwise the first continuous column is averaged."""
    numeric = [c for c in schema if c["type"] == "numeric" and not c.get("discrete")]
    for word in AMOUNT_NAME:
        for c in numeric:
            if word in c["name"].lower():
                return c["name"], "sum"
    if numeric:
        return numeric[0]["name"], "mean"
    return None, "count"


def timeseries(df, date_col, value_col=None, agg="sum", freq="auto"):
    if agg not in ("sum", "mean", "median", "min", "max", "count"):
        raise ValueError("Unknown aggregation.")
    dates = df[date_col]
    if value_col:
        frame = pd.DataFrame({"date": dates, "v": df[value_col].astype(float)})
    else:
        frame = pd.DataFrame({"date": dates, "v": 1.0})
        agg = "count"
    missing_dates = int(frame["date"].isna().sum())
    frame = frame.dropna(subset=["date"])
    missing_values = int(frame["v"].isna().sum()) if value_col else 0
    if value_col:
        frame = frame.dropna(subset=["v"])
    if len(frame) < 2:
        raise ValueError("Not enough rows with a valid date to build a time series.")

    start, end = frame["date"].min(), frame["date"].max()
    span_days = max((end - start).days, 0)
    if freq == "auto":
        freq = _auto_freq(span_days)
    if freq not in FREQ_LABELS:
        raise ValueError("Unknown frequency.")
    approx_periods = {"D": span_days, "W": span_days / 7, "M": span_days / 30, "Q": span_days / 91, "Y": span_days / 365}[freq]
    if approx_periods > MAX_PERIODS:
        raise ValueError(f"{FREQ_LABELS[freq]} resolution would create about {int(approx_periods):,} points. Choose a coarser frequency.")

    s = frame.set_index("date")["v"].sort_index()
    values, counts = _resample(s, freq, agg)
    window = MA_WINDOW[freq]
    moving_avg = values.rolling(window, min_periods=1).mean()
    valid = values.dropna()

    summary = {"periods": int(len(values)), "periods_with_data": int(len(valid)),
               "empty_periods": int((counts == 0).sum()), "start": start.isoformat(), "end": end.isoformat(),
               "span_days": span_days, "records_used": int(len(frame)),
               "missing_dates": missing_dates, "missing_values": missing_values}
    if len(valid):
        summary.update({
            "peak_period": valid.idxmax().isoformat(), "peak_value": float(valid.max()),
            "low_period": valid.idxmin().isoformat(), "low_value": float(valid.min()),
            "average": float(valid.mean()),
        })
    if len(valid) >= 3:
        positions = np.arange(len(valid))
        slope = float(np.polyfit(positions, valid.values, 1)[0])
        fitted_change = slope * (len(valid) - 1)
        base = abs(valid.mean()) or 1.0
        rel = fitted_change / base * 100
        direction = "roughly flat" if abs(rel) < 5 else ("increasing" if slope > 0 else "decreasing")
        first, last = float(valid.iloc[0]), float(valid.iloc[-1])
        summary.update({
            "trend": direction, "trend_slope_per_period": slope, "trend_change_pct_of_mean": rel,
            "first_value": first, "last_value": last,
            "first_to_last_pct": ((last - first) / abs(first) * 100) if first != 0 else None,
        })

    anomalies = []
    if len(valid) >= 8:
        baseline = valid.rolling(window * 2 + 1, center=True, min_periods=3).median()
        resid = valid - baseline
        mad = (resid - resid.median()).abs().median()
        if mad and mad > 0:
            robust_z = 0.6745 * (resid - resid.median()) / mad
            threshold = 3.5
        else:
            sd = resid.std()
            robust_z = (resid - resid.mean()) / sd if sd and sd > 0 else resid * 0
            threshold = 3.0
        for idx in robust_z[robust_z.abs() > threshold].index[:25]:
            anomalies.append({"period": idx.isoformat(), "value": float(valid[idx]),
                              "expected": float(baseline[idx]), "direction": "above" if resid[idx] > 0 else "below"})

    seasonal = {}
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    monthly, _ = _resample(s, "M", agg)
    monthly = monthly.dropna()
    if len(monthly) >= 12:
        by_month = monthly.groupby(monthly.index.month).mean()
        seasonal["month"] = {"labels": [month_names[m - 1] for m in by_month.index],
                             "values": by_month.values.tolist(),
                             "description": f"Average monthly {agg} for each calendar month"}
    daily, _ = _resample(s, "D", agg) if span_days <= 365 * 30 else (pd.Series(dtype=float), None)
    daily = daily.dropna()
    if len(daily) >= 14 and daily.index.dayofweek.nunique() == 7:
        by_dow = daily.groupby(daily.index.dayofweek).mean()
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        seasonal["weekday"] = {"labels": [days[d] for d in by_dow.index], "values": by_dow.values.tolist(),
                               "description": f"Average daily {agg} for each day of the week"}
    if frame["date"].dt.hour.nunique() > 1:
        by_hour = frame.groupby(frame["date"].dt.hour)["v"]
        hour_values = by_hour.size() if agg == "count" else by_hour.agg(agg)
        seasonal["hour"] = {"labels": [f"{h:02d}:00" for h in hour_values.index], "values": hour_values.values.tolist(),
                            "description": ("Number of records" if agg == "count" else f"{agg.capitalize()} of values") + " by hour of day (all dates combined)"}
    for key, block in seasonal.items():
        if block["values"]:
            i = int(np.nanargmax(block["values"]))
            block["peak"] = block["labels"][i]

    return {
        "date": date_col, "value": value_col, "agg": agg, "freq": freq, "freq_label": FREQ_LABELS[freq],
        "ma_window": window, "ma_label": f"{window}-{MA_UNIT[freq]} moving average",
        "x": [i.isoformat() for i in values.index], "y": values.tolist(),
        "ma": moving_avg.tolist(), "counts": [int(c) for c in counts.values],
        "summary": summary, "anomalies": anomalies, "seasonal": seasonal,
    }


# ---------------------------------------------------------------------------
# Comparing two datasets
# ---------------------------------------------------------------------------
def compare(ds_a, ds_b):
    df_a, df_b = ds_a["df"], ds_b["df"]
    sa, sb = schema_map(ds_a["schema"]), schema_map(ds_b["schema"])
    common = [c for c in sa if c in sb]
    numeric_rows, category_rows, type_mismatch = [], [], []
    for c in common:
        ta, tb = sa[c]["type"], sb[c]["type"]
        if ta != tb:
            type_mismatch.append({"column": c, "type_a": ta, "type_b": tb})
            continue
        if ta == "numeric":
            a, b = describe_numeric(df_a[c]), describe_numeric(df_b[c])
            mean_a, mean_b = a.get("mean"), b.get("mean")
            change = ((mean_b - mean_a) / abs(mean_a) * 100) if mean_a not in (None, 0) and mean_b is not None else None
            numeric_rows.append({
                "column": c, "mean_a": mean_a, "mean_b": mean_b, "mean_change_pct": change,
                "median_a": a.get("median"), "median_b": b.get("median"),
                "std_a": a.get("std"), "std_b": b.get("std"),
                "missing_pct_a": sa[c]["missing_pct"], "missing_pct_b": sb[c]["missing_pct"],
            })
        elif ta == "categorical":
            ca, cb = categorical_summary(df_a[c]), categorical_summary(df_b[c])
            set_a = set(df_a[c].dropna().map(label))
            set_b = set(df_b[c].dropna().map(label))
            new = sorted(set_b - set_a)
            gone = sorted(set_a - set_b)
            category_rows.append({
                "column": c, "unique_a": ca["unique"], "unique_b": cb["unique"],
                "top_a": ca.get("mode"), "top_a_pct": ca.get("mode_pct"),
                "top_b": cb.get("mode"), "top_b_pct": cb.get("mode_pct"),
                "new_in_b": new[:8], "new_count": len(new), "missing_in_b": gone[:8], "missing_count": len(gone),
            })

    def overview(ds):
        df, schema = ds["df"], ds["schema"]
        cells = df.shape[0] * df.shape[1]
        return {"name": ds["name"], "rows": int(df.shape[0]), "columns": int(df.shape[1]),
                "missing_pct": sum(c["missing"] for c in schema) / cells * 100 if cells else 0,
                "duplicates": int(df.duplicated().sum())}

    return {
        "a": overview(ds_a), "b": overview(ds_b),
        "common": common, "only_a": [c for c in sa if c not in sb], "only_b": [c for c in sb if c not in sa],
        "type_mismatch": type_mismatch, "numeric": numeric_rows, "categorical": category_rows,
    }


# ---------------------------------------------------------------------------
# Full report built right after upload
# ---------------------------------------------------------------------------
def build_report(dataset):
    df, schema = dataset["df"], dataset["schema"]
    numeric = columns_of(schema, "numeric")
    categorical = columns_of(schema, "categorical")
    datetimes = columns_of(schema, "datetime")
    groupable = grouping_columns(schema)

    stats = {c: describe_numeric(df[c]) for c in numeric}
    distributions = {c: {"histogram": histogram(df[c]), "box": box_stats(df[c])} for c in numeric}
    categories = {c: categorical_summary(df[c]) for c in categorical}
    for c in columns_of(schema, "numeric"):
        if schema_map(schema)[c].get("discrete"):
            categories[c] = categorical_summary(df[c])

    corr = {"pearson": correlation(df, numeric, "pearson"), "spearman": correlation(df, numeric, "spearman")}

    ts_default = None
    ts_error = None
    if datetimes:
        date_col = max(datetimes, key=lambda c: df[c].notna().sum())
        try:
            value_col, agg = default_timeseries_value(schema)
            ts_default = timeseries(df, date_col, value_col, agg, "auto")
        except ValueError as exc:
            ts_error = str(exc)

    preview_rows = []
    for _, row in df.head(50).iterrows():
        cells = []
        for c in df.columns:
            v = row[c]
            if pd.isna(v):
                cells.append(None)
            elif isinstance(v, pd.Timestamp):
                cells.append(v.strftime("%Y-%m-%d %H:%M") if (v.hour or v.minute) else v.strftime("%Y-%m-%d"))
            else:
                cells.append(label(v))
        preview_rows.append(cells)

    report = {
        "dataset": {"id": dataset["id"], "name": dataset["name"], "size_bytes": dataset["size_bytes"],
                    "rows": int(df.shape[0]), "columns": int(df.shape[1])},
        "load": dataset["load_report"],
        "schema": schema,
        "type_counts": {t: sum(1 for c in schema if c["type"] == t) for t in ("numeric", "categorical", "datetime", "text", "identifier")},
        "columns": {"numeric": numeric, "categorical": categorical, "datetime": datetimes, "groupable": groupable,
                    "all": list(df.columns)},
        "preview": {"columns": list(df.columns), "rows": preview_rows},
        "quality": data_quality(df, schema),
        "stats": stats,
        "distributions": distributions,
        "categories": categories,
        "correlation": corr,
        "outliers": outliers(df, numeric),
        "timeseries": ts_default,
        "timeseries_error": ts_error,
    }
    from .insights import generate_insights  # local import avoids a circular import
    report["insights"] = generate_insights(report)
    return report
