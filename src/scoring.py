"""Transparent, rule-based scoring and the explainable review queue.

Every flag is backed by one or more reason codes with a plain-English
explanation and the actual value compared with the configured threshold.
Terminology is deliberately limited to "flagged for review" / "unusual
pattern"; this module never labels anything as fraud.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .config import get_path, load_config, require_path
from .indicators import IndicatorResult
from .review_store import list_outcomes
from .utils import json_dumps

OPERATORS = {
    ">=": lambda a, b: a >= b,
    ">": lambda a, b: a > b,
    "<=": lambda a, b: a <= b,
    "<": lambda a, b: a < b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


@dataclass
class ScoringResult:
    """Scored records, the flagged review queue and a reason-code summary."""

    all_scored: pd.DataFrame
    queue: pd.DataFrame
    reason_summary: pd.DataFrame
    methodology: dict[str, Any]


def _compare(actual: Any, operator: str, threshold: float) -> bool:
    try:
        value = float(actual)
    except (TypeError, ValueError):
        return False
    if not np.isfinite(value):
        return False
    comparator = OPERATORS.get(operator)
    return bool(comparator(value, float(threshold))) if comparator else False


def _display(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not np.isfinite(number):
        return "n/a"
    return f"{number:.2f}" if not number.is_integer() else str(int(number))


def evaluate_record(record: pd.Series, rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the reason codes triggered for one record."""
    record_type = str(record.get("record_type", ""))
    reasons: list[dict[str, Any]] = []
    for rule in rules:
        if record_type not in rule.get("record_types", []):
            continue
        field = rule["field"]
        actual = record.get(field, 0)
        operator = rule["operator"]
        threshold = rule["threshold"]
        if not _compare(actual, operator, threshold):
            continue
        reasons.append({
            "code": rule["code"],
            "explanation": rule["explanation"],
            "field": field,
            "actual": actual,
            "threshold": threshold,
            "operator": operator,
            "weight": int(rule["weight"]),
            "detail": (
                f"{field} = {_display(actual)} ({operator} {_display(threshold)}), "
                f"weight {rule['weight']}"
            ),
            "record_type": record_type,
        })
    return reasons


def flagged_transactions(queue: pd.DataFrame) -> pd.DataFrame:
    """Return only the flagged records that represent actual transactions.

    The review queue also contains customer, merchant and device records. KPIs
    must use this subset so the flagged count can never exceed the number of
    reconciled transactions.
    """
    if queue.empty or "record_type" not in queue.columns:
        return queue.iloc[0:0]
    return queue[queue["record_type"] == "transaction"]


def distinct_flagged_transactions(queue: pd.DataFrame) -> int:
    """Number of distinct transactions flagged for review."""
    subset = flagged_transactions(queue)
    return int(subset["record_id"].nunique()) if not subset.empty else 0


def flagged_transaction_rate(queue: pd.DataFrame, total_transactions: int) -> float:
    """Share of reconciled transactions that are flagged for review."""
    if not total_transactions:
        return 0.0
    return distinct_flagged_transactions(queue) / float(total_transactions)


def _priority(score: float, config: dict[str, Any]) -> str:
    if score >= float(require_path(config, "scoring.high_priority_score")):
        return "high"
    if score >= float(require_path(config, "scoring.medium_priority_score")):
        return "medium"
    return "low"


def _add_secondary_signal(
    scored: pd.DataFrame, config: dict[str, Any]
) -> pd.DataFrame:
    """Attach an IsolationForest signal *only* to already rule-flagged records.

    This signal can contribute weight but can never be the sole reason a record
    appears in the review queue. Disabled by default in ``config.yaml``.
    """
    settings = get_path(config, "scoring.isolation_forest", {}) or {}
    if not settings.get("enabled", False):
        return scored
    fields = [
        "captured_amount", "refund_ratio_amount", "attempt_count", "retry_count",
        "failed_streak", "max_txns_1h", "amount_zscore_abs", "failure_rate",
    ]
    matrix = scored.reindex(columns=fields).apply(pd.to_numeric, errors="coerce")
    matrix = matrix.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    if len(matrix) < 10:
        return scored
    try:
        from sklearn.ensemble import IsolationForest

        model = IsolationForest(
            contamination=float(settings.get("contamination", 0.03)),
            random_state=int(settings.get("random_state", 7)),
        )
        predictions = model.fit_predict(matrix.to_numpy())
    except Exception:  # pragma: no cover - defensive: optional dependency
        return scored
    weight = int(settings.get("weight", 8))
    for index, (position, prediction) in enumerate(zip(matrix.index, predictions)):
        if prediction != -1:
            continue
        reasons = scored.at[position, "reasons_list"]
        if not reasons:  # never a stand-alone reason
            continue
        reason = {
            "code": "STATISTICAL_OUTLIER_SECONDARY",
            "explanation": (
                "A secondary statistical model also found unusual indicator values; "
                "it is supplementary and is never the sole reason for review."
            ),
            "field": "isolation_forest",
            "actual": -1,
            "threshold": 1,
            "operator": "==",
            "weight": weight,
            "detail": f"secondary signal present, supplementary weight {weight}",
            "record_type": scored.at[position, "record_type"],
        }
        reasons.append(reason)
        scored.at[position, "reasons_list"] = reasons
        scored.at[position, "score"] = min(
            float(scored.at[position, "score"]) + weight,
            float(require_path(config, "scoring.max_score")),
        )
    return scored


