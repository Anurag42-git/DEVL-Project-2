"""Tests for reconciliation, idempotency and raw-vs-ledger conservation."""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.reconcile import ReconciliationResult, reconcile


def event(event_id: str, transaction_id: str, event_type: str, status: str,
          amount: float = 100.0, ts: str = "2024-05-01 10:00:00",
          customer_id: str = "C1", merchant_id: str = "M1", device_id: str = "D1",
          currency: str = "USD") -> dict[str, Any]:
    return dict(
        event_id=event_id, transaction_id=transaction_id, customer_id=customer_id,
        merchant_id=merchant_id, amount=amount, currency=currency,
        event_timestamp=ts, event_type=event_type, status=status, device_id=device_id,
    )


def status(txn: str, value: str, ts: str) -> dict[str, str]:
    return dict(transaction_id=txn, status=value, status_timestamp=ts)


def refund(rid: str, txn: str, amount: float, ts: str) -> dict[str, Any]:
    return dict(refund_id=rid, transaction_id=txn, refund_amount=amount,
                refund_timestamp=ts, refund_status="completed")


def run(config: dict, events: list[dict], refunds: list[dict],
        statuses: list[dict]) -> ReconciliationResult:
    return reconcile(
        config,
        pd.DataFrame(events),
        pd.DataFrame(refunds, columns=["refund_id", "transaction_id", "refund_amount",
                                       "refund_timestamp", "refund_status"]),
        pd.DataFrame(statuses, columns=["transaction_id", "status", "status_timestamp"]),
    )


def test_duplicate_events_are_removed_once(config: dict) -> None:
    events = [
        event("EV1", "TXN1", "authorization", "authorized", ts="2024-05-01 10:00:00"),
        event("EV2", "TXN1", "capture", "captured", ts="2024-05-01 10:01:00"),
        event("EV2", "TXN1", "capture", "captured", ts="2024-05-01 10:01:00"),  # exact duplicate
    ]
    result = run(config, events, [], [status("TXN1", "authorized", "2024-05-01 10:00:00"),
                                      status("TXN1", "captured", "2024-05-01 10:01:00")])
    row = result.ledger.iloc[0]
    assert len(result.ledger) == 1
    assert row["attempt_count"] == 2
    assert row["captured_amount"] == 100.0
    assert row["duplicate_events_removed"] == 1
    assert "duplicate event(s) removed" in row["reconciliation_notes"]
    assert result.adjustments["duplicate_events_removed"] == 1
    assert result.invariant["matched"]


def test_retries_are_attempts_not_revenue(config: dict) -> None:
    events = [
        event("EV1", "TXN1", "authorization", "authorized", ts="2024-05-01 10:00:00"),
        *[event(f"R{i}", "TXN1", "retry", "authorized", ts=f"2024-05-01 10:00:{i:02d}")
          for i in range(1, 7)],
        event("EV2", "TXN1", "capture", "captured", ts="2024-05-01 10:01:00"),
    ]
    result = run(config, events, [], [status("TXN1", "captured", "2024-05-01 10:01:00")])
    row = result.ledger.iloc[0]
    assert row["retry_count"] == 6
    assert row["attempt_count"] == 8
    assert row["captured_amount"] == 100.0
    assert "merged as attempts, not revenue" in row["reconciliation_notes"]
    assert result.invariant["matched"]


def test_partial_refunds_aggregated(config: dict) -> None:
    events = [
        event("EV1", "TXN1", "authorization", "authorized", ts="2024-05-01 10:00:00"),
        event("EV2", "TXN1", "capture", "captured", ts="2024-05-01 10:01:00"),
    ]
    refunds = [
        refund("R1", "TXN1", 20.0, "2024-05-02 10:00:00"),
        refund("R2", "TXN1", 30.0, "2024-05-03 10:00:00"),
        refund("R3", "TXN1", 10.0, "2024-05-04 10:00:00"),
    ]
    result = run(config, events, refunds, [status("TXN1", "captured", "2024-05-01 10:01:00")])
    row = result.ledger.iloc[0]
    assert row["refund_count"] == 3
    assert row["total_refunded"] == 60.0
    assert row["remaining_amount"] == 40.0
    assert abs(row["refund_ratio"] - 0.6) < 1e-9
    assert "3 refund(s) aggregated" in row["reconciliation_notes"]
    assert result.invariant["matched"]


def test_over_refund_and_final_status(config: dict) -> None:
    events = [
        event("EV1", "TXN1", "authorization", "authorized", ts="2024-05-01 10:00:00"),
        event("EV2", "TXN1", "capture", "captured", ts="2024-05-01 10:01:00"),
    ]
    refunds = [refund("R1", "TXN1", 150.0, "2024-05-02 10:00:00")]
    statuses = [
        status("TXN1", "authorized", "2024-05-01 10:00:00"),
        status("TXN1", "captured", "2024-05-01 10:01:00"),
        status("TXN1", "refunded", "2024-05-02 10:00:00"),
    ]
    row = run(config, events, refunds, statuses).ledger.iloc[0]
    assert row["final_status"] == "refunded"
    assert row["over_refund_amount"] == 50.0
    assert row["remaining_amount"] == -50.0
    assert "over-refund" in row["reconciliation_notes"]


def test_orphan_refund_and_status_ids_kept(config: dict) -> None:
    events = [event("EV1", "TXN1", "authorization", "authorized")]
    result = run(
        config, events,
        [refund("R1", "TXN-ORPHAN", 25.0, "2024-05-02 10:00:00")],
        [status("TXN-STATUS-ONLY", "captured", "2024-05-02 11:00:00")],
    )
    assert set(result.ledger["transaction_id"]) == {"TXN1", "TXN-ORPHAN", "TXN-STATUS-ONLY"}
    orphan = result.ledger[result.ledger["transaction_id"] == "TXN-ORPHAN"].iloc[0]
    assert orphan["captured_amount"] == 0.0
    assert orphan["total_refunded"] == 25.0
    assert "orphan reference" in orphan["reconciliation_notes"]
    assert result.invariant["matched"]


def test_generated_dataset_conservation_and_idempotency(config: dict, raw: dict[str, Any]) -> None:
    first = reconcile(config, raw["transactions"], raw["refunds"], raw["payment_status"])
    second = reconcile(config, raw["transactions"], raw["refunds"], raw["payment_status"])
    assert first.invariant["matched"], first.invariant
    assert first.invariant["captured_difference"] == 0.0
    assert first.invariant["refunded_difference"] == 0.0
    pd.testing.assert_frame_equal(first.ledger, second.ledger)
    assert first.ledger["transaction_id"].is_unique
    assert first.adjustments["duplicate_events_removed"] > 0
    assert first.adjustments["retry_events_merged"] > 0
    assert first.ledger["over_refund_amount"].gt(0).any()
