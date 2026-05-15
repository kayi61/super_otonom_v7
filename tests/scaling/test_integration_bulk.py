"""
Entegrasyon testleri: analyzer → OMEGA → blend; gate + merge + DecisionContext.

Eskiden: 4×5×3=60 + 10×4=40 kombinatoryal test (tip kontrolü seviyesinde assert).
Şimdi: açık davranış senaryoları — her test farklı bir iş kuralını doğrular.
"""
from __future__ import annotations

import pytest
from super_otonom.ai_confidence_bridge import blend_omega_confidence
from super_otonom.decision_context import DecisionContext
from super_otonom.omega_regime import compute_omega_regime
from super_otonom.pre_trade_gate import gate_buy_signal_and_slots, merge_entry_notional

# ─── compute_omega_regime ─────────────────────────────────────────────────────


def test_omega_trending_scenario() -> None:
    """Güçlü trend: TRENDING rejim, adj_quality = round(bq * qm)."""
    analysis = {"regime": "TRENDING", "hurst": 0.65, "volatility": 0.02}
    oreg, qm, sf, adj, log = compute_omega_regime(analysis, base_quality=80)
    assert oreg == "TRENDING"
    assert adj == round(80 * qm)
    assert "[OMEGA-AI]" in log
    assert sf >= 0.2


def test_omega_crash_risk_on_flash_crash() -> None:
    """flash_crash=True, diğer koşullar ne olursa olsun CRASH_RISK."""
    analysis = {"regime": "TRENDING", "hurst": 0.70, "volatility": 0.01, "flash_crash": True}
    oreg, qm, sf, _, _ = compute_omega_regime(analysis, base_quality=90)
    assert oreg == "CRASH_RISK"
    assert sf == pytest.approx(0.35)
    assert qm == pytest.approx(0.75)


def test_omega_crash_risk_on_high_volatility() -> None:
    """Volatilite > 0.075 → flash_crash olmasa da CRASH_RISK."""
    analysis = {"regime": "TRENDING", "hurst": 0.60, "volatility": 0.09}
    oreg, _, _, _, _ = compute_omega_regime(analysis, base_quality=70)
    assert oreg == "CRASH_RISK"


def test_omega_ranging_on_mean_reverting_regime() -> None:
    """MEAN_REVERTING rejim → RANGING."""
    analysis = {"regime": "MEAN_REVERTING", "hurst": 0.38, "volatility": 0.02}
    oreg, _, _, _, _ = compute_omega_regime(analysis, base_quality=60)
    assert oreg == "RANGING"


def test_omega_adj_quality_clamped_0_to_100() -> None:
    """adj_quality her zaman [0, 100] aralığında olmalı."""
    for bq in (0, 50, 100):
        _, _, _, adj, _ = compute_omega_regime(
            {"regime": "TRENDING", "hurst": 0.65, "volatility": 0.02}, bq
        )
        assert 0 <= adj <= 100


def test_omega_low_quality_caps_size_factor() -> None:
    """base_quality 40–52 → CRASH_RISK dışında sf ≤ 0.45."""
    _, _, sf, _, _ = compute_omega_regime(
        {"regime": "TRENDING", "hurst": 0.60, "volatility": 0.02}, base_quality=45
    )
    assert sf <= 0.45


def test_omega_high_quality_trending_boosts_sf() -> None:
    """base_quality ≥ 90, TRENDING → sf ≥ 1.0."""
    _, _, sf, _, _ = compute_omega_regime(
        {"regime": "TRENDING", "hurst": 0.65, "volatility": 0.02}, base_quality=95
    )
    assert sf >= 1.0


# ─── blend_omega_confidence ───────────────────────────────────────────────────


def test_blend_no_ml_score_passes_base_through() -> None:
    conf, note = blend_omega_confidence(0.70, {})
    assert conf == pytest.approx(0.70)
    assert note == "no_external_ml"


def test_blend_with_ml_score_merges_between_base_and_ml() -> None:
    # BLEND=0.35 → merged = 0.65*0.60 + 0.35*0.80 = 0.67
    conf, note = blend_omega_confidence(0.60, {"ml_score": 0.80})
    assert 0.60 < conf < 0.80
    assert "ml_fusion" in note


def test_blend_clamps_output_to_0_1() -> None:
    conf, _ = blend_omega_confidence(1.5, {"ml_score": 1.5})
    assert 0.0 <= conf <= 1.0


# ─── gate_buy_signal_and_slots ────────────────────────────────────────────────


def test_gate_non_buy_signal_passes_through() -> None:
    """HOLD/SELL bu fonksiyonda engellenmez — çağıran BUY yolunda kullanır."""
    ok, code = gate_buy_signal_and_slots("HOLD", open_position_count=10, confidence=0.0)
    assert ok is True
    assert code == ""


def test_gate_buy_blocked_on_low_confidence() -> None:
    ok, code = gate_buy_signal_and_slots("BUY", open_position_count=0, confidence=0.10)
    assert ok is False
    assert code == "below_entry_confidence"


def test_gate_buy_blocked_on_max_positions() -> None:
    # max_open_positions varsayılanı 1 → 1 açık pozisyon yeterli
    ok, code = gate_buy_signal_and_slots("BUY", open_position_count=1, confidence=0.90)
    assert ok is False
    assert code == "max_open_positions"


def test_gate_buy_passes_when_all_conditions_met() -> None:
    ok, code = gate_buy_signal_and_slots("BUY", open_position_count=0, confidence=0.90)
    assert ok is True
    assert code == ""


# ─── merge_entry_notional ─────────────────────────────────────────────────────


def test_merge_ob_none_uses_technical_only() -> None:
    notional, source, blocked = merge_entry_notional(150.0, None)
    assert notional == pytest.approx(150.0)
    assert source == "technical_only"
    assert blocked == ""


def test_merge_ob_zero_blocks_entry() -> None:
    notional, source, blocked = merge_entry_notional(150.0, 0.0)
    assert notional == pytest.approx(0.0)
    assert blocked == "ob_safe_size_zero"


def test_merge_ob_smaller_than_tech_limits_notional() -> None:
    notional, source, _ = merge_entry_notional(200.0, 80.0)
    assert notional == pytest.approx(80.0)
    assert source == "min_technical_ob_safe"


def test_merge_ob_larger_than_tech_uses_tech() -> None:
    notional, source, _ = merge_entry_notional(50.0, 200.0)
    assert notional == pytest.approx(50.0)
    assert source == "min_technical_ob_safe"


def test_merge_ob_invalid_type_falls_back_to_technical() -> None:
    notional, source, _ = merge_entry_notional(100.0, "bad_value")
    assert notional == pytest.approx(100.0)
    assert source == "technical_only_invalid_ob"


# ─── DecisionContext ──────────────────────────────────────────────────────────


def test_decision_context_serialization_preserves_fields() -> None:
    analysis = {"signal": "BUY", "regime": "TRENDING"}
    dc = DecisionContext.start("BTC/USDT", tick_id=1, analysis=analysis)
    d = dc.to_dict()
    assert d["symbol"] == "BTC/USDT"
    assert d["analysis_signal"] == "BUY"
