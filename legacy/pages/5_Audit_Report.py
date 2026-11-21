"""Generate and download the audit report and review-queue CSV."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from src.config import get_path
from src.dashboard import load_pipeline, setup_page
from src.review_store import audit_trail, list_outcomes

setup_page("Audit Report", "📄")
result = load_pipeline()

st.title("Audit report")
st.caption("Reproducible summary of methodology, data quality, reconciliation "
           "adjustments, review outcomes and detection quality.")

cols = st.columns(3)
cols[0].metric("Flagged records", len(result.scoring.queue))
cols[1].metric("Review outcomes recorded", len(list_outcomes(config=result.config)))
cols[2].metric("Audit events", len(audit_trail(config=result.config)))

if st.button("Generate / refresh report files"):
    try:
        from src.report import generate_report

        files = generate_report(result)
        st.success("Report generated: " + ", ".join(str(path) for path in files.values()))
    except Exception as exc:  # pragma: no cover - surfaced in the UI
        st.error(f"Report generation failed: {exc}")

reports_dir = Path(str(get_path(result.config, "data.reports_directory", "reports")))
md_path = reports_dir / "audit_report.md"
html_path = reports_dir / "audit_report.html"
csv_path = reports_dir / "review_queue.csv"

for label, path in [("Markdown", md_path), ("HTML", html_path), ("Review queue CSV", csv_path)]:
    if path.is_file():
        with open(path, "rb") as handle:
            st.download_button(f"Download {label}", handle.read(),
                               file_name=path.name, width="stretch")
    else:
        st.caption(f"{label} not generated yet — click the button above.")

if md_path.is_file():
    with st.expander("Report preview"):
        st.markdown(md_path.read_text(encoding="utf-8"))