def build_review_queue(
    indicators: IndicatorResult,
    config: dict[str, Any] | None = None,
    db_path: str | None = None,
) -> ScoringResult:
    """Score all records and return the ranked, explainable review queue."""
    cfg = config or load_config()
    rules = list(require_path(cfg, "scoring.rules"))
    records = indicators.all_records()
    records = records.copy()
    for rule in rules:
        field = rule["field"]
        if field not in records.columns:
            records[field] = 0
    reasons = [evaluate_record(row, rules) for _, row in records.iterrows()]
    scored = records.copy()
    scored["reasons_list"] = reasons
    scored["reason_codes"] = [[r["code"] for r in row] for row in reasons]
    scored["reasons"] = [json_dumps(row) for row in reasons]
    scored["score"] = [min(sum(r["weight"] for r in row),
                           int(require_path(cfg, "scoring.max_score"))) for row in reasons]
    scored = _add_secondary_signal(scored, cfg)
    # Recompute reason columns after the optional secondary signal.
    scored["reason_codes"] = [[r["code"] for r in row] for row in scored["reasons_list"]]
    scored["reasons"] = [json_dumps(row) for row in scored["reasons_list"]]
    scored["priority"] = scored["score"].apply(lambda s: _priority(float(s), cfg))

    outcomes = list_outcomes(db_path=db_path, config=cfg)
    scored = scored.merge(outcomes, on="record_id", how="left")
    for column, default in [("outcome", "pending"), ("reviewer", ""),
                            ("notes", ""), ("updated_at", "")]:
        scored[column] = scored[column].fillna(default)
    scored = scored.sort_values(["score", "record_id"], ascending=[False, True]).reset_index(drop=True)

    flag_min = float(require_path(cfg, "scoring.flag_min_score"))
    queue = scored[scored["score"] >= flag_min].copy().reset_index(drop=True)

    exploded = queue[["record_id", "reason_codes"]].explode("reason_codes").dropna()
    exploded = exploded.rename(columns={"reason_codes": "reason_code"})
    if exploded.empty:
        reason_summary = pd.DataFrame(columns=["reason_code", "flagged_records", "points_per_flag"])
    else:
        points = {
            r["code"]: r["weight"] for r in require_path(cfg, "scoring.rules")
        }
        reason_summary = (
            exploded.groupby("reason_code").size()
            .reset_index(name="flagged_records")
            .sort_values("flagged_records", ascending=False)
            .reset_index(drop=True)
        )
        reason_summary["points_per_flag"] = reason_summary["reason_code"].map(points).fillna(
            get_path(cfg, "scoring.isolation_forest.weight", 0)
        ).astype(int)

    methodology = {
        "rules": [
            {key: rule[key] for key in ("code", "field", "operator", "threshold", "weight",
                                        "record_types", "explanation")}
            for rule in rules
        ],
        "flag_min_score": flag_min,
        "medium_priority_score": float(require_path(cfg, "scoring.medium_priority_score")),
        "high_priority_score": float(require_path(cfg, "scoring.high_priority_score")),
        "max_score": int(require_path(cfg, "scoring.max_score")),
        "secondary_signal_enabled": bool(
            get_path(cfg, "scoring.isolation_forest.enabled", False)
        ),
    }
    return ScoringResult(
        all_scored=scored.drop(columns=["reasons_list"]),
        queue=queue.drop(columns=["reasons_list"]),
        reason_summary=reason_summary,
        methodology=methodology,
    )
