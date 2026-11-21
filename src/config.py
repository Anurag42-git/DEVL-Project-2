"""Configuration loading and project-root-aware path resolution.

All tunable values live in ``config.yaml``. No module contains hard-coded data
or report file paths; they are resolved relative to the project root here.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_FILE: Path = PROJECT_ROOT / "config.yaml"


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load ``config.yaml`` and return it as a plain dictionary.

    Args:
        path: Optional explicit config file. Defaults to ``<project root>/config.yaml``.

    Raises:
        FileNotFoundError: If the config file does not exist.
        ValueError: If the YAML root is not a mapping.
    """
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_FILE
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    if not config_path.is_file():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"Configuration root must be a mapping: {config_path}")
    return loaded


def get_path(config: dict[str, Any], dotted_key: str, default: Any = None) -> Any:
    """Read a nested config value using a dotted key such as ``data.files.transactions``."""
    node: Any = config
    for part in dotted_key.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def require_path(config: dict[str, Any], dotted_key: str) -> Any:
    """Like :func:`get_path` but raises when the key is absent."""
    sentinel = object()
    value = get_path(config, dotted_key, sentinel)
    if value is sentinel:
        raise KeyError(f"Missing required configuration key: {dotted_key}")
    return value


def resolve_path(config: dict[str, Any], dotted_key: str) -> Path:
    """Resolve a configured relative path against the project root."""
    raw = require_path(config, dotted_key)
    path = Path(str(raw))
    return path if path.is_absolute() else PROJECT_ROOT / path


def data_file(config: dict[str, Any], name: str) -> Path:
    """Return the absolute path of a named data CSV (e.g. ``transactions``)."""
    data_dir = resolve_path(config, "data.directory")
    filename = require_path(config, f"data.files.{name}")
    return data_dir / str(filename)


def ground_truth_file(config: dict[str, Any]) -> Path:
    """Return the path of the hidden injected-issue answer key."""
    return resolve_path(config, "data.directory") / str(
        require_path(config, "data.ground_truth")
    )


def reports_dir(config: dict[str, Any]) -> Path:
    """Return the (possibly not-yet-created) reports directory."""
    return resolve_path(config, "data.reports_directory")


def review_db_path(config: dict[str, Any]) -> Path:
    """Return the SQLite review database path.

    ``REVIEW_DB_PATH`` overrides the configured location so container deployments
    can persist review outcomes on a mounted volume without changing config.yaml.
    """
    override = os.environ.get("REVIEW_DB_PATH")
    if override:
        path = Path(override)
        return path if path.is_absolute() else PROJECT_ROOT / path
    return resolve_path(config, "data.review_db")
