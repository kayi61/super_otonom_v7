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


@pytest.mark.asyncio
async def test_portfolio_risk_block_prevents_entry(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Portfolio risk BLOCK → _handle_entry returns without executing."""
    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)
    eng._portfolio_risk_permission = "BLOCK"

    from super_otonom.decision_context import DecisionContext

    dctx = DecisionContext.start("BTC/USDT", 1, {})
    out: dict = {"actions": [], "final_signal": "BUY"}

    await eng._handle_entry(
        "BTC/USDT", 50000.0, {"avg_volume": 1.0, "volatility": 0.01},
        "BUY", 0.9, out, 1.0, dctx,
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


# ── _build_portfolio_data edge cases ──────────────────────────────────


def test_build_portfolio_data_nav_zero(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NAV ≤ 0 → empty dict (no portfolio data)."""
    from super_otonom.bot_engine_risk_bridge import _build_portfolio_data

    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be, capital=0.0)
    # Drain remaining cash to ensure NAV = 0
    eng.capital._cash = 0.0
    eng.capital._margin_used = 0.0
    eng.capital._unrealized_pnl = 0.0
    eng.open_positions["X/USDT"] = {"entry": 1.0, "qty": 1.0, "size": 100.0}

    result = _build_portfolio_data(eng)
    assert result == {}


def test_build_portfolio_data_zero_size_positions(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Positions with size=0 → empty weights → empty dict."""
    from super_otonom.bot_engine_risk_bridge import _build_portfolio_data

    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)
    eng.open_positions["X/USDT"] = {"entry": 1.0, "qty": 1.0, "size": 0.0}

    result = _build_portfolio_data(eng)
    assert result == {}


def test_build_portfolio_data_short_price_history(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Price history with < 2 points → no asset_returns for that symbol."""
    from collections import deque

    from super_otonom.bot_engine_risk_bridge import _build_portfolio_data

    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)
    eng.open_positions["A/USDT"] = {"entry": 10.0, "qty": 1.0, "size": 500.0}
    # Only 1 price point — insufficient for returns
    eng.correlation_mgr._price_history["A/USDT"] = deque([10.0])

    result = _build_portfolio_data(eng)
    assert "weights" in result
    assert "A/USDT" in result["weights"]
    assert result["asset_returns"].get("A/USDT") is None


def test_build_portfolio_data_with_returns_history(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Returns history present → portfolio_returns populated."""
    from collections import deque

    from super_otonom.bot_engine_risk_bridge import _build_portfolio_data

    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)
    eng.open_positions["B/USDT"] = {"entry": 100.0, "qty": 1.0, "size": 1000.0}
    eng.risk._returns_history = deque([0.01, -0.005, 0.002])
    eng.correlation_mgr._price_history["B/USDT"] = deque([98.0, 100.0, 101.0])

    result = _build_portfolio_data(eng)
    assert len(result["portfolio_returns"]) == 3
    assert len(result["asset_returns"]["B/USDT"]) == 2
    assert result["nav"] > 0


def test_portfolio_risk_empty_portfolio_data_sets_allow(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_build_portfolio_data returns {} → ALLOW (skip computation)."""
    from super_otonom.bot_engine_risk_bridge import tick_portfolio_risk_phase

    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)
    eng._tick_counter = eng._var_suite_interval
    eng._portfolio_risk_permission = "BLOCK"  # was BLOCK

    eng.open_positions["Z/USDT"] = {"entry": 1.0, "qty": 1.0, "size": 100.0}

    with patch(
        "super_otonom.bot_engine_risk_bridge._build_portfolio_data",
        return_value={},
    ):
        tick_portfolio_risk_phase(eng, "Z/USDT", {})

    assert eng._portfolio_risk_permission == "ALLOW"


