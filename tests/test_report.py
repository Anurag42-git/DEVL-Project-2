"""Tests for the audit report and ground-truth detection metrics."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.report import DetectionQuality, build_markdown, compute_detection_quality, generate_report


def test_report_files_and_sections(pipeline_result, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("src.report.reports_dir", lambda config: tmp_path)
    files = generate_report(pipeline_result)
    assert set(files) == {"markdown", "html", "csv"}
    for path in files.values():
        assert Path(path).is_file() and Path(path).stat().st_size > 0

    markdown = files["markdown"].read_text(encoding="utf-8")
    for section in [
        "## 1. Data summary", "## 2. Validation findings",
        "## 3. Reconciliation adjustments", "## 4. Methodology and thresholds",
        "## 5. Flagged-record summary", "## 6. Review outcomes",
        "## 7. Detection quality", "## 8. Limitations and assumptions",
    ]:
        assert section in markdown
    assert "Duplicate events removed" in markdown
    assert "PASS" in markdown
    assert "not determinations of fraud" in markdown

    html = files["html"].read_text(encoding="utf-8")
    assert "<table>" in html and "<h2>" in html
    assert "<code>" in html
    assert "Disclaimer" in html
    assert pd.read_csv(files["csv"])["record_id"].notna().all()


def test_detection_quality_metrics(pipeline_result) -> None:
    quality = compute_detection_quality(pipeline_result)
    assert isinstance(quality, DetectionQuality)
    assert 0 <= quality.precision <= 1
    assert 0 <= quality.recall <= 1
    assert quality.recall >= 0.75
    assert quality.expected_pairs > 100
    assert quality.matched_pairs <= quality.detected_pairs
    assert not quality.by_reason.empty
    assert set(quality.by_reason.columns) == {"reason_code", "injected", "detected", "missed", "recall"}
    assert "Recall" in build_markdown(pipeline_result)


def test_missing_ground_truth_is_handled(pipeline_result, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("src.report.ground_truth_file", lambda config: tmp_path / "missing.csv")
    assert compute_detection_quality(pipeline_result) is None
    text = build_markdown(pipeline_result)
    assert "not computed" in text
