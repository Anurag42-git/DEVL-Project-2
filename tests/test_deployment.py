"""Tests for single-origin production serving and deployment overrides."""

from __future__ import annotations

import copy
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.static import mount_frontend
from src.config import load_config, review_db_path


def test_static_spa_serving_and_api_priority(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html><body>SPA</body></html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")

    config = copy.deepcopy(load_config())
    config["deployment"]["static_dir"] = str(dist)
    app = FastAPI()

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    mount_frontend(app, config)
    with TestClient(app) as client:
        assert "SPA" in client.get("/").text
        assert "SPA" in client.get("/review").text  # client-side route fallback
        assert client.get("/assets/app.js").text == "console.log('ok')"
        assert client.get("/api/health").json() == {"status": "ok"}
        assert client.get("/api/does-not-exist").status_code == 404
        assert client.get("/docs").status_code == 200


def test_missing_build_returns_hint(tmp_path: Path) -> None:
    config = copy.deepcopy(load_config())
    config["deployment"]["static_dir"] = str(tmp_path / "not-built")
    app = FastAPI()
    assert mount_frontend(app, config) is False
    with TestClient(app) as client:
        body = client.get("/").json()
        assert "npm" in body["message"]


def test_review_db_environment_override(monkeypatch) -> None:
    config = load_config()
    monkeypatch.setenv("REVIEW_DB_PATH", "persistent/reviews.db")
    path = review_db_path(config)
    assert path.name == "reviews.db"
    assert path.is_absolute()
    monkeypatch.delenv("REVIEW_DB_PATH")
    assert review_db_path(config).name == "review.db"
