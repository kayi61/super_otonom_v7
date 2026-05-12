"""Faz 18 — derivatives_intel modülü (Faz 21/25 tarzı ince testler)."""

from __future__ import annotations

from super_otonom.derivatives_intel import analyze_derivatives_intel, run_derivatives_phase


def test_derivatives_empty_dict_blocks_quality_health_zero() -> None:
    """Boş veri → BLOCK, data_health 0, QUALITY."""
    a: dict = {}
    r = analyze_derivatives_intel("BTC/USDT", {}, a, attach_to_analysis=True)

    assert r["trade_permission"] == "BLOCK"
    assert r["data_health"] == 0.0
    assert r["score_type"] == "QUALITY"
    assert r.get("empty_reason") == "no_derivatives_data"


def test_derivatives_normal_allow_alpha_in_01() -> None:
    """Normal türev verisi → ALLOW, alpha_score 0–1."""
    a = {"signal": "BUY", "event_ts": 1_700_000_000_000}
    d = {
        "funding_rate": 0.0001,
        "open_interest": 1e9,
        "open_interest_prev": 0.995e9,
        "long_short_ratio": 1.08,
        "spot_price": 50_000.0,
        "mark_price": 50_020.0,
    }
    r = analyze_derivatives_intel("ETH/USDT", d, a, attach_to_analysis=False)

    assert r["trade_permission"] == "ALLOW"
    assert 0.0 <= r["alpha_score"] <= 1.0
    assert 0.0 <= r["risk_score"] <= 1.0
    assert 0.0 <= r["confidence"] <= 1.0
    assert r["score_type"] == "ALPHA"


def test_derivatives_high_funding_high_ls_halts_or_blocks() -> None:
    """Uç funding + uç L/S → BLOCK veya HALT (eşik: crowd_fr & ls_risk)."""
    a = {"signal": "BUY"}
    d = {
        "funding_rate": 0.00076,
        "long_short_ratio": 4.0,
        "spot_price": 100.0,
        "mark_price": 100.5,
        "open_interest": 1e9,
        "open_interest_prev": 1e9,
    }
    r = analyze_derivatives_intel("ALT/USDT", d, a, attach_to_analysis=False)

    assert r["trade_permission"] in ("BLOCK", "HALT")


def test_derivatives_liquidation_map_sets_cluster_score() -> None:
    """Likidite haritası dolu → liquidity_cluster_score hesaplanır."""
    a = {}
    d = {
        "spot_price": 100.0,
        "mark_price": 100.2,
        "liquidation_levels": [
            {"price": 99.0, "size": 2e6},
            {"price": 101.0, "size": 1e6},
            {"price": 150.0, "size": 1e3},
        ],
        "funding_rate": 0.00005,
        "long_short_ratio": 1.1,
    }
    r = analyze_derivatives_intel("Z/USDT", d, a, attach_to_analysis=False)
    inner = r["derivatives"]

    assert "liquidity_cluster_score" in inner
    assert inner["liquidity_cluster_score"] >= 0.0
    assert inner["liquidity_cluster_score"] <= 1.0


def test_derivatives_phase18_faz18_aliases_populated() -> None:
    """analysis phase18 / faz18 aynı payload."""
    a: dict = {}
    d = {"funding_rate": 0.0002, "spot_price": 10.0, "mark_price": 10.01}
    analyze_derivatives_intel("X/USDT", d, a, attach_to_analysis=True)

    assert "phase18" in a
    assert "faz18" in a
    assert a["phase18"] is a["faz18"]
    assert a["phase18"]["phase"] == "18"
    assert a["phase18"]["source"] == "derivatives_intel"


def test_run_derivatives_phase_matches_analyze() -> None:
    """run_derivatives_phase çalışır ve analyze ile aynı mantık."""
    a1: dict = {}
    a2: dict = {}
    d = {
        "funding_rate": -0.00015,
        "long_short_ratio": 0.95,
        "spot_price": 200.0,
        "mark_price": 199.5,
    }
    r1 = run_derivatives_phase("Q/USDT", d, a1, attach_to_analysis=True)
    r2 = analyze_derivatives_intel("Q/USDT", d, a2, attach_to_analysis=True)

    assert r1["trade_permission"] == r2["trade_permission"]
    assert r1["alpha_score"] == r2["alpha_score"]
    assert r1["risk_score"] == r2["risk_score"]
    assert a1["phase18"] == a2["phase18"]
