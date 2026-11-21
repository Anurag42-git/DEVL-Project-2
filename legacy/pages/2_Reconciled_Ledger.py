"""Reconciled ledger with filtering and raw-event drill-down."""

from __future__ import annotations

import streamlit as st

from src.dashboard import format_money, human_columns, load_pipeline, setup_page
from src.utils import parse_datetime

setup_page("Reconciled Ledger", "🧾")
result = load_pipeline()
ledger = result.reconciliation.ledger.copy()

st.title("Reconciled payment ledger")
st.caption("One row per transaction. Retries are attempts, duplicates are collapsed, "
           "and completed partial refunds are aggregated.")

search = st.text_input("Search transaction / customer / merchant / device", "")
statuses = st.multiselect("Final status", sorted(ledger["final_status"].dropna().unique()))
only_flagged = st.checkbox("Only transactions in the review queue", value=False)

filtered = ledger.copy()
if search:
    mask = False
    for column in ("transaction_id", "customer_id", "merchant_id", "device_id"):
        mask = mask | filtered[column].astype(str).str.contains(search, case=False, na=False)
    filtered = filtered[mask]
if statuses:
    filtered = filtered[filtered["final_status"].isin(statuses)]
if only_flagged:
    flagged_ids = set(result.scoring.queue.loc[
        result.scoring.queue["record_type"] == "transaction", "record_id"
    ])
    filtered = filtered[filtered["transaction_id"].isin(flagged_ids)]

display_columns = [
    "transaction_id", "customer_id", "merchant_id", "device_id", "final_status",
    "captured_amount", "total_refunded", "remaining_amount", "refund_ratio",
    "refund_count", "attempt_count", "retry_count", "duplicate_events_removed",
    "first_event_time", "last_event_time",
]
st.dataframe(
    human_columns(filtered[display_columns].reset_index(drop=True)),
    width="stretch",
    hide_index=True,
)
st.caption(f"Showing {len(filtered):,} of {len(ledger):,} reconciled transactions.")

if filtered.empty:
    st.info("No transactions match these filters.")
else:
    selected = st.selectbox("Drill into a transaction", filtered["transaction_id"].tolist())
    row = ledger[ledger["transaction_id"] == selected].iloc[0]
    cols = st.columns(4)
    cols[0].metric("Captured", format_money(row["captured_amount"]))
    cols[1].metric("Refunded", format_money(row["total_refunded"]))
    cols[2].metric("Remaining", format_money(row["remaining_amount"]))
    cols[3].metric("Attempts", int(row["attempt_count"]))
    st.markdown("**Reconciliation notes:** " + str(row["reconciliation_notes"]))

    raw = result.reconciliation.raw_events
    events = raw[raw["transaction_id"] == selected].copy()
    events["parsed_time"] = parse_datetime(events["event_timestamp"])
    events = events.sort_values("parsed_time").drop(columns=["parsed_time"])
    st.subheader("Raw events")
    st.dataframe(human_columns(events.reset_index(drop=True)), width="stretch", hide_index=True)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Refunds")
        refunds = result.raw["refunds"]
        st.dataframe(
            human_columns(refunds[refunds["transaction_id"] == selected].reset_index(drop=True)),
            width="stretch", hide_index=True,
        )
    with col2:
        st.subheader("Status history")
        status = result.raw["payment_status"]
        st.dataframe(
            human_columns(status[status["transaction_id"] == selected].reset_index(drop=True)),
            width="stretch", hide_index=True,
        )
