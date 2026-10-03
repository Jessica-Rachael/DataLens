"""Checks that DataLens works on this computer.

Run:  python self_test.py
It uploads the sample files and a set of deliberately messy CSVs through the real
upload route and every analysis route, then prints PASS or FAIL for each check.
"""
import io
import sys

from app import app

client = app.test_client()
results = []


def check(name, condition, detail=""):
    results.append(condition)
    print(f"{'PASS' if condition else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not condition else ""))


def upload(filename, content):
    data = {"file": (io.BytesIO(content), filename)}
    return client.post("/api/upload", data=data, content_type="multipart/form-data")


def get(path, **params):
    return client.get(path, query_string=params)


print("\n--- Library versions ---")
import flask, numpy, pandas, scipy  # noqa: E402
try:
    import plotly
    plotly_version = plotly.__version__
except ImportError:
    plotly_version = "NOT INSTALLED"
print(f"Python {sys.version.split()[0]}, pandas {pandas.__version__}, numpy {numpy.__version__}, "
      f"scipy {scipy.__version__}, plotly {plotly_version}")
check("Plotly is installed (needed for charts)", plotly_version != "NOT INSTALLED")

print("\n--- Sample datasets ---")
ids = {}
for name in ("student_performance.csv", "retail_sales.csv", "city_weather.csv"):
    with open(f"sample_data/{name}", "rb") as f:
        r = upload(name, f.read())
    body = r.get_json()
    check(f"upload {name}", r.status_code == 200, body.get("error") if body else r.status_code)
    if r.status_code == 200:
        ids[name] = body["dataset"]["id"]

sid, rid, wid = ids.get("student_performance.csv"), ids.get("retail_sales.csv"), ids.get("city_weather.csv")
if sid:
    r = get(f"/api/datasets/{sid}/scatter", x="Study_Hours", y="Final_Marks", color="Gender")
    check("scatter plot with colour groups", r.status_code == 200 and r.get_json()["pearson"] is not None)
    r = get(f"/api/datasets/{sid}/scatter-matrix", cols=["Study_Hours", "Final_Marks", "Attendance_Pct"])
    check("scatter matrix", r.status_code == 200)
    r = get(f"/api/datasets/{sid}/pivot", rows="Department", cols="Gender", values="Final_Marks", agg="mean")
    check("pivot table", r.status_code == 200)
    r = get(f"/api/datasets/{sid}/crosstab", a="Department", b="Extracurricular")
    check("cross-tabulation with chi-square", r.status_code == 200 and r.get_json()["chi2"] is not None)
    r = get(f"/api/datasets/{sid}/download", dedupe="1")
    check("download cleaned CSV", r.status_code == 200 and r.data.count(b"\n") == 601)
if rid:
    for freq in ("auto", "D", "W", "M", "Q", "Y"):
        r = get(f"/api/datasets/{rid}/timeseries", date="Order_Date", value="Total_Amount", agg="sum", freq=freq)
        check(f"time series ({freq})", r.status_code == 200, r.get_json().get("error"))
if sid and wid:
    r = get("/api/compare", a=sid, b=wid)
    check("compare two datasets", r.status_code == 200)

print("\n--- Messy files ---")
messy = {
    "latin1.csv": "name,city,score\nJosé,São Paulo,5\nRené,Zürich,7\nAna,Köln,9\n".encode("latin-1"),
    "utf16.txt": "a\tb\n1\tx\n2\ty\n3\tz\n".encode("utf-16"),
    "semicolon_decimal_comma.csv": b"name;val\nA;1,5\nB;2,5\nC;3,75\n",
    "bad_rows.csv": b"a,b,c\n1,2,3\n4,5\n6,7,8,9\n10,11,12\n",
    "no_header.csv": b"1,2,3\n4,5,6\n7,8,9\n",
    "currency.csv": "item,price\nA,\"\u20b91,200\"\nB,$300\nC,450\n".encode(),
    "timezones.csv": b"ts,v\n2024-01-01T10:00:00Z,1\n2024-01-02T11:00:00+05:30,2\n2024-01-03T12:00:00Z,3\n",
    "missing_markers.csv": b"a,b\n1,NA\n2,?\n3,-\n4,5\n",
}
for name, content in messy.items():
    r = upload(name, content)
    check(f"reads {name}", r.status_code == 200, (r.get_json() or {}).get("error"))

print("\n--- Files that should be rejected with a clear message ---")
for name, content in {"empty.csv": b"", "header_only.csv": b"a,b,c\n", "fake.csv": b"PK\x03\x04xx", "photo.png": b"abc"}.items():
    r = upload(name, content)
    check(f"rejects {name}", r.status_code == 400 and "error" in r.get_json(), r.status_code)

passed = sum(results)
print(f"\n{passed} of {len(results)} checks passed.")
sys.exit(0 if passed == len(results) else 1)
