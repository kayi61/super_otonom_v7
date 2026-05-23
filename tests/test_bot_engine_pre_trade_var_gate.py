"""VR-17 integration: pre_trade_var_check wired into BotEngine._handle_entry."""

from __future__ import annotations

import asyncio
from collections import deque
from unittest.mock import MagicMock, patch

import pytest


def _make_engine(capital: float = 10_000.0):
    """Lightweight BotEngine for testing (paper mode, stub exchange)."""
    from super_otonom.bot_engine import BotEngine

    with patch("super_otonom.bot_engine.MetricsExporter"):
        eng = BotEngine(capital=capital, paper=True, exec_seed=42)
    eng.metrics = MagicMock()
    eng._state_mgr.save = lambda: None
    eng.open_positions.clear()
    return eng


def _candles(price: float = 100.0, n: int = 1):
    import time

    ts = time.time() * 1000
    return [{"close": price, "open": price, "high": price, "low": price,
             "volume": 1000.0, "timestamp": ts + i * 60_000} for i in range(n)]


def _seed_price_history(engine, symbol: str, prices: list[float]):
    """Populate correlation_mgr price history for a symbol."""
    engine.correlation_mgr._price_history[symbol] = deque(prices, maxlen=200)


def _mock_result(approved=True, reason="", **kw):
    from super_otonom.risk.pre_trade_var_gate import PreTradeVarResult

    defaults = dict(
        approved=approved, reason=reason,
        current_var=0.01, new_var=0.02, marginal_var=0.01,
        latency_ms=1.0, symbol="BTCUSDT", trade_weight=0.05,
    )
    defaults.update(kw)
    return PreTradeVarResult(**defaults)


# ── Test: gate is called and approves a normal trade ──────────────────────


def test_var_gate_pass_allows_entry():
    """When pre_trade_var_check approves, the BUY should proceed."""
    eng = _make_engine(10_000.0)
    _seed_price_history(eng, "BTCUSDT", [100.0 + i * 0.01 for i in range(50)])

    with patch(
        "super_otonom.bot_engine_risk_bridge._build_and_check",
        return_value=_mock_result(approved=True),
    ):
        out = {"actions": [], "final_signal": "BUY", "dynamic_stop": None}
        asyncio.run(
            eng._handle_entry(
                "BTCUSDT", 100.0, {"volatility": 0.01, "avg_volume": 1000.0},
                "BUY", 0.9, out, 1.0, None, _candles(100.0),
            )
        )

    buys = [a for a in out["actions"] if a.get("type") == "BUY"]
    assert len(buys) >= 1, "BUY should proceed when VaR gate passes"


# ── Test: gate rejects and blocks entry ───────────────────────────────────


def test_var_gate_reject_blocks_entry():
    """When pre_trade_var_check rejects, _handle_entry must return without BUY."""
    eng = _make_engine(10_000.0)
    _seed_price_history(eng, "BTCUSDT", [100.0 + i * 0.01 for i in range(50)])

    with patch(
        "super_otonom.bot_engine_risk_bridge._build_and_check",
        return_value=_mock_result(
            approved=False, reason="var_limit_breach_total:0.0600>0.05",
            current_var=0.04, new_var=0.06, marginal_var=0.02,
        ),
    ):
        out = {"actions": [], "final_signal": "BUY", "dynamic_stop": None}
        asyncio.run(
            eng._handle_entry(
                "BTCUSDT", 100.0, {"volatility": 0.01, "avg_volume": 1000.0},
                "BUY", 0.9, out, 1.0, None, _candles(100.0),
            )
        )

    buys = [a for a in out["actions"] if a.get("type") == "BUY"]
    assert len(buys) == 0, "BUY must be blocked when VaR gate rejects"


# ── Test: gate sets dctx.entry_blocked on rejection ───────────────────────


def test_var_gate_reject_sets_dctx():
    """Rejection should mark dctx.entry_blocked with VaR reason."""
    eng = _make_engine(10_000.0)
    _seed_price_history(eng, "BTCUSDT", [100.0 + i * 0.01 for i in range(50)])

    from super_otonom.decision_context import DecisionContext

    dctx = DecisionContext.start("BTCUSDT", 1, {})

    with patch(
        "super_otonom.bot_engine_risk_bridge._build_and_check",
        return_value=_mock_result(
            approved=False, reason="var_limit_breach_marginal:0.0300>0.02",
            current_var=0.03, new_var=0.04, marginal_var=0.03,
        ),
    ):
        out = {"actions": [], "final_signal": "BUY", "dynamic_stop": None}
        asyncio.run(
            eng._handle_entry(
                "BTCUSDT", 100.0, {"volatility": 0.01, "avg_volume": 1000.0},
                "BUY", 0.9, out, 1.0, dctx, _candles(100.0),
            )
        )

    assert dctx.entry_blocked is not None
    assert "PRE_TRADE_VAR" in dctx.entry_blocked


# ── Test: gate records Prometheus metrics ─────────────────────────────────


def test_var_gate_records_prometheus_on_pass():
    """Prometheus record_pre_trade_var_gate called on pass."""
    eng = _make_engine(10_000.0)
    _seed_price_history(eng, "BTCUSDT", [100.0 + i * 0.01 for i in range(50)])

    with patch(
        "super_otonom.bot_engine_risk_bridge._build_and_check",
        return_value=_mock_result(approved=True, new_var=0.015, marginal_var=0.005),
    ):
        out = {"actions": [], "final_signal": "BUY", "dynamic_stop": None}
        asyncio.run(
            eng._handle_entry(
                "BTCUSDT", 100.0, {"volatility": 0.01, "avg_volume": 1000.0},
                "BUY", 0.9, out, 1.0, None, _candles(100.0),
            )
        )

    eng.metrics.record_pre_trade_var_gate.assert_called()
    call_kw = eng.metrics.record_pre_trade_var_gate.call_args
    assert call_kw[1]["approved"] is True


