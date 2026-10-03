"""Small helpers shared by the DataLens modules."""
import math
from datetime import date, datetime

import numpy as np
import pandas as pd


def to_json_safe(obj):
    """Recursively convert NumPy / pandas values into plain JSON-friendly Python values.

    NaN and infinity become None (null in JSON), timestamps become ISO strings.
    """
    if obj is None or isinstance(obj, (str, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_json_safe(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [to_json_safe(v) for v in obj.tolist()]
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        value = float(obj)
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if obj is pd.NaT:
        return None
    if isinstance(obj, (pd.Timestamp, datetime, date)):
        try:
            if pd.isna(obj):
                return None
        except (TypeError, ValueError):
            pass
        return obj.isoformat()
    try:
        if pd.isna(obj):
            return None
    except (TypeError, ValueError):
        pass
    return str(obj)


def label(value):
    """Turn a category value into a readable string (2.0 -> '2')."""
    if value is None:
        return "(missing)"
    try:
        if pd.isna(value):
            return "(missing)"
    except (TypeError, ValueError):
        pass
    if isinstance(value, (float, np.floating)) and float(value).is_integer():
        return str(int(value))
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return str(value)


def top_n_labels(series, n, keep_missing=True):
    """Convert a column to string labels, keeping the n most frequent values and
    grouping the rest into 'Other'. Returns (labelled_series, ordered_labels)."""
    labelled = series.map(label) if keep_missing else series.dropna().map(label)
    counts = labelled.value_counts()
    top = list(counts.index[:n])
    if len(counts) > n:
        labelled = labelled.where(labelled.isin(top), "Other")
        order = top + ["Other"]
    else:
        order = top
    return labelled, order


def round_or_none(value, digits=4):
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return round(value, digits)
