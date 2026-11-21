"""Tests for every validation rule and the status state machine."""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd
import pytest

from src.validate import ValidationReport, is_valid_transition, validate_data, validate_status_history

NOW = pd.Timestamp("2024-06-01 00:00:00")


def base_tables() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame,
                           pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """A small, fully valid dataset that mutations can build upon."""
    transactions = pd.DataFrame([
        dict(event_id="EV1", transaction_id="TXN1", customer_id="C1", merchant_id="M1",
             amount=100.0, currency="USD", event_timestamp="2024-05-01 10:00:00",
             event_type="authorization", status="authorized", device_id="D1"),
        dict(event_id="EV2", transaction_id="TXN1", customer_id="C1", merchant_id="M1",
             amount=100.0, currency="USD", event_timestamp="2024-05-01 10:01:00",
             event_type="capture", status="captured", device_id="D1"),
        dict(event_id="EV3", transaction_id="TXN2", customer_id="C1", merchant_id="M1",
             amount=50.0, currency="USD", event_timestamp="2024-05-01 11:00:00",
             event_type="authorization", status="failed", device_id="D1"),
    ])
    refunds = pd.DataFrame([
        dict(refund_id="R1", transaction_id="TXN1", refund_amount=30.0,
             refund_timestamp="2024-05-02 10:00:00", refund_status="completed"),
    ])
    status = pd.DataFrame([
        dict(transaction_id="TXN1", status="authorized", status_timestamp="2024-05-01 10:00:00"),
        dict(transaction_id="TXN1", status="captured", status_timestamp="2024-05-01 10:01:00"),
        dict(transaction_id="TXN1", status="partially_refunded",
             status_timestamp="2024-05-02 10:00:00"),
        dict(transaction_id="TXN2", status="failed", status_timestamp="2024-05-01 11:00:00"),
    ])
    customers = pd.DataFrame([dict(customer_id="C1", signup_date="2024-01-01",
                                   country="US", risk_segment="low")])
    merchants = pd.DataFrame([dict(merchant_id="M1", category="retail",
                                   country="US", onboarding_date="2024-01-01")])
    devices = pd.DataFrame([dict(device_id="D1", customer_count=1,
                                 first_seen="2024-05-01", last_seen="2024-05-02",
                                 failed_attempt_count=1)])
    return transactions, refunds, status, customers, merchants, devices


def run(config: dict, txn: pd.DataFrame, rfd: pd.DataFrame, pst: pd.DataFrame,
        cust: pd.DataFrame, merch: pd.DataFrame, dev: pd.DataFrame) -> ValidationReport:
    return validate_data(config, txn, rfd, pst, cust, merch, dev, now=NOW)


def test_clean_dataset_has_no_violations(config: dict) -> None:
    report = run(config, *base_tables())
    assert report.violations.empty
    assert report.summary()["count"].sum() == 0


def test_state_machine_transitions(config: dict) -> None:
    assert is_valid_transition("pending", "authorized", config)
    assert is_valid_transition("authorized", "captured", config)
    assert is_valid_transition("captured", "partially_refunded", config)
    assert is_valid_transition("partially_refunded", "refunded", config)
    assert is_valid_transition("authorized", "authorized", config)  # retry self-loop
    assert not is_valid_transition("refunded", "captured", config)
    assert not is_valid_transition("failed", "captured", config)
    assert not is_valid_transition("voided", "authorized", config)
    assert not is_valid_transition("captured", "authorized", config)

    status = pd.DataFrame([
        dict(transaction_id="TXN1", status="authorized", status_timestamp="2024-05-01 10:00:00"),
        dict(transaction_id="TXN1", status="captured", status_timestamp="2024-05-01 10:02:00"),
        dict(transaction_id="TXN1", status="refunded", status_timestamp="2024-05-01 10:01:30"),
    ])
    bad = validate_status_history(status, config)
    # Sorted by timestamp: authorized -> refunded -> captured, the last hop is illegal.
    assert any("refunded -> captured" in v["detail"] for v in bad), bad


Mutation = Callable[[pd.DataFrame, pd.DataFrame, pd.DataFrame],
                    tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]]


def _dup(t: pd.DataFrame, r: pd.DataFrame, p: pd.DataFrame):
    return pd.concat([t, t.iloc[[0]]], ignore_index=True), r, p


def _bad_amount_nonnumeric(t, r, p):
    t["amount"] = t["amount"].astype(object); t.loc[0, "amount"] = "abc"; return t, r, p


def _bad_amount_refund(t, r, p):
    r.loc[0, "refund_amount"] = -5.0; return t, r, p


def _bad_currency(t, r, p):
    t.loc[0, "currency"] = "XYZ"; return t, r, p


def _currency_mismatch(t, r, p):
    t.loc[1, "currency"] = "EUR"; return t, r, p


def _over_refund(t, r, p):
    r.loc[0, "refund_amount"] = 250.0; return t, r, p