def test_var_gate_records_prometheus_on_reject():
    """Prometheus record_pre_trade_var_gate called with approved=False on reject."""
    eng = _make_engine(10_000.0)
    _seed_price_history(eng, "BTCUSDT", [100.0 + i * 0.01 for i in range(50)])

    with patch(
        "super_otonom.bot_engine_risk_bridge._build_and_check",
        return_value=_mock_result(
            approved=False, reason="var_limit_breach_total:0.0600>0.05",
            new_var=0.06, marginal_var=0.02,
        ),
    ):
        out = {"actions": [], "final_signal": "BUY", "dynamic_stop": None}
        asyncio.run(
            eng._handle_entry(
                "BTCUSDT", 100.0, {"volatility": 0.01, "avg_volume": 1000.0},
                "BUY", 0.9, out, 1.0, None, _candles(100.0),
            )
        )

    eng.metrics.record_pre_trade_var_gate.assert_called()
    call_kw = eng.metrics.record_pre_trade_var_gate.call_args
    assert call_kw[1]["approved"] is False


# ── Test: stub risk skips gate ────────────────────────────────────────────


def test_stub_risk_skips_var_gate():
    """When _risk_engine=None, gate is skipped entirely."""
    eng = _make_engine(10_000.0)
    eng._risk_engine = None

    with patch(
        "super_otonom.bot_engine_risk_bridge._build_and_check",
        side_effect=AssertionError("should not be called"),
    ) as mock_check:
        out = {"actions": [], "final_signal": "BUY", "dynamic_stop": None}
        asyncio.run(
            eng._handle_entry(
                "BTCUSDT", 100.0, {"volatility": 0.01, "avg_volume": 1000.0},
                "BUY", 0.9, out, 1.0, None, _candles(100.0),
            )
        )

    mock_check.assert_not_called()


# ── Test: insufficient data → conservative pass (trade proceeds) ──────────


def test_insufficient_data_conservative_pass():
    """insufficient_data_pass reason should NOT block the trade."""
    eng = _make_engine(10_000.0)

    with patch(
        "super_otonom.bot_engine_risk_bridge._build_and_check",
        return_value=_mock_result(approved=True, reason="insufficient_data_pass"),
    ):
        out = {"actions": [], "final_signal": "BUY", "dynamic_stop": None}
        asyncio.run(
            eng._handle_entry(
                "NEWCOIN", 100.0, {"volatility": 0.01, "avg_volume": 1000.0},
                "BUY", 0.9, out, 1.0, None, _candles(100.0),
            )
        )

    buys = [a for a in out["actions"] if a.get("type") == "BUY"]
    assert len(buys) >= 1, "Insufficient data should allow trade (conservative pass)"


# ── Test: compute error → conservative pass ───────────────────────────────


def test_compute_error_conservative_pass():
    """If _build_and_check raises, trade should proceed (conservative pass)."""
    eng = _make_engine(10_000.0)
    _seed_price_history(eng, "BTCUSDT", [100.0 + i * 0.01 for i in range(50)])

    with patch(
        "super_otonom.bot_engine_risk_bridge._build_and_check",
        side_effect=RuntimeError("numpy exploded"),
    ):
        out = {"actions": [], "final_signal": "BUY", "dynamic_stop": None}
        asyncio.run(
            eng._handle_entry(
                "BTCUSDT", 100.0, {"volatility": 0.01, "avg_volume": 1000.0},
                "BUY", 0.9, out, 1.0, None, _candles(100.0),
            )
        )

    buys = [a for a in out["actions"] if a.get("type") == "BUY"]
    assert len(buys) >= 1, "Compute error should fallback to conservative pass"


# ── Test: bridge builds correct weights from open_positions ───────────────


def test_bridge_builds_weights_from_positions():
    """_build_and_check should derive weights from engine.open_positions."""
    eng = _make_engine(10_000.0)
    eng.open_positions["ETHUSDT"] = {"entry": 3000.0, "qty": 1.0, "size": 3000.0}
    _seed_price_history(eng, "ETHUSDT", [3000.0 + i * 0.5 for i in range(50)])
    _seed_price_history(eng, "BTCUSDT", [100.0 + i * 0.01 for i in range(50)])

    from super_otonom.bot_engine_risk_bridge import _build_and_check

    result = _build_and_check(eng, "BTCUSDT", 500.0)
    assert result.symbol == "BTCUSDT"
    assert result.trade_weight == pytest.approx(500.0 / eng.capital.nav, rel=0.01)


# ── Test: SELL signal does not trigger gate ────────────────────────────────


def test_sell_signal_skips_gate():
    """_handle_entry returns immediately for non-BUY signals."""
    eng = _make_engine(10_000.0)

    with patch(
        "super_otonom.bot_engine_risk_bridge._build_and_check",
        side_effect=AssertionError("should not be called"),
    ) as mock_check:
        out = {"actions": [], "final_signal": "SELL", "dynamic_stop": None}
        asyncio.run(
            eng._handle_entry(
                "BTCUSDT", 100.0, {"volatility": 0.01, "avg_volume": 1000.0},
                "SELL", 0.9, out, 1.0, None, _candles(100.0),
            )
        )

    mock_check.assert_not_called()
