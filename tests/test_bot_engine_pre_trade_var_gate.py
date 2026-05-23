"""VR-17 — Pre-trade marginal VaR gate integration tests."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from super_otonom.decision_context import DecisionContext
from super_otonom.risk.pre_trade_var_gate import PreTradeVarResult


def _be_paths(tmp_path, monkeypatch: pytest.MonkeyPatch):
    from super_otonom import bot_engine as be

    monkeypatch.setattr(be, "_STATE_FILE", str(tmp_path / "s.json"))
    monkeypatch.setattr(be, "_TRADE_LOG_FILE", str(tmp_path / "tr" / "tr.log"))
    return be


def _make_engine(be, capital: float = 10_000.0):
    """Lightweight engine with mocked side-effects for VR-17 tests."""
    eng = be.BotEngine(capital, paper=True)
    eng._state_mgr.save = lambda: None
    eng.open_positions.clear()
    return eng


def _run_handle_entry(eng, symbol: str = "BTCUSDT"):
    """Call _handle_entry directly, bypassing upstream tick() filters."""
    dctx = DecisionContext(symbol=symbol, tick_id=1)
    out: dict = {"actions": [], "final_signal": "BUY", "ai_explain": ""}
    analysis = {
        "signal": "BUY",
        "volatility": 0.01,
        "regime": "R",
        "order_book": {},
    }

    # Patch upstream gates so we reach the VaR gate
    with (
        patch.object(
            eng, "_entry_check_gates", return_value=(True, 1000)
        ),
        patch.object(
            eng, "_entry_calculate_size", return_value=(500.0, 500.0, True)
        ),
        patch.object(eng, "_entry_safety_checks", return_value=True),
        patch.object(eng, "_entry_kill_switch_check", return_value=False),
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


def test_pre_trade_gate_blocks_excessive_var(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gate REJECTS trade when marginal VaR breaches limits."""
    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)

    rejected = PreTradeVarResult(
        approved=False,
        reason="var_limit_breach_total:0.0800>0.05",
        new_var=0.08,
        marginal_var=0.03,
    )

    with patch(
        "super_otonom.bot_engine_risk_bridge._build_and_run_var_gate",
        return_value=rejected,
    ):
        dctx, _ = _run_handle_entry(eng, "BTCUSDT")

    assert dctx.entry_blocked is not None
    assert "PRE_TRADE_VAR" in dctx.entry_blocked
    assert "BTCUSDT" not in eng.open_positions


def test_pre_trade_gate_allows_safe_trade(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gate ALLOWS trade when VaR is within limits."""
    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)

    approved = PreTradeVarResult(
        approved=True,
        reason="",
        new_var=0.02,
        marginal_var=0.005,
    )

    with patch(
        "super_otonom.bot_engine_risk_bridge._build_and_run_var_gate",
        return_value=approved,
    ):
        dctx, _ = _run_handle_entry(eng, "ETHUSDT")

    # Gate should NOT block — entry_blocked should not contain PRE_TRADE_VAR
    blocked = dctx.entry_blocked or ""
    assert "PRE_TRADE_VAR" not in blocked


def test_pre_trade_gate_compute_error_passes(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Compute error → conservative pass (never block due to bugs)."""
    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)

    with patch(
        "super_otonom.bot_engine_risk_bridge._build_and_run_var_gate",
        side_effect=RuntimeError("numpy boom"),
    ):
        dctx, _ = _run_handle_entry(eng, "XRPUSDT")

    blocked = dctx.entry_blocked or ""
    assert "PRE_TRADE_VAR" not in blocked


def test_pre_trade_gate_skipped_without_risk_engine(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gate skipped when _risk_engine is None (_StubRisk fallback)."""
    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)
    eng._risk_engine = None

    with patch(
        "super_otonom.bot_engine_risk_bridge._build_and_run_var_gate",
        side_effect=RuntimeError("gate should not be called"),
    ) as mock_gate:
        _run_handle_entry(eng, "SOLUSDT")

    mock_gate.assert_not_called()
