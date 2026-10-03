"""Creates three synthetic sample CSV files in sample_data/ for demonstrating DataLens.

The data is randomly generated (not real) and deliberately includes common problems:
missing values, duplicate rows, inconsistent spellings, invalid entries and outliers.
Run:  python generate_samples.py
"""
import os

import numpy as np
import pandas as pd

rng = np.random.default_rng(42)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_data")
os.makedirs(OUT, exist_ok=True)


def student_performance(n=600):
    gender = rng.choice(["Male", "Female"], n)
    dept = rng.choice(["Science", "Commerce", "Arts", "Engineering"], n, p=[0.3, 0.25, 0.2, 0.25])
    study = np.clip(rng.normal(4.5, 1.8, n), 0.5, 10).round(1)
    attendance = np.clip(rng.normal(80, 10, n) + study * 1.5, 40, 100).round(1)
    assignment = np.clip(40 + study * 5 + rng.normal(0, 8, n), 0, 100).round(0)
    internal = np.clip(10 + study * 2 + attendance * 0.1 + rng.normal(0, 3, n), 0, 40).round(0)
    final = np.clip(15 + study * 6 + attendance * 0.25 + rng.normal(0, 7, n), 0, 100).round(0)
    df = pd.DataFrame({
        "Student_ID": [f"S{i:04d}" for i in range(1, n + 1)],
        "Gender": gender,
        "Department": dept,
        "Age": rng.integers(17, 24, n),
        "Attendance_Pct": attendance.astype(object),
        "Study_Hours": study,
        "Assignment_Score": assignment,
        "Internal_Marks": internal,
        "Final_Marks": final,
        "Extracurricular": rng.choice(["Yes", "No"], n, p=[0.4, 0.6]),
        "Enrollment_Date": pd.to_datetime("2023-06-01") + pd.to_timedelta(rng.integers(0, 800, n), unit="D"),
    })
    df["Enrollment_Date"] = df["Enrollment_Date"].dt.strftime("%d/%m/%Y")
    # Deliberate problems
    df.loc[rng.choice(n, 25, replace=False), "Attendance_Pct"] = np.nan
    df.loc[rng.choice(n, 4, replace=False), "Attendance_Pct"] = "absent"
    df.loc[rng.choice(n, 12, replace=False), "Gender"] = "M"
    df.loc[rng.choice(n, 6, replace=False), "Gender"] = "female"
    df.loc[rng.choice(n, 15, replace=False), "Study_Hours"] = np.nan
    df.loc[rng.choice(n, 3, replace=False), "Study_Hours"] = [22.0, 25.5, 30.0]
    df.loc[rng.choice(n, 8, replace=False), "Final_Marks"] = np.nan
    df = pd.concat([df, df.sample(8, random_state=1)], ignore_index=True)
    df.to_csv(os.path.join(OUT, "student_performance.csv"), index=False)


def retail_sales(n=3000):
    start = pd.Timestamp("2024-01-01")
    days = rng.integers(0, 731, n * 3)
    dates = start + pd.to_timedelta(days, unit="D")
    month = dates.month
    weight = np.where(np.isin(month, [10, 11]), 1.8, np.where(month == 12, 1.4, 1.0))
    weight = weight * np.where(dates.dayofweek >= 5, 1.3, 1.0)
    keep = rng.random(len(dates)) < weight / weight.max()
    dates = dates[keep][:n]
    n = len(dates)
    times = pd.to_timedelta(rng.integers(9 * 60, 22 * 60, n), unit="m")
    dates = (dates + times).sort_values()
    category = rng.choice(["Electronics", "Clothing", "Groceries", "Home", "Beauty"], n, p=[0.2, 0.25, 0.3, 0.15, 0.1])
    base_price = {"Electronics": 6000, "Clothing": 1200, "Groceries": 350, "Home": 1800, "Beauty": 700}
    price = np.array([rng.normal(base_price[c], base_price[c] * 0.3) for c in category]).clip(50).round(0)
    qty = rng.integers(1, 6, n)
    qty[rng.choice(n, 6, replace=False)] = rng.integers(40, 80, 6)  # bulk orders (outliers)
    discount = rng.choice([0, 5, 10, 15, 20], n, p=[0.4, 0.2, 0.2, 0.1, 0.1])
    total = (price * qty * (1 - discount / 100)).round(2)
    rating = rng.choice([1, 2, 3, 4, 5], n, p=[0.05, 0.08, 0.2, 0.37, 0.3]).astype(float)
    rating[rng.choice(n, 180, replace=False)] = np.nan
    df = pd.DataFrame({
        "Order_ID": [f"ORD-{i:05d}" for i in range(1, n + 1)],
        "Order_Date": dates.strftime("%Y-%m-%d %H:%M"),
        "Product_Category": category,
        "Region": rng.choice(["North", "South", "East", "West"], n, p=[0.3, 0.3, 0.2, 0.2]),
        "Payment_Method": rng.choice(["UPI", "Card", "Cash", "Net Banking"], n, p=[0.45, 0.25, 0.2, 0.1]),
        "Quantity": qty,
        "Unit_Price": price,
        "Discount_Pct": discount,
        "Total_Amount": total,
        "Customer_Rating": rating,
    })
    df.to_csv(os.path.join(OUT, "retail_sales.csv"), index=False)


def city_weather():
    dates = pd.date_range("2023-01-01", "2025-12-31", freq="D")
    rows = []
    for city, base_t, rain_months in (("Chennai", 29, [10, 11, 12]), ("Delhi", 25, [7, 8]), ("Mumbai", 28, [6, 7, 8, 9])):
        doy = dates.dayofyear.values
        temp = base_t + 6 * np.sin((doy - 100) / 365 * 2 * np.pi) + rng.normal(0, 1.5, len(dates))
        rainy = np.isin(dates.month, rain_months)
        rain = np.where(rainy, rng.gamma(2, 8, len(dates)), rng.gamma(0.3, 2, len(dates))).round(1)
        humidity = np.clip(55 + rain * 0.8 + rng.normal(0, 8, len(dates)), 20, 100).round(0)
        aqi = np.clip(rng.normal(180 if city == "Delhi" else 90, 40, len(dates)) - rain, 20, 500).round(0)
        wind = np.clip(rng.normal(12, 4, len(dates)), 0, 50).round(1)
        for i, d in enumerate(dates):
            rows.append([d.strftime("%Y-%m-%d"), city, round(temp[i], 1), humidity[i], rain[i], wind[i], aqi[i]])
    df = pd.DataFrame(rows, columns=["Date", "City", "Temperature_C", "Humidity_Pct", "Rainfall_mm", "Wind_Speed_kmph", "AQI"])
    df.loc[rng.choice(len(df), 40, replace=False), "AQI"] = np.nan
    df.to_csv(os.path.join(OUT, "city_weather.csv"), index=False, sep=";")


if __name__ == "__main__":
    student_performance()
    retail_sales()
    city_weather()
    print("Sample files written to", OUT)
