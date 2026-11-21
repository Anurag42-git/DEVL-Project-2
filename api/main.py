"""FastAPI application exposing the investigation pipeline as JSON endpoints."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from src.config import get_path, load_config
from src.pipeline import PipelineResult
from src.report import compute_detection_quality, generate_report
from src.review_store import audit_trail, list_outcomes
from src.scoring import distinct_flagged_transactions, flagged_transaction_rate

from . import state
from .schemas import (
    AuditEvent,
    AuditTrailResponse,
    BulkOutcomeRequest,
    DataQualityResponse,
    HealthResponse,
    LedgerResponse,
    LedgerRow,
    NameCount,
    OutcomeRequest,
    OutcomeResponse,
    OverviewResponse,
    Reason,
    ReportResponse,
    ReportSection,
    ReviewItem,
    ReviewQueueResponse,
    RuleSummary,
    TransactionDetail,
    TimelineEvent,
)
from .serialize import clean, records

app = FastAPI(
    title="Transaction Anomaly and Refund Investigation API",
    version="1.0.0",
    description="Explainable review of unusual payment patterns. Flags are review triggers, "
                "not determinations of intent.",
)

_default_origins = [
    "http://localhost:5173", "http://127.0.0.1:5173",
    "http://localhost:3000", "http://127.0.0.1:3000",
]
_configured_origins = [
    origin.strip()
    for origin in os.environ.get("API_CORS_ORIGINS", "").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(dict.fromkeys(_default_origins + _configured_origins)),
    allow_origin_regex=os.environ.get("CORS_ORIGIN_REGEX") or r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DISCLAIMER = "Flags are review triggers for unusual patterns, not fraud determinations."
LEDGER_SORT_FIELDS = {
    "transaction_id", "customer_id", "merchant_id", "final_status", "captured_amount",
    "total_refunded", "remaining_amount", "refund_ratio", "attempt_count", "retry_count",
    "first_event_time", "last_event_time", "over_refund_amount",
}
QUEUE_SORT_FIELDS = {"score", "record_id", "priority", "outcome", "captured_amount", "updated_at"}


def _result() -> PipelineResult:
    return state.get_result()


def _page(items: list[Any], page: int, page_size: int) -> list[Any]:
    start = (page - 1) * page_size
    return items[start:start + page_size]


def _parse_reasons(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return []
    return [clean(item) for item in (raw or [])]


def _ledger_row(row: pd.Series) -> dict[str, Any]:
    return {
        "transaction_id": str(row.get("transaction_id", "")),
        "customer_id": str(row.get("customer_id", "")),
        "merchant_id": str(row.get("merchant_id", "")),
        "device_id": str(row.get("device_id", "")),
        "currency": str(row.get("currency", "")),
        "final_status": str(row.get("final_status", "")),
        "captured_amount": float(row.get("captured_amount", 0) or 0),
        "total_refunded": float(row.get("total_refunded", 0) or 0),
        "remaining_amount": float(row.get("remaining_amount", 0) or 0),
        "refund_ratio": float(row.get("refund_ratio", 0) or 0),
        "refund_count": int(row.get("refund_count", 0) or 0),
        "attempt_count": int(row.get("attempt_count", 0) or 0),
        "retry_count": int(row.get("retry_count", 0) or 0),
        "duplicate_events_removed": int(row.get("duplicate_events_removed", 0) or 0),
        "over_refund_amount": float(row.get("over_refund_amount", 0) or 0),
        "first_event_time": clean(row.get("first_event_time")),
        "last_event_time": clean(row.get("last_event_time")),
        "reconciliation_notes": str(row.get("reconciliation_notes", "")),
    }


def _ledger_map(result: PipelineResult) -> dict[str, pd.Series]:
    ledger = result.reconciliation.ledger
    return {str(txn): row for txn, row in ledger.set_index("transaction_id").iterrows()}


def _review_items(result: PipelineResult, queue: pd.DataFrame) -> list[dict[str, Any]]:
    ledger = _ledger_map(result)
    items: list[dict[str, Any]] = []
    for _, row in queue.iterrows():
        record_id = str(row["record_id"])
        record_type = str(row["record_type"])
        linked = ledger.get(record_id) if record_type == "transaction" else None
        items.append({
            "record_id": record_id,
            "record_type": record_type,
            "score": int(row["score"]),
            "priority": str(row["priority"]),
            "reason_codes": [str(code) for code in row["reason_codes"]],
            "reasons": _parse_reasons(row.get("reasons")),
            "outcome": str(row.get("outcome", "pending")),
            "reviewer": str(row.get("reviewer", "") or ""),
            "notes": str(row.get("notes", "") or ""),
            "updated_at": clean(row.get("updated_at")),
            "customer_id": str(linked["customer_id"]) if linked is not None else "",
            "merchant_id": str(linked["merchant_id"]) if linked is not None else "",
            "captured_amount": float(row.get("captured_amount", 0) or 0),
            "refund_ratio_amount": float(row.get("refund_ratio_amount", 0) or 0),
            "first_event_time": clean(linked["first_event_time"]) if linked is not None else None,
        })
    return items


def _delta(current: float, previous: float) -> tuple[float | None, str]:
    if previous in (0, None):
        return None, "flat"
    change = (current - previous) / abs(previous) * 100
    return round(change, 2), ("up" if change > 0.5 else "down" if change < -0.5 else "flat")


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Report service status and cache provenance."""
    return HealthResponse(status="ok", cache=state.state_info(), disclaimer=DISCLAIMER)


