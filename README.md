# DataLens
### An Automated Exploratory Data Analysis and Interactive Visualization Platform

DataLens is a web application that takes a raw CSV file and automatically performs
exploratory data analysis (EDA) on it: it profiles the dataset, checks data quality,
computes statistics, chooses suitable charts for each column type, analyses
relationships between variables, detects outliers, analyses time trends when a date
column exists, and summarises its findings in plain language.

## Problem statement

Many beginners and non-technical users have datasets but lack the technical knowledge
required to perform systematic exploratory data analysis. Existing analytics tools can
also require considerable configuration or learning. DataLens provides a simplified
workflow that automatically profiles an uploaded dataset, identifies its
characteristics, performs standard EDA techniques, generates appropriate
visualizations, detects potential data-quality issues and outliers, and presents the
findings through a single interactive dashboard.

## Technology

| Layer | Technology |
|---|---|
| Backend / web server | Python, Flask |
| Data processing | Pandas, NumPy |
| Statistical tests | SciPy (correlation p-values, chi-square test) |
| Charts | Plotly.js (served offline from the installed `plotly` package) |
| Frontend | HTML, CSS, JavaScript (no framework) |

## Setup (Windows, VS Code terminal / PowerShell)

```powershell
cd datalens
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python self_test.py
python app.py
```

Then open http://127.0.0.1:5000 in a browser.

If PowerShell blocks the activate script, run this once and try again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

## Setup (macOS / Linux)

```bash
cd datalens
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python self_test.py
python app.py
```

## Project files

| Path | Purpose |
|---|---|
| `app.py` | Flask server: page, upload API, interactive analysis APIs, download, compare |
| `datalens/loader.py` | Robust CSV reading: encoding, delimiter, bad rows, headers, missing markers, column-type detection |
| `datalens/analysis.py` | EDA engine: statistics, distributions, data quality, outliers, correlation, scatter, pivot, cross-tab, time series, comparison |
| `datalens/insights.py` | Rule-based automatic insights written from the computed numbers |
| `datalens/utils.py` | JSON-safe conversion and small helpers |
| `templates/index.html` | Dashboard page structure |
| `static/css/style.css` | Styling (screen and print/PDF) |
| `static/js/app.js` | Upload, rendering of all charts/tables, interactive controls |
| `sample_data/*.csv` | Three synthetic demo datasets (generated, not real data) |
| `generate_samples.py` | Script that regenerates the sample datasets |
| `self_test.py` | Automated check of every feature on your machine |
| `requirements.txt` | Python packages |
| `.vscode/launch.json` | "Run DataLens" configuration for the VS Code Run button |

## Features

1. **Upload** – drag-and-drop or browse, with progress bar; up to 50 MB.
   Handles UTF-8 / UTF-8 with BOM / UTF-16 / Windows-1252 / Latin-1 encodings,
   comma / semicolon / tab / pipe delimiters, decimal commas, currency symbols,
   thousands separators, files without a header row, malformed rows (skipped and
   counted), and markers such as `?`, `NA`, `-`, `missing`. Excel files, images and
   empty files are rejected with a clear message.
2. **Automatic profiling** – each column is classified as numeric (continuous or
   discrete), categorical, date/time, identifier or free text.
3. **Data quality** – missing values, duplicate rows, invalid entries in numeric or
   date columns, inconsistent spellings (e.g. `M` / `Male` / `male`), constant
   columns, duplicate IDs, extra whitespace. A cleaned CSV can be downloaded.
4. **Statistical EDA** – mean, median, mode, standard deviation, variance, min, max,
   quartiles, 5th/95th percentiles, IQR, skewness, kurtosis.
5. **Automatic visualisation** – histogram + box plot for numeric columns, bar chart
   (and pie chart when there are few categories) for categorical columns,
   heatmap for correlations, line chart for time series.
6. **Correlation analysis** – Pearson and Spearman matrices, strongest pairs ranked.
7. **Multivariate analysis** – scatter explorer (choose X, Y and colour group; shows
   r, Spearman rho, R², slope, p-value, trend line), scatter matrix, pivot tables.
8. **Cross-tabulation** – contingency table with chi-square test and Cramér's V.
9. **Time-series analysis** – daily / weekly / monthly / quarterly / yearly
   resampling, moving average, trend, peak and lowest periods, unusual periods,
   seasonal patterns by month, weekday and hour.
10. **Outlier detection** – IQR method and Z-score method, with row numbers of the
    most extreme values.
11. **Automatic insights** – short findings generated from the actual numbers.
12. **Dataset comparison** – compare two uploaded datasets (e.g. 2025 vs 2026).
13. **Export** – print or save the report as PDF from the browser.

## Notes for the viva

* DataLens reports **association**, not causation. A strong correlation only means two
  variables move together in the uploaded data.
* Outliers are flagged as **potential** outliers – they may be errors or genuine
  extreme values; the user decides.
* The insights are rule-based: every sentence is produced from a computed number,
  nothing is pre-written for a particular dataset.
* The sample datasets are synthetic (generated by `generate_samples.py`) and contain
  deliberate problems (duplicates, "absent" in a marks column, `M`/`male` variants,
  outlier orders) so the data-quality features can be demonstrated.
* Uploaded data is kept only in the server's memory while `app.py` runs (the last 8
  datasets); nothing is written to disk or sent anywhere.
