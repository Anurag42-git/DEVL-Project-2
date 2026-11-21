"""Rule-based data validation with an explicit payment-status state machine.

The output is a :class:`ValidationReport` containing one long-form table of
violations and a summary table with rule name, count, severity and example
rows. The dashboard and audit report consume the same object.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pandas as pd

from .config import get_path, load_config, require_path
from .utils import json_dumps, parse_datetime, to_iso

VIOLATION_COLUMNS = ["rule", "severity", "source_file", "record_id", "detail", "example"]


@dataclass
class ValidationReport:
    """Result of running all validation rules against a set of raw tables."""

    violations: pd.DataFrame
    generated_at: str
    rule_order: list[str]
    severity_map: dict[str, str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.severity_map is None:
            self.severity_map = {}

    def count(self, rule: str) -> int:
        """Number of violations recorded for ``rule``."""
        if self.violations.empty:
            return 0
        return int((self.violations["rule"] == rule).sum())

    def examples(self, rule: str, limit: int = 3) -> list[dict[str, Any]]:
        """Up to ``limit`` example rows for a rule, as plain dictionaries."""
        if self.violations.empty:
            return []
        subset = self.violations[self.violations["rule"] == rule].head(limit)
        return subset.to_dict(orient="records")

    def summary(self) -> pd.DataFrame:
        """Summary with rule, severity, violation count and example records."""
        rows = []
        for rule in self.rule_order:
            examples = self.examples(rule)
            rows.append(
                {
                    "rule": rule,
                    "severity": self.severity_map.get(rule, "medium"),
                    "count": self.count(rule),
                    "examples": "; ".join(
                        f"{e.get('record_id')}: {e.get('detail')}" for e in examples
                    ) or "-",
                }
            )
        return pd.DataFrame(rows)

    def set_severities(self, severities: dict[str, str]) -> None:
        """Attach the configured severity map (used by :meth:`summary`)."""
        self.severity_map = severities

    def to_dataframe(self) -> pd.DataFrame:
        """Return the long-form violations table."""
        return self.violations.copy()


def is_valid_transition(previous: str, current: str, config: dict[str, Any]) -> bool:
    """Return True if ``previous -> current`` is allowed by the configured state machine."""
    transitions = get_path(config, "validation.allowed_transitions", {}) or {}
    return current in list(transitions.get(previous, []))


def validate_status_history(
    payment_status: pd.DataFrame, config: dict[str, Any]
) -> list[dict[str, Any]]:
    """Check every transaction's status sequence against the state machine.

    Rows are ordered by ``status_timestamp`` with the original file order as a
    stable tie-breaker. Terminal states (``failed``/``voided``/``refunded``)
    have no outgoing transitions in ``config.yaml``.
    """
    allowed = set(get_path(config, "validation.allowed_statuses", []) or [])
    violations: list[dict[str, Any]] = []
    if payment_status.empty:
        return violations

    frame = payment_status.copy()
    frame["_ts"] = parse_datetime(frame["status_timestamp"])
    frame["_order"] = range(len(frame))
    frame = frame.sort_values(["transaction_id", "_ts", "_order"], kind="stable")

    for txn_id, group in frame.groupby("transaction_id", sort=False):
        previous: str | None = None
        for row in group.to_dict(orient="records"):
            status = str(row["status"])
            if status not in allowed:
                continue  # reported by UNKNOWN_STATUS_VALUE instead
            if previous is not None and not is_valid_transition(previous, status, config):
                violations.append(
                    _violation(
                        "INVALID_STATUS_TRANSITION", config, "payment_status.csv",
                        str(txn_id),
                        f"illegal transition {previous} -> {status} at "
                        f"{to_iso(row['_ts'])}",
                        row,
                    )
                )
            previous = status
    return violations


def _violation(
    rule: str,
    config: dict[str, Any],
    source: str,
    record_id: str,
    detail: str,
    example: dict[str, Any] | None = None,
) -> dict[str, Any]:
    severity = get_path(config, f"validation.severity.{rule}", "medium")
    clean = {
        key: to_iso(value)
        for key, value in (example or {}).items()
        if not str(key).startswith("_")
    }
    return {
        "rule": rule,
        "severity": severity,
        "source_file": source,
        "record_id": str(record_id),
        "detail": detail,
        "example": json_dumps(clean),
    }


def validate_data(
    config: dict[str, Any] | None = None,
    transactions: pd.DataFrame | None = None,
    refunds: pd.DataFrame | None = None,
    payment_status: pd.DataFrame | None = None,
    customers: pd.DataFrame | None = None,
    merchants: pd.DataFrame | None = None,
    device_summary: pd.DataFrame | None = None,
    now: pd.Timestamp | None = None,
) -> ValidationReport:
    """Run every validation rule and return a consolidated report.

    Tables default to loading from the paths configured in ``config.yaml`` so
    the dashboard can call ``validate_data(config)`` without manual IO.
    """
    cfg = config or load_config()
    if transactions is None or refunds is None or payment_status is None:
        from .utils import read_csv
        from .config import data_file

        transactions = transactions if transactions is not None else read_csv(
            data_file(cfg, "transactions")
        )
        refunds = refunds if refunds is not None else read_csv(data_file(cfg, "refunds"))
        payment_status = payment_status if payment_status is not None else read_csv(
            data_file(cfg, "payment_status")
        )
    customers = customers if customers is not None else pd.DataFrame(columns=["customer_id"])
    merchants = merchants if merchants is not None else pd.DataFrame(columns=["merchant_id"])
    device_summary = device_summary if device_summary is not None else pd.DataFrame(
        columns=["device_id"]
    )

    now = now or pd.Timestamp.now()
    tolerance = timedelta(minutes=int(get_path(cfg, "validation.future_tolerance_minutes", 120)))
    allowed_currencies = set(get_path(cfg, "validation.allowed_currencies", []) or [])
    allowed_event_types = set(get_path(cfg, "validation.allowed_event_types", []) or [])
    allowed_statuses = set(get_path(cfg, "validation.allowed_statuses", []) or [])
    allowed_refund_statuses = set(get_path(cfg, "validation.allowed_refund_statuses", []) or [])
    capture_statuses = set(get_path(cfg, "validation.capture_statuses", []) or [])
    violations: list[dict[str, Any]] = []

    txn = transactions.reset_index(drop=True).copy()
    rfd = refunds.reset_index(drop=True).copy()
    pst = payment_status.reset_index(drop=True).copy()

    # --- amounts -------------------------------------------------------------
    txn_amount = pd.to_numeric(txn.get("amount"), errors="coerce")
    rfd_amount = pd.to_numeric(rfd.get("refund_amount"), errors="coerce")
    for idx in txn.index[txn["amount"].notna() & txn_amount.isna()]:
        violations.append(_violation("AMOUNT_NOT_NUMERIC", cfg, "transactions.csv",
                                     str(txn.at[idx, "event_id"]), "amount is not numeric",
                                     txn.loc[idx].to_dict()))
    for idx in rfd.index[rfd["refund_amount"].notna() & rfd_amount.isna()]:
        violations.append(_violation("AMOUNT_NOT_NUMERIC", cfg, "refunds.csv",
                                     str(rfd.at[idx, "refund_id"]), "refund_amount is not numeric",
                                     rfd.loc[idx].to_dict()))
    for idx in txn.index[txn_amount.notna() & (txn_amount <= 0)]:
        violations.append(_violation("AMOUNT_NOT_POSITIVE", cfg, "transactions.csv",
                                     str(txn.at[idx, "event_id"]), f"amount={txn_amount.at[idx]}",
                                     txn.loc[idx].to_dict()))
    for idx in rfd.index[rfd_amount.notna() & (rfd_amount <= 0)]:
        violations.append(_violation("AMOUNT_NOT_POSITIVE", cfg, "refunds.csv",
                                     str(rfd.at[idx, "refund_id"]),
                                     f"refund_amount={rfd_amount.at[idx]}",
                                     rfd.loc[idx].to_dict()))

    # --- currency ------------------------------------------------------------
    for idx in txn.index[~txn["currency"].isin(allowed_currencies)]:
        violations.append(_violation("CURRENCY_NOT_ALLOWED", cfg, "transactions.csv",
                                     str(txn.at[idx, "event_id"]),
                                     f"currency={txn.at[idx, 'currency']}", txn.loc[idx].to_dict()))
    if allowed_currencies:
        for txn_id, group in txn.groupby("transaction_id", sort=False):
            currencies = set(group["currency"].dropna().astype(str))
            if len(currencies) > 1:
                violations.append(_violation(
                    "CURRENCY_MISMATCH", cfg, "transactions.csv", str(txn_id),
                    "currencies=" + ",".join(sorted(currencies)),
                    {"transaction_id": txn_id, "currencies": sorted(currencies)},
                ))

    # --- timestamps ----------------------------------------------------------
    txn_ts = parse_datetime(txn["event_timestamp"])
    rfd_ts = parse_datetime(rfd["refund_timestamp"])
    pst_ts = parse_datetime(pst["status_timestamp"])
    for frame, series, source, id_col, ts_col in [
        (txn, txn_ts, "transactions.csv", "event_id", "event_timestamp"),
        (rfd, rfd_ts, "refunds.csv", "refund_id", "refund_timestamp"),
        (pst, pst_ts, "payment_status.csv", "transaction_id", "status_timestamp"),
    ]:
        for idx in frame.index[series.isna() & frame[ts_col].notna()]:
            violations.append(_violation("TIMESTAMP_NOT_PARSEABLE", cfg, source,
                                         str(frame.at[idx, id_col]),
                                         f"unparseable {ts_col}={frame.at[idx, ts_col]}",
                                         frame.loc[idx].to_dict()))
        for idx in frame.index[series.notna() & (series > now + tolerance)]:
            violations.append(_violation("TIMESTAMP_IN_FUTURE", cfg, source,
                                         str(frame.at[idx, id_col]),
                                         f"{ts_col}={to_iso(series.at[idx])} is after {to_iso(now)}",
                                         frame.loc[idx].to_dict()))

    # --- refund/order consistency -------------------------------------------
    captured = txn[txn["status"].isin(capture_statuses)].drop_duplicates(subset=["event_id"])
    capture_amount = captured.groupby("transaction_id")["amount"].apply(
        lambda s: pd.to_numeric(s, errors="coerce").sum(min_count=1)
    )
    capture_first_time = (
        pd.DataFrame({"transaction_id": captured["transaction_id"], "_ts": parse_datetime(captured["event_timestamp"])})
        .groupby("transaction_id")["_ts"].min()
    )
    completed = rfd[rfd["refund_status"] == "completed"]
    refund_total = completed.groupby("transaction_id")["refund_amount"].apply(
        lambda s: pd.to_numeric(s, errors="coerce").sum()
    )
    for txn_id, total in refund_total.items():
        cap = capture_amount.get(txn_id, 0.0)
        if pd.notna(total) and float(total) > float(cap if pd.notna(cap) else 0.0):
            violations.append(_violation(
                "REFUND_EXCEEDS_CAPTURED", cfg, "refunds.csv", str(txn_id),
                f"completed refunds={float(total):.2f} exceed captured={float(cap or 0):.2f}",
                {"transaction_id": txn_id, "refund_total": float(total), "captured": cap},
            ))
    for _, row in completed.iterrows():
        cap_time = capture_first_time.get(row["transaction_id"], pd.NaT)
        refund_time = parse_datetime(pd.Series([row["refund_timestamp"]])).iloc[0]
        if pd.notna(cap_time) and pd.notna(refund_time) and refund_time < cap_time:
            violations.append(_violation(
                "REFUND_BEFORE_CAPTURE", cfg, "refunds.csv", str(row["refund_id"]),
                f"refund at {to_iso(refund_time)} before capture at {to_iso(cap_time)}",
                row.to_dict(),
            ))

    event_frame = pd.DataFrame({
        "transaction_id": txn["transaction_id"],
        "event_type": txn["event_type"],
        "_ts": txn_ts,
    })
    for txn_id, group in event_frame.groupby("transaction_id", sort=False):
        auth_times = group.loc[group["event_type"] == "authorization", "_ts"]
        others = group.loc[group["event_type"].isin(["capture", "retry", "void"]), "_ts"]
        if auth_times.notna().any() and others.notna().any() and others.min() < auth_times.min():
            violations.append(_violation(
                "EVENTS_OUT_OF_ORDER", cfg, "transactions.csv", str(txn_id),
                f"first non-auth event {to_iso(others.min())} precedes "
                f"first authorization {to_iso(auth_times.min())}",
                {"transaction_id": txn_id},
            ))

    # --- categorical values and state machine -------------------------------
    for idx in txn.index[~txn["event_type"].isin(allowed_event_types)]:
        violations.append(_violation("UNKNOWN_EVENT_TYPE", cfg, "transactions.csv",
                                     str(txn.at[idx, "event_id"]),
                                     f"event_type={txn.at[idx, 'event_type']}", txn.loc[idx].to_dict()))
    for frame, column, source, id_col, rule in [
        (txn, "status", "transactions.csv", "event_id", "UNKNOWN_STATUS_VALUE"),
        (pst, "status", "payment_status.csv", "transaction_id", "UNKNOWN_STATUS_VALUE"),
        (rfd, "refund_status", "refunds.csv", "refund_id", "UNKNOWN_REFUND_STATUS"),
    ]:
        allowed_set = allowed_refund_statuses if rule == "UNKNOWN_REFUND_STATUS" else allowed_statuses
        for idx in frame.index[~frame[column].isin(allowed_set)]:
            violations.append(_violation(rule, cfg, source, str(frame.at[idx, id_col]),
                                         f"{column}={frame.at[idx, column]}",
                                         frame.loc[idx].to_dict()))
    violations.extend(validate_status_history(pst, cfg))

    # --- referential integrity ----------------------------------------------
    customer_ids = set(customers.get("customer_id", pd.Series(dtype=str)).astype(str))
    merchant_ids = set(merchants.get("merchant_id", pd.Series(dtype=str)).astype(str))
    device_ids = set(device_summary.get("device_id", pd.Series(dtype=str)).astype(str))
    for column, known, rule in [
        ("customer_id", customer_ids, "ORPHAN_CUSTOMER"),
        ("merchant_id", merchant_ids, "ORPHAN_MERCHANT"),
        ("device_id", device_ids, "ORPHAN_DEVICE"),
    ]:
        bad = txn[~txn[column].astype(str).isin(known)]
        for txn_id, group in bad.groupby("transaction_id", sort=False):
            values = sorted(set(group[column].astype(str)))
            violations.append(_violation(
                rule, cfg, "transactions.csv", str(txn_id),
                f"unknown {column}: {', '.join(values)}",
                {"transaction_id": txn_id, column: values},
            ))
    known_txns = set(txn["transaction_id"].astype(str))
    for frame, source, id_col in [
        (rfd, "refunds.csv", "refund_id"),
        (pst, "payment_status.csv", "transaction_id"),
    ]:
        bad = frame[~frame["transaction_id"].astype(str).isin(known_txns)]
        for txn_id, group in bad.groupby("transaction_id", sort=False):
            violations.append(_violation(
                "ORPHAN_TRANSACTION", cfg, source, str(txn_id),
                f"{len(group)} row(s) reference unknown transaction; "
                f"e.g. {id_col}={group.iloc[0][id_col]}",
                group.iloc[0].to_dict(),
            ))

    # --- duplicate event ids -------------------------------------------------
    duplicate_ids = txn["event_id"][txn["event_id"].duplicated(keep=False)]
    for event_id, group in txn[txn["event_id"].isin(duplicate_ids)].groupby("event_id"):
        violations.append(_violation(
            "DUPLICATE_EVENT_ID", cfg, "transactions.csv", str(event_id),
            f"{len(group)} rows share this event id",
            group.iloc[0].to_dict(),
        ))

    result = pd.DataFrame(violations, columns=VIOLATION_COLUMNS)
    if not result.empty:
        result = result.sort_values(["rule", "record_id"]).reset_index(drop=True)
    report = ValidationReport(result, to_iso(now), list(
        get_path(cfg, "validation.severity", {}) or {}
    ))
    report.set_severities(dict(get_path(cfg, "validation.severity", {}) or {}))
    return report
