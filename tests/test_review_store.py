"""Tests for review outcomes and the append-only audit trail."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from src.config import review_db_path
from src.review_store import (
    OUTCOMES,
    audit_trail,
    get_outcome,
    init_db,
    list_outcomes,
    set_outcome,
)


def test_default_outcome_is_pending(tmp_path: Path) -> None:
    db = tmp_path / "review.db"
    outcome = get_outcome("TXN-1", db)
    assert outcome["outcome"] == "pending"
    assert outcome["notes"] == ""


def test_set_outcome_writes_audit_row(tmp_path: Path) -> None:
    db = tmp_path / "review.db"
    set_outcome("TXN-1", "needs_follow_up", "alice", "check refund timing", db)
    current = get_outcome("TXN-1", db)
    assert current["outcome"] == "needs_follow_up"
    assert current["reviewer"] == "alice"
    assert current["notes"] == "check refund timing"
    assert current["updated_at"]

    audit = audit_trail(db)
    assert len(audit) == 1
    assert audit.iloc[0]["old_outcome"] == "pending"
    assert audit.iloc[0]["new_outcome"] == "needs_follow_up"
    assert audit.iloc[0]["reviewer"] == "alice"


def test_every_change_is_audited(tmp_path: Path) -> None:
    db = tmp_path / "nested" / "review.db"
    set_outcome("TXN-2", "escalated", "bob", "first pass", db)
    set_outcome("TXN-2", "reviewed_normal", "carol", "verified with merchant", db)
    trail = audit_trail(db, record_id="TXN-2")
    assert len(trail) == 2
    assert list(trail["old_outcome"]) == ["pending", "escalated"]
    assert list(trail["new_outcome"]) == ["escalated", "reviewed_normal"]
    assert list(trail["reviewer"]) == ["bob", "carol"]
    assert list_outcomes(db).loc[0, "outcome"] == "reviewed_normal"
    assert audit_trail(tmp_path / "empty.db").empty


def test_invalid_outcome_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        set_outcome("TXN-3", "confirmed_fraud", db_path=tmp_path / "review.db")
    assert set(OUTCOMES) == {"pending", "reviewed_normal", "needs_follow_up", "escalated"}


def test_db_path_comes_from_config(config: dict) -> None:
    path = review_db_path(config)
    assert path.name == "review.db"
    assert path.parent.is_dir()
    init_db(path)
    assert path.is_file()


def test_vercel_kv_backend(monkeypatch) -> None:
    """KV credentials switch the same public API to REST-backed storage."""
    store: dict[str, Any] = {"outcomes": {}, "ids": set(), "audit": []}

    class Response:
        def __init__(self, result: Any) -> None:
            self.result = result

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"result": self.result}

    def fake_post(url: str, headers: dict, json: list, timeout: float) -> Response:
        assert url == "https://kv.example.test"
        assert headers["Authorization"].startswith("Bearer ")
        command = json
        operation = str(command[0]).upper()
        if operation == "GET":
            result = store["outcomes"].get(command[1])
        elif operation == "SET":
            store["outcomes"][command[1]] = command[2]
            result = "OK"
        elif operation == "SADD":
            store["ids"].add(command[2])
            result = 1
        elif operation == "SMEMBERS":
            result = sorted(store["ids"])
        elif operation == "LPUSH":
            store["audit"].insert(0, command[2])
            result = len(store["audit"])
        elif operation == "LRANGE":
            start = int(command[2])
            end = int(command[3])
            result = store["audit"][start:] if end == -1 else store["audit"][start:end + 1]
        else:
            raise AssertionError(f"unexpected command {command}")
        return Response(result)

    monkeypatch.setenv("KV_REST_API_URL", "https://kv.example.test")
    monkeypatch.setenv("KV_REST_API_TOKEN", "token")
    monkeypatch.setattr("src.review_store.httpx.post", fake_post)

    assert get_outcome("TXN-KV", "unused.db")["outcome"] == "pending"
    set_outcome("TXN-KV", "escalated", "alice", "needs review")
    assert get_outcome("TXN-KV", "unused.db")["outcome"] == "escalated"
    assert list_outcomes().iloc[0]["reviewer"] == "alice"

    set_outcome("TXN-KV", "reviewed_normal", "bob", "verified")
    trail = audit_trail(record_id="TXN-KV")
    assert len(trail) == 2
    assert list(trail["old_outcome"]) == ["pending", "escalated"]
    assert list(trail["new_outcome"]) == ["escalated", "reviewed_normal"]
