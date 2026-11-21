"""Review outcomes with an append-only who/what/when audit trail.

Storage is selected automatically:
* local SQLite (``data/review.db``) by default;
* Vercel KV / Upstash REST when ``KV_REST_API_URL`` and ``KV_REST_API_TOKEN``
  are set. Serverless filesystems are ephemeral, so SQLite cannot persist there.

Both backends expose the same public functions, so the rest of the app is
unchanged.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from .config import load_config, review_db_path

OUTCOMES = ("pending", "reviewed_normal", "needs_follow_up", "escalated")
OUTCOME_COLUMNS = ["record_id", "outcome", "reviewer", "notes", "updated_at"]
AUDIT_COLUMNS = ["id", "record_id", "old_outcome", "new_outcome", "reviewer", "notes", "changed_at"]

OUTCOME_KEY_PREFIX = "review:outcome:"
OUTCOME_IDS_KEY = "review:outcome-ids"
AUDIT_KEY = "review:audit"


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _kv_configured() -> bool:
    return bool(os.environ.get("KV_REST_API_URL") and os.environ.get("KV_REST_API_TOKEN"))


def _kv_command(*command: Any) -> Any:
    """Run one command against the Upstash/Vercel KV REST API."""
    url = os.environ["KV_REST_API_URL"].rstrip("/")
    token = os.environ["KV_REST_API_TOKEN"]
    response = httpx.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        json=list(command),
        timeout=10.0,
    )
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict) and "error" in payload:
        raise RuntimeError(f"Vercel KV error: {payload['error']}")
    return payload.get("result") if isinstance(payload, dict) else payload


def _kv_outcome_key(record_id: str) -> str:
    return f"{OUTCOME_KEY_PREFIX}{record_id}"


# --------------------------------------------------------------------------
# SQLite backend (local development and container deployments)
# --------------------------------------------------------------------------
def _connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def init_db(db_path: str | Path) -> None:
    """Create tables if they do not exist (safe to call repeatedly)."""
    with _connect(db_path) as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS review_outcomes (
                   record_id TEXT PRIMARY KEY,
                   outcome TEXT NOT NULL,
                   reviewer TEXT NOT NULL DEFAULT '',
                   notes TEXT NOT NULL DEFAULT '',
                   updated_at TEXT NOT NULL
               )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS review_audit (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   record_id TEXT NOT NULL,
                   old_outcome TEXT NOT NULL,
                   new_outcome TEXT NOT NULL,
                   reviewer TEXT NOT NULL,
                   notes TEXT NOT NULL,
                   changed_at TEXT NOT NULL
               )"""
        )


def _sqlite_get_outcome(record_id: str, db_path: str | Path) -> dict[str, str]:
    init_db(db_path)
    with _connect(db_path) as connection:
        row = connection.execute(
            "SELECT record_id, outcome, reviewer, notes, updated_at "
            "FROM review_outcomes WHERE record_id = ?",
            (str(record_id),),
        ).fetchone()
    if row is None:
        return {
            "record_id": str(record_id), "outcome": "pending", "reviewer": "",
            "notes": "", "updated_at": "",
        }
    return dict(row)


def _sqlite_list_outcomes(db_path: str | Path) -> pd.DataFrame:
    init_db(db_path)
    with _connect(db_path) as connection:
        rows = connection.execute(
            "SELECT record_id, outcome, reviewer, notes, updated_at FROM review_outcomes"
        ).fetchall()
    return pd.DataFrame([dict(row) for row in rows], columns=OUTCOME_COLUMNS)