@app.post("/api/reload", response_model=HealthResponse)
def reload() -> HealthResponse:
    """Re-run the pipeline from the CSV files and replace the cached result."""
    state.reload_result()
    return HealthResponse(status="ok", cache=state.state_info(), disclaimer=DISCLAIMER)


@app.get("/api/overview", response_model=OverviewResponse)
def overview() -> OverviewResponse:
    """KPIs, daily series and the highest-priority pending items."""
    result = _result()
    ledger = result.reconciliation.ledger
    queue = result.scoring.queue
    ledger_count = len(ledger)
    captured = float(ledger["captured_amount"].sum())
    refunded = float(ledger["total_refunded"].sum())
    ratio = refunded / captured if captured else 0.0
    txn_flags = distinct_flagged_transactions(queue)
    pending = int((queue["outcome"] == "pending").sum())

    daily_frame = (
        ledger.assign(day=pd.to_datetime(ledger["first_event_time"], errors="coerce").dt.date)
        .groupby("day", dropna=True)
        .agg(transactions=("transaction_id", "size"),
             captured=("captured_amount", "sum"),
             refunded=("total_refunded", "sum"))
        .reset_index()
        .sort_values("day")
    )
    daily = []
    for _, row in daily_frame.iterrows():
        cap = float(row["captured"])
        daily.append({
            "date": str(row["day"]),
            "transactions": int(row["transactions"]),
            "captured": round(cap, 2),
            "refunded": round(float(row["refunded"]), 2),
            "refund_ratio": round(float(row["refunded"]) / cap, 4) if cap else 0.0,
        })

    # Compare the second half of the observed window with the first half.
    split = len(daily) // 2
    earlier, later = daily[:split], daily[split:]
    def total(rows: list[dict[str, Any]], key: str) -> float:
        return float(sum(row[key] for row in rows))
    txn_delta, txn_trend = _delta(total(later, "transactions"), total(earlier, "transactions"))
    cap_delta, cap_trend = _delta(total(later, "captured"), total(earlier, "captured"))
    ratio_delta, ratio_trend = _delta(
        (total(later, "refunded") / total(later, "captured")) if total(later, "captured") else 0,
        (total(earlier, "refunded") / total(earlier, "captured")) if total(earlier, "captured") else 0,
    )

    kpis = [
        {"id": "transactions", "label": "Transactions reconciled", "value": ledger_count,
         "display": f"{ledger_count:,}", "delta_pct": txn_delta, "trend": txn_trend},
        {"id": "captured", "label": "Captured amount", "value": round(captured, 2),
         "display": f"${captured:,.2f}", "delta_pct": cap_delta, "trend": cap_trend},
        {"id": "refund_ratio", "label": "Refund ratio", "value": round(ratio, 4),
         "display": f"{ratio:.2%}", "delta_pct": ratio_delta, "trend": ratio_trend},
        {"id": "flagged", "label": "Flagged transactions", "value": txn_flags,
         "display": f"{txn_flags:,}", "delta_pct": None, "trend": "flat"},
        {"id": "pending", "label": "Pending reviews", "value": pending,
         "display": f"{pending:,}", "delta_pct": None, "trend": "flat"},
    ]
    reason_counts = [
        {"name": row["reason_code"], "value": int(row["flagged_records"])}
        for _, row in result.scoring.reason_summary.iterrows()
    ]
    priority_counts = [
        {"name": name, "value": int(count)}
        for name, count in queue["priority"].value_counts().items()
    ]
    needs = _review_items(result, queue[queue["outcome"] == "pending"].head(5))
    threshold = next(
        (float(rule["threshold"]) for rule in result.scoring.methodology["rules"]
         if rule["code"] == "HIGH_REFUND_RATIO"), 0.7
    )
    return OverviewResponse(
        kpis=kpis,
        daily=daily,
        reason_counts=reason_counts,
        priority_counts=priority_counts,
        refund_threshold=threshold,
        needs_attention=[{
            "record_id": item["record_id"], "record_type": item["record_type"],
            "score": item["score"], "priority": item["priority"],
            "reason_codes": item["reason_codes"], "outcome": item["outcome"],
        } for item in needs],
        metrics={
            "flag_rate": round(flagged_transaction_rate(queue, ledger_count), 4),
            "flagged_transactions": txn_flags,
            "total_transactions": ledger_count,
            "queue_records": len(queue),
            "validation_violations": len(result.validation.violations),
            "reconciliation": result.reconciliation.summary(),
        },
        conservation=clean(result.reconciliation.invariant),
        disclaimer=DISCLAIMER,
        generated_at=state.state_info()["generated_at"],
    )


