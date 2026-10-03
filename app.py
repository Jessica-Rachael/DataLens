"""DataLens: An Automated Exploratory Data Analysis and Interactive Visualization Platform.

Run with:  python app.py   then open http://127.0.0.1:5000
"""
import io
import json
import os
import time
import traceback
import uuid
from collections import OrderedDict

from flask import Flask, Response, render_template, request, send_from_directory
from werkzeug.exceptions import HTTPException

from datalens import analysis
from datalens.loader import ALLOWED_EXTENSIONS, MAX_FILE_MB, DataLoadError, load_csv
from datalens.utils import to_json_safe

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAMPLE_DIR = os.path.join(BASE_DIR, "sample_data")
MAX_DATASETS_IN_MEMORY = 8

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_MB * 1024 * 1024

# Uploaded datasets live in memory for the session: {id: {...}}
DATASETS = OrderedDict()
_PLOTLY_JS = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def json_response(payload, status=200):
    return Response(json.dumps(to_json_safe(payload)), status=status, mimetype="application/json")


def log(message):
    """Print to the terminal without crashing on characters the Windows console can't show."""
    try:
        print(f"[DataLens] {message}", flush=True)
    except UnicodeEncodeError:
        print(f"[DataLens] {message}".encode("ascii", "replace").decode(), flush=True)


def error(message, status=400):
    return json_response({"error": message}, status)


def get_dataset(dataset_id):
    ds = DATASETS.get(dataset_id)
    if ds is None:
        raise LookupError("This dataset is no longer in memory (the server may have restarted). Upload the file again.")
    return ds


def require_column(ds, name, types, purpose):
    info = analysis.schema_map(ds["schema"]).get(name)
    if info is None:
        raise ValueError(f"Column '{name}' does not exist in this dataset.")
    ok = info["type"] in types or ("grouping" in types and (info["type"] == "categorical" or info.get("discrete")))
    if not ok:
        raise ValueError(f"'{name}' cannot be used as {purpose}.")
    return name


def api(fn):
    """Wrap an API route so every failure returns a clear JSON error."""
    def wrapper(*args, **kwargs):
        try:
            return json_response(fn(*args, **kwargs))
        except HTTPException:
            raise  # e.g. file too large: handled by the error handlers below
        except LookupError as exc:
            return error(str(exc), 404)
        except (ValueError, DataLoadError) as exc:
            return error(str(exc), 400)
        except Exception:  # unexpected bug: log it, show a short message
            traceback.print_exc()
            return error("Something went wrong while analysing this request. See the terminal for details.", 500)
    wrapper.__name__ = fn.__name__
    return wrapper


# ---------------------------------------------------------------------------
# Pages and static assets
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    samples = sorted(f for f in os.listdir(SAMPLE_DIR) if f.lower().endswith(".csv")) if os.path.isdir(SAMPLE_DIR) else []
    return render_template("index.html", samples=samples, max_mb=MAX_FILE_MB)


@app.route("/vendor/plotly.min.js")
def plotly_js():
    """Serve Plotly's JavaScript from the installed Python package, so no internet is needed."""
    global _PLOTLY_JS
    if _PLOTLY_JS is None:
        try:
            from plotly.offline import get_plotlyjs
            _PLOTLY_JS = get_plotlyjs()
        except ImportError:
            return Response("console.error('Plotly is not installed. Run: pip install -r requirements.txt');",
                            mimetype="application/javascript")
    resp = Response(_PLOTLY_JS, mimetype="application/javascript")
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@app.route("/samples/<path:filename>")
def sample_file(filename):
    return send_from_directory(SAMPLE_DIR, filename, as_attachment=False, mimetype="text/csv")


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------
@app.post("/api/upload")
@api
def upload():
    file = request.files.get("file")
    if file is None or not file.filename:
        raise ValueError("No file was received. Choose a CSV file and try again.")
    name = os.path.basename(file.filename)
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"'{name}' is not a CSV file. Upload a .csv, .tsv or .txt file.")
    raw = file.read()

    started = time.time()
    df, schema, load_report = load_csv(raw, name)
    dataset_id = uuid.uuid4().hex[:12]
    dataset = {"id": dataset_id, "name": name, "size_bytes": len(raw), "df": df,
               "schema": schema, "load_report": load_report}
    DATASETS[dataset_id] = dataset
    while len(DATASETS) > MAX_DATASETS_IN_MEMORY:
        DATASETS.popitem(last=False)

    report = analysis.build_report(dataset)
    report["dataset"]["seconds"] = round(time.time() - started, 2)
    log(f"Analysed {name}: {df.shape[0]} rows x {df.shape[1]} columns in {report['dataset']['seconds']}s")
    return report


