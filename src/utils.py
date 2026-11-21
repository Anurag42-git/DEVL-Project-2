"""Small shared helpers for IO, datetimes and numeric safety."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def ensure_parent(path: str | Path) -> Path:
    """Create the parent directory of ``path`` and return it as an absolute Path."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def write_csv(frame: pd.DataFrame, path: str | Path) -> Path:
    """Write a DataFrame to CSV, creating parent directories as needed."""
    target = ensure_parent(path)
    frame.to_csv(target, index=False)
    return target


def read_csv(path: str | Path, **kwargs: Any) -> pd.DataFrame:
    """Read a CSV file with a clear error if it is missing."""
    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(f"Expected data file is missing: {target}")
    return pd.read_csv(target, **kwargs)


def parse_datetime(series: pd.Series) -> pd.Series:
    """Parse a Series of timestamps robustly; unparseable values become NaT."""
    return pd.to_datetime(series, errors="coerce", format="mixed")


def to_iso(value: Any) -> str:
    """Return an ISO-8601 string for a datetime-like value, or ``''`` when missing."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    if isinstance(value, (list, tuple, set, dict)):
        return str(value)
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Divide two numbers, returning ``default`` for zero/invalid denominators."""
    try:
        if denominator is None or pd.isna(denominator) or float(denominator) == 0.0:
            return default
        result = float(numerator) / float(denominator)
        return result if np.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def json_dumps(value: Any) -> str:
    """JSON-serialise values that may contain numpy/pandas scalars."""
    return json.dumps(value, default=_json_default, ensure_ascii=False)


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return to_iso(value)
    return str(value)


def short_id(prefix: str, number: int, width: int = 6) -> str:
    """Format a stable identifier such as ``TXN-000123``."""
    return f"{prefix}-{number:0{width}d}"
