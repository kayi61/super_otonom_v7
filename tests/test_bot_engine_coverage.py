"""BotEngine ve yardımcı sınıflar— yüksek kapsam (mock + tmp)."""

from __future__ import annotations

import asyncio
import importlib
import json
import random
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from super_otonom.bot_engine import (
    BotEngine,
    ExecutionSimulator,
    OrderTracker,
    TradeLogger,
    _min_entry_confidence,
)


def _be_mod():
    """test_bot_engine_96 modülü drop/reload yapabiliyor; StateManager her zaman güncel ``bot_engine`` kullanır."""
    return importlib.import_module("super_otonom.bot_engine")


def test_min_entry_confidence_clamp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENTRY_MIN_CONFIDENCE", "not-a-float")
    assert _min_entry_confidence() == 0.55
    monkeypatch.setenv("ENTRY_MIN_CONFIDENCE", "0.99")
    assert _min_entry_confidence() == 0.95
    monkeypatch.setenv("ENTRY_MIN_CONFIDENCE", "0.1")
    assert _min_entry_confidence() == 0.45


def test_execution_simulator_buy_paper(monkeypatch: pytest.MonkeyPatch) -> None:
    # ExecutionSimulator stdlib random.Random kullanır; sınıf metodunu sabitle.
    monkeypatch.setattr(random.Random, "uniform", lambda self, a, b: float(a))
    sim = ExecutionSimulator(
        slippage_range=(0.001, 0.001),
        latency_range=(0.0, 0.0),
        fill_ratio_range=(1.0, 1.0),
    )
    monkeypatch.setattr(_be_mod().asyncio, "sleep", AsyncMock())

    async def _run() -> None:
        r = await sim.simulate_order("buy", 100.0, 50.0, paper=True)
        assert "executed_price" in r
        assert r["filled_size"] > 0

    asyncio.run(_run())


def test_execution_simulator_sell_not_paper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(random.Random, "uniform", lambda self, a, b: float(a))
    sim = ExecutionSimulator(
        slippage_range=(0.001, 0.001),
        latency_range=(0.05, 0.05),
        fill_ratio_range=(1.0, 1.0),
    )

    async def _run() -> None:
        r = await sim.simulate_order("sell", 100.0, 50.0, paper=False)
        assert r["executed_price"] < 100.0

    asyncio.run(_run())


def test_trade_logger_writes_line(tmp_path: Path) -> None:
    p = tmp_path / "t" / "trades.log"
    tl = TradeLogger(str(p))
    tl.log_trade({"symbol": "X", "pnl": 1.0})
    text = p.read_text(encoding="utf-8")
    assert "X" in text
    assert "pnl" in text


def test_order_tracker_track_and_filled() -> None:
    ex = MagicMock()
    ex.get_order_status = AsyncMock(return_value="filled")
    ot = OrderTracker(ex)
    asyncio.run(ot.check_status())  # empty
    ot.track("oid1", "BTC/USDT")
    asyncio.run(ot.check_status())
    assert "oid1" not in ot.active_orders


def test_order_tracker_timeout_cancel() -> None:
    ex = MagicMock()
    ex.get_order_status = AsyncMock(return_value="open")
    ex.cancel_order = AsyncMock(return_value=None)
    ot = OrderTracker(ex)
    ot._timeout_sec = -1.0
    ot.track("oid1", "BTC/USDT")
    asyncio.run(ot.check_status())
    ex.cancel_order.assert_awaited()


def test_bot_engine_open_exposure_and_avg_volume() -> None:
    e = BotEngine(capital=1000.0, paper=True)
    pr = {"BTC/USDT": 50000.0}
    e.open_positions["BTC/USDT"] = {"entry": 50000.0, "qty": 0.1}
    assert e._open_exposure(pr) > 0
    assert e._avg_volume([]) == 1.0
    c = [{"volume": 2.0}, {"volume": 4.0}]
    assert e._avg_volume(c, n=10) >= 1.0


def test_bot_engine_status_and_calc_wr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    st = tmp_path / "state.json"
    monkeypatch.setattr(_be_mod(), "_STATE_FILE", str(st))
    monkeypatch.setattr(_be_mod(), "_TRADE_LOG_FILE", str(tmp_path / "tr" / "trades.log"))
    e = BotEngine(capital=1000.0, paper=True)
    e.trade_log.append({"pnl": 10.0})
    e.trade_log.append({"pnl": -2.0})
    s = e.status()
    assert s["mode"] == "PAPER"
    assert s["total_trades"] == 2
    assert s["order_tracker_active"] is False
    wr, rr, g = e._calc_wr_rr()
    assert wr is not None and rr is not None
    e2 = BotEngine(capital=100.0, paper=True)
    w2, r2, g2 = e2._calc_wr_rr()
    assert w2 is None and g2 == "kapanan_islem_yok"


def test_tick_empty_candles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_be_mod(), "_STATE_FILE", str(tmp_path / "s.json"))
    monkeypatch.setattr(_be_mod(), "_TRADE_LOG_FILE", str(tmp_path / "trades.log"))
    e = BotEngine(capital=1000.0, paper=True)

    async def _run() -> None:
        out = await e.tick("BTC/USDT", {}, [])
        assert out["final_signal"] == "HOLD"
        assert out["actions"] == []

    asyncio.run(_run())