def _bad_timestamp(t, r, p):
    t.loc[0, "event_timestamp"] = "not-a-timestamp"; return t, r, p


def _future_timestamp(t, r, p):
    t.loc[0, "event_timestamp"] = "2024-07-01 10:00:00"; return t, r, p


def _refund_before_capture(t, r, p):
    r.loc[0, "refund_timestamp"] = "2024-05-01 09:00:00"; return t, r, p


def _out_of_order(t, r, p):
    t.loc[0, "event_timestamp"], t.loc[1, "event_timestamp"] = (
        t.loc[1, "event_timestamp"], t.loc[0, "event_timestamp"]
    )
    return t, r, p


def _bad_transition(t, r, p):
    p = pd.concat([p, pd.DataFrame([
        dict(transaction_id="TXN1", status="refunded",
             status_timestamp="2024-05-01 10:01:30"),
        dict(transaction_id="TXN1", status="captured",
             status_timestamp="2024-05-01 10:02:00"),
    ])], ignore_index=True)
    return t, r, p


def _unknown_status(t, r, p):
    p.loc[0, "status"] = "banana"; return t, r, p


def _unknown_event_type(t, r, p):
    t.loc[0, "event_type"] = "banana"; return t, r, p


def _unknown_refund_status(t, r, p):
    r.loc[0, "refund_status"] = "banana"; return t, r, p


def _orphan_customer(t, r, p):
    t.loc[0, "customer_id"] = "C999"; return t, r, p


def _orphan_merchant(t, r, p):
    t.loc[0, "merchant_id"] = "M999"; return t, r, p


def _orphan_device(t, r, p):
    t.loc[0, "device_id"] = "D999"; return t, r, p


def _orphan_transaction(t, r, p):
    r.loc[0, "transaction_id"] = "TXN999"; return t, r, p


@pytest.mark.parametrize("mutation,rule", [
    (_dup, "DUPLICATE_EVENT_ID"),
    (_bad_amount_nonnumeric, "AMOUNT_NOT_NUMERIC"),
    (_bad_amount_refund, "AMOUNT_NOT_POSITIVE"),
    (_bad_currency, "CURRENCY_NOT_ALLOWED"),
    (_currency_mismatch, "CURRENCY_MISMATCH"),
    (_over_refund, "REFUND_EXCEEDS_CAPTURED"),
    (_bad_timestamp, "TIMESTAMP_NOT_PARSEABLE"),
    (_future_timestamp, "TIMESTAMP_IN_FUTURE"),
    (_refund_before_capture, "REFUND_BEFORE_CAPTURE"),
    (_out_of_order, "EVENTS_OUT_OF_ORDER"),
    (_bad_transition, "INVALID_STATUS_TRANSITION"),
    (_unknown_status, "UNKNOWN_STATUS_VALUE"),
    (_unknown_event_type, "UNKNOWN_EVENT_TYPE"),
    (_unknown_refund_status, "UNKNOWN_REFUND_STATUS"),
    (_orphan_customer, "ORPHAN_CUSTOMER"),
    (_orphan_merchant, "ORPHAN_MERCHANT"),
    (_orphan_device, "ORPHAN_DEVICE"),
    (_orphan_transaction, "ORPHAN_TRANSACTION"),
])
def test_each_validation_rule_detects_its_issue(
    config: dict, mutation: Mutation, rule: str
) -> None:
    t, r, p, c, m, d = base_tables()
    t, r, p = mutation(t, r, p)
    report = run(config, t, r, p, c, m, d)
    assert report.count(rule) >= 1, f"{rule} not detected; got {report.summary()}"
    assert report.examples(rule)[0]["rule"] == rule
    assert report.examples(rule)[0]["severity"] in {"low", "medium", "high"}


def test_report_summary_shape(config: dict) -> None:
    report = run(config, *base_tables())
    summary = report.summary()
    assert list(summary.columns) == ["rule", "severity", "count", "examples"]
    assert len(summary) >= 18
    assert report.to_dataframe().equals(report.violations)


def test_generated_dataset_reports_injected_families(config: dict, raw: dict[str, Any]) -> None:
    report = validate_data(
        config, raw["transactions"], raw["refunds"], raw["payment_status"],
        raw["customers"], raw["merchants"], raw["device_summary"],
    )
    for rule in [
        "DUPLICATE_EVENT_ID", "AMOUNT_NOT_POSITIVE", "CURRENCY_MISMATCH",
        "REFUND_EXCEEDS_CAPTURED", "TIMESTAMP_IN_FUTURE", "REFUND_BEFORE_CAPTURE",
        "EVENTS_OUT_OF_ORDER", "INVALID_STATUS_TRANSITION", "ORPHAN_CUSTOMER",
        "ORPHAN_MERCHANT", "ORPHAN_DEVICE", "ORPHAN_TRANSACTION",
    ]:
        assert report.count(rule) > 0, rule
