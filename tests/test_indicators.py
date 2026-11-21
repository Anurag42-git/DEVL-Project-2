"""Tests for rolling windows, robust deviations and entity indicators."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pandas as pd

from src.config import get_path
from src.indicators import IndicatorResult, _failed_streak, _max_in_window, _robust_zscores


def test_max_in_window_respects_boundary() -> None:
    base = pd.Timestamp("2024-05-01 12:00:00")
    times = [base, base + timedelta(minutes=10), base + timedelta(minutes=20),
             base + timedelta(minutes=90), base + timedelta(minutes=95)]
    assert _max_in_window(times, timedelta(hours=1)) == 3
    assert _max_in_window(times, timedelta(hours=2)) == 5
    assert _max_in_window([], timedelta(hours=1)) == 0


def test_failed_streak() -> None:
    assert _failed_streak(["failed", "failed", "authorized", "failed"]) == 2
    assert _failed_streak(["captured", "captured"]) == 0
    assert _failed_streak(["failed"] * 6) == 6


def test_robust_zscores_are_zero_for_small_baseline() -> None:
    values = pd.Series([100.0, 5000.0], index=["A", "B"])
    result = _robust_zscores(values, min_samples=8, scale=1.4826)
    assert (result == 0).all()  # too few samples to establish a baseline

    many = pd.Series([100.0] * 10 + [1000.0], index=[f"T{i}" for i in range(11)])
    z = _robust_zscores(many, min_samples=8, scale=1.4826)
    assert z.iloc[-1] > 4.0
    assert z.iloc[0] == 0.0


def test_config_drives_window_values(config: dict[str, Any]) -> None:
    assert get_path(config, "indicators.windows.one_hour") == "1h"
    assert get_path(config, "indicators.windows.seven_day") == "7d"
    assert get_path(config, "indicators.min_baseline_samples") >= 2


def test_entity_indicators_cover_all_record_types(
    indicator_result: IndicatorResult,
) -> None:
    types = set(indicator_result.entities["record_type"])
    assert types == {"customer", "merchant", "device"}
    assert not indicator_result.transactions.empty
    unified = indicator_result.all_records()
    assert set(unified["record_type"]) == {"transaction", "customer", "merchant", "device"}
    assert unified["record_id"].notna().all()


def test_injected_patterns_show_up_in_indicators(
    config: dict[str, Any], raw: dict[str, Any], indicator_result: IndicatorResult
) -> None:
    gt = raw["ground_truth"]
    entities = indicator_result.entities
    txn = indicator_result.transactions

    def ids_for(issue: str) -> list[str]:
        return gt.loc[gt["issue_type"] == issue, "entity_id"].astype(str).tolist()

    def entity_values(record_type: str, entity_ids: list[str], column: str) -> pd.Series:
        subset = entities[
            (entities["record_type"] == record_type)
            & (entities["record_id"].isin(entity_ids))
        ]
        return subset[column]

    burst_threshold = next(
        rule["threshold"] for rule in config["scoring"]["rules"]
        if rule["code"] == "BURST_ACTIVITY"
    )
    burst = entity_values("customer", ids_for("transaction_burst"), "max_txns_1h")
    assert len(burst) > 0 and (burst >= burst_threshold).all()

    failures = entity_values("customer", ids_for("repeated_failed_attempts"), "failed_streak")
    assert len(failures) > 0 and (failures >= 5).all()

    devices = entity_values("device", ids_for("shared_device"), "distinct_customers")
    assert len(devices) > 0 and (devices >= 5).all()

    rounds = entity_values("customer", ids_for("round_amount_pattern"), "round_amount_ratio")
    assert len(rounds) > 0 and (rounds >= 0.6).all()

    retries = ids_for("retry_storm")
    assert (txn[txn["transaction_id"].isin(retries)]["retry_count"] >= 5).all()

    fast = ids_for("fast_refund")
    assert (txn[txn["transaction_id"].isin(fast)]["fast_refund_minutes"] <= 10).all()
