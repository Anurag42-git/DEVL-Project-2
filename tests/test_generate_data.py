"""Tests for seeded generation and deliberate injections."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.config import ground_truth_file
from src.generate_data import DataGenerator, GeneratedData, generate_data


def test_schema_and_reproducible_seed(config: dict, generated: GeneratedData) -> None:
    expected_columns = {
        "customers": ["customer_id", "signup_date", "country", "risk_segment"],
        "merchants": ["merchant_id", "category", "country", "onboarding_date"],
        "transactions": [
            "event_id", "transaction_id", "customer_id", "merchant_id", "amount",
            "currency", "event_timestamp", "event_type", "status", "device_id",
        ],
        "refunds": [
            "refund_id", "transaction_id", "refund_amount", "refund_timestamp", "refund_status"
        ],
        "payment_status": ["transaction_id", "status", "status_timestamp"],
        "device_summary": [
            "device_id", "customer_count", "first_seen", "last_seen", "failed_attempt_count"
        ],
    }
    frames = {
        "customers": generated.customers,
        "merchants": generated.merchants,
        "transactions": generated.transactions,
        "refunds": generated.refunds,
        "payment_status": generated.payment_status,
        "device_summary": generated.device_summary,
    }
    for name, columns in expected_columns.items():
        assert list(frames[name].columns) == columns, name
        assert not frames[name].empty, name

    second = DataGenerator(config).generate()
    pd.testing.assert_frame_equal(
        generated.transactions.reset_index(drop=True),
        second.transactions.reset_index(drop=True),
    )
    pd.testing.assert_frame_equal(
        generated.ground_truth.reset_index(drop=True),
        second.ground_truth.reset_index(drop=True),
    )


def test_files_written_including_hidden_truth(
    config: dict, generated: GeneratedData
) -> None:
    for path in generated.paths.values():
        assert Path(path).is_file(), path
    assert ground_truth_file(config).name.startswith(".")
    assert generated.ground_truth["issue_id"].is_unique


def test_all_required_injection_families_present(generated: GeneratedData) -> None:
    families = set(generated.ground_truth["issue_type"])
    expected = {
        "duplicate_event", "retry_storm", "partial_refund_high", "over_refund",
        "invalid_status_transition", "nonpositive_amount", "future_timestamp",
        "out_of_order_timestamp", "orphan_customer", "orphan_merchant", "orphan_device",
        "orphan_refund_reference", "orphan_status_reference", "transaction_burst",
        "repeated_failed_attempts", "shared_device", "round_amount_pattern",
        "fast_refund", "currency_mismatch",
    }
    assert expected <= families, expected - families
    assert (generated.ground_truth["expected_reason_code"] != "").sum() >= 60


def test_specific_corruptions_are_observable(generated: GeneratedData) -> None:
    txns = generated.transactions
    assert txns["event_id"].duplicated().any(), "duplicate event ids must exist"
    assert (txns["amount"] <= 0).any(), "non-positive amounts must exist"
    assert (txns["event_type"] == "retry").sum() > 50, "retries must exist"
    assert generated.refunds["refund_id"].duplicated().sum() == 0
    assert (generated.refunds["transaction_id"] == "TXN-UNKNOWN").any()
    assert (generated.payment_status["transaction_id"] == "TXN-ORPHAN-STATUS").any()
    assert (generated.device_summary["customer_count"] >= 5).any()
    assert (generated.transactions["device_id"] == "DEV-UNKNOWN").any()


def test_over_refunds_exceed_captures(generated: GeneratedData) -> None:
    over = generated.ground_truth[
        generated.ground_truth["issue_type"] == "over_refund"
    ]
    assert not over.empty
    for txn in over["entity_id"]:
        captured = generated.transactions[
            (generated.transactions["transaction_id"] == txn)
            & (generated.transactions["event_type"] == "capture")
        ]["amount"].sum()
        refunded = generated.refunds[
            (generated.refunds["transaction_id"] == txn)
            & (generated.refunds["refund_status"] == "completed")
        ]["refund_amount"].sum()
        assert refunded > captured, (txn, refunded, captured)


def test_generate_data_wrapper_matches_class(config: dict) -> None:
    result = generate_data(config)
    assert len(result.ground_truth) > 0
    assert len(result.transactions) > 1000
