"""v8 mimarisi: pipelines, state_machine, FORCE_ALL_CLOSE, explain."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from super_otonom.bot_engine import BotEngine
from super_otonom.pipelines import risk_pipeline, signal_pipeline
from super_otonom.state_machine import TradingState, compute_trading_state


def test_compute_trading_state_defensive_vol(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GLOBAL_TRADE_DISABLE", "")
    e = BotEngine(1000.0, paper=True)
    st = compute_trading_state(e, {"volatility": 0.09})
    assert st == TradingState.DEFENSIVE


def test_compute_trading_state_defensive_omega_tighten(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GLOBAL_TRADE_DISABLE", "")
    e = BotEngine(1000.0, paper=True)
    e.risk._omega_qmin_tighten = 16
    st = compute_trading_state(e, {"volatility": 0.01})
    assert st == TradingState.DEFENSIVE


def test_force_all_close_open_position(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FORCE_ALL_CLOSE", "1")
    monkeypatch.delenv("GLOBAL_TRADE_DISABLE", raising=False)
    e = BotEngine(100_000.0, paper=True)
    e.open_positions["X"] = {
        "entry": 1.0,
        "qty": 1.0,
        "size": 1.0,
        "peak": 1.0,
        "hold_bars": 0,
    }
    c = [{"close": 1.0, "volume": 1.0}]
    with (
        patch("super_otonom.bot_patch_registry.compute_signal_quality", return_value=(90, [], {}, "m")),
        patch("super_otonom.bot_patch_registry.compute_omega_regime", return_value=("TRENDING", 1.0, 1.0, 90, "om")),
        patch.object(e.ai, "validate_signal", return_value=("BUY", 0.9, "ok")),
    ):
        out = asyncio.run(
            e.tick("X", {"signal": "BUY", "volatility": 0.01, "regime": "TRENDING"}, c)
        )
    assert out["final_signal"] == "CLOSE_ALL"
    assert "FORCE_ALL_CLOSE" in (out.get("decision_reason") or "")


def test_force_all_close_no_position_hold(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FORCE_ALL_CLOSE", "true")
    monkeypatch.delenv("GLOBAL_TRADE_DISABLE", raising=False)
    e = BotEngine(1000.0, paper=True)
    c = [{"close": 1.0, "volume": 1.0}]
    with (
        patch("super_otonom.bot_patch_registry.compute_signal_quality", return_value=(90, [], {}, "m")),
        patch("super_otonom.bot_patch_registry.compute_omega_regime", return_value=("TRENDING", 1.0, 1.0, 90, "om")),
        patch.object(e.ai, "validate_signal", return_value=("BUY", 0.9, "ok")),
    ):
        out = asyncio.run(
            e.tick("Z", {"signal": "BUY", "volatility": 0.01, "regime": "TRENDING"}, c)
        )
    assert out["final_signal"] == "HOLD"
    assert "FORCE_ALL_CLOSE_NO_NEW" in (out.get("decision_reason") or "")


def test_min_entry_confidence_valueerror_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENTRY_MIN_CONFIDENCE", "not_a_float")
    assert signal_pipeline._min_entry_confidence() == 0.55


def test_risk_pipeline_force_all_close_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORCE_ALL_CLOSE", "on")
    assert risk_pipeline.force_all_close_requested() is True


def test_ai_explain_method() -> None:
    from super_otonom.ai_layer import AILayer

    a = AILayer(model_path="___nope___")
    s = a.explain(
        "S", "BUY", {"regime": "TRENDING", "hurst": 0.5, "volatility": 0.02}, "BUY", 0.7, "ok"
    )
    assert "symbol=S" in s and "BUY" in s and "lstm=off" in s
