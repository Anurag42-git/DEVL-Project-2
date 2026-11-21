"""Tests for the FastAPI endpoints."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import state
from api.main import app


@pytest.fixture()
def api_client(tmp_path: Path, pipeline_result):
    """Install an isolated pipeline result with a temporary review database."""
    result = copy.deepcopy(pipeline_result)
    result.config["data"]["review_db"] = str(tmp_path / "review.db")
    state.set_result(result)
    with TestClient(app) as client:
        yield client, result
    state.clear_result()


def test_health_and_reload(api_client, monkeypatch) -> None:
    client, result = api_client
    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["cache"]["loaded"] is True

    monkeypatch.setattr(state, "run_pipeline", lambda: copy.deepcopy(result))
    reloaded = client.post("/api/reload").json()
    assert reloaded["status"] == "ok"
    assert reloaded["cache"]["generated_at"]


def test_overview_kpis_and_series(api_client) -> None:
    client, _ = api_client
    body = client.get("/api/overview").json()
    kpis = {item["id"]: item for item in body["kpis"]}
    assert set(kpis) == {"transactions", "captured", "refund_ratio", "flagged", "pending"}
    assert kpis["flagged"]["value"] <= kpis["transactions"]["value"]
    assert 0.05 <= body["metrics"]["flag_rate"] <= 0.15
    assert body["daily"] and body["reason_counts"]
    assert len(body["needs_attention"]) <= 5
    assert "not fraud determinations" in body["disclaimer"]
    assert body["conservation"]["matched"] is True


def test_ledger_filters_sorting_and_pagination(api_client) -> None:
    client, result = api_client
    txn_id = result.reconciliation.ledger.iloc[0]["transaction_id"]
    assert client.get("/api/ledger", params={"page_size": 5}).json()["total"] > 5
    found = client.get("/api/ledger", params={"search": str(txn_id)}).json()
    assert found["total"] == 1
    assert found["items"][0]["transaction_id"] == txn_id

    desc = client.get("/api/ledger", params={
        "sort_by": "captured_amount", "sort_dir": "desc", "page_size": 5
    }).json()["items"]
    amounts = [row["captured_amount"] for row in desc]
    assert amounts == sorted(amounts, reverse=True)

    status = result.reconciliation.ledger.iloc[0]["final_status"]
    filtered = client.get("/api/ledger", params={"status": str(status)}).json()
    assert filtered["total"] > 0
    assert all(row["final_status"] == status for row in filtered["items"])
    assert client.get("/api/ledger", params={"page": 0}).status_code == 422


def test_transaction_detail_and_unknown(api_client) -> None:
    client, result = api_client
    txn_id = str(result.reconciliation.ledger.iloc[0]["transaction_id"])
    detail = client.get(f"/api/transactions/{txn_id}").json()
    assert detail["ledger"]["transaction_id"] == txn_id
    assert detail["events"] and detail["status_history"]
    assert detail["timeline"]
    assert isinstance(detail["reasons"], list)
    assert "reconciliation_notes" in detail
    assert client.get("/api/transactions/DOES-NOT-EXIST").status_code == 404


def test_review_queue_filters(api_client) -> None:
    client, result = api_client
    base = client.get("/api/review-queue", params={"page_size": 10}).json()
    assert base["total"] > 10
    assert base["flagged_transactions"] <= base["total_transactions"]
    assert len(base["items"][0]["reasons"]) >= 1

    high = client.get("/api/review-queue", params={"priority": "high"}).json()
    assert high["items"] and all(item["priority"] == "high" for item in high["items"])

    code = base["items"][0]["reason_codes"][0]
    by_reason = client.get("/api/review-queue", params={"reason": code}).json()
    assert by_reason["items"]
    assert all(code in item["reason_codes"] for item in by_reason["items"])

    entity = client.get("/api/review-queue", params={"record_type": "device"}).json()
    assert entity["items"] and all(item["record_type"] == "device" for item in entity["items"])
    assert client.get("/api/review-queue", params={"page_size": 500}).status_code == 422


def test_outcome_validation_audit_and_bulk(api_client) -> None:
    client, result = api_client
    pending = result.scoring.queue[result.scoring.queue["outcome"] == "pending"]
    record_id = str(pending.iloc[0]["record_id"])

    missing_notes = client.post(f"/api/review/{record_id}/outcome", json={
        "outcome": "escalated", "reviewer": "alice", "notes": "   "
    })
    assert missing_notes.status_code == 422

    saved = client.post(f"/api/review/{record_id}/outcome", json={
        "outcome": "needs_follow_up", "reviewer": "alice", "notes": "verify merchant records"
    })
    assert saved.status_code == 200
    assert saved.json()["outcome"] == "needs_follow_up"

    queue_after = client.get("/api/review-queue", params={
        "search": record_id, "outcome": "needs_follow_up"
    }).json()
    assert queue_after["total"] == 1
    assert queue_after["items"][0]["reviewer"] == "alice"

    trail = client.get(f"/api/audit-trail/{record_id}").json()
    assert trail["total"] == 1
    assert trail["items"][0]["old_outcome"] == "pending"
    assert trail["items"][0]["new_outcome"] == "needs_follow_up"

    ids = [str(value) for value in pending["record_id"].head(3)]
    bulk = client.post("/api/review/bulk-outcome", json={
        "record_ids": ids, "outcome": "reviewed_normal", "reviewer": "bob", "notes": "checked"
    })
    assert bulk.status_code == 200
    assert len(bulk.json()) == 3
    assert client.post("/api/review/bulk-outcome", json={
        "record_ids": ["UNKNOWN"], "outcome": "reviewed_normal"
    }).status_code == 404


def test_data_quality_and_report(api_client) -> None:
    client, _ = api_client
    quality = client.get("/api/data-quality").json()
    assert len(quality["summary"]) >= 18
    assert quality["totals"]["violations"] > 0
    assert "authorized" in quality["state_machine"]

    report = client.get("/api/report").json()
    assert len(report["sections"]) >= 8
    assert report["detection_quality"]["recall"] >= 0.75
    assert report["sections"][0]["title"].startswith("1.")

    for fmt in ("md", "html", "csv"):
        response = client.get(f"/api/report/download/{fmt}")
        assert response.status_code == 200
        assert len(response.content) > 100
    assert client.get("/api/report/download/pdf").status_code == 400