@app.errorhandler(413)
def too_large(_exc):
    return error(f"The file is larger than {MAX_FILE_MB} MB. Upload a smaller CSV.", 413)


# ---------------------------------------------------------------------------
# Interactive analysis endpoints
# ---------------------------------------------------------------------------
@app.get("/api/datasets/<dataset_id>/scatter")
@api
def scatter(dataset_id):
    ds = get_dataset(dataset_id)
    x = require_column(ds, request.args.get("x", ""), ("numeric",), "the X axis")
    y = require_column(ds, request.args.get("y", ""), ("numeric",), "the Y axis")
    if x == y:
        raise ValueError("Choose two different columns for X and Y.")
    color = request.args.get("color") or None
    if color:
        require_column(ds, color, ("grouping",), "a colour group")
    return analysis.scatter(ds["df"], x, y, color)


@app.get("/api/datasets/<dataset_id>/scatter-matrix")
@api
def scatter_matrix(dataset_id):
    ds = get_dataset(dataset_id)
    cols = request.args.getlist("cols")
    if not 2 <= len(cols) <= 6:
        raise ValueError("Select between 2 and 6 numeric columns.")
    for c in cols:
        require_column(ds, c, ("numeric",), "a scatter-matrix column")
    return analysis.scatter_matrix(ds["df"], cols)


@app.get("/api/datasets/<dataset_id>/pivot")
@api
def pivot(dataset_id):
    ds = get_dataset(dataset_id)
    rows = require_column(ds, request.args.get("rows", ""), ("grouping",), "pivot rows")
    cols = request.args.get("cols") or None
    if cols:
        require_column(ds, cols, ("grouping",), "pivot columns")
        if cols == rows:
            raise ValueError("Choose different columns for rows and columns.")
    values = request.args.get("values") or None
    if values:
        require_column(ds, values, ("numeric",), "pivot values")
    return analysis.pivot(ds["df"], rows, cols, values, request.args.get("agg", "mean"))


@app.get("/api/datasets/<dataset_id>/crosstab")
@api
def crosstab(dataset_id):
    ds = get_dataset(dataset_id)
    a = require_column(ds, request.args.get("a", ""), ("grouping",), "a cross-tab row")
    b = require_column(ds, request.args.get("b", ""), ("grouping",), "a cross-tab column")
    if a == b:
        raise ValueError("Choose two different columns.")
    return analysis.crosstab(ds["df"], a, b)


@app.get("/api/datasets/<dataset_id>/timeseries")
@api
def timeseries(dataset_id):
    ds = get_dataset(dataset_id)
    date = require_column(ds, request.args.get("date", ""), ("datetime",), "a date column")
    value = request.args.get("value") or None
    if value:
        require_column(ds, value, ("numeric",), "a time-series value")
    return analysis.timeseries(ds["df"], date, value, request.args.get("agg", "sum"), request.args.get("freq", "auto"))


@app.get("/api/compare")
@api
def compare():
    a, b = get_dataset(request.args.get("a", "")), get_dataset(request.args.get("b", ""))
    return analysis.compare(a, b)


@app.get("/api/datasets/<dataset_id>/download")
def download(dataset_id):
    ds = DATASETS.get(dataset_id)
    if ds is None:
        return error("This dataset is no longer in memory. Upload the file again.", 404)
    df = ds["df"]
    if request.args.get("dedupe") == "1":
        df = df.drop_duplicates()
    buffer = io.StringIO()
    df.to_csv(buffer, index=False)
    stem = os.path.splitext(ds["name"])[0]
    return Response(buffer.getvalue().encode("utf-8-sig"), mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{stem}_cleaned.csv"'})


if __name__ == "__main__":
    print("DataLens is running. Open http://127.0.0.1:5000 in your browser. Press CTRL+C to stop.")
    app.run(host="127.0.0.1", port=5000, debug=False)