def test_tick_hold_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_be_mod(), "_STATE_FILE", str(tmp_path / "s.json"))
    monkeypatch.setattr(_be_mod(), "_TRADE_LOG_FILE", str(tmp_path / "trades.log"))
    monkeypatch.setenv("GLOBAL_TRADE_DISABLE", "0")
    e = BotEngine(capital=10000.0, paper=True)
    candles = [{"close": 100.0, "volume": 1e6}]
    analysis = {
        "signal": "HOLD",
        "volatility": 0.02,
        "regime": "TRENDING",
        "hurst": 0.55,
        "rsi": 50.0,
        "strategist": "trend",
    }

    async def _run() -> None:
        out = await e.tick("BTC/USDT", analysis, candles)
        assert out["symbol"] == "BTC/USDT"
        assert out.get("decision_context") is not None

    asyncio.run(_run())


def test_global_trade_disable_short_circuit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_be_mod(), "_STATE_FILE", str(tmp_path / "s.json"))
    monkeypatch.setattr(_be_mod(), "_TRADE_LOG_FILE", str(tmp_path / "trades.log"))
    monkeypatch.setenv("GLOBAL_TRADE_DISABLE", "1")
    e = BotEngine(capital=1000.0, paper=True)
    candles = [{"close": 1.0, "volume": 1.0}]

    async def _run() -> None:
        out = await e.tick("X", {"signal": "BUY", "volatility": 0.01}, candles)
        assert out["decision_context"] is not None

    asyncio.run(_run())
    monkeypatch.setenv("GLOBAL_TRADE_DISABLE", "0")


def test_close_on_strategy_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_be_mod(), "_STATE_FILE", str(tmp_path / "s.json"))
    monkeypatch.setattr(_be_mod(), "_TRADE_LOG_FILE", str(tmp_path / "trades.log"))
    e = BotEngine(capital=1000.0, paper=True)

    async def _run() -> None:
        r = await e.close_on_strategy_change("A", [], {})
        assert r["final_signal"] == "HOLD"
        e.open_positions["A"] = {"entry": 1.0, "qty": 1.0, "size": 1.0, "peak": 1.0, "hold_bars": 0}
        c = [{"close": 1.0, "volume": 1.0}]
        r2 = await e.close_on_strategy_change("A", c, {"strategist": "t", "volatility": 0.01})
        assert "A" not in e.open_positions
        assert any(a.get("type") == "SELL" for a in r2.get("actions", []))

    asyncio.run(_run())


def test_set_exchange_and_shutdown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_be_mod(), "_STATE_FILE", str(tmp_path / "s.json"))
    monkeypatch.setattr(_be_mod(), "_TRADE_LOG_FILE", str(tmp_path / "trades.log"))
    e = BotEngine(capital=100.0, paper=True)
    e.set_exchange_handler(MagicMock())
    assert e.status()["order_tracker_active"] is True
    e.shutdown()


def test_tick_async_order_tracker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_be_mod(), "_STATE_FILE", str(tmp_path / "s.json"))
    monkeypatch.setattr(_be_mod(), "_TRADE_LOG_FILE", str(tmp_path / "trades.log"))
    ex = MagicMock()
    ex.get_order_status = AsyncMock(return_value="filled")
    e = BotEngine(capital=2000.0, paper=True, exchange_handler=ex)
    e._tick_counter = 9
    analysis = {
        "signal": "HOLD",
        "volatility": 0.02,
        "regime": "TRENDING",
        "hurst": 0.6,
    }
    candles = [{"close": 50.0, "volume": 1e3}]

    async def _run() -> None:
        await e.tick_async("ETH/USDT", analysis, candles)
        e._tick_counter = 10
        await e.tick_async("ETH/USDT", analysis, candles)

    asyncio.run(_run())


def test_check_orders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_be_mod(), "_STATE_FILE", str(tmp_path / "s.json"))
    monkeypatch.setattr(_be_mod(), "_TRADE_LOG_FILE", str(tmp_path / "trades.log"))

    async def _run() -> None:
        e = BotEngine(100.0, paper=True)
        await e.check_orders()
        e.set_exchange_handler(MagicMock())
        await e.check_orders()

    asyncio.run(_run())


def test_load_state_mode_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "st.json"
    p.write_text(
        json.dumps(
            {
                "mode": "LIVE",
                "equity": 999.0,
                "open_positions": {},
                "trade_log": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(_be_mod(), "_STATE_FILE", str(p))
    monkeypatch.setattr(_be_mod(), "_TRADE_LOG_FILE", str(tmp_path / "t.log"))
    e = BotEngine(100.0, paper=True)
    assert e.mode == "PAPER"


def test_load_state_happy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "st.json"
    p.write_text(
        json.dumps(
            {
                "mode": "PAPER",
                "equity": 500.0,
                "free_capital": 500.0,
                "peak_equity": 1000.0,
                "open_positions": {},
                "trade_log": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(_be_mod(), "_STATE_FILE", str(p))
    monkeypatch.setattr(_be_mod(), "_TRADE_LOG_FILE", str(tmp_path / "t.log"))
    e2 = BotEngine(100.0, paper=True)
    assert e2.equity == 500.0
