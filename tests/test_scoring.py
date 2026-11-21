"""Tests for explainable scoring, priorities and detection quality."""

from __future__ import annotations

import copy
import json
from typing import Any

import pandas as pd

from src.scoring import (
    ScoringResult,
    build_review_queue,
    distinct_flagged_transactions,
    flagged_transaction_rate,
)


def test_queue_shape_and_explanations(scoring_result: ScoringResult) -> None:
    queue = scoring_result.queue
    assert not queue.empty
    assert {"record_id", "record_type", "score", "priority", "reason_codes",
            "reasons", "outcome"}.issubset(queue.columns)
    assert queue["score"].is_monotonic_decreasing
    for _, row in queue.head(25).iterrows():
        assert row["reason_codes"], row["record_id"]
        parsed = json.loads(row["reasons"])
        assert parsed
        for reason in parsed:
            assert {"code", "explanation", "actual", "threshold", "detail", "weight"} <= reason.keys()
            assert reason["detail"]  # actual value vs threshold is always shown
            assert reason["explanation"]
        assert row["priority"] in {"low", "medium", "high"}


def test_no_fraud_wording(scoring_result: ScoringResult) -> None:
    text = " ".join(scoring_result.queue["reasons"].tolist()).lower()
    assert "fraud" not in text
    text_all = " ".join(
        str(reason["explanation"])
        for rule in scoring_result.methodology["rules"]
        for reason in [rule]
    ).lower()
    assert "fraud" not in text_all


def test_priority_bands_follow_config(scoring_result: ScoringResult, config: dict) -> None:
    queue = scoring_result.queue
    high = queue[queue["priority"] == "high"]
    medium = queue[queue["priority"] == "medium"]
    assert (high["score"] >= config["scoring"]["high_priority_score"]).all()
    assert (medium["score"] >= config["scoring"]["medium_priority_score"]).all()
    assert (medium["score"] < config["scoring"]["high_priority_score"]).all()


def test_thresholds_are_config_driven(
    config: dict, indicator_result
) -> None:
    strict = copy.deepcopy(config)
    strict["scoring"]["flag_min_score"] = 10_000
    empty = build_review_queue(indicator_result, strict)
    assert empty.queue.empty

    changed = copy.deepcopy(config)
    for rule in changed["scoring"]["rules"]:
        if rule["code"] == "DUPLICATE_EVENT":
            rule["weight"] = 99
    heavier = build_review_queue(indicator_result, changed)
    base = build_review_queue(indicator_result, config)
    dupe_base = base.queue[base.queue["reason_codes"].apply(
        lambda codes: "DUPLICATE_EVENT" in codes
    )]["score"]
    dupe_heavy = heavier.queue[heavier.queue["reason_codes"].apply(
        lambda codes: "DUPLICATE_EVENT" in codes
    )]["score"]
    assert not dupe_base.empty and not dupe_heavy.empty
    assert dupe_heavy.max() > dupe_base.max()


def test_secondary_signal_never_the_only_reason(
    config: dict, indicator_result
) -> None:
    enabled = copy.deepcopy(config)
    enabled["scoring"]["isolation_forest"]["enabled"] = True
    result = build_review_queue(indicator_result, enabled)
    for codes in result.queue["reason_codes"]:
        assert any(code != "STATISTICAL_OUTLIER_SECONDARY" for code in codes)


def test_injected_issue_recall(scoring_result: ScoringResult, raw: dict[str, Any]) -> None:
    gt = raw["ground_truth"]
    gt = gt[gt["expected_reason_code"] != ""]
    flagged_pairs = set()
    for _, row in scoring_result.queue.iterrows():
        for code in row["reason_codes"]:
            flagged_pairs.add((row["record_id"], code))
    expected = set(zip(gt["entity_id"].astype(str), gt["expected_reason_code"]))
    hits = expected & flagged_pairs
    recall = len(hits) / len(expected)
    assert recall >= 0.75, f"recall={recall:.3f}; missed {len(expected - hits)}"
    # Reason codes are part of a vocabulary defined in config, not arbitrary text.
    assert set(scoring_result.reason_summary["reason_code"]).issubset(
        {r["code"] for r in scoring_result.methodology["rules"]}
        | {"STATISTICAL_OUTLIER_SECONDARY"}
    )


def test_missing_refund_gap_does_not_trigger_fast_refund(
    scoring_result: ScoringResult, indicator_result
) -> None:
    """NaN means 'no refund observed'; it must never read as a zero-minute gap."""
    no_refund = set(
        indicator_result.transactions.loc[
            indicator_result.transactions["fast_refund_minutes"].isna(), "transaction_id"
        ].astype(str)
    )
    assert len(no_refund) > 100  # the regression affected the majority of transactions
    flagged = scoring_result.queue[scoring_result.queue["record_type"] == "transaction"]
    bad = flagged[
        flagged["record_id"].isin(no_refund)
        & flagged["reason_codes"].apply(lambda codes: "FAST_REFUND" in codes)
    ]
    assert bad.empty, bad[["record_id", "reason_codes"]].head(5).to_dict("records")


def test_flagged_count_is_distinct_and_bounded(
    scoring_result: ScoringResult, reconciled
) -> None:
    queue = scoring_result.queue
    distinct = distinct_flagged_transactions(queue)
    assert 0 < distinct <= len(reconciled.ledger)
    assert distinct <= len(queue)  # entity records add rows, not transactions
    assert queue[queue["record_type"] == "transaction"]["record_id"].is_unique


def test_flag_rate_is_realistic_and_recall_retained(
    scoring_result: ScoringResult, reconciled, raw: dict[str, Any]
) -> None:
    rate = flagged_transaction_rate(scoring_result.queue, len(reconciled.ledger))
    assert 0.05 <= rate <= 0.15, f"flag rate {rate:.1%}"

    gt = raw["ground_truth"]
    gt = gt[gt["expected_reason_code"] != ""]
    flagged_pairs = {
        (row["record_id"], code)
        for _, row in scoring_result.queue.iterrows()
        for code in row["reason_codes"]
    }
    expected = set(zip(gt["entity_id"].astype(str), gt["expected_reason_code"]))
    assert len(expected & flagged_pairs) / len(expected) >= 0.75


def test_one_flag_can_carry_multiple_reason_codes(scoring_result: ScoringResult) -> None:
    multi = scoring_result.queue[
        scoring_result.queue["reason_codes"].apply(len) > 1
    ]
    assert not multi.empty
