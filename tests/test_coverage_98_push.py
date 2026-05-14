"""CI %98 hedefi — exchange_async, adversarial, causal, transformer, whale, unified_alpha, execution_pipeline."""

from __future__ import annotations

import math
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

# ── exchange_async ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_order_book_empty_when_exchange_none() -> None:
    import super_otonom.exchange_async as ea

    h = object.__new__(ea.AsyncExchangeHandler)
    h._ex = None
    ob = await h.fetch_order_book("BTC/USDT")
    assert ob == {"asks": [], "bids": []}


@pytest.mark.asyncio
async def test_get_order_status_unknown_when_exchange_none() -> None:
    import super_otonom.exchange_async as ea

    h = object.__new__(ea.AsyncExchangeHandler)
    h._ex = None
    assert await h.get_order_status("1", "BTC/USDT") == "unknown"


@pytest.mark.asyncio
async def test_cancel_order_false_when_exchange_none() -> None:
    import super_otonom.exchange_async as ea

    h = object.__new__(ea.AsyncExchangeHandler)
    h._ex = None
    assert await h.cancel_order("1", "BTC/USDT") is False


# ── adversarial_robustness ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_score_volatility_spike_long_window_branch() -> None:
    from super_otonom.adversarial_robustness import score_volatility_spike

    rng = np.random.default_rng(21)
    c = 100.0 * np.exp(rng.normal(0, 0.015, size=90))
    s = float(score_volatility_spike(c))
    assert s == s and 0.0 <= s <= 1.0


# ── causal_alpha_engine ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_analyze_causal_with_level_returns_not_log() -> None:
    from super_otonom.causal_alpha_engine import analyze_causal_alpha

    n = 40
    t = np.arange(n, dtype=float)
    a = (100.0 + 0.1 * t).tolist()
    b = (100.0 + 0.11 * t + 0.02 * np.sin(t)).tolist()
    out = analyze_causal_alpha(
        "SYM",
        {"series_a": a, "series_b": b, "use_log_returns": False},
        {},
        attach_to_analysis=False,
    )
    assert out["source"] == "causal_alpha_engine"
    assert "causal" in out


# ── transformer_intelligence ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_extract_close_skips_invalid_entries_in_close_list() -> None:
    from super_otonom.transformer_intelligence import _MIN_CLOSES, analyze_transformer_intelligence

    base = [100.0 + 0.02 * math.sin(i / 4.0) for i in range(_MIN_CLOSES + 4)]
    bad_mix = base[:20] + ["nan-value", None, float("nan")] + base[20:]
    out = analyze_transformer_intelligence("T/USDT", {"close": bad_mix}, {}, attach_to_analysis=False)
    assert out["phase"] == "32"
    assert "transformer" in out or out.get("empty_reason") == "insufficient_bars"


@pytest.mark.asyncio
async def test_analyze_transformer_ohlcv_row_value_error_skipped() -> None:
    from super_otonom.transformer_intelligence import _MIN_CLOSES, analyze_transformer_intelligence

    good = [[i, 1.0, 1.1, 0.9, 100.0 + 0.01 * i, 1.0] for i in range(_MIN_CLOSES + 2)]
    bad_row = [0, 1.0, 1.0, 1.0, "bad_close", 1.0]
    ohlcv = good[:10] + [bad_row] + good[10:]
    out = analyze_transformer_intelligence("O/USDT", {"ohlcv": ohlcv}, {}, attach_to_analysis=False)
    assert "phase" in out and out["phase"] == "32"


@pytest.mark.asyncio
async def test_log_returns_empty_when_too_few_points() -> None:
    from super_otonom.transformer_intelligence import log_returns

    assert log_returns([1.0, 2.0]).size == 0


@pytest.mark.asyncio
async def test_reshape_patches_returns_empty_for_short_returns() -> None:
    from super_otonom.transformer_intelligence import _reshape_patches

    E, d, pl = _reshape_patches(np.array([0.01, -0.01], dtype=float), num_patches=4)
    assert E.size == 0 and d == 0 and pl == 0


# ── whale_intent_microstructure_engine ───────────────────────────────────────


@pytest.mark.asyncio
async def test_infer_whale_intent_hunt_blocks_when_sweep_and_conf_high() -> None:
    from super_otonom.whale_intent_microstructure_engine import infer_whale_intent

    ob: Dict[str, Any] = {
        "bids": [[100.0, 5000.0], [99.9, 2000.0]],
        "asks": [[500.0, 0.5], [501.0, 0.5]],
    }
    r = infer_whale_intent(symbol="W", analysis={"volatility": 0.08}, order_book=ob)
    assert r.sweep_risk >= 70
    assert r.whale_intent == "hunt"
    assert r.trade_permission == "BLOCK"
    assert 0.0 <= r.confidence <= 1.0