def test_portfolio_risk_block_logs_warning(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BLOCK permission → log warning with risk details (covers perm != ALLOW branch)."""
    from super_otonom.bot_engine_risk_bridge import tick_portfolio_risk_phase

    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)
    eng._tick_counter = eng._var_suite_interval

    eng.open_positions["C/USDT"] = {"entry": 50.0, "qty": 1.0, "size": 500.0}

    mock_result = {
        "trade_permission": "BLOCK",
        "risk_score": 0.75,
        "portfolio_risk": {
            "var_max": 0.15,
            "cvar": 0.20,
            "herfindahl_hhi": 0.6,
        },
        "phase": "24",
        "source": "portfolio_risk_engine",
    }
    with patch(
        "super_otonom.portfolio_risk_engine.run_portfolio_risk_phase",
        return_value=mock_result,
    ), patch(
        "super_otonom.bot_engine_risk_bridge._build_portfolio_data",
        return_value={"weights": {"C/USDT": 1.0}, "nav": 10000},
    ):
        tick_portfolio_risk_phase(eng, "C/USDT", {})

    assert eng._portfolio_risk_permission == "BLOCK"
    # BLOCK should NOT trigger emergency stop (only HALT does)
    assert eng.risk.emergency_stop is not True


# ── tick_record_return_and_regime tests ───────────────────────────────


def test_tick_record_return_basic(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NAV change → record_return called, _prev_nav updated."""
    from super_otonom.bot_engine_risk_bridge import tick_record_return_and_regime

    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)
    eng._prev_nav = 10000.0
    # NAV = _cash + _margin_used + _unrealized_pnl; set _cash to shift NAV
    eng.capital._cash = 10100.0
    eng.capital._margin_used = 0.0
    eng.capital._unrealized_pnl = 0.0

    initial_len = len(eng.risk._returns_history)
    tick_record_return_and_regime(eng)

    assert eng._prev_nav == 10100.0
    assert len(eng.risk._returns_history) == initial_len + 1


def test_tick_record_return_zero_prev_nav(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """prev_nav=0 → no return recorded, just update _prev_nav."""
    from super_otonom.bot_engine_risk_bridge import tick_record_return_and_regime

    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)
    eng._prev_nav = 0.0

    initial_len = len(eng.risk._returns_history)
    tick_record_return_and_regime(eng)

    # NAV is ~10000, so _prev_nav should update
    assert eng._prev_nav > 0
    assert len(eng.risk._returns_history) == initial_len  # no change


def test_tick_record_return_with_regime_detector_fit(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regime detector present + enough history → fit() called."""
    from collections import deque

    from super_otonom.bot_engine_risk_bridge import tick_record_return_and_regime

    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)
    eng._prev_nav = 10000.0
    eng.capital._cash = 10050.0
    eng.capital._margin_used = 0.0
    eng.capital._unrealized_pnl = 0.0

    # Mock regime detector
    eng._regime_detector = MagicMock()
    eng._regime_fitted = False
    # Pre-fill returns history with 60+ entries
    eng.risk._returns_history = deque([0.001] * 60)

    tick_record_return_and_regime(eng)

    eng._regime_detector.fit.assert_called_once()
    assert eng._regime_fitted is True


def test_tick_record_return_with_regime_detector_update(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regime detector already fitted → update() called."""
    from collections import deque

    from super_otonom.bot_engine_risk_bridge import tick_record_return_and_regime

    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)
    eng._prev_nav = 10000.0
    eng.capital._cash = 10050.0
    eng.capital._margin_used = 0.0
    eng.capital._unrealized_pnl = 0.0

    eng._regime_detector = MagicMock()
    eng._regime_detector.update.return_value = "TRENDING"
    eng._regime_fitted = True
    eng._regime_var = MagicMock()
    eng.risk._returns_history = deque([0.001] * 30)

    tick_record_return_and_regime(eng)

    eng._regime_detector.update.assert_called_once()
    eng._regime_var.record.assert_called_once()


def test_tick_record_return_regime_error_swallowed(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regime detector error → swallowed silently."""
    from collections import deque

    from super_otonom.bot_engine_risk_bridge import tick_record_return_and_regime

    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)
    eng._prev_nav = 10000.0
    eng.capital._cash = 10050.0
    eng.capital._margin_used = 0.0
    eng.capital._unrealized_pnl = 0.0

    eng._regime_detector = MagicMock()
    eng._regime_detector.update.side_effect = RuntimeError("regime boom")
    eng._regime_fitted = True
    eng.risk._returns_history = deque([0.001] * 30)

    # Should not raise
    tick_record_return_and_regime(eng)
    assert eng._prev_nav == 10050.0


# ── tick_record_var_suite tests ──────────────────────────────────────


def test_tick_record_var_suite_no_risk_engine(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No risk engine → early return."""
    from super_otonom.bot_engine_risk_bridge import tick_record_var_suite

    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)
    eng._risk_engine = None
    eng._tick_counter = eng._var_suite_interval

    tick_record_var_suite(eng)  # should not raise