@app.get("/api/ledger", response_model=LedgerResponse)
def ledger_endpoint(
    search: str = "",
    status: str | None = None,
    customer: str | None = None,
    merchant: str | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    sort_by: str = "first_event_time",
    sort_dir: str = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
) -> LedgerResponse:
    """Filtered, sorted, paginated reconciled ledger."""
    frame = _result().reconciliation.ledger.copy()
    if search:
        needle = search.lower()
        mask = False
        for column in ("transaction_id", "customer_id", "merchant_id", "device_id",
                       "reconciliation_notes"):
            mask = mask | frame[column].astype(str).str.lower().str.contains(needle, na=False)
        frame = frame[mask]
    if status:
        frame = frame[frame["final_status"] == status]
    if customer:
        frame = frame[frame["customer_id"].astype(str).str.contains(customer, case=False, na=False)]
    if merchant:
        frame = frame[frame["merchant_id"].astype(str).str.contains(merchant, case=False, na=False)]
    if min_amount is not None:
        frame = frame[frame["captured_amount"] >= min_amount]
    if max_amount is not None:
        frame = frame[frame["captured_amount"] <= max_amount]
    sort_by = sort_by if sort_by in LEDGER_SORT_FIELDS else "first_event_time"
    frame = frame.sort_values(sort_by, ascending=sort_dir != "desc", kind="stable")
    total = len(frame)
    rows = [_ledger_row(row) for _, row in frame.iloc[(page - 1) * page_size:page * page_size].iterrows()]
    return LedgerResponse(
        items=rows, total=total, page=page, page_size=page_size,
        facets={"statuses": sorted(_result().reconciliation.ledger["final_status"].dropna().unique().tolist())},
    )