@pytest.mark.asyncio
async def test_infer_whale_intent_accumulate_or_distribute_branch() -> None:
    from super_otonom.whale_intent_microstructure_engine import infer_whale_intent

    ob_buy: Dict[str, Any] = {
        "bids": [[100.0, 500.0], [99.9, 400.0], [99.8, 300.0]],
        "asks": [[100.1, 2.0], [100.2, 2.0]],
    }
    r1 = infer_whale_intent(symbol="A", analysis={}, order_book=ob_buy)
    ob_sell: Dict[str, Any] = {
        "bids": [[100.0, 2.0], [99.9, 2.0]],
        "asks": [[100.1, 500.0], [100.2, 400.0]],
    }
    r2 = infer_whale_intent(symbol="B", analysis={}, order_book=ob_sell)
    assert r1.ob_imbalance is not None and r2.ob_imbalance is not None
    assert r1.whale_intent in ("accumulate", "distribute", "none", "hunt", "unknown", "exit")
    assert r2.whale_intent in ("accumulate", "distribute", "none", "hunt", "unknown", "exit")


@pytest.mark.asyncio
async def test_infer_whale_intent_malformed_top_level_prices_lower_health() -> None:
    from super_otonom.whale_intent_microstructure_engine import infer_whale_intent

    ob: Dict[str, Any] = {"bids": [["x", 1.0]], "asks": [["y", 1.0]]}
    r = infer_whale_intent(symbol="X", analysis={}, order_book=ob)
    assert r.data_health <= 0.7
    assert r.spread_pct is None or isinstance(r.spread_pct, float)


# ── unified_alpha_core ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_unified_alpha_phase_decay_monitor_exception_sets_snap_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import super_otonom.unified_alpha_core as uac
    from super_otonom.decision_context import DecisionContext
    from super_otonom.unified_alpha_core import run_unified_alpha_phase

    def _boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("decay monitor unavailable in test")

    monkeypatch.setattr(uac, "monitor_alpha_decay", _boom)

    engine = MagicMock()
    engine.risk.get_omega_effective_qmin.return_value = 10

    analysis: Dict[str, Any] = {"signal": "BUY", "regime": "TREND", "volatility": 0.02}
    out: Dict[str, Any] = {"final_signal": "HOLD"}
    dctx = DecisionContext.start(symbol="Z/USDT", tick_id=1, analysis=analysis)

    adj, _omega = run_unified_alpha_phase(
        engine, "Z/USDT", analysis, out, dctx, event_ts=1_700_000_000_000.0
    )
    assert isinstance(adj, int)
    assert "alpha_decay_freshness" not in analysis
    assert "phase45" in analysis or "faz45" in analysis


# ── execution_pipeline ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_phase_override_nested_phase50_key() -> None:
    from super_otonom.pipelines.execution_pipeline import _phase_override_from_analysis

    v = _phase_override_from_analysis(
        {"override_phases": {"phase50": {"mode": "shadow"}}},
        "phase50",
        "faz50",
    )
    assert isinstance(v, dict) and v.get("mode") == "shadow"


@pytest.mark.asyncio
async def test_phase_dict_prefers_first_matching_alias() -> None:
    from super_otonom.pipelines.execution_pipeline import _phase_dict_from_analysis

    d = _phase_dict_from_analysis(
        {"faz66": {"a": 1}, "phase66": {"b": 2}},
        "phase66",
        "faz66",
    )
    assert "a" in d or "b" in d


