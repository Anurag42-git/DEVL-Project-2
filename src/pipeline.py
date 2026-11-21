"""Single orchestration path used by the dashboard, report and tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import DEFAULT_CONFIG_FILE, data_file, load_config
from .indicators import IndicatorResult, compute_indicators
from .reconcile import ReconciliationResult, reconcile
from .scoring import ScoringResult, build_review_queue
from .utils import read_csv
from .validate import ValidationReport, validate_data


@dataclass
class PipelineResult:
    """All artifacts produced from one pass over the generated CSV files."""

    config: dict[str, Any]
    raw: dict[str, Any]
    validation: ValidationReport
    reconciliation: ReconciliationResult
    indicators: IndicatorResult
    scoring: ScoringResult
    source_files: dict[str, Path]


def data_fingerprint(config: dict[str, Any] | None = None) -> tuple[tuple[str, int], ...]:
    """File names and modification times used to invalidate dashboard caches."""
    cfg = config or load_config()
    paths = [DEFAULT_CONFIG_FILE] + [
        data_file(cfg, name) for name in (
            "customers", "merchants", "transactions", "refunds",
            "payment_status", "device_summary",
        )
    ]
    return tuple((str(path), int(path.stat().st_mtime_ns)) for path in paths if path.exists())


def run_pipeline(config: dict[str, Any] | None = None) -> PipelineResult:
    """Load raw CSVs, validate, reconcile, compute indicators and score records."""
    cfg = config or load_config()
    source_files = {
        name: data_file(cfg, name)
        for name in (
            "customers", "merchants", "transactions", "refunds",
            "payment_status", "device_summary",
        )
    }
    raw = {name: read_csv(path) for name, path in source_files.items()}
    validation = validate_data(
        cfg, raw["transactions"], raw["refunds"], raw["payment_status"],
        raw["customers"], raw["merchants"], raw["device_summary"],
    )
    reconciliation = reconcile(
        cfg, raw["transactions"], raw["refunds"], raw["payment_status"]
    )
    indicators = compute_indicators(
        cfg, reconciliation.ledger, reconciliation.deduped_events,
        raw["refunds"], validation,
    )
    scoring = build_review_queue(indicators, cfg)
    return PipelineResult(
        config=cfg,
        raw=raw,
        validation=validation,
        reconciliation=reconciliation,
        indicators=indicators,
        scoring=scoring,
        source_files=source_files,
    )
