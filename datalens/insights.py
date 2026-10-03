"""Plain-language findings generated from the computed report.

Each insight is produced by a rule that looks at actual numbers in the report;
nothing is written unless the data supports it.
"""


def _fmt(x, digits=2):
    if x is None:
        return "n/a"
    if abs(x) >= 1000:
        return f"{x:,.0f}"
    return f"{x:,.{digits}f}"


def generate_insights(report):
    out = []
    ds, q, tc = report["dataset"], report["quality"], report["type_counts"]

    parts = [f"{tc[t]} {name}" for t, name in (("numeric", "numeric"), ("categorical", "categorical"),
                                                ("datetime", "date/time"), ("text", "free-text"),
                                                ("identifier", "ID")) if tc[t]]
    out.append({"area": "Overview", "level": "info",
                "text": f"{ds['rows']:,} rows and {ds['columns']} columns were analysed: {', '.join(parts)}."})

    # Data quality
    if q["missing_cells"] == 0:
        out.append({"area": "Data quality", "level": "good", "text": "No missing values were found."})
    else:
        worst = sorted((c for c in q["per_column"] if c["missing"]), key=lambda c: -c["missing_pct"])[:3]
        names = ", ".join(f"{c['name']} ({c['missing_pct']:.1f}%)" for c in worst)
        out.append({"area": "Data quality", "level": "warning" if q["missing_pct"] > 5 else "info",
                    "text": f"{q['missing_pct']:.1f}% of all cells are missing, spread across {q['columns_with_missing']} column(s). Most affected: {names}."})
    if q["duplicate_rows"]:
        out.append({"area": "Data quality", "level": "warning",
                    "text": f"{q['duplicate_rows']:,} row(s) ({q['duplicate_pct']:.1f}%) are exact duplicates of an earlier row."})
    else:
        out.append({"area": "Data quality", "level": "good", "text": "No duplicate rows were found."})
    invalid = [c for c in report["schema"] if c["invalid"]]
    if invalid:
        out.append({"area": "Data quality", "level": "warning",
                    "text": "Some values do not match their column's type: " +
                            ", ".join(f"{c['name']} ({c['invalid']})" for c in invalid[:4]) + "."})
    inconsistent = [c["name"] for c in report["schema"] if c.get("case_variants") or c.get("abbreviations")]
    if inconsistent:
        out.append({"area": "Data quality", "level": "warning",
                    "text": f"Possible inconsistent category spellings in: {', '.join(inconsistent[:5])}."})

    # Correlation
    corr = report["correlation"]["pearson"]
    if corr and corr["pairs"]:
        strong = [p for p in corr["pairs"] if abs(p["r"]) >= 0.5]
        if strong:
            p = strong[0]
            direction = "rise together" if p["r"] > 0 else "move in opposite directions"
            out.append({"area": "Relationships", "level": "info",
                        "text": f"The strongest linear relationship is between {p['a']} and {p['b']} (r = {p['r']:.3f}, {p['strength']}): they tend to {direction}. "
                                f"{len(strong)} pair(s) have |r| of 0.5 or more. Correlation shows association, not cause and effect."})
        else:
            p = corr["pairs"][0]
            out.append({"area": "Relationships", "level": "info",
                        "text": f"No strong linear relationships were found; the largest is {p['a']} and {p['b']} (r = {p['r']:.3f})."})

    # Distribution shape
    skewed = [(c, s["skewness"]) for c, s in report["stats"].items()
              if s.get("skewness") is not None and abs(s["skewness"]) > 1]
    if skewed:
        skewed.sort(key=lambda t: -abs(t[1]))
        out.append({"area": "Distributions", "level": "info",
                    "text": "Highly skewed columns: " + ", ".join(f"{c} ({s:+.2f})" for c, s in skewed[:4]) +
                            ". For these, the median describes a typical value better than the mean."})

    # Outliers
    flagged = [o for o in report["outliers"] if o["iqr_count"]]
    if flagged:
        top = max(flagged, key=lambda o: o["iqr_pct"])
        out.append({"area": "Outliers", "level": "warning" if top["iqr_pct"] > 5 else "info",
                    "text": f"{len(flagged)} numeric column(s) contain values outside the IQR fences. {top['column']} has the most: "
                            f"{top['iqr_count']:,} value(s) ({top['iqr_pct']:.1f}%) outside {_fmt(top['lower_bound'])} to {_fmt(top['upper_bound'])}."})
    elif report["outliers"]:
        out.append({"area": "Outliers", "level": "good", "text": "No values fall outside the IQR fences in any numeric column."})

    # Categories
    for name, c in report["categories"].items():
        if c.get("imbalanced"):
            out.append({"area": "Categories", "level": "info",
                        "text": f"{name} is dominated by one value: \"{c['mode']}\" makes up {c['mode_pct']:.1f}% of rows."})

    # Time series
    ts = report.get("timeseries")
    if ts and ts["summary"].get("trend"):
        s = ts["summary"]
        agg_word = {"sum": "total", "mean": "average", "median": "median", "min": "minimum", "max": "maximum"}.get(ts["agg"], ts["agg"])
        what = "record count" if ts["agg"] == "count" else f"{agg_word} of {ts['value']}"
        text = (f"{ts['freq_label']} {what} over {ts['date']} is {s['trend']} "
                f"from {s['start'][:10]} to {s['end'][:10]}. The highest period begins {s['peak_period'][:10]} ({_fmt(s['peak_value'])}).")
        if ts["seasonal"].get("month"):
            text += f" On average, {ts['seasonal']['month']['peak']} is the highest calendar month."
        if ts["anomalies"]:
            text += f" {len(ts['anomalies'])} period(s) stand out from the surrounding trend."
        out.append({"area": "Time series", "level": "info", "text": text})

    ids = [c["name"] for c in report["schema"] if c["type"] == "identifier"]
    if ids:
        out.append({"area": "Columns", "level": "info",
                    "text": f"Treated as identifiers and left out of statistics: {', '.join(ids[:5])}."})
    return out
