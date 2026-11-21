"""Overview page — KPIs, time series and distributions.

Run with ``streamlit run app.py`` after generating the data.
"""

from __future__ import annotations

import plotly.express as px
import streamlit as st

from src.config import get_path
from src.dashboard import format_money, load_pipeline, setup_page
from src.scoring import distinct_flagged_transactions, flagged_transaction_rate
from src.utils import parse_datetime


def main() -> None:
    setup_page("Overview", "📊")
    result = load_pipeline()
    ledger = result.reconciliation.ledger
    queue = result.scoring.queue

    st.title("Transaction Anomaly and Refund Investigation")
    st.caption(
        "Reconciled payment activity and explainable review flags. "
        + str(get_path(result.config, "project.disclaimer", ""))
    )

    captured = float(ledger["captured_amount"].sum())
    refunded = float(ledger["total_refunded"].sum())
    refund_ratio = refunded / captured if captured else 0.0
    kpis = st.columns(4)
    kpis[0].metric("Transactions reconciled", f"{len(ledger):,}")
    kpis[1].metric("Captured amount", format_money(captured))
    kpis[2].metric("Refund ratio", f"{refund_ratio:.2%}")
    kpis[3].metric(
        "Flagged for review",
        f"{distinct_flagged_transactions(queue):,} "
        f"({flagged_transaction_rate(queue, len(ledger)):.1%})",
    )

    st.subheader("Activity over time")
    times = parse_datetime(ledger["first_event_time"])
    daily = (
        ledger.assign(day=times.dt.date)
        .groupby("day", dropna=True)
        .agg(transactions=("transaction_id", "size"), captured=("captured_amount", "sum"))
        .reset_index()
    )
    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            px.line(daily, x="day", y="transactions", title="Transactions per day",
                    labels={"day": "Date", "transactions": "Transactions"}),
            width="stretch",
        )
    with right:
        st.plotly_chart(
            px.line(daily, x="day", y="captured", title="Captured amount per day",
                    labels={"day": "Date", "captured": "Captured amount"}),
            width="stretch",
        )

    st.subheader("Distributions")
    left, right = st.columns(2)
    with left:
        status_counts = ledger["final_status"].value_counts().reset_index()
        status_counts.columns = ["final_status", "count"]
        st.plotly_chart(
            px.bar(status_counts, x="final_status", y="count", title="Final status distribution",
                   labels={"final_status": "Final status", "count": "Transactions"}),
            width="stretch",
        )
    with right:
        reasons = result.scoring.reason_summary.head(12)
        st.plotly_chart(
            px.bar(reasons, x="reason_code", y="flagged_records",
                   title="Most common review reasons",
                   labels={"reason_code": "Reason code", "flagged_records": "Records"}),
            width="stretch",
        )

    st.subheader("Pipeline health")
    health = st.columns(3)
    health[0].metric("Validation violations", f"{len(result.validation.violations):,}")
    health[1].metric("Duplicate events removed",
                     f"{result.reconciliation.adjustments['duplicate_events_removed']:,}")
    health[2].metric(
        "Ledger conservation check",
        "PASS" if result.reconciliation.invariant["matched"] else "FAIL",
    )
    with st.expander("Reconciliation summary"):
        st.json(result.reconciliation.summary())


main()
