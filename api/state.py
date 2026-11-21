"""In-memory cache for one pipeline run, with on-demand reload."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.pipeline import PipelineResult, data_fingerprint, run_pipeline
from src.review_store import list_outcomes, set_outcome
from src.utils import to_iso

_OUTCOME_COLUMNS = ["outcome", "reviewer", "notes", "updated_at"]
_lock = threading.RLock()


@dataclass
class AppState:
    """The cached pipeline result and its provenance."""

    result: PipelineResult | None = None
    fingerprint: tuple[tuple[str, int], ...] = ()
    generated_at: str = ""


_state = AppState()


def get_result() -> PipelineResult:
    """Return the cached pipeline result, running the pipeline on first use."""
    with _lock:
        if _state.result is None:
            return reload_result()
        return _state.result


def reload_result() -> PipelineResult:
    """Re-run the pipeline from the CSV files and replace the cached result."""
    with _lock:
        result = run_pipeline()
        _state.result = result
        _state.fingerprint = data_fingerprint(result.config)
        _state.generated_at = to_iso(pd.Timestamp.now())
        return result


def set_result(result: PipelineResult) -> PipelineResult:
    """Install a pre-built result (used by tests and tooling)."""
    with _lock:
        _state.result = result
        _state.fingerprint = data_fingerprint(result.config)
        _state.generated_at = to_iso(pd.Timestamp.now())
        return result


def clear_result() -> None:
    """Drop the cached result (used by tests)."""
    with _lock:
        _state.result = None
        _state.fingerprint = ()
        _state.generated_at = ""


def state_info() -> dict[str, Any]:
    """Small status object returned by the health endpoint."""
    with _lock:
        return {
            "loaded": _state.result is not None,
            "generated_at": _state.generated_at,
            "source_files": len(_state.fingerprint),
        }


def _merge_outcomes(frame: pd.DataFrame, outcomes: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    cleaned = frame.drop(columns=[c for c in _OUTCOME_COLUMNS if c in frame.columns])
    merged = cleaned.merge(outcomes, on="record_id", how="left")
    for column, default in [
        ("outcome", "pending"), ("reviewer", ""), ("notes", ""), ("updated_at", "")
    ]:
        merged[column] = merged[column].fillna(default)
    return merged


def record_outcome(
    record_id: str, outcome: str, reviewer: str, notes: str
) -> dict[str, str]:
    """Persist an outcome and refresh the cached queue so reads see it immediately."""
    with _lock:
        result = get_result()
        saved = set_outcome(
            record_id, outcome, reviewer, notes, config=result.config
        )
        outcomes = list_outcomes(config=result.config)
        for frame in (result.scoring.queue, result.scoring.all_scored):
            refreshed = _merge_outcomes(frame, outcomes)
            frame.drop(frame.index, inplace=True)
            for column in refreshed.columns:
                frame[column] = refreshed[column].values
        return saved
