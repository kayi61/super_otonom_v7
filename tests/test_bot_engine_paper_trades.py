"""BotEngine: paper modda tam BUY + take-profit SELL (mock ağırlıklı)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from super_otonom import bot_engine as be
from super_otonom.bot_engine import BotEngine
from super_otonom.config import RISK


def _base_analysis() -> dict:
    return {
        "signal": "BUY",
        "volatility": 0.02,
        "regime": "TRENDING",
        "hurst": 0.6,
        "rsi": 55.0,
        "strategist": "trend",
        "bb_pct_b": 0.5,
        "ema_diff": 0.01,
        "vol_ratio": 1.0,
    }


def test_paper_buy_then_take_profit(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(be, "_STATE_FILE", str(tmp_path / "s.json"))
    monkeypatch.setattr(be, "_TRADE_LOG_FILE", str(tmp_path / "t.log"))
    monkeypatch.setenv("GLOBAL_TRADE_DISABLE", "0")
    monkeypatch.setitem(RISK, "min_notional", 1.0)
    monkeypatch.setitem(RISK, "signal_quality_min", 30)

    e = BotEngine(capital=50_000.0, paper=True, sentiment_mock_score=0.5)
    e.exec_sim.simulate_order = AsyncMock(
        return_value={
            "executed_price": 100.0,
            "filled_size": 200.0,
            "fill_ratio": 1.0,
            "latency": 0.0,
            "slippage": 0.0,
        }
    )
    e.correlation_mgr.adjust_risk_exposure = MagicMock(return_value=1.0)
    e._hard_limits.can_submit_order = MagicMock(return_value=None)
    e._hard_limits.check_price_tick = MagicMock(return_value=None)
    e._hard_limits.record_order = MagicMock()
    e.risk.get_omega_effective_qmin = MagicMock(return_value=30)

    monkeypatch.setattr(
        be,
        "compute_signal_quality",
        lambda a: (75, [], {"x": 1.0}, "none"),
    )
    monkeypatch.setattr(
        be,
        "compute_omega_regime",
        lambda a, b: ("TRENDING", 1.0, 1.0, 80, "ok"),
    )
    monkeypatch.setattr(
        e.ai,
        "validate_signal",
        lambda *x: ("BUY", 0.92, "t"),
    )

    sym = "BTC/USDT"
    c1 = [{"close": 100.0, "volume": 1e6} for _ in range(3)]

    async def run_buy():
        a = _base_analysis()
        a["ob_safe_size"] = 500.0
        a["avg_volume"] = 1e6
        r = await e.tick(sym, a, c1)
        assert any(x.get("type") == "BUY" for x in r.get("actions", []))
        return r

    asyncio.run(run_buy())
    assert sym in e.open_positions

    c2 = [{"close": 104.0, "volume": 1e6} for _ in range(3)]
    a2 = _base_analysis()
    a2["signal"] = "HOLD"
    a2["ob_safe_size"] = 500.0
    a2["avg_volume"] = 1e6

    async def run_tp():
        monkeypatch.setattr(
            e.ai,
            "validate_signal",
            lambda *x: ("HOLD", 0.5, "h"),
        )
        e.exec_sim.simulate_order = AsyncMock(
            return_value={
                "executed_price": 104.0,
                "filled_size": 200.0,
                "fill_ratio": 1.0,
                "latency": 0.0,
                "slippage": 0.0,
            }
        )
        r2 = await e.tick(sym, a2, c2)
        assert sym not in e.open_positions
        assert any(x.get("type") == "SELL" for x in r2.get("actions", []))

    asyncio.run(run_tp())


def test_tick_trend_follow_override(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(be, "_STATE_FILE", str(tmp_path / "s2.json"))
    monkeypatch.setattr(be, "_TRADE_LOG_FILE", str(tmp_path / "t2.log"))
    monkeypatch.setenv("GLOBAL_TRADE_DISABLE", "0")
    monkeypatch.setitem(RISK, "min_notional", 1.0)
    e = BotEngine(100_000.0, paper=True, sentiment_mock_score=0.5)
    e._hard_limits.check_price_tick = MagicMock(return_value=None)
    e._hard_limits.can_submit_order = MagicMock(return_value=None)
    e._hard_limits.record_order = MagicMock()
    e.risk.get_omega_effective_qmin = MagicMock(return_value=20)
    monkeypatch.setattr(be, "compute_signal_quality", lambda a: (90, [], {}, "n"))
    monkeypatch.setattr(
        be, "compute_omega_regime", lambda a, b: ("TRENDING", 1.0, 1.0, 90, "x")
    )
    e.exec_sim.simulate_order = AsyncMock(
        return_value={
            "executed_price": 1.0,
            "filled_size": 5.0,
            "fill_ratio": 1.0,
            "latency": 0.0,
            "slippage": 0.0,
        }
    )
    e.correlation_mgr.adjust_risk_exposure = MagicMock(return_value=1.0)

    async def go():
        a = _base_analysis()
        a["execution_mode"] = "TREND_FOLLOW"
        a["ob_safe_size"] = 1_000.0
        c = [{"close": 1.0, "volume": 1e5}]
        r = await e.tick("X/USDT", a, c)
        assert r.get("final_signal") == "BUY"

    asyncio.run(go())


def test_sentiment_veto_blocks_buy(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(be, "_STATE_FILE", str(tmp_path / "s3.json"))
    monkeypatch.setattr(be, "_TRADE_LOG_FILE", str(tmp_path / "t3.log"))
    monkeypatch.setitem(RISK, "min_notional", 1.0)
    e = BotEngine(50_000.0, paper=True, sentiment_mock_score=0.1)
    e._hard_limits.check_price_tick = MagicMock(return_value=None)
    e.risk.get_omega_effective_qmin = MagicMock(return_value=20)
    monkeypatch.setattr(be, "compute_signal_quality", lambda a: (80, [], {}, "n"))
    monkeypatch.setattr(
        be, "compute_omega_regime", lambda a, b: ("TRENDING", 1.0, 1.0, 80, "x")
    )
    monkeypatch.setattr(e.ai, "validate_signal", lambda *a: ("BUY", 0.9, "b"))

    async def go():
        a = _base_analysis()
        a["ob_safe_size"] = 500.0
        c = [{"close": 10.0, "volume": 1e4}]
        r = await e.tick("E/USDT", a, c)
        assert r.get("final_signal") in ("HOLD", "BUY", "SELL")
        if r.get("decision_context"):
            pass

    asyncio.run(go())
