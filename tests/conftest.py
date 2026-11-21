"""Shared pytest fixtures."""

from __future__ import annotations

from typing import Any

import pytest

from src.config import load_config
from src.generate_data import GeneratedData, generate_data


@pytest.fixture(scope="session")
def config() -> dict[str, Any]:
    """Load the project configuration once per test session."""
    return load_config()


@pytest.fixture(scope="session")
def generated(config: dict[str, Any]) -> GeneratedData:
    """Generate the deterministic dataset once per test session."""
    return generate_data(config)


@pytest.fixture(scope="session")
def raw(generated: GeneratedData) -> dict[str, Any]:
    """Expose the generated tables in a dictionary keyed by table name."""
    return {
        "customers": generated.customers,
        "merchants": generated.merchants,
        "transactions": generated.transactions,
        "refunds": generated.refunds,
        "payment_status": generated.payment_status,
        "device_summary": generated.device_summary,
        "ground_truth": generated.ground_truth,
    }


@pytest.fixture(scope="session")
def validated(config: dict[str, Any], raw: dict[str, Any]):
    """Validation report for the generated dataset."""
    from src.validate import validate_data

    return validate_data(
        config, raw["transactions"], raw["refunds"], raw["payment_status"],
        raw["customers"], raw["merchants"], raw["device_summary"],
    )


@pytest.fixture(scope="session")
def reconciled(config: dict[str, Any], raw: dict[str, Any]):
    """Reconciliation result for the generated dataset."""
    from src.reconcile import reconcile

    return reconcile(config, raw["transactions"], raw["refunds"], raw["payment_status"])


@pytest.fixture(scope="session")
def indicator_result(config: dict[str, Any], raw: dict[str, Any], validated, reconciled):
    """Indicators for the generated dataset."""
    from src.indicators import compute_indicators

    return compute_indicators(
        config, reconciled.ledger, reconciled.deduped_events,
        raw["refunds"], validated,
    )


@pytest.fixture(scope="session")
def scoring_result(config: dict[str, Any], indicator_result):
    """Explainable review queue for the generated dataset."""
    from src.scoring import build_review_queue

    return build_review_queue(indicator_result, config)


@pytest.fixture(scope="session")
def pipeline_result(config, raw, validated, reconciled, indicator_result, scoring_result):
    """Assemble all artifacts in the same shape as the dashboard pipeline."""
    from src.pipeline import PipelineResult

    return PipelineResult(
        config=config,
        raw=raw,
        validation=validated,
        reconciliation=reconciled,
        indicators=indicator_result,
        scoring=scoring_result,
        source_files={},
    )
