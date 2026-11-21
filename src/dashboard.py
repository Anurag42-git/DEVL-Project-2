"""Shared Streamlit helpers: cached pipeline access, disclaimer and formatting."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from .config import get_path, load_config
from .pipeline import PipelineResult, data_fingerprint, run_pipeline
from .review_store import list_outcomes

_OUTCOME_COLUMNS = ["outcome", "reviewer", "notes", "updated_at"]


def setup_page(title: str, icon: str = "🔎") -> None:
    """Configure a Streamlit page and show the persistent disclaimer."""
    st.set_page_config(page_title=title, page_icon=icon, layout="wide")
    st.sidebar.title("Transaction Investigation")
    st.sidebar.caption("Synthetic monitoring demo — explainable review queue")
    st.sidebar.info(get_path(load_config(), "project.disclaimer", ""))
    st.sidebar.markdown(
        "1. Overview  \n2. Reconciled ledger  \n3. Review queue  \n"
        "4. Data quality  \n5. Audit report"
    )


@st.cache_data(show_spinner="Reading and reconciling payment data...", ttl=3600)
def _cached_pipeline(fingerprint: tuple[tuple[str, int], ...]) -> PipelineResult:
    return run_pipeline()


def load_pipeline() -> PipelineResult:
    """Return the cached pipeline result for the current data files."""
    result = _cached_pipeline(data_fingerprint())
    refresh_outcomes(result)
    return result


def refresh_outcomes(result: PipelineResult) -> None:
    """Re-merge current SQLite outcomes into the cached scoring frames in place."""
    outcomes = list_outcomes(config=result.config)
    for frame in (result.scoring.queue, result.scoring.all_scored):
        for column in _OUTCOME_COLUMNS:
            if column in frame.columns:
                frame.drop(columns=[column], inplace=True)
        merged = frame.merge(outcomes, on="record_id", how="left")
        for column, default in [
            ("outcome", "pending"), ("reviewer", ""), ("notes", ""), ("updated_at", "")
        ]:
            merged[column] = merged[column].fillna(default)
        frame.drop(frame.index, inplace=True)
        for column in merged.columns:
            frame[column] = merged[column].values


def format_money(value: Any) -> str:
    """Format a numeric amount for dashboard display."""
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "-"


def reason_table(queue: pd.DataFrame, record_id: str) -> pd.DataFrame:
    """Return the reason-code explanation table for one flagged record."""
    import json

    row = queue[queue["record_id"] == record_id]
    if row.empty:
        return pd.DataFrame(columns=["code", "explanation", "actual vs threshold", "weight"])
    reasons = json.loads(row.iloc[0]["reasons"])
    return pd.DataFrame([{
        "code": r["code"],
        "explanation": r["explanation"],
        "actual vs threshold": r["detail"],
        "weight": r["weight"],
    } for r in reasons])


def human_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Prettify column labels for a Streamlit dataframe."""
    renamed = frame.rename(columns=lambda col: str(col).replace("_", " ").title())
    return renamed
