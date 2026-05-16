"""main_loop modülü— yardımcı fonksiyonlar (ağır async döngü yok)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import super_otonom.health_summary as hs
import super_otonom.main_loop as ml


def test_handle_signal_sets_shutdown() -> None:
    ml._shutdown.clear()
    ml._handle_signal()
    assert ml._shutdown.is_set()


def test_circuit_breaker_open_helper() -> None:
    h = MagicMock()
    h.circuit_breaker_status.return_value = {"X": "OPEN (recovery=1s)"}
    assert ml._circuit_breaker_open(h, "X") is True
    h.circuit_breaker_status.return_value = {"X": "CLOSED"}
    assert ml._circuit_breaker_open(h, "X") is False


def test_prep_symbol_returns_none_when_cb_open() -> None:
    handler = MagicMock()
    handler.circuit_breaker_status.return_value = {"BTC/USDT": "OPEN (x)"}
    handler.fetch_order_book = AsyncMock()

    class A:
        def analyze(self, *a, **k):
            return {
                "signal": "HOLD",
                "regime": "TRENDING",
                "hurst": 0.5,
                "volatility": 0.02,
                "rsi": 50.0,
            }

        def analyze_v5_1(self, *a, **k):
            return self.analyze("", [])

        def apply_liquidity_context(self, *a, **k):
            pass

    engine = MagicMock()
    engine.equity = 1000.0
    engine.trade_log = []
    engine.sizer = MagicMock()
    engine.sizer.calculate.return_value = 100.0
    engine.sizer.set_trade_log = MagicMock()
    engine.risk = MagicMock()

    raw = {"BTC/USDT": [[0, 1, 1, 1, 1, 1]]}

    async def _run() -> None:
        out = await ml.prep_symbol_for_tick("BTC/USDT", handler, A(), engine, raw, {})
        assert out is None

    asyncio.run(_run())
    handler.fetch_order_book.assert_not_called()


def test_prep_symbol_cb_open_empty_raw_logs(caplog: pytest.LogCaptureFixture) -> None:
    handler = MagicMock()
    handler.circuit_breaker_status.return_value = {"Z/USDT": "OPEN (x)"}
    handler.fetch_order_book = AsyncMock()

    class A:
        def analyze(self, *a, **k):
            return {}

        def apply_liquidity_context(self, *a, **k):
            pass

    engine = MagicMock()
    engine.sizer = MagicMock()
    engine.risk = MagicMock()

    async def _run() -> None:
        with caplog.at_level("DEBUG", logger="super_otonom.main"):
            out = await ml.prep_symbol_for_tick("Z/USDT", handler, A(), engine, {}, {})
        assert out is None

    asyncio.run(_run())
    assert "CB_OPEN" in caplog.text and "Z/USDT" in caplog.text


def test_prep_symbol_storm_after_order_book(caplog: pytest.LogCaptureFixture) -> None:
    handler = MagicMock()
    handler.circuit_breaker_status.return_value = {}
    handler.fetch_order_book = AsyncMock(return_value={"asks": [[1.0, 1.0]], "bids": [[0.9, 1.0]]})

    class A:
        def analyze(self, *a, **k):
            return {
                "signal": "HOLD",
                "regime": "RANGING",
                "hurst": 0.5,
                "volatility": 0.05,
            }

        def apply_liquidity_context(self, *a, **k):
            pass

    engine = MagicMock()
    engine.equity = 10_000.0
    engine.trade_log = []
    engine.sizer = MagicMock()
    engine.sizer.validate_and_calculate.return_value = 1.0
    engine.sizer.calculate.return_value = 50.0
    engine.sizer.set_trade_log = MagicMock()
    engine.risk = MagicMock()

    ts = int(time.time() * 1000)
    raw = {"S/USDT": [[ts, 1.0, 1.1, 0.9, 1.0, 100.0]]}

    with patch.object(ml, "apply_storm_trip_to_risk", return_value=True):
        with caplog.at_level("CRITICAL", logger="super_otonom.main"):
            asyncio.run(ml.prep_symbol_for_tick("S/USDT", handler, A(), engine, raw, {}))

    assert "EMERGENCY_STOP" in caplog.text


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