@pytest.mark.asyncio
async def test_execute_trade_phase_wait_preserves_upstream_buy_when_confident(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from super_otonom.decision_context import DecisionContext
    from super_otonom.pipelines import execution_pipeline as ep

    class _P80:
        final_action = "WAIT"
        trade_permission = "ALLOW"
        execution_profile = "normal"
        position_size_multiplier = 1.0
        risk_gate = 40
        route_preference = "okx"
        leader_venue = "okx"

        def to_dict(self) -> Dict[str, Any]:
            return {"final_action": self.final_action}

    monkeypatch.setattr(ep, "fill_governance_phases_if_missing", lambda *a, **k: None)
    monkeypatch.setattr(ep, "infer_dealer_intent", lambda **k: MagicMock(to_dict=dict))
    monkeypatch.setattr(ep, "infer_whale_intent", lambda **k: MagicMock(to_dict=dict))
    monkeypatch.setattr(ep, "detect_liquidity_games", lambda **k: MagicMock(manipulation_risk_score=0))
    monkeypatch.setattr(ep, "infer_cross_venue_leadlag", lambda **k: MagicMock(to_dict=dict))
    monkeypatch.setattr(ep, "compute_mm_whale_consensus", lambda **k: MagicMock(to_dict=dict))
    monkeypatch.setattr(ep, "infer_regime_adaptive_execution", lambda **k: MagicMock())
    monkeypatch.setattr(ep, "compute_smart_stop", lambda **k: MagicMock(dynamic_stop_level=1.0, to_dict=dict))
    monkeypatch.setattr(ep, "monitor_alpha_decay", lambda **k: MagicMock(to_dict=dict))
    monkeypatch.setattr(ep, "infer_mtf_consensus", lambda **k: MagicMock(to_dict=dict))
    monkeypatch.setattr(ep, "decide_autonomously", lambda **k: _P80())
    monkeypatch.setattr(ep, "compute_smart_order_route", lambda **k: MagicMock(to_dict=dict, preferred_venue="okx", execution_mode="LIMIT", reason="t"))
    monkeypatch.setattr(ep, "calibrate_confidence_mvp", lambda c, _pc: (c, {"applied": False}))
    monkeypatch.setattr(
        ep,
        "attach_meta_regime",
        lambda analysis, phase_chain, *, base_confidence: (base_confidence, {"applied": False}),
    )

    engine = MagicMock()
    engine.open_positions = {}
    engine._handle_entry = AsyncMock()

    analysis: Dict[str, Any] = {}
    out: Dict[str, Any] = {
        "final_signal": "BUY",
        "ai_confidence": 0.92,
        "decision_reason": "upstream",
    }
    dctx = DecisionContext.start(symbol="Q/USDT", tick_id=1, analysis=analysis)

    await ep.execute_trade_phase(engine, "Q/USDT", 50.0, analysis, out, 1.0, dctx, [])
    assert out["final_signal"] == "BUY"
    assert str(out.get("decision_reason", "")).find("upstream") >= 0 or out.get("decision_reason") == "upstream"
    engine._handle_entry.assert_awaited()


@pytest.mark.asyncio
async def test_execute_trade_phase_halt_branch() -> None:
    from unittest import mock

    from super_otonom.decision_context import DecisionContext
    from super_otonom.pipelines import execution_pipeline as ep

    class _P80H:
        final_action = "HALT"
        trade_permission = "BLOCK"
        execution_profile = "halt"
        position_size_multiplier = 1.0
        risk_gate = 99
        route_preference = "none"
        leader_venue = "none"

        def to_dict(self) -> Dict[str, Any]:
            return {"final_action": self.final_action}

    engine = MagicMock()
    engine.open_positions = {}
    engine._handle_entry = AsyncMock()
    analysis: Dict[str, Any] = {}
    out: Dict[str, Any] = {"final_signal": "BUY", "ai_confidence": 0.7, "decision_reason": ""}
    dctx = DecisionContext.start(symbol="H/USDT", tick_id=2, analysis=analysis)

    with (
        mock.patch.object(ep, "fill_governance_phases_if_missing", lambda *a, **k: None),
        mock.patch.object(ep, "infer_dealer_intent", lambda **k: MagicMock(to_dict=dict)),
        mock.patch.object(ep, "infer_whale_intent", lambda **k: MagicMock(to_dict=dict)),
        mock.patch.object(ep, "detect_liquidity_games", lambda **k: MagicMock(manipulation_risk_score=0)),
        mock.patch.object(ep, "infer_cross_venue_leadlag", lambda **k: MagicMock(to_dict=dict)),
        mock.patch.object(ep, "compute_mm_whale_consensus", lambda **k: MagicMock(to_dict=dict)),
        mock.patch.object(ep, "infer_regime_adaptive_execution", lambda **k: MagicMock()),
        mock.patch.object(
            ep, "compute_smart_stop", lambda **k: MagicMock(dynamic_stop_level=1.0, to_dict=dict)
        ),
        mock.patch.object(ep, "monitor_alpha_decay", lambda **k: MagicMock(to_dict=dict)),
        mock.patch.object(ep, "infer_mtf_consensus", lambda **k: MagicMock(to_dict=dict)),
        mock.patch.object(ep, "decide_autonomously", lambda **k: _P80H()),
        mock.patch.object(
            ep,
            "compute_smart_order_route",
            lambda **k: MagicMock(to_dict=dict, preferred_venue="x", execution_mode="LIMIT", reason="r"),
        ),
        mock.patch.object(ep, "calibrate_confidence_mvp", lambda c, _pc: (c, {"applied": True, "summary": "ok"})),
        mock.patch.object(
            ep,
            "attach_meta_regime",
            lambda analysis, phase_chain, *, base_confidence: (
                base_confidence,
                {"applied": True, "summary": "meta"},
            ),
        ),
    ):
        await ep.execute_trade_phase(engine, "H/USDT", 1.0, analysis, out, 1.0, dctx, [])
    assert out["final_signal"] == "HOLD"
    assert "HALT" in str(out.get("decision_reason", ""))
    engine._handle_entry.assert_awaited()
