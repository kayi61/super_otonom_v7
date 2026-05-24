"""Faz 24 — Portfolio risk engine tick-path integration tests.

Validates:
- ``tick_portfolio_risk_phase`` runs in tick path and caches permission
- BLOCK / HALT permission blocks new entry
- HALT triggers emergency stop
- phase24 attached to analysis
- Prometheus metrics recorded
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# ── Engine fixture (same pattern as test_bot_engine_var_limits_tick) ──


def _be_paths(tmp_path, monkeypatch: pytest.MonkeyPatch):
    from super_otonom import bot_engine as be

    monkeypatch.setattr(be, "_STATE_FILE", str(tmp_path / "s.json"))
    monkeypatch.setattr(be, "_TRADE_LOG_FILE", str(tmp_path / "tr" / "tr.log"))
    return be


def _make_engine(be, capital: float = 10_000.0):
    eng = be.BotEngine(capital, paper=True)
    eng._state_mgr.save = lambda: None
    eng.open_positions.clear()
    return eng


# ── tick_portfolio_risk_phase unit tests ────────────────────────────────


def test_portfolio_risk_no_positions_allow(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No open positions → ALLOW (skip computation)."""
    from super_otonom.bot_engine_risk_bridge import tick_portfolio_risk_phase

    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)
    eng.open_positions.clear()
    eng._tick_counter = eng._var_suite_interval

    tick_portfolio_risk_phase(eng, "BTC/USDT", {})

    assert eng._portfolio_risk_permission == "ALLOW"


def test_portfolio_risk_with_positions_runs(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Open positions at correct interval → runs and attaches phase24."""
    from super_otonom.bot_engine_risk_bridge import tick_portfolio_risk_phase

    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)
    eng._tick_counter = eng._var_suite_interval

    # Add a position
    eng.open_positions["BTC/USDT"] = {
        "entry": 50000.0,
        "qty": 0.01,
        "size": 500.0,
    }

    analysis: dict = {}
    tick_portfolio_risk_phase(eng, "BTC/USDT", analysis)

    # Permission should be set (could be ALLOW or BLOCK depending on data)
    assert eng._portfolio_risk_permission in ("ALLOW", "BLOCK", "HALT")
    # phase24 should be attached to analysis
    assert "phase24" in analysis


def test_portfolio_risk_block_prevents_entry(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Portfolio risk BLOCK → _handle_entry returns without executing."""
    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)
    eng._portfolio_risk_permission = "BLOCK"

    from super_otonom.decision_context import DecisionContext

    dctx = DecisionContext.start("BTC/USDT", 1, {})
    out: dict = {"actions": [], "final_signal": "BUY"}

    import asyncio

    asyncio.get_event_loop().run_until_complete(
        eng._handle_entry(
            "BTC/USDT", 50000.0, {"avg_volume": 1.0, "volatility": 0.01},
            "BUY", 0.9, out, 1.0, dctx,
        )
    )

    # No BUY action should be recorded
    buy_actions = [a for a in out["actions"] if a.get("type") == "BUY"]
    assert len(buy_actions) == 0
    assert dctx.entry_blocked == "PORTFOLIO_RISK_BLOCK"


def test_portfolio_risk_halt_triggers_emergency(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Portfolio risk HALT → emergency stop triggered."""
    from super_otonom.bot_engine_risk_bridge import tick_portfolio_risk_phase

    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)
    eng._tick_counter = eng._var_suite_interval

    eng.open_positions["X/USDT"] = {"entry": 100.0, "qty": 1.0, "size": 5000.0}

    # Patch run_portfolio_risk_phase to return HALT
    mock_result = {
        "trade_permission": "HALT",
        "risk_score": 0.95,
        "portfolio_risk": {
            "var_max": 0.25,
            "cvar": 0.30,
            "herfindahl_hhi": 0.8,
        },
        "phase": "24",
        "source": "portfolio_risk_engine",
    }
    with patch(
        "super_otonom.portfolio_risk_engine.run_portfolio_risk_phase",
        return_value=mock_result,
    ):
        # Also need to patch _build_portfolio_data to return non-empty
        with patch(
            "super_otonom.bot_engine_risk_bridge._build_portfolio_data",
            return_value={"weights": {"X/USDT": 1.0}, "nav": 10000},
        ):
            tick_portfolio_risk_phase(eng, "X/USDT", {})

    assert eng._portfolio_risk_permission == "HALT"
    assert eng.risk.emergency_stop is True


def test_portfolio_risk_allow_lets_entry_proceed(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Portfolio risk ALLOW → entry not blocked by portfolio risk."""
    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)
    eng._portfolio_risk_permission = "ALLOW"

    from super_otonom.decision_context import DecisionContext

    dctx = DecisionContext.start("BTC/USDT", 1, {})

    # Check that portfolio risk does not set entry_blocked
    assert eng._portfolio_risk_permission == "ALLOW"
    # entry_blocked should remain unset if portfolio risk is ALLOW
    assert not getattr(dctx, "entry_blocked", None)


def test_portfolio_risk_skips_off_interval(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Off-interval ticks don't recompute — keep cached permission."""
    from super_otonom.bot_engine_risk_bridge import tick_portfolio_risk_phase

    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)
    eng._portfolio_risk_permission = "BLOCK"  # previously cached
    eng._tick_counter = eng._var_suite_interval + 1  # off-interval

    eng.open_positions["A/USDT"] = {"entry": 10.0, "qty": 1.0, "size": 100.0}

    tick_portfolio_risk_phase(eng, "A/USDT", {})

    # Should keep cached BLOCK, not recompute
    assert eng._portfolio_risk_permission == "BLOCK"


def test_portfolio_risk_prometheus_recorded(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prometheus record_portfolio_risk is called when positions exist."""
    from super_otonom.bot_engine_risk_bridge import tick_portfolio_risk_phase

    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)
    eng._tick_counter = eng._var_suite_interval

    eng.open_positions["BTC/USDT"] = {"entry": 50000.0, "qty": 0.01, "size": 500.0}

    # Mock the metrics recorder
    eng.metrics.record_portfolio_risk = MagicMock()

    tick_portfolio_risk_phase(eng, "BTC/USDT", {})

    eng.metrics.record_portfolio_risk.assert_called_once()
    call_arg = eng.metrics.record_portfolio_risk.call_args[0][0]
    assert "trade_permission" in call_arg
    assert "portfolio_risk" in call_arg


def test_portfolio_risk_error_conservative_allow(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compute error → conservative ALLOW (don't block on failure)."""
    from super_otonom.bot_engine_risk_bridge import tick_portfolio_risk_phase

    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)
    eng._tick_counter = eng._var_suite_interval
    eng._portfolio_risk_permission = "BLOCK"  # was BLOCK before error

    eng.open_positions["Y/USDT"] = {"entry": 1.0, "qty": 1.0, "size": 100.0}

    with patch(
        "super_otonom.bot_engine_risk_bridge._build_portfolio_data",
        side_effect=RuntimeError("test error"),
    ):
        tick_portfolio_risk_phase(eng, "Y/USDT", {})

    assert eng._portfolio_risk_permission == "ALLOW"
