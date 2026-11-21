"""Validation results and violation examples."""

from __future__ import annotations

import json

import streamlit as st

from src.dashboard import human_columns, load_pipeline, setup_page

setup_page("Data Quality", "🧪")
result = load_pipeline()
summary = result.validation.summary()

st.title("Data quality")
st.caption("Independent validation rules run on the raw files before reconciliation. "
           "Some violations are deliberate injections in this synthetic dataset.")

cols = st.columns(4)
cols[0].metric("Rules evaluated", len(summary))
cols[1].metric("Rules with findings", int((summary["count"] > 0).sum()))
cols[2].metric("Total violations", int(summary["count"].sum()))
cols[3].metric("High-severity findings",
               int(summary.loc[summary["severity"] == "high", "count"].sum()))

st.subheader("Rule summary")
st.dataframe(human_columns(summary), width="stretch", hide_index=True)

st.subheader("Violation examples")
violations = result.validation.violations
if violations.empty:
    st.success("No validation violations found.")
else:
    rule = st.selectbox("Rule", sorted(violations["rule"].unique()))
    subset = violations[violations["rule"] == rule].copy()
    subset["example"] = subset["example"].apply(
        lambda value: json.dumps(json.loads(value), indent=2) if value else ""
    )
    st.caption(f"{len(subset)} violation(s) for {rule}")
    st.dataframe(
        human_columns(subset[["record_id", "source_file", "severity", "detail", "example"]]),
        width="stretch", hide_index=True,
    )

with st.expander("Status state machine"):
    transitions = result.config["validation"]["allowed_transitions"]
    for state, allowed in transitions.items():
        st.markdown(f"- **{state}** → {', '.join(allowed) if allowed else '_terminal_'}")
    st.caption("A transition outside this map is reported as INVALID_STATUS_TRANSITION.")