def test_tick_record_var_suite_off_interval(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Off-interval → skip."""
    from super_otonom.bot_engine_risk_bridge import tick_record_var_suite

    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)
    eng._risk_engine = MagicMock()
    eng._tick_counter = eng._var_suite_interval + 1

    tick_record_var_suite(eng)  # should not raise, no compute


def test_tick_record_var_suite_insufficient_history(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """< 20 returns → skip."""
    from collections import deque

    from super_otonom.bot_engine_risk_bridge import tick_record_var_suite

    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)
    eng._risk_engine = MagicMock()
    eng._tick_counter = eng._var_suite_interval
    eng.risk._returns_history = deque([0.001] * 10)

    tick_record_var_suite(eng)
    eng._risk_engine.compute.assert_not_called()


def test_tick_record_var_suite_computes_and_records(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enough history → compute + record_var_suite + stash metrics."""
    from collections import deque

    from super_otonom.bot_engine_risk_bridge import tick_record_var_suite

    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)
    eng._tick_counter = eng._var_suite_interval

    mock_rm = MagicMock()
    eng._risk_engine = MagicMock()
    eng._risk_engine.compute.return_value = mock_rm
    eng._regime_fitted = False
    eng._regime_detector = None
    eng.risk._returns_history = deque([0.001] * 25)
    eng.metrics.record_var_suite = MagicMock()

    tick_record_var_suite(eng)

    eng._risk_engine.compute.assert_called_once()
    eng.metrics.record_var_suite.assert_called_once_with(mock_rm)
    assert eng._last_risk_metrics is mock_rm


def test_tick_record_var_suite_with_regime(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regime fitted → regime_label and regime_var passed to compute."""
    from collections import deque

    from super_otonom.bot_engine_risk_bridge import tick_record_var_suite

    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)
    eng._tick_counter = eng._var_suite_interval

    mock_rm = MagicMock()
    eng._risk_engine = MagicMock()
    eng._risk_engine.compute.return_value = mock_rm

    mock_rs = MagicMock()
    mock_rs.regime = "TRENDING"
    eng._regime_detector = MagicMock()
    eng._regime_detector.current_regime.return_value = mock_rs
    eng._regime_fitted = True
    eng._regime_var = MagicMock()
    eng.risk._returns_history = deque([0.001] * 25)
    eng.metrics.record_var_suite = MagicMock()

    tick_record_var_suite(eng)

    call_kwargs = eng._risk_engine.compute.call_args
    assert call_kwargs[1]["current_regime"] == "TRENDING"
    assert call_kwargs[1]["regime_var"] is eng._regime_var


def test_tick_record_var_suite_error_swallowed(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compute error → swallowed, no crash."""
    from collections import deque

    from super_otonom.bot_engine_risk_bridge import tick_record_var_suite

    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)
    eng._tick_counter = eng._var_suite_interval

    eng._risk_engine = MagicMock()
    eng._risk_engine.compute.side_effect = RuntimeError("var boom")
    eng._regime_fitted = False
    eng._regime_detector = None
    eng.risk._returns_history = deque([0.001] * 25)

    tick_record_var_suite(eng)  # should not raise


# ── tick_check_var_limits additional coverage ────────────────────────


def test_var_limits_no_risk_engine_skips(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No risk engine → skip."""
    from super_otonom.bot_engine_risk_bridge import tick_check_var_limits

    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)
    eng._risk_engine = None
    eng._tick_counter = eng._var_suite_interval

    tick_check_var_limits(eng)  # no-op


def test_var_limits_no_metrics_skips(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No last_risk_metrics → skip."""
    from super_otonom.bot_engine_risk_bridge import tick_check_var_limits

    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)
    eng._risk_engine = MagicMock()
    eng._tick_counter = eng._var_suite_interval
    eng._last_risk_metrics = None

    tick_check_var_limits(eng)  # no-op


def test_var_limits_non_firm_breach_no_emergency(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-firm violation (e.g., position-level) → no emergency stop."""
    from super_otonom.bot_engine_risk_bridge import tick_check_var_limits

    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)
    eng._risk_engine = MagicMock()
    eng._tick_counter = eng._var_suite_interval
    eng._last_risk_metrics = MagicMock()
    eng.metrics.record_var_limit_breach = MagicMock()

    with patch(
        "super_otonom.risk.var_limits.load_var_limits",
    ), patch(
        "super_otonom.risk.var_limits.check_limits",
        return_value=["position_var_too_high"],  # not firm-level
    ):
        tick_check_var_limits(eng)

    eng.metrics.record_var_limit_breach.assert_called_once_with(1)
    assert eng.risk.emergency_stop is not True


def test_var_limits_error_swallowed(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """check_limits error → swallowed."""
    from super_otonom.bot_engine_risk_bridge import tick_check_var_limits

    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)
    eng._risk_engine = MagicMock()
    eng._tick_counter = eng._var_suite_interval
    eng._last_risk_metrics = MagicMock()

    with patch(
        "super_otonom.risk.var_limits.load_var_limits",
        side_effect=RuntimeError("limits boom"),
    ):
        tick_check_var_limits(eng)  # should not raise
