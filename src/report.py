"""Markdown/HTML audit report with ground-truth detection quality."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .config import get_path, ground_truth_file, reports_dir
from .pipeline import PipelineResult
from .review_store import audit_trail, list_outcomes
from .utils import ensure_parent, to_iso

DISCLAIMER = (
    "This report describes records flagged for manual review because they show "
    "unusual patterns. Flags are not determinations of fraud, and no record here "
    "is labelled as confirmed fraud."
)


@dataclass
class DetectionQuality:
    """Precision/recall of review flags against the hidden injected-issue key."""

    expected_pairs: int
    detected_pairs: int
    matched_pairs: int
    precision: float
    recall: float
    f1: float
    restricted_precision: float
    by_reason: pd.DataFrame


def compute_detection_quality(result: PipelineResult) -> DetectionQuality | None:
    """Compare flagged (record_id, reason_code) pairs with the hidden answer key."""
    path = ground_truth_file(result.config)
    if not path.is_file():
        return None
    truth = pd.read_csv(path)
    if "expected_reason_code" not in truth.columns:
        return None
    truth = truth[truth["expected_reason_code"].fillna("").astype(str) != ""].copy()
    expected = set(zip(truth["entity_id"].astype(str), truth["expected_reason_code"].astype(str)))
    flagged: set[tuple[str, str]] = set()
    for _, row in result.scoring.queue.iterrows():
        for code in row["reason_codes"]:
            flagged.add((str(row["record_id"]), str(code)))
    matched = expected & flagged
    precision = len(matched) / len(flagged) if flagged else 0.0
    recall = len(matched) / len(expected) if expected else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    known_codes = {code for _, code in expected}
    restricted = {pair for pair in flagged if pair[1] in known_codes}
    restricted_precision = len(matched) / len(restricted) if restricted else 0.0

    rows = []
    for code, group in truth.groupby("expected_reason_code"):
        injected = set(zip(group["entity_id"].astype(str), group["expected_reason_code"].astype(str)))
        hits = injected & matched
        rows.append({
            "reason_code": code,
            "injected": len(injected),
            "detected": len(hits),
            "missed": len(injected) - len(hits),
            "recall": round(len(hits) / len(injected), 3) if injected else 0.0,
        })
    return DetectionQuality(
        expected_pairs=len(expected),
        detected_pairs=len(flagged),
        matched_pairs=len(matched),
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
        restricted_precision=round(restricted_precision, 4),
        by_reason=pd.DataFrame(rows).sort_values("missed", ascending=False).reset_index(drop=True),
    )


def _md_table(frame: pd.DataFrame, max_rows: int | None = None) -> str:
    if frame.empty:
        return "_No rows._"
    shown = frame.head(max_rows) if max_rows else frame
    header = "| " + " | ".join(str(c) for c in shown.columns) + " |"
    divider = "| " + " | ".join("---" for _ in shown.columns) + " |"
    rows = [
        "| " + " | ".join(str(value).replace("|", "/").replace("\n", " ") for value in row) + " |"
        for row in shown.itertuples(index=False, name=None)
    ]
    return "\n".join([header, divider, *rows])


def build_markdown(result: PipelineResult) -> str:
    """Build the complete Markdown audit report."""
    cfg = result.config
    raw = result.raw
    ledger = result.reconciliation.ledger
    queue = result.scoring.queue
    outcomes = list_outcomes(config=cfg)
    quality = compute_detection_quality(result)
    times = pd.to_datetime(ledger["first_event_time"], errors="coerce")
    date_range = f"{to_iso(times.min())} to {to_iso(times.max())}"
    captured = float(ledger["captured_amount"].sum())
    refunded = float(ledger["total_refunded"].sum())

    lines: list[str] = []
    add = lines.append
    add("# Transaction Anomaly and Refund Investigation — Audit Report")
    add("")
    add(f"Generated: {to_iso(pd.Timestamp.now())}  ")
    add(f"Configuration: `config.yaml` (seed {get_path(cfg, 'data.generation.seed', 'n/a')})")
    add("")
    add(f"> **Disclaimer:** {DISCLAIMER}")
    add("")

    add("## 1. Data summary")
    add("")
    add(_md_table(pd.DataFrame([
        ("Customers", len(raw["customers"])),
        ("Merchants", len(raw["merchants"])),
        ("Raw transaction events", len(raw["transactions"])),
        ("Distinct transactions", raw["transactions"]["transaction_id"].nunique()),
        ("Refund rows", len(raw["refunds"])),
        ("Payment-status rows", len(raw["payment_status"])),
        ("Devices", len(raw["device_summary"])),
        ("Event date range", date_range),
        ("Reconciled ledger rows", len(ledger)),
        ("Captured amount", f"{captured:,.2f}"),
        ("Completed refunds", f"{refunded:,.2f}"),
    ], columns=["Metric", "Value"])))
    add("")

    add("## 2. Validation findings")
    add("")
    findings = result.validation.summary()
    add(_md_table(findings, max_rows=30))
    add("")
    add("Status transitions are checked with an explicit state machine:")
    add("")
    for state, allowed in get_path(cfg, "validation.allowed_transitions", {}).items():
        add(f"- `{state}` → {', '.join(f'`{a}`' for a in allowed) if allowed else '_terminal_'}")
    add("")

    add("## 3. Reconciliation adjustments")
    add("")
    adjustments = result.reconciliation.adjustments
    add(_md_table(pd.DataFrame([
        ("Duplicate events removed (idempotent on event_id)", adjustments["duplicate_events_removed"]),
        ("Retry events merged as attempts (not revenue)", adjustments["retry_events_merged"]),
        ("Refund rows aggregated into transactions", adjustments["refund_rows_total"]),
        ("Orphan transaction rows retained in ledger", adjustments["orphan_transaction_rows"]),
    ], columns=["Adjustment", "Count"])))
    add("")
    inv = result.reconciliation.invariant
    add(
        f"Conservation check: raw captured **{inv['raw_captured']:.2f}** vs ledger "
        f"**{inv['ledger_captured']:.2f}** (difference {inv['captured_difference']:.2f}); "
        f"raw refunds **{inv['raw_refunded']:.2f}** vs ledger "
        f"**{inv['ledger_refunded']:.2f}** (difference {inv['refunded_difference']:.2f}). "
        f"Result: **{'PASS' if inv['matched'] else 'FAIL'}**."
    )
    add("")

    add("## 4. Methodology and thresholds")
    add("")
    add(
        "Each record receives a transparent score equal to the sum of the weights of "
        "the rules it triggers (capped at "
        f"{result.scoring.methodology['max_score']}). Records scoring at least "
        f"{result.scoring.methodology['flag_min_score']} enter the review queue. "
        f"Medium priority starts at {result.scoring.methodology['medium_priority_score']} "
        f"and high priority at {result.scoring.methodology['high_priority_score']}."
    )
    add("")
    add(_md_table(pd.DataFrame(result.scoring.methodology["rules"])[
        ["code", "record_types", "field", "operator", "threshold", "weight"]
    ]))
    add("")
    add(
        f"Rolling windows: {get_path(cfg, 'indicators.windows.one_hour')} / "
        f"{get_path(cfg, 'indicators.windows.twenty_four_hour')} / "
        f"{get_path(cfg, 'indicators.windows.seven_day')}. Amount deviations use a "
        f"robust MAD baseline with at least "
        f"{get_path(cfg, 'indicators.min_baseline_samples')} observations. "
        f"Secondary statistical signal enabled: "
        f"{result.scoring.methodology['secondary_signal_enabled']} (never the sole reason)."
    )
    add("")

    add("## 5. Flagged-record summary")
    add("")
    add(_md_table(pd.DataFrame([
        ("Records flagged for review", len(queue)),
        ("High priority", int((queue["priority"] == "high").sum())),
        ("Medium priority", int((queue["priority"] == "medium").sum())),
        ("Low priority", int((queue["priority"] == "low").sum())),
    ], columns=["Metric", "Count"])))
    add("")
    add("Reason-code counts:")
    add("")
    add(_md_table(result.scoring.reason_summary))
    add("")
    top = queue[["record_id", "record_type", "score", "priority", "reason_codes", "outcome"]].head(15)
    add("Highest-scoring records:")
    add("")
    add(_md_table(top))
    add("")

    add("## 6. Review outcomes")
    add("")
    if outcomes.empty:
        add("_No review outcomes recorded yet._")
    else:
        outcome_counts = outcomes["outcome"].value_counts().rename_axis("outcome").reset_index(name="count")
        add(_md_table(outcome_counts))
        add("")
        add("Recent audit events:")
        add("")
        add(_md_table(audit_trail(config=cfg).tail(10)))
    add("")
    add(DISCLAIMER)
    add("")

    add("## 7. Detection quality against injected issues")
    add("")
    if quality is None:
        add("_Hidden ground-truth file was not available; detection quality not computed._")
    else:
        add(_md_table(pd.DataFrame([
            ("Injected issue pairs", quality.expected_pairs),
            ("Flagged reason pairs", quality.detected_pairs),
            ("Correctly matched pairs", quality.matched_pairs),
            ("Precision (all flagged pairs)", f"{quality.precision:.1%}"),
            ("Precision (codes in answer key only)", f"{quality.restricted_precision:.1%}"),
            ("Recall", f"{quality.recall:.1%}"),
            ("F1", f"{quality.f1:.1%}"),
        ], columns=["Metric", "Value"])))
        add("")
        add("Per reason code:")
        add("")
        add(_md_table(quality.by_reason))
        add("")
        add(
            "Precision is intentionally conservative: routine patterns such as fast "
            "refunds and round amounts are also flagged for review, so many review "
            "flags are not among the deliberately injected issues. Recall measures "
            "how many injected issues received at least one matching reason code."
        )
    add("")

    add("## 8. Limitations and assumptions")
    add("")
    for item in [
        "Data is synthetic; thresholds are illustrative and should be recalibrated on real traffic.",
        "Timestamps are treated as naive local time; no timezone normalisation is applied.",
        "The first canonical capture event supplies captured amount; multi-capture and "
        "multi-currency settlement scenarios are simplified.",
        "Refunds are counted only when refund_status is `completed`.",
        "A rule flag is an unusual-pattern signal requiring human judgement, not a "
        "conclusion about intent or correctness.",
        "Hidden ground truth covers deliberate injections only; it is not a complete "
        "labelling of all unusual activity.",
    ]:
        add(f"- {item}")
    add("")
    return "\n".join(lines)


def _markdown_to_html(markdown: str) -> str:
    """Minimal, dependency-free Markdown renderer for headings/tables/lists."""
    out: list[str] = []
    lines = markdown.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("|") and index + 1 < len(lines) and set(lines[index + 1].replace("|", "").replace(" ", "")) <= {"-", ":"}:
            header = [cell.strip() for cell in line.strip("|").split("|")]
            index += 2
            rows: list[list[str]] = []
            while index < len(lines) and lines[index].startswith("|"):
                rows.append([cell.strip() for cell in lines[index].strip("|").split("|")])
                index += 1
            out.append("<table><thead><tr>" + "".join(f"<th>{html.escape(c)}</th>" for c in header)
                       + "</tr></thead><tbody>")
            for row in rows:
                out.append("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in row) + "</tr>")
            out.append("</tbody></table>")
            continue
        if line.startswith("### "):
            out.append(f"<h3>{html.escape(line[4:])}</h3>")
        elif line.startswith("## "):
            out.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("# "):
            out.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("> "):
            out.append(f"<blockquote>{_inline(line[2:])}</blockquote>")
        elif line.startswith("- "):
            out.append(f"<li>{_inline(line[2:])}</li>")
        elif not line.strip():
            out.append("")
        else:
            out.append(f"<p>{_inline(line)}</p>")
        index += 1
    body = "\n".join(out)
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Audit Report — Transaction Anomaly and Refund Investigation</title>"
        "<style>body{font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:1100px;"
        "margin:2rem auto;padding:0 1rem;color:#1f2937;line-height:1.5}"
        "h1,h2,h3{color:#0f172a}table{border-collapse:collapse;width:100%;margin:1rem 0;font-size:.9rem}"
        "th,td{border:1px solid #d1d5db;padding:.4rem .6rem;text-align:left;vertical-align:top}"
        "th{background:#f3f4f6}blockquote{border-left:4px solid #f59e0b;background:#fffbeb;"
        "padding:.8rem;margin:1rem 0}code{background:#f3f4f6;padding:.1rem .3rem;border-radius:3px}"
        "li{margin:.25rem 0}</style></head><body>" + body + "</body></html>"
    )


def _inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


def generate_report(result: PipelineResult) -> dict[str, Path]:
    """Write Markdown, HTML and review-queue CSV to the configured reports folder."""
    directory = reports_dir(result.config)
    directory.mkdir(parents=True, exist_ok=True)
    markdown = build_markdown(result)
    md_path = ensure_parent(directory / "audit_report.md")
    html_path = directory / "audit_report.html"
    csv_path = directory / "review_queue.csv"
    md_path.write_text(markdown, encoding="utf-8")
    html_path.write_text(_markdown_to_html(markdown), encoding="utf-8")
    result.scoring.queue.to_csv(csv_path, index=False)
    return {"markdown": md_path, "html": html_path, "csv": csv_path}
