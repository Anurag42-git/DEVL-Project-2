"""Smoke test for the Streamlit dashboard using AppTest."""

from __future__ import annotations

from src.config import PROJECT_ROOT


def test_all_page_files_exist() -> None:
    expected = [
        "legacy/app.py", "legacy/pages/2_Reconciled_Ledger.py",
        "legacy/pages/3_Review_Queue.py", "legacy/pages/4_Data_Quality.py",
        "legacy/pages/5_Audit_Report.py",
    ]
    for name in expected:
        assert (PROJECT_ROOT / name).is_file(), name


def test_overview_page_renders_without_errors() -> None:
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(PROJECT_ROOT / "legacy" / "app.py"), default_timeout=180).run()
    assert not app.exception, [str(error.value) for error in app.exception]
    assert any("Transaction Anomaly" in title.value for title in app.title)
    assert len(app.metric) >= 4
