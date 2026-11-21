"""Reconcile raw payment events into one row per transaction.

Key rules:
* ``event_id`` is an idempotency key — repeated copies are removed.
* Retry events count as *attempts*, never as additional revenue.
* The first canonical capture event supplies the captured amount; multiple
  capture events are reported in the notes but never double-counted.
* Completed partial refunds are summed; refunds for unknown transaction ids
  get their own ledger row so that they remain visible to review.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .config import get_path, load_config
from .utils import parse_datetime, read_csv, safe_divide

LEDGER_COLUMNS = [
    "transaction_id", "customer_id", "merchant_id", "device_id", "currency",
    "authorized_amount", "captured_amount", "total_refunded", "remaining_amount",
    "refund_ratio", "refund_count", "final_status", "attempt_count", "retry_count",
    "duplicate_events_removed", "first_event_time", "last_event_time",
    "first_refund_time", "last_refund_time", "over_refund_amount",
    "capture_event_count", "event_count_raw", "event_count_deduped",
    "reconciliation_notes",
]


@dataclass
class ReconciliationResult:
    """Ledger plus adjustment counters and the raw-vs-ledger conservation check."""

    ledger: pd.DataFrame
    raw_events: pd.DataFrame
    deduped_events: pd.DataFrame
    adjustments: dict[str, int]
    invariant: dict[str, Any]

    def summary(self) -> dict[str, Any]:
        """Compact metrics used by the dashboard and audit report."""
        return {
            **self.adjustments,
            "transactions_in_ledger": int(len(self.ledger)),
            "captured_amount": float(self.ledger["captured_amount"].sum()),
            "total_refunded": float(self.ledger["total_refunded"].sum()),
            "invariant_matched": bool(self.invariant["matched"]),
        }


def _canonical_captures(events: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    """One canonical capture row per transaction (the first in file order)."""
    types = set(get_path(config, "reconcile.capture_event_types", ["capture"]) or [])
    statuses = set(get_path(config, "reconcile.capture_statuses", ["captured"]) or [])
    mask = events["event_type"].isin(types) & events["status"].isin(statuses)
    captures = events[mask].copy()
    captures["_amount"] = pd.to_numeric(captures["amount"], errors="coerce").fillna(0.0)
    captures = captures.sort_values("_order", kind="stable")
    return captures.drop_duplicates(subset=["transaction_id"], keep="first")


def reconcile(
    config: dict[str, Any] | None = None,
    transactions: pd.DataFrame | None = None,
    refunds: pd.DataFrame | None = None,
    payment_status: pd.DataFrame | None = None,
) -> ReconciliationResult:
    """Build the reconciled ledger from raw payment tables."""
    cfg = config or load_config()
    if transactions is None or refunds is None or payment_status is None:
        from .config import data_file

        transactions = transactions if transactions is not None else read_csv(data_file(cfg, "transactions"))
        refunds = refunds if refunds is not None else read_csv(data_file(cfg, "refunds"))
        payment_status = payment_status if payment_status is not None else read_csv(
            data_file(cfg, "payment_status")
        )

    raw = transactions.copy().reset_index(drop=True)
    raw["_order"] = np.arange(len(raw))
    raw["_ts"] = parse_datetime(raw["event_timestamp"])
    raw["_amount"] = pd.to_numeric(raw["amount"], errors="coerce").fillna(0.0)

    # 1. Idempotent collapse on event_id (keep the first occurrence in file order).
    duplicate_mask = raw["event_id"].duplicated(keep="first")
    duplicates = raw[duplicate_mask].copy()
    events = raw[~duplicate_mask].copy()
    event_counts = raw.groupby("event_id", sort=False).size()
    duplicated_event_ids = sorted(event_counts[event_counts > 1].index.astype(str))

    # 2. Captured amount: canonical capture only, never a sum over retries.
    captures = _canonical_captures(events, cfg)
    capture_amount = captures.set_index("transaction_id")["_amount"]
    capture_count = events[events["event_type"].isin(
        set(get_path(cfg, "reconcile.capture_event_types", ["capture"]) or [])
    )].groupby("transaction_id").size()

    # 3. Refunds (completed only) aggregated per transaction id.
    completed_statuses = set(
        get_path(cfg, "reconcile.completed_refund_statuses", ["completed"]) or []
    )
    rfd = refunds.copy().reset_index(drop=True)
    rfd["_refund_amount"] = pd.to_numeric(rfd["refund_amount"], errors="coerce").fillna(0.0)
    rfd["_ts"] = parse_datetime(rfd["refund_timestamp"])
    rfd_completed = rfd[rfd["refund_status"].isin(completed_statuses)].copy()
    refund_groups = rfd_completed.groupby("transaction_id", sort=False).agg(
        total_refunded=("_refund_amount", "sum"),
        refund_count=("_refund_amount", "size"),
        first_refund_time=("_ts", "min"),
        last_refund_time=("_ts", "max"),
    )

    # 4. Final status from the status history (timestamp order, file order tie-break).
    pst = payment_status.copy().reset_index(drop=True)
    pst["_ts"] = parse_datetime(pst["status_timestamp"])
    pst["_order"] = np.arange(len(pst))
    pst = pst.sort_values(["_ts", "_order"], kind="stable")
    final_status = pst.groupby("transaction_id", sort=False)["status"].last()

    # 5. Assemble one row per transaction id seen anywhere in the raw data.
    all_ids = sorted(set(events["transaction_id"].astype(str))
                     | set(rfd["transaction_id"].astype(str))
                     | set(pst["transaction_id"].astype(str)))
    # Pre-index events once instead of scanning the whole table per transaction.
    event_indices: dict[str, list[int]] = {}
    for index, txn_id in zip(events.index, events["transaction_id"].astype(str)):
        event_indices.setdefault(txn_id, []).append(index)
    raw_counts = raw["transaction_id"].astype(str).value_counts()
    dupe_counts = duplicates["transaction_id"].astype(str).value_counts()
    ledgers: list[dict[str, Any]] = []
    note_limit = int(get_path(cfg, "reconcile.duplicate_notes_limit", 20))
    known_event_ids = set(events["transaction_id"].astype(str))

    for txn_id in all_ids:
        group = events.loc[event_indices.get(txn_id, [])]
        notes: list[str] = []
        if group.empty:
            customer = merchant = device = currency = ""
            authorized = captured = 0.0
            first_time = last_time = pd.NaT
            attempt_count = retry_count = 0
            capture_n = 0
            notes.append("orphan reference: id appears only in refund/status files; "
                         "no transaction events were found")
        else:
            first = group.iloc[0]  # events retain original file order
            customer = str(first["customer_id"])
            merchant = str(first["merchant_id"])
            device_modes = group["device_id"].mode()
            device = str(device_modes.iloc[0]) if not device_modes.empty else str(first["device_id"])
            currencies = sorted(set(group["currency"].astype(str)))
            currency = currencies[0]
            if len(currencies) > 1:
                notes.append(f"multiple currencies observed ({', '.join(currencies)}); "
                             f"ledger keeps {currency}")
            auth_mask = group["event_type"] == "authorization"
            authorized = float(group.loc[auth_mask, "_amount"].iloc[0]) \
                if auth_mask.any() else 0.0
            captured = float(capture_amount.get(txn_id, 0.0))
            capture_n = int(capture_count.get(txn_id, 0))
            if capture_n > 1:
                notes.append(f"{capture_n} capture events seen; first used once as revenue")
            first_time = group["_ts"].min()
            last_time = group["_ts"].max()
            attempt_count = int(len(group))
            retry_count = int((group["event_type"] == "retry").sum())
            if retry_count:
                notes.append(f"{retry_count} retry event(s) merged as attempts, not revenue")

        n_dupes = int(dupe_counts.get(txn_id, 0))
        if n_dupes:
            sample = ", ".join(duplicated_event_ids[:note_limit])
            notes.append(f"{n_dupes} duplicate event(s) removed by event_id ({sample})")

        refund_row = refund_groups.loc[txn_id] if txn_id in refund_groups.index else None
        if refund_row is not None:
            total_refunded = float(refund_row["total_refunded"])
            refund_count = int(refund_row["refund_count"])
            first_refund = refund_row["first_refund_time"]
            last_refund = refund_row["last_refund_time"]
            if refund_count > 1:
                notes.append(f"{refund_count} refund(s) aggregated into one total")
        else:
            total_refunded = refund_count = 0
            first_refund = last_refund = pd.NaT

        over = max(0.0, total_refunded - captured)
        if over > 0:
            notes.append(
                f"over-refund: refunds {total_refunded:.2f} exceed captured {captured:.2f} "
                f"by {over:.2f}"
            )

        status = str(final_status.get(txn_id, "unknown"))
        if txn_id not in known_event_ids:
            notes.append("orphan transaction id retained for investigation")

        ledgers.append({
            "transaction_id": txn_id,
            "customer_id": customer,
            "merchant_id": merchant,
            "device_id": device,
            "currency": currency,
            "authorized_amount": authorized,
            "captured_amount": captured,
            "total_refunded": total_refunded,
            "remaining_amount": captured - total_refunded,
            "refund_ratio": safe_divide(total_refunded, captured),
            "refund_count": refund_count,
            "final_status": status,
            "attempt_count": attempt_count,
            "retry_count": retry_count,
            "duplicate_events_removed": n_dupes,
            "first_event_time": first_time,
            "last_event_time": last_time,
            "first_refund_time": first_refund,
            "last_refund_time": last_refund,
            "over_refund_amount": over,
            "capture_event_count": capture_n,
            "event_count_raw": int(raw_counts.get(txn_id, 0)),
            "event_count_deduped": len(group),
            "reconciliation_notes": "; ".join(notes) if notes else "no adjustments",
        })

    ledger = pd.DataFrame(ledgers, columns=LEDGER_COLUMNS).sort_values(
        "transaction_id"
    ).reset_index(drop=True)

    result = ReconciliationResult(
        ledger=ledger,
        raw_events=raw.drop(columns=["_order", "_ts", "_amount"]),
        deduped_events=events.drop(columns=["_order", "_ts", "_amount"]),
        adjustments={
            "duplicate_events_removed": int(duplicate_mask.sum()),
            "retry_events_merged": int((events["event_type"] == "retry").sum()),
            "refunds_aggregated": int(max(0, len(rfd_completed) - int(
                (refund_groups["refund_count"] > 1).sum()
            ))),
            "refund_rows_total": int(len(rfd_completed)),
            "orphan_transaction_rows": int((~pd.Series(all_ids).isin(known_event_ids)).sum()),
        },
        invariant={},
    )
    result.invariant = check_ledger_invariant(result, rfd_completed, cfg)
    return result


def check_ledger_invariant(
    result: ReconciliationResult,
    completed_refunds: pd.DataFrame,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify ledger totals equal a direct raw-data computation.

    The two measurements are computed independently: captured revenue from the
    de-duplicated canonical capture events, and refunded money from all
    completed refund rows. They must agree with ledger sums exactly.
    """
    cfg = config or load_config()
    canonical_input = result.deduped_events.assign(
        _order=np.arange(len(result.deduped_events)),
        _amount=pd.to_numeric(result.deduped_events["amount"], errors="coerce").fillna(0.0),
    )
    raw_captured = float(_canonical_captures(canonical_input, cfg)["_amount"].sum())
    raw_refunded = float(pd.to_numeric(
        completed_refunds["refund_amount"], errors="coerce"
    ).fillna(0.0).sum())
    ledger_captured = float(result.ledger["captured_amount"].sum())
    ledger_refunded = float(result.ledger["total_refunded"].sum())
    return {
        "raw_captured": raw_captured,
        "ledger_captured": ledger_captured,
        "raw_refunded": raw_refunded,
        "ledger_refunded": ledger_refunded,
        "captured_difference": ledger_captured - raw_captured,
        "refunded_difference": ledger_refunded - raw_refunded,
        "matched": bool(
            np.isclose(ledger_captured, raw_captured, atol=0.01)
            and np.isclose(ledger_refunded, raw_refunded, atol=0.01)
        ),
    }


def reconcile_from_config(config: dict[str, Any]) -> ReconciliationResult:
    """Reconcile the CSV files described by ``config.yaml``."""
    from .config import data_file

    return reconcile(
        config,
        read_csv(data_file(config, "transactions")),
        read_csv(data_file(config, "refunds")),
        read_csv(data_file(config, "payment_status")),
    )
