"""PROMPT-10.1 — Insider Intelligence Fusion Controller + entegrasyon."""

from __future__ import annotations

from super_otonom.mm_whale_consensus_controller import as_insider_signal
from super_otonom.signals.insider_fusion_controller import (
    BUY,
    HALT,
    STRONG_BUY,
    STRONG_SELL,
    WAIT,
    analyze_insider_fusion,
    run_insider_fusion_phase,
)
from super_otonom.signals.signal_fusion_engine import _apply_fusion_to_out

# ── Birleşik fusion ──────────────────────────────────────────────────────────


def test_bullish_confluence_boosts_conviction() -> None:
    sig = {
        "whale_signal": {"alpha_bias": 0.6},
        "onchain_signal": {"alpha_bias": 0.5},
        "defi_signal": {"defi_alpha_bias": 0.5},
    }
    res = analyze_insider_fusion(sig)
    assert res is not None
    assert res.confluence_count == 3
    assert res.direction > 0
    assert res.decision in (BUY, STRONG_BUY)
    assert res.insider_conviction > 0
    assert res.position_size_suggestion > 0


def test_exploit_alert_overrides_halt() -> None:
    sig = {"whale_signal": {"alpha_bias": 0.9}, "exploit_alert": True}
    res = analyze_insider_fusion(sig)
    assert res.decision == HALT
    assert res.trade_permission == "HALT"
    assert res.override_reason == "exploit_alert"
    assert res.position_size_suggestion == 0.0


def test_macro_riskoff_whale_sell_strong_sell() -> None:
    sig = {"macro_signal": {"environment": "RISK_OFF"}, "whale_signal": {"alpha_bias": -0.6}}
    res = analyze_insider_fusion(sig)
    assert res.decision == STRONG_SELL
    assert "macro_risk_off" in res.override_reason
    assert res.direction < 0


def test_whale_stablecoin_etf_strong_buy() -> None:
    sig = {
        "whale_signal": {"alpha_bias": 0.5},
        "macro_signal": {"stablecoin_mint": True},
        "etf_signal": {"net_flow_usd": 5e8},
    }
    res = analyze_insider_fusion(sig)
    assert res.decision == STRONG_BUY
    assert res.insider_conviction >= 80


def test_conflict_whale_bullish_funding_extreme_wait() -> None:
    sig = {"whale_signal": {"alpha_bias": 0.6}, "derivatives_signal": {"funding_rate": 0.002}}
    res = analyze_insider_fusion(sig)
    assert res.conflict is True
    assert res.decision == WAIT
    assert any("funding" in r for r in res.reasons)


def test_position_sizing_formula() -> None:
    sig = {
        "whale_signal": {"alpha_bias": 0.8, "conviction": 90},
        "onchain_signal": {"alpha_bias": 0.7},
        "etf_signal": {"net_flow_usd": 3e8},
    }
    full = analyze_insider_fusion(sig, kelly_fraction=0.5, risk_budget=1.0)
    half = analyze_insider_fusion(sig, kelly_fraction=0.5, risk_budget=0.5)
    assert full.position_size_suggestion > half.position_size_suggestion
    assert half.position_size_suggestion <= full.position_size_suggestion


def test_empty_none() -> None:
    assert analyze_insider_fusion({}) is None
    assert analyze_insider_fusion("nope") is None


def test_signal_direction_from_action_and_env() -> None:
    # action etiketi
    r1 = analyze_insider_fusion({"token_signal": {"action": "STRONG_SELL"}})
    assert r1.direction < 0
    # macro environment
    r2 = analyze_insider_fusion({"macro_signal": {"environment": "BULLISH"}})
    assert r2.direction > 0


# ── run_insider_fusion_phase (BotEngine girişi) ──────────────────────────────


def test_run_phase_writes_analysis_and_alias() -> None:
    analysis: dict = {}
    sig = {"whale_signal": {"alpha_bias": 0.6}, "onchain_signal": {"alpha_bias": 0.5}}
    payload = run_insider_fusion_phase(analysis, sig)
    assert payload is not None
    assert analysis["insider_conviction"] == payload["insider_conviction"]
    assert "insider_fusion" in analysis
    assert analysis["phase76"]["source"] == "insider_fusion_controller"
    assert analysis["phase76"] is analysis["faz76"]


def test_run_phase_collects_from_analysis() -> None:
    analysis = {"whale_signal": {"alpha_bias": -0.6}, "macro_signal": {"environment": "RISK_OFF"}}
    payload = run_insider_fusion_phase(analysis)
    assert payload is not None
    assert payload["decision"] == STRONG_SELL


def test_run_phase_no_signal_none() -> None:
    analysis: dict = {"unrelated": 1}
    assert run_insider_fusion_phase(analysis) is None
    assert "insider_conviction" not in analysis


# ── signal_fusion_engine (Faz 36) entegrasyonu ───────────────────────────────


def test_signal_fusion_insider_halt_override() -> None:
    analysis = {"signal": "BUY", "insider_fusion": {"decision": HALT, "insider_conviction": 100}}
    out = {"final_signal": "BUY", "ai_confidence": 0.8}
    _apply_fusion_to_out(analysis, out)
    assert out["final_signal"] == "HOLD"
    assert out["decision_reason"] == "INSIDER_EXPLOIT_HALT"
    assert out["insider_conviction"] == 100


def test_signal_fusion_no_insider_unchanged() -> None:
    """insider_fusion yoksa eski davranış korunur (BUY → BUY)."""
    analysis = {"signal": "BUY", "sentiment_score": 0.3, "high_tf_trend": "UP", "ml_score": 0.7}
    out = {"final_signal": "BUY", "ai_confidence": 0.7}
    _apply_fusion_to_out(analysis, out)
    assert out["final_signal"] == "BUY"  # confluence/veto tetiklenmedi


# ── mm_whale_consensus_controller (Faz 75) adapter ───────────────────────────


def test_as_insider_signal_adapter() -> None:
    result = {"action": "TRADE", "conviction": 72, "alpha_score": 70, "risk_score": 30,
              "trade_permission": "ALLOW"}
    sig = as_insider_signal(result)
    assert sig["conviction"] == 72
    assert sig["alpha_bias"] > 0  # alpha(70) > risk(30) → bullish
    assert sig["source"] == "mm_whale_consensus"
    # insider fusion bunu whale_signal olarak tüketebilir
    res = analyze_insider_fusion({"whale_signal": sig, "onchain_signal": {"alpha_bias": 0.4}})
    assert res is not None and res.direction > 0
