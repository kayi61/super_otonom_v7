"""Faz 16 — social_signal modülü (Faz 18 derivative testleri ile aynı üslup)."""

from __future__ import annotations

from super_otonom.signals.social_signal import analyze_social_signal, run_social_signal_phase


def test_social_empty_blocks_quality_zero_health() -> None:
    """Boş veri → BLOCK, data_health 0, QUALITY."""
    a: dict = {}
    r = analyze_social_signal("BTC/USDT", {}, a, attach_to_analysis=True)

    assert r["trade_permission"] == "BLOCK"
    assert r["data_health"] == 0.0
    assert r["score_type"] == "QUALITY"
    assert r.get("empty_reason") == "no_social_data"


def test_social_normal_balanced_allow_alpha_in_01() -> None:
    """Dengeli sosyal veri → ALLOW, alpha 0–1."""
    a = {"signal": "HOLD"}
    d = {
        "sentiment_score": 0.52,
        "mention_momentum": 0.0,
        "engagement_rate": 0.35,
        "sentiment_trend": "flat",
    }
    r = analyze_social_signal("ETH/USDT", d, a, attach_to_analysis=False)

    assert r["trade_permission"] == "ALLOW"
    assert 0.0 <= r["alpha_score"] <= 1.0
    assert r["social"]["hype_cycle_stage"] == "NEUTRAL"


def test_social_fomo_stage_blocks() -> None:
    """FOMO aşaması → BLOCK."""
    d = {
        "sentiment_score": 0.75,
        "mention_momentum": 0.40,
        "engagement_rate": 0.65,
        "sentiment_trend": "flat",
    }
    r = analyze_social_signal("ALT/USDT", d, {}, attach_to_analysis=False)

    assert r["social"]["hype_cycle_stage"] == "FOMO"
    assert r["trade_permission"] == "BLOCK"


def test_social_peak_stage_blocks() -> None:
    """PEAK aşaması → BLOCK."""
    d = {
        "sentiment_score": 0.9,
        "mention_momentum": 0.56,
        "engagement_rate": 0.75,
        "sentiment_trend": "flat",
    }
    r = analyze_social_signal("MEME/USDT", d, {}, attach_to_analysis=False)

    assert r["social"]["hype_cycle_stage"] == "PEAK"
    assert r["trade_permission"] == "BLOCK"


def test_social_capitulation_high_contrarian_alpha() -> None:
    """CAPITULATION → yüksek alpha (contrarian)."""
    a = {"signal": "BUY"}
    d = {
        "sentiment_score": 0.10,
        "mention_count": 100,
        "engagement_rate": 0.2,
        "sentiment_trend": "down",
    }
    r = analyze_social_signal("CAP/USDT", d, a, attach_to_analysis=False)

    assert r["social"]["hype_cycle_stage"] == "CAPITULATION"
    assert r["alpha_score"] >= 0.70


def test_social_extreme_engagement_and_risk_halts() -> None:
    """Yüksek engagement + yüksek risk → HALT."""
    d = {
        "sentiment_score": 1.0,
        "mention_momentum": 1.0,
        "engagement_rate": 0.95,
        "sentiment_trend": "up",
    }
    r = analyze_social_signal("HYPE/USDT", d, {}, attach_to_analysis=False)

    assert r["trade_permission"] == "HALT"


def test_social_phase16_faz16_aliases() -> None:
    """analysis phase16 / faz16 aynı nesne."""
    a: dict = {}
    d = {"sentiment_score": 0.55, "engagement_rate": 0.4}
    analyze_social_signal("X/USDT", d, a, attach_to_analysis=True)

    assert "phase16" in a
    assert "faz16" in a
    assert a["phase16"] is a["faz16"]
    assert a["phase16"]["phase"] == "16"
    assert a["phase16"]["source"] == "social_signal"


def test_run_social_signal_phase_matches_analyze() -> None:
    """run_social_signal_phase çalışır ve analyze ile uyumlu."""
    a1: dict = {}
    a2: dict = {}
    d = {"sentiment_score": 0.6, "engagement_rate": 0.45, "mention_momentum": -0.2}
    ts = 1_778_469_549_424
    r1 = run_social_signal_phase("Q/USDT", d, a1, attach_to_analysis=True, event_ts=ts)
    r2 = analyze_social_signal("Q/USDT", d, a2, attach_to_analysis=True, event_ts=ts)

    assert r1["trade_permission"] == r2["trade_permission"]
    assert r1["alpha_score"] == r2["alpha_score"]
    assert r1["risk_score"] == r2["risk_score"]
    assert a1["phase16"] == a2["phase16"]
