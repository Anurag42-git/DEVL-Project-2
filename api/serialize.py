"""Convert pandas/numpy values into JSON-safe Python primitives."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd


def clean(value: Any) -> Any:
    """Recursively turn NumPy/Pandas scalars into JSON-serialisable values."""
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return None if not np.isfinite(number) else number
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [clean(item) for item in value]
    try:
        missing = pd.isna(value)
        if isinstance(missing, (bool, np.bool_)) and bool(missing):
            return None
    except (TypeError, ValueError):
        pass
    return value


def records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Return a DataFrame as a list of JSON-safe dictionaries."""
    return [clean(row) for row in frame.to_dict(orient="records")]
