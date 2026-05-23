"""VR-18 — VaR-aware position sizing (size_with_var_cap) integration tests."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from super_otonom.decision_context import DecisionContext


def _be_paths(tmp_path, monkeypatch: pytest.MonkeyPatch):
    from super_otonom import bot_engine as be

    monkeypatch.setattr(be, "_STATE_FILE", str(tmp_path / "s.json"))
    monkeypatch.setattr(be, "_TRADE_LOG_FILE", str(tmp_path / "tr" / "tr.log"))
    return be


def _make_engine(be, capital: float = 10_000.0):
    """Lightweight engine with mocked side-effects for VR-18 tests."""
    eng = be.BotEngine(capital, paper=True)
    eng._state_mgr.save = lambda: None
    eng.open_positions.clear()
    return eng


def _run_handle_entry(eng, symbol: str = "BTCUSDT", var_cap_return=500.0):
    """Call _handle_entry directly with var cap mock."""
    dctx = DecisionContext(symbol=symbol, tick_id=1)
    out: dict = {"actions": [], "final_signal": "BUY", "ai_explain": ""}
    analysis = {
        "signal": "BUY",
        "volatility": 0.01,
        "regime": "R",
        "order_book": {},
    }

    with (
        patch.object(
            eng, "_entry_check_gates", return_value=(True, 1000)
        ),
        patch.object(
            eng, "_entry_calculate_size", return_value=(500.0, 500.0, True)
        ),
        patch.object(eng, "_entry_safety_checks", return_value=True),
        patch.object(eng, "_entry_kill_switch_check", return_value=False),
        patch(
            "super_otonom.bot_engine_risk_bridge.run_var_cap_sizing",
            return_value=var_cap_return,
        ),
    ):
        asyncio.run(
            eng._handle_entry(
                symbol=symbol,
                price=100.0,
                analysis=analysis,
                signal="BUY",
                confidence=0.85,
                out=out,
                dctx=dctx,
            )
        )

    return dctx, out


# ── Tests ───────────────────────────────────────────────────────────────


def test_var_cap_reduces_oversized_position(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VR-18: VaR cap reduces Kelly size when marginal VaR exceeds threshold."""
    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)

    # run_var_cap_sizing returns 200 (reduced from 500)
    dctx, _ = _run_handle_entry(eng, "BTCUSDT", var_cap_return=200.0)

    # Should NOT be blocked — just reduced
    blocked = dctx.entry_blocked or ""
    assert "VAR_CAP_ZERO_SIZE" not in blocked


def test_var_cap_passes_safe_size(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VR-18: VaR cap passes through when Kelly size is within limits."""
    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)

    # run_var_cap_sizing returns full 500 (no reduction)
    dctx, _ = _run_handle_entry(eng, "ETHUSDT", var_cap_return=500.0)

    blocked = dctx.entry_blocked or ""
    assert "VAR_CAP" not in blocked


def test_var_cap_zero_blocks_entry(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VR-18: VaR cap returning 0 blocks entry entirely."""
    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)

    dctx, _ = _run_handle_entry(eng, "BTCUSDT", var_cap_return=0.0)

    assert dctx.entry_blocked is not None
    assert "VAR_CAP_ZERO_SIZE" in dctx.entry_blocked
    assert "BTCUSDT" not in eng.open_positions


def test_var_cap_skipped_without_risk_engine(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VR-18: Gate skipped when _risk_engine is None (_StubRisk fallback)."""
    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)
    eng._risk_engine = None

    dctx = DecisionContext(symbol="SOLUSDT", tick_id=1)
    out: dict = {"actions": [], "final_signal": "BUY", "ai_explain": ""}
    analysis = {
        "signal": "BUY",
        "volatility": 0.01,
        "regime": "R",
        "order_book": {},
    }

    with (
        patch.object(
            eng, "_entry_check_gates", return_value=(True, 1000)
        ),
        patch.object(
            eng, "_entry_calculate_size", return_value=(500.0, 500.0, True)
        ),
        patch.object(eng, "_entry_safety_checks", return_value=True),
        patch.object(eng, "_entry_kill_switch_check", return_value=False),
        patch(
            "super_otonom.bot_engine_risk_bridge.run_var_cap_sizing",
            side_effect=RuntimeError("gate should not be called"),
        ) as mock_cap,
    ):
        asyncio.run(
            eng._handle_entry(
                symbol="SOLUSDT",
                price=100.0,
                analysis=analysis,
                signal="BUY",
                confidence=0.85,
                out=out,
                dctx=dctx,
            )
        )

    mock_cap.assert_not_called()


# ── Unit tests for run_var_cap_sizing bridge function ──────────────────


def test_bridge_run_var_cap_sizing_applies_cap() -> None:
    """Bridge function correctly calls size_with_var_cap and returns result."""
    from super_otonom.bot_engine_risk_bridge import run_var_cap_sizing

    dctx = DecisionContext(symbol="BTCUSDT", tick_id=1)

    # Mock the internal _build_and_run_var_cap to return a capped result
    with patch(
        "super_otonom.bot_engine_risk_bridge._build_and_run_var_cap",
        return_value={
            "capped_size": 300.0,
            "marginal_var": 0.003,
            "cap_abs": 50.0,
        },
    ):
        result = run_var_cap_sizing(None, "BTCUSDT", 500.0, dctx)

    assert result == 300.0
    assert dctx.var_cap_original_size == 500.0
    assert dctx.var_cap_final_size == 300.0
    assert dctx.var_cap_binding is True
    assert dctx.var_cap_marginal_var == 0.003


def test_bridge_run_var_cap_sizing_passthrough() -> None:
    """Bridge returns original size when no cap binding."""
    from super_otonom.bot_engine_risk_bridge import run_var_cap_sizing

    dctx = DecisionContext(symbol="ETHUSDT", tick_id=1)

    with patch(
        "super_otonom.bot_engine_risk_bridge._build_and_run_var_cap",
        return_value={
            "capped_size": 500.0,
            "marginal_var": 0.001,
            "cap_abs": 50.0,
        },
    ):
        result = run_var_cap_sizing(None, "ETHUSDT", 500.0, dctx)

    assert result == 500.0
    assert dctx.var_cap_binding is False


def test_bridge_run_var_cap_compute_error_passes() -> None:
    """Compute error → conservative pass (return original size)."""
    from super_otonom.bot_engine_risk_bridge import run_var_cap_sizing

    dctx = DecisionContext(symbol="XRPUSDT", tick_id=1)

    with patch(
        "super_otonom.bot_engine_risk_bridge._build_and_run_var_cap",
        side_effect=RuntimeError("numpy boom"),
    ):
        result = run_var_cap_sizing(None, "XRPUSDT", 500.0, dctx)

    assert result == 500.0  # Conservative pass — no change