@app.get("/api/transactions/{transaction_id}", response_model=TransactionDetail)
def transaction_detail(transaction_id: str) -> TransactionDetail:
    """Ledger row plus raw lifecycle evidence for one transaction."""
    result = _result()
    ledger = result.reconciliation.ledger
    match = ledger[ledger["transaction_id"].astype(str) == transaction_id]
    if match.empty:
        raise HTTPException(status_code=404, detail="Transaction not found")
    row = match.iloc[0]
    events = records(result.reconciliation.raw_events[
        result.reconciliation.raw_events["transaction_id"].astype(str) == transaction_id
    ])
    refunds = records(result.raw["refunds"][
        result.raw["refunds"]["transaction_id"].astype(str) == transaction_id
    ])
    statuses = records(result.raw["payment_status"][
        result.raw["payment_status"]["transaction_id"].astype(str) == transaction_id
    ])

    timeline: list[dict[str, Any]] = []
    for event in events:
        timeline.append({
            "kind": event["event_type"], "time": event["event_timestamp"],
            "label": str(event["event_type"]).title(), "status": event["status"],
            "amount": event["amount"], "invalid": False,
        })
    for refund in refunds:
        timeline.append({
            "kind": "refund", "time": refund["refund_timestamp"], "label": "Refund",
            "status": refund["refund_status"], "amount": refund["refund_amount"],
            "invalid": refund["refund_status"] == "completed"
            and float(refund["refund_amount"] or 0) > float(row["captured_amount"] or 0),
        })
    timeline.sort(key=lambda item: str(item["time"] or ""))
    invalid_rules = set(
        result.validation.violations.loc[
            result.validation.violations["record_id"] == transaction_id, "rule"
        ]
    )
    if "INVALID_STATUS_TRANSITION" in invalid_rules:
        for item in timeline:
            item["invalid"] = True

    scored = result.scoring.all_scored
    indicator_row = scored[scored["record_id"].astype(str) == transaction_id]
    indicators = clean(indicator_row.iloc[0].to_dict()) if not indicator_row.empty else {}
    reasons = _parse_reasons(indicator_row.iloc[0].get("reasons")) if not indicator_row.empty else []

    ledger_row = _ledger_row(row)
    return TransactionDetail(
        ledger=LedgerRow(**ledger_row),
        events=events,
        refunds=refunds,
        status_history=statuses,
        timeline=[TimelineEvent(**item) for item in timeline],
        indicators=indicators,
        reasons=[Reason(**reason) for reason in reasons],
        reconciliation_notes=ledger_row["reconciliation_notes"],
        context={
            "customer": str(row["customer_id"]),
            "merchant": str(row["merchant_id"]),
            "device": str(row["device_id"]),
            "currency": str(row["currency"]),
        },
    )


@app.get("/api/review-queue", response_model=ReviewQueueResponse)
def review_queue(
    search: str = "",
    priority: list[str] | None = Query(None),
    reason: list[str] | None = Query(None),
    outcome: list[str] | None = Query(None),
    record_type: list[str] | None = Query(None),
    from_date: str | None = None,
    to_date: str | None = None,
    sort_by: str = "score",
    sort_dir: str = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
) -> ReviewQueueResponse:
    """Filtered, sorted, paginated review queue with explainable reasons."""
    result = _result()
    queue = result.scoring.queue
    items = _review_items(result, queue)
    if search:
        needle = search.lower()
        items = [item for item in items if needle in (
            item["record_id"] + " " + item["customer_id"] + " " + item["merchant_id"]
            + " " + " ".join(item["reason_codes"])
        ).lower()]
    if priority:
        items = [item for item in items if item["priority"] in priority]
    if reason:
        wanted = set(reason)
        items = [item for item in items if wanted & set(item["reason_codes"])]
    if outcome:
        items = [item for item in items if item["outcome"] in outcome]
    if record_type:
        items = [item for item in items if item["record_type"] in record_type]
    if from_date:
        items = [item for item in items if item["first_event_time"] and item["first_event_time"] >= from_date]
    if to_date:
        end = to_date if len(to_date) > 10 else to_date + "T23:59:59"
        items = [item for item in items if item["first_event_time"] and item["first_event_time"] <= end]
    sort_by = sort_by if sort_by in QUEUE_SORT_FIELDS else "score"
    items.sort(
        key=lambda item: (item.get(sort_by) if item.get(sort_by) is not None else "",
                          item["record_id"]),
        reverse=sort_dir != "desc",
    )
    total = len(items)
    page_items = _page(items, page, page_size)
    facets = {
        "priorities": sorted(queue["priority"].dropna().unique().tolist()),
        "reasons": sorted({code for codes in queue["reason_codes"] for code in codes}),
        "outcomes": sorted(queue["outcome"].dropna().unique().tolist()),
        "record_types": sorted(queue["record_type"].dropna().unique().tolist()),
    }
    return ReviewQueueResponse(
        items=[ReviewItem(**item) for item in page_items],
        total=total, page=page, page_size=page_size, facets=facets,
        flagged_transactions=distinct_flagged_transactions(queue),
        total_transactions=len(result.reconciliation.ledger),
        flag_rate=round(flagged_transaction_rate(queue, len(result.reconciliation.ledger)), 4),
    )


