"""main_loop modülü— yardımcı fonksiyonlar (ağır async döngü yok)."""
from __future__ import annotations

import logging
from typing import Any
from unittest.mock import patch

import pytest
import super_otonom.health_summary as hs
import super_otonom.main_loop as ml


def test_handle_signal_sets_shutdown() -> None:
    ml._shutdown.clear()
    ml._handle_signal()
    assert ml._shutdown.is_set()


@pytest.fixture
def mock_engine() -> Any:
    class E:
        risk = type("R", (), {"emergency_stop": False})()

    return E()


def test_log_elite_startup(mock_engine: Any) -> None:
    ml._log_elite_startup(mock_engine)


def test_ensure_health_file_handler_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hs, "_HEALTH_FILE_SETUP", False)
    with patch("super_otonom.health_summary.logging.FileHandler", side_effect=OSError("e")):
        hs.ensure_health_file_logger("x_logs")
    assert hs._HEALTH_FILE_SETUP is True
    assert hs.log_health.propagate is True


def test_format_tick_health_emergency_on_label() -> None:
    s = {
        "emergency_stop": True,
        "emergency_reason": None,
        "pnl_pct": 0.0,
        "exposure_pct": 0.0,
        "hard_limits": {},
    }
    out = hs.format_tick_health(s, None)
    assert "Emergency(on)" in out


def test_log_tick_health_filehandler_flush(tmp_path: object) -> None:
    p = str(tmp_path / "health_t.log")
    fh = logging.FileHandler(p, encoding="utf-8")
    hs.log_health.addHandler(fh)
    try:
        hs.log_tick_health(
            {"pnl_pct": 0.0, "exposure_pct": 0.0, "hard_limits": {}},
            {"symbol": "S", "tick_id": 1},
        )
    finally:
        hs.log_health.removeHandler(fh)
        fh.close()
