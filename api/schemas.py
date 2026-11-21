"""Pydantic v2 response/request models for the JSON API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

OUTCOME_VALUES = Literal["pending", "reviewed_normal", "needs_follow_up", "escalated"]
PRIORITY_VALUES = Literal["high", "medium", "low"]


class Kpi(BaseModel):
    """A single overview KPI with an optional delta vs the previous period."""

    id: str
    label: str
    value: float
    display: str
    delta_pct: float | None = None
    trend: Literal["up", "down", "flat"] = "flat"


class DailyPoint(BaseModel):
    date: str
    transactions: int = 0
    captured: float = 0.0
    refunded: float = 0.0
    refund_ratio: float = 0.0


class NameCount(BaseModel):
    name: str
    value: float


class NeedsAttention(BaseModel):
    record_id: str
    record_type: str
    score: int
    priority: str
    reason_codes: list[str]
    outcome: str


class OverviewResponse(BaseModel):
    kpis: list[Kpi]
    daily: list[DailyPoint]
    reason_counts: list[NameCount]
    priority_counts: list[NameCount]
    refund_threshold: float
    needs_attention: list[NeedsAttention]
    metrics: dict[str, Any]
    conservation: dict[str, Any]
    disclaimer: str
    generated_at: str


class LedgerRow(BaseModel):
    transaction_id: str
    customer_id: str = ""
    merchant_id: str = ""
    device_id: str = ""
    currency: str = ""
    final_status: str = ""
    captured_amount: float = 0.0
    total_refunded: float = 0.0
    remaining_amount: float = 0.0
    refund_ratio: float = 0.0
    refund_count: int = 0
    attempt_count: int = 0
    retry_count: int = 0
    duplicate_events_removed: int = 0
    over_refund_amount: float = 0.0
    first_event_time: str | None = None
    last_event_time: str | None = None
    reconciliation_notes: str = ""


class LedgerResponse(BaseModel):
    items: list[LedgerRow]
    total: int
    page: int
    page_size: int
    facets: dict[str, Any]


class TimelineEvent(BaseModel):
    kind: str
    time: str | None = None
    label: str
    status: str = ""
    amount: float | None = None
    invalid: bool = False


class Reason(BaseModel):
    code: str
    explanation: str
    field: str
    actual: float | None = None
    threshold: float | None = None
    operator: str = ""
    weight: int = 0
    detail: str = ""


class TransactionDetail(BaseModel):
    ledger: LedgerRow
    events: list[dict[str, Any]]
    refunds: list[dict[str, Any]]
    status_history: list[dict[str, Any]]
    timeline: list[TimelineEvent]
    indicators: dict[str, Any]
    reasons: list[Reason]
    reconciliation_notes: str
    context: dict[str, Any]


class ReviewItem(BaseModel):
    record_id: str
    record_type: str
    score: int
    priority: str
    reason_codes: list[str]
    reasons: list[Reason]
    outcome: str = "pending"
    reviewer: str = ""
    notes: str = ""
    updated_at: str | None = None
    customer_id: str = ""
    merchant_id: str = ""
    captured_amount: float = 0.0
    refund_ratio_amount: float = 0.0
    first_event_time: str | None = None


class ReviewQueueResponse(BaseModel):
    items: list[ReviewItem]
    total: int
    page: int
    page_size: int
    facets: dict[str, Any]
    flagged_transactions: int
    total_transactions: int
    flag_rate: float


class OutcomeRequest(BaseModel):
    outcome: OUTCOME_VALUES
    reviewer: str = ""
    notes: str = ""

    @model_validator(mode="after")
    def notes_required_for_escalation(self) -> "OutcomeRequest":
        if self.outcome in {"needs_follow_up", "escalated"} and not self.notes.strip():
            raise ValueError("notes are required for needs_follow_up and escalated outcomes")
        return self


class BulkOutcomeRequest(OutcomeRequest):
    record_ids: list[str] = Field(default_factory=list, max_length=200)


class OutcomeResponse(BaseModel):
    record_id: str
    outcome: str
    reviewer: str
    notes: str
    updated_at: str


class AuditEvent(BaseModel):
    id: int
    record_id: str
    old_outcome: str
    new_outcome: str
    reviewer: str
    notes: str
    changed_at: str


class AuditTrailResponse(BaseModel):
    items: list[AuditEvent]
    total: int


class RuleSummary(BaseModel):
    rule: str
    severity: str
    count: int
    examples: str


class DataQualityResponse(BaseModel):
    summary: list[RuleSummary]
    violations: list[dict[str, Any]]
    state_machine: dict[str, list[str]]
    totals: dict[str, Any]


class ReportSection(BaseModel):
    title: str
    body: str


class ReportResponse(BaseModel):
    sections: list[ReportSection]
    detection_quality: dict[str, Any] | None
    review_outcomes: list[NameCount]
    generated_at: str
    disclaimer: str


class HealthResponse(BaseModel):
    status: str
    cache: dict[str, Any]
    disclaimer: str