def _sqlite_set_outcome(
    record_id: str, outcome: str, reviewer: str, notes: str, db_path: str | Path
) -> dict[str, str]:
    init_db(db_path)
    now = _timestamp()
    with _connect(db_path) as connection:
        existing = connection.execute(
            "SELECT outcome FROM review_outcomes WHERE record_id = ?",
            (str(record_id),),
        ).fetchone()
        old = existing["outcome"] if existing else "pending"
        connection.execute(
            """INSERT INTO review_outcomes (record_id, outcome, reviewer, notes, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(record_id) DO UPDATE SET
                   outcome=excluded.outcome, reviewer=excluded.reviewer,
                   notes=excluded.notes, updated_at=excluded.updated_at""",
            (str(record_id), outcome, reviewer, notes, now),
        )
        connection.execute(
            """INSERT INTO review_audit
               (record_id, old_outcome, new_outcome, reviewer, notes, changed_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (str(record_id), old, outcome, reviewer, notes, now),
        )
    return {
        "record_id": str(record_id), "outcome": outcome, "reviewer": reviewer,
        "notes": notes, "updated_at": now,
    }


def _sqlite_audit_trail(db_path: str | Path, record_id: str | None) -> pd.DataFrame:
    init_db(db_path)
    with _connect(db_path) as connection:
        if record_id is None:
            rows = connection.execute(
                "SELECT " + ", ".join(AUDIT_COLUMNS) + " FROM review_audit ORDER BY id"
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT " + ", ".join(AUDIT_COLUMNS) + " FROM review_audit "
                "WHERE record_id = ? ORDER BY id",
                (str(record_id),),
            ).fetchall()
    return pd.DataFrame([dict(row) for row in rows], columns=AUDIT_COLUMNS)


# --------------------------------------------------------------------------
# Vercel KV backend (serverless production)
# --------------------------------------------------------------------------
def _kv_get_outcome(record_id: str) -> dict[str, str]:
    raw = _kv_command("GET", _kv_outcome_key(str(record_id)))
    if raw:
        return json.loads(raw)
    return {
        "record_id": str(record_id), "outcome": "pending", "reviewer": "",
        "notes": "", "updated_at": "",
    }


def _kv_list_outcomes() -> pd.DataFrame:
    ids = _kv_command("SMEMBERS", OUTCOME_IDS_KEY) or []
    rows = []
    for record_id in ids:
        value = _kv_command("GET", _kv_outcome_key(str(record_id)))
        if value:
            rows.append(json.loads(value))
    return pd.DataFrame(rows, columns=OUTCOME_COLUMNS)


def _kv_set_outcome(
    record_id: str, outcome: str, reviewer: str, notes: str
) -> dict[str, str]:
    old = _kv_get_outcome(record_id)["outcome"]
    now = _timestamp()
    saved = {
        "record_id": str(record_id), "outcome": outcome, "reviewer": reviewer,
        "notes": notes, "updated_at": now,
    }
    _kv_command("SET", _kv_outcome_key(str(record_id)), json.dumps(saved))
    _kv_command("SADD", OUTCOME_IDS_KEY, str(record_id))
    _kv_command(
        "LPUSH", AUDIT_KEY,
        json.dumps({
            "id": int(time.time() * 1000),
            "record_id": str(record_id),
            "old_outcome": old,
            "new_outcome": outcome,
            "reviewer": reviewer,
            "notes": notes,
            "changed_at": now,
        }),
    )
    return saved


def _kv_audit_trail(record_id: str | None) -> pd.DataFrame:
    values = _kv_command("LRANGE", AUDIT_KEY, 0, -1) or []
    rows = [json.loads(value) for value in values]
    rows.reverse()  # LPUSH stores newest first; public API returns chronological order
    if record_id is not None:
        rows = [row for row in rows if row.get("record_id") == str(record_id)]
    return pd.DataFrame(rows, columns=AUDIT_COLUMNS)


# --------------------------------------------------------------------------
# Public API — unchanged for callers
# --------------------------------------------------------------------------
def get_outcome(record_id: str, db_path: str | Path) -> dict[str, str]:
    """Return the current outcome for a record; missing records are ``pending``."""
    if _kv_configured():
        return _kv_get_outcome(record_id)
    return _sqlite_get_outcome(record_id, db_path)


def list_outcomes(
    db_path: str | Path | None = None,
    config: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Return all stored outcomes as a DataFrame."""
    if _kv_configured():
        return _kv_list_outcomes()
    if db_path is None:
        db_path = review_db_path(config or load_config())
    return _sqlite_list_outcomes(db_path)


def set_outcome(
    record_id: str,
    outcome: str,
    reviewer: str = "",
    notes: str = "",
    db_path: str | Path | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Set a review outcome and append one audit row, even for the first value.

    Raises:
        ValueError: If ``outcome`` is not one of :data:`OUTCOMES`.
    """
    if outcome not in OUTCOMES:
        raise ValueError(f"Unknown review outcome {outcome!r}; expected one of {OUTCOMES}")
    if _kv_configured():
        return _kv_set_outcome(record_id, outcome, reviewer, notes)
    if db_path is None:
        db_path = review_db_path(config or load_config())
    return _sqlite_set_outcome(record_id, outcome, reviewer, notes, db_path)


def audit_trail(
    db_path: str | Path | None = None,
    record_id: str | None = None,
    config: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Return the audit trail, optionally filtered to one record."""
    if _kv_configured():
        return _kv_audit_trail(record_id)
    if db_path is None:
        db_path = review_db_path(config or load_config())
    return _sqlite_audit_trail(db_path, record_id)
