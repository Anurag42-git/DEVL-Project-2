"""Explainable indicators computed per transaction, customer, merchant and device.

Every threshold used here comes from ``config.yaml``. Indicators describe
*unusual patterns*; they never assert fraud. Scoring combines them into review
flags in :mod:`src.scoring`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .config import get_path, load_config
from .utils import parse_datetime, safe_divide
from .validate import ValidationReport

ENTITY_COLUMN = {"customer": "customer_id", "merchant": "merchant_id", "device": "device_id"}

TXN_FIELD_FROM_RULE = {
    "AMOUNT_NOT_POSITIVE": "invalid_amount_count",
    "AMOUNT_NOT_NUMERIC": "invalid_amount_count",
    "TIMESTAMP_IN_FUTURE": "future_timestamp_count",
    "EVENTS_OUT_OF_ORDER": "out_of_order_count",
    "CURRENCY_MISMATCH": "currency_mismatch_count",
    "INVALID_STATUS_TRANSITION": "invalid_transition_count",
    "ORPHAN_CUSTOMER": "orphan_reference_count",
    "ORPHAN_MERCHANT": "orphan_reference_count",
    "ORPHAN_DEVICE": "orphan_reference_count",
    "ORPHAN_TRANSACTION": "orphan_reference_count",
}

ENTITY_FIELDS = [
    "record_type", "record_id", "transaction_count", "captured_amount", "total_refunded",
    "refund_ratio_amount", "refund_count_ratio", "failed_event_count", "total_event_count",
    "failure_rate", "failed_streak", "max_amount_zscore", "max_txns_1h", "max_txns_24h",
    "max_txns_7d", "distinct_customers", "max_retry_count", "round_amount_ratio",
    "invalid_amount_count", "future_timestamp_count", "out_of_order_count",
    "currency_mismatch_count", "invalid_transition_count", "orphan_reference_count",
    "over_refund_amount", "duplicate_events_removed",
]

TXN_FIELDS = [
    "transaction_id", "amount_zscore_abs", "fast_refund_minutes",
    "invalid_amount_count", "future_timestamp_count", "out_of_order_count",
    "currency_mismatch_count", "invalid_transition_count", "orphan_reference_count",
    "over_refund_amount", "duplicate_events_removed", "retry_count",
    "refund_ratio_amount", "max_txns_1h", "failed_streak",
]


@dataclass
class IndicatorResult:
    """Transaction-level and entity-level indicator tables."""

    transactions: pd.DataFrame
    entities: pd.DataFrame
    config: dict[str, Any]

    def for_type(self, record_type: str) -> pd.DataFrame:
        """Return indicator rows for one entity type."""
        if self.entities.empty:
            return pd.DataFrame(columns=ENTITY_FIELDS)
        return self.entities[self.entities["record_type"] == record_type].reset_index(drop=True)

    def all_records(self) -> pd.DataFrame:
        """Return a unified frame of every scorable record (transaction + entities)."""
        txn = self.transactions.copy()
        txn["record_type"] = "transaction"
        txn["record_id"] = txn["transaction_id"]
        extras: list[str] = []
        for frame in (txn, self.entities):
            for column in frame.columns:
                if column in {"record_type", "record_id", "transaction_id"}:
                    continue
                if column not in extras:
                    extras.append(column)
        columns = ["record_type", "record_id"] + extras
        frames = []
        for frame in (txn, self.entities):
            part = frame.reindex(columns=columns).copy()
            for column in columns:
                if column not in frame.columns:
                    part[column] = 0
            # Keep missing values as NaN. A missing indicator means "not observed"
            # (e.g. no refund => no refund gap); converting it to 0 falsely triggers
            # rules such as FAST_REFUND (`0 <= 10`). Scoring treats NaN as no match.
            frames.append(part[columns])
        return pd.concat(frames, ignore_index=True)


def _max_in_window(times: Iterable[pd.Timestamp], window: timedelta) -> int:
    """Largest number of events inside any ``window``-length interval."""
    values = sorted(t for t in times if pd.notna(t))
    if not values:
        return 0
    best = 0
    left = 0
    for right, current in enumerate(values):
        while current - values[left] > window:
            left += 1
        best = max(best, right - left + 1)
    return best


def _failed_streak(statuses: Iterable[str]) -> int:
    """Longest run of consecutive failed attempts in timestamp order."""
    best = run = 0
    for status in statuses:
        run = run + 1 if status == "failed" else 0
        best = max(best, run)
    return best


def _round_amount_ratio(amounts: pd.Series, denominators: list[float]) -> float:
    if amounts.empty:
        return 0.0
    values = pd.to_numeric(amounts, errors="coerce").dropna()
    if values.empty:
        return 0.0
    hits = 0
    for value in values:
        if any(d > 0 and abs(float(value) % d) < 1e-6 for d in denominators):
            hits += 1
    return hits / len(values)


def _robust_zscores(values: pd.Series, min_samples: int, scale: float) -> pd.Series:
    """Robust MAD-based z-scores; returns zeros for small/unstable baselines."""
    result = pd.Series(0.0, index=values.index, dtype=float)
    numeric = pd.to_numeric(values, errors="coerce")
    valid = numeric.dropna()
    if len(valid) < min_samples:
        return result
    median = float(valid.median())
    deviations = (valid - median).abs()
    mad = float(deviations.median())
    if mad <= 1e-9:
        # Degenerate MAD (e.g. a long run of identical amounts): fall back to
        # the mean absolute deviation so a single outlier is still visible.
        mad = float(deviations.mean())
        scale = 1.0
    if mad <= 1e-9:
        return result
    result.loc[valid.index] = (valid - median) / (scale * mad)
    return result


def compute_indicators(
    config: dict[str, Any] | None = None,
    ledger: pd.DataFrame | None = None,
    transactions: pd.DataFrame | None = None,
    refunds: pd.DataFrame | None = None,
    validation: ValidationReport | None = None,
) -> IndicatorResult:
    """Compute transaction-level and entity-level indicators."""
    cfg = config or load_config()
    if ledger is None or transactions is None:
        from .reconcile import reconcile_from_config

        reconciled = reconcile_from_config(cfg)
        ledger = reconciled.ledger
        transactions = reconciled.deduped_events
    if refunds is None:
        from .config import data_file
        from .utils import read_csv

        refunds = read_csv(data_file(cfg, "refunds"))

    windows_cfg = get_path(cfg, "indicators.windows", {}) or {}
    windows = {
        "1h": pd.to_timedelta(windows_cfg.get("one_hour", "1h")),
        "24h": pd.to_timedelta(windows_cfg.get("twenty_four_hour", "24h")),
        "7d": pd.to_timedelta(windows_cfg.get("seven_day", "7d")),
    }
    min_samples = int(get_path(cfg, "indicators.min_baseline_samples", 8))
    mad_scale = float(get_path(cfg, "indicators.mad_scale", 1.4826))
    denominators = [float(d) for d in get_path(cfg, "indicators.round_denominators", [100, 500, 1000])]

    led = ledger.copy()
    led["_first_ts"] = parse_datetime(led["first_event_time"])
    events = transactions.copy()
    events["_ts"] = parse_datetime(events["event_timestamp"])
    rfd = refunds.copy()
    rfd["_ts"] = parse_datetime(rfd["refund_timestamp"])
    rfd["_amount"] = pd.to_numeric(rfd["refund_amount"], errors="coerce").fillna(0.0)

    # ---- transaction-level fields -----------------------------------------
    txn = pd.DataFrame({"transaction_id": led["transaction_id"]}).set_index("transaction_id")
    txn["retry_count"] = led.set_index("transaction_id")["retry_count"]
    txn["refund_ratio_amount"] = led.set_index("transaction_id")["refund_ratio"]
    txn["over_refund_amount"] = led.set_index("transaction_id")["over_refund_amount"]
    txn["duplicate_events_removed"] = led.set_index("transaction_id")["duplicate_events_removed"]
    for field in TXN_FIELD_FROM_RULE.values():
        txn[field] = 0
    if validation is not None and not validation.violations.empty:
        event_to_txn = dict(zip(events["event_id"].astype(str),
                                events["transaction_id"].astype(str)))
        for rule, field in TXN_FIELD_FROM_RULE.items():
            subset = validation.violations[validation.violations["rule"] == rule]
            if subset.empty:
                continue
            # Some rules report the event_id rather than the transaction_id;
            # translate those to the owning transaction so flags line up.
            record_ids = subset["record_id"].astype(str).map(
                lambda value: event_to_txn.get(value, value)
            )
            counts = record_ids.value_counts()
            txn[field] = txn[field] + txn.index.map(counts).fillna(0).astype(int)

    # Robust amount deviation uses each customer's own captured amounts.
    txn["amount_zscore_abs"] = 0.0
    if "customer_id" in led.columns:
        for customer, group in led.groupby("customer_id", sort=False):
            if not isinstance(customer, str) or not customer:
                continue
            z = _robust_zscores(
                group.set_index("transaction_id")["captured_amount"], min_samples, mad_scale
            )
            txn.loc[z.index, "amount_zscore_abs"] = z.abs().values

    # Minimum non-negative gap between capture and completed refund.
    captures = events[events["event_type"] == "capture"].copy()
    capture_time = captures.groupby("transaction_id")["_ts"].min()
    gaps: dict[str, float] = {}
    completed = rfd[rfd["refund_status"] == "completed"]
    for txn_id, refund_time in zip(completed["transaction_id"], completed["_ts"]):
        cap = capture_time.get(txn_id, pd.NaT)
        if pd.notna(cap) and pd.notna(refund_time):
            minutes = (refund_time - cap).total_seconds() / 60.0
            if 0 <= minutes and (txn_id not in gaps or minutes < gaps[txn_id]):
                gaps[txn_id] = minutes
    txn["fast_refund_minutes"] = txn.index.map(gaps)
    txn["max_txns_1h"] = 0
    txn["failed_streak"] = 0
    txn = txn.reset_index()

    # ---- entity-level fields ----------------------------------------------
    entity_rows: list[dict[str, Any]] = []
    entity_types = [str(t) for t in get_path(cfg, "indicators.entity_types", ["customer", "merchant", "device"])]
    for record_type in entity_types:
        column = ENTITY_COLUMN[record_type]
        valid_ledger = led[led[column].astype(str).str.len() > 0].copy()
        for record_id, group in valid_ledger.groupby(column, sort=False):
            ids = set(group["transaction_id"].astype(str))
            group_events = events[events["transaction_id"].astype(str).isin(ids)]
            event_times = [t for t in group["_first_ts"] if pd.notna(t)]
            txn_fields = txn[txn["transaction_id"].astype(str).isin(ids)]
            status_order = group_events.sort_values(["_ts"], kind="stable")["status"]
            row: dict[str, Any] = {
                "record_type": record_type,
                "record_id": str(record_id),
                "transaction_count": int(len(group)),
                "captured_amount": float(group["captured_amount"].sum()),
                "total_refunded": float(group["total_refunded"].sum()),
                "refund_count_ratio": safe_divide(
                    float(group["refund_count"].sum()), float(len(group))
                ),
                "failed_event_count": int((status_order == "failed").sum()),
                "total_event_count": int(len(group_events)),
                "failed_streak": _failed_streak(status_order),
                "max_amount_zscore": float(txn_fields["amount_zscore_abs"].max()) if not txn_fields.empty else 0.0,
                "max_txns_1h": _max_in_window(event_times, windows["1h"]),
                "max_txns_24h": _max_in_window(event_times, windows["24h"]),
                "max_txns_7d": _max_in_window(event_times, windows["7d"]),
                "distinct_customers": int(group_events["customer_id"].nunique())
                    if record_type == "device" else int(group["customer_id"].nunique()),
                "max_retry_count": int(group["retry_count"].max()) if not group.empty else 0,
                "round_amount_ratio": _round_amount_ratio(group["captured_amount"], denominators),
                "over_refund_amount": float(group["over_refund_amount"].sum()),
                "duplicate_events_removed": int(group["duplicate_events_removed"].sum()),
            }
            for field in TXN_FIELD_FROM_RULE.values():
                row[field] = int(txn_fields[field].sum()) if not txn_fields.empty else 0
            row["refund_ratio_amount"] = safe_divide(
                row["total_refunded"], row["captured_amount"]
            )
            row["failure_rate"] = safe_divide(row["failed_event_count"], row["total_event_count"])
            entity_rows.append(row)

    entities = pd.DataFrame(entity_rows, columns=ENTITY_FIELDS)
    if entities.empty:
        entities = pd.DataFrame(columns=ENTITY_FIELDS)
    return IndicatorResult(
        transactions=txn[TXN_FIELDS], entities=entities, config=cfg
    )
