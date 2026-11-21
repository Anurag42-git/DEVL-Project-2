"""Ranked, explainable review queue with outcome forms and audit trail."""

from __future__ import annotations

import streamlit as st

from src.dashboard import human_columns, load_pipeline, reason_table, setup_page
from src.review_store import OUTCOMES, audit_trail, set_outcome

setup_page("Review Queue", "🚩")
result = load_pipeline()
queue = result.scoring.queue.copy()

st.title("Review queue")
st.caption("Each flag is an unusual pattern that warrants a human look — "
           "it is not a determination of fraud.")

priorities = st.multiselect("Priority", ["high", "medium", "low"], default=["high", "medium", "low"])
all_reasons = sorted({code for codes in queue["reason_codes"] for code in codes})
reasons = st.multiselect("Reason code", all_reasons)
outcomes = st.multiselect("Review outcome", list(OUTCOMES), default=list(OUTCOMES))
record_types = st.multiselect("Record type", sorted(queue["record_type"].unique()),
                              default=sorted(queue["record_type"].unique()))

filtered = queue[
    queue["priority"].isin(priorities)
    & queue["outcome"].isin(outcomes)
    & queue["record_type"].isin(record_types)
]
if reasons:
    filtered = filtered[filtered["reason_codes"].apply(
        lambda codes: bool(set(codes) & set(reasons))
    )]

table_columns = ["record_id", "record_type", "score", "priority", "reason_codes", "outcome",
                 "captured_amount", "refund_ratio_amount", "reviewer"]
table_columns = [c for c in table_columns if c in filtered.columns]
st.dataframe(
    human_columns(filtered[table_columns].reset_index(drop=True)),
    width="stretch", hide_index=True,
)
st.caption(f"Showing {len(filtered):,} of {len(queue):,} flagged records.")

if filtered.empty:
    st.info("No flagged records match these filters.")
else:
    selected = st.selectbox("Inspect a flagged record", filtered["record_id"].tolist())
    row = filtered[filtered["record_id"] == selected].iloc[0]
    st.subheader(f"{selected} — {row['record_type']}")
    metric_cols = st.columns(3)
    metric_cols[0].metric("Risk score", int(row["score"]))
    metric_cols[1].metric("Priority", str(row["priority"]).upper())
    metric_cols[2].metric("Outcome", str(row["outcome"]).replace("_", " "))

    st.markdown("#### Why this record was flagged")
    st.table(human_columns(reason_table(queue, selected)))
    st.caption("Values are compared with thresholds defined in config.yaml.")

    indicators = result.scoring.all_scored
    indicator_row = indicators[indicators["record_id"] == selected]
    interesting = [
        "captured_amount", "total_refunded", "refund_ratio_amount", "attempt_count",
        "retry_count", "failed_streak", "failure_rate", "max_txns_1h", "max_txns_24h",
        "distinct_customers", "round_amount_ratio", "amount_zscore_abs",
        "duplicate_events_removed", "invalid_amount_count", "invalid_transition_count",
        "orphan_reference_count",
    ]
    with st.expander("Indicator values"):
        available = [c for c in interesting if c in indicator_row.columns]
        st.dataframe(human_columns(indicator_row[available].T.reset_index().rename(
            columns={"index": "indicator", 0: "value"}
        )), hide_index=True, width="stretch")

    st.markdown("#### Record a review outcome")
    with st.form(key=f"outcome-form-{selected}"):
        new_outcome = st.selectbox("Outcome", list(OUTCOMES),
                                   index=list(OUTCOMES).index(str(row["outcome"])))
        reviewer = st.text_input("Reviewer", value=str(row["reviewer"] or ""))
        notes = st.text_area("Reviewer notes", value=str(row["notes"] or ""))
        submitted = st.form_submit_button("Save outcome")
    if submitted:
        set_outcome(selected, new_outcome, reviewer, notes, config=result.config)
        st.success(f"Outcome for {selected} saved to the audit trail.")
        st.rerun()

    with st.expander("Audit trail for this record"):
        trail = audit_trail(config=result.config, record_id=selected)
        st.dataframe(human_columns(trail), hide_index=True, width="stretch")