@app.post("/api/review/{record_id}/outcome", response_model=OutcomeResponse)
def set_review_outcome(record_id: str, payload: OutcomeRequest) -> OutcomeResponse:
    """Persist a review outcome and refresh the cached queue."""
    queue = _result().scoring.queue
    if record_id not in set(queue["record_id"].astype(str)):
        raise HTTPException(status_code=404, detail="Flagged record not found")
    saved = state.record_outcome(record_id, payload.outcome, payload.reviewer, payload.notes)
    return OutcomeResponse(**saved)


@app.post("/api/review/bulk-outcome", response_model=list[OutcomeResponse])
def bulk_set_outcome(payload: BulkOutcomeRequest) -> list[OutcomeResponse]:
    """Set the same outcome on several flagged records."""
    known = set(_result().scoring.queue["record_id"].astype(str))
    unknown = [record_id for record_id in payload.record_ids if record_id not in known]
    if unknown:
        raise HTTPException(status_code=404, detail=f"Unknown records: {', '.join(unknown[:5])}")
    return [
        OutcomeResponse(**state.record_outcome(record_id, payload.outcome, payload.reviewer,
                                               payload.notes))
        for record_id in payload.record_ids
    ]


@app.get("/api/audit-trail/{record_id}", response_model=AuditTrailResponse)
def audit_for_record(record_id: str) -> AuditTrailResponse:
    """All who/what/when changes recorded for one flagged record."""
    trail = audit_trail(config=_result().config, record_id=record_id)
    return AuditTrailResponse(
        items=[AuditEvent(**item) for item in records(trail)], total=len(trail)
    )


@app.get("/api/data-quality", response_model=DataQualityResponse)
def data_quality() -> DataQualityResponse:
    """Validation rule summary, violation examples and the status state machine."""
    result = _result()
    summary = result.validation.summary()
    return DataQualityResponse(
        summary=[RuleSummary(**row) for row in records(summary)],
        violations=records(result.validation.violations),
        state_machine={
            str(key): [str(value) for value in values]
            for key, values in get_path(result.config, "validation.allowed_transitions", {}).items()
        },
        totals={
            "rules": len(summary),
            "violations": len(result.validation.violations),
            "high_severity": int(summary.loc[summary["severity"] == "high", "count"].sum()),
        },
    )


@app.get("/api/report", response_model=ReportResponse)
def report() -> ReportResponse:
    """Structured audit-report sections and detection quality."""
    from src.report import build_markdown

    result = _result()
    markdown = build_markdown(result)
    sections: list[ReportSection] = []
    for chunk in markdown.split("\n## ")[1:]:
        title, _, body = chunk.partition("\n")
        sections.append(ReportSection(title=title.strip(), body=body.strip()))
    quality = compute_detection_quality(result)
    detection_quality = None
    if quality is not None:
        detection_quality = clean({
            key: value for key, value in quality.__dict__.items() if key != "by_reason"
        })
        detection_quality["by_reason"] = records(quality.by_reason)
    outcome_counts = list_outcomes(config=result.config)["outcome"].value_counts()
    return ReportResponse(
        sections=sections,
        detection_quality=detection_quality,
        review_outcomes=[NameCount(name=str(name), value=int(value))
                         for name, value in outcome_counts.items()],
        generated_at=state.state_info()["generated_at"],
        disclaimer=DISCLAIMER,
    )


@app.get("/api/report/download/{format}")
def download_report(format: str) -> FileResponse:
    """Download the generated Markdown, HTML or CSV report file."""
    if format not in {"md", "html", "csv"}:
        raise HTTPException(status_code=400, detail="format must be md, html or csv")
    files = generate_report(_result())
    path: Path = files[{"md": "markdown", "html": "html", "csv": "csv"}[format]]
    media = {"md": "text/markdown", "html": "text/html", "csv": "text/csv"}[format]
    return FileResponse(path, filename=path.name, media_type=media)


# Register last: SPA fallback must never shadow a JSON endpoint.
from .static import mount_frontend  # noqa: E402  (intentional late import)

frontend_mounted: bool = mount_frontend(app, load_config())
