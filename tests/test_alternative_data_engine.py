"""Faz 27 — alternative_data_engine (opsiyon akışı, dev, adoption, tokenomics)."""

from __future__ import annotations

import numpy as np
from super_otonom.alternative_data_engine import (
    analyze_alternative_data,
    run_alternative_data_phase,
)


def _balanced_alt_data() -> dict:
    """Dengeli örnek (ALLOW örüntüsü)."""
    return {
        "options_flow": {"put_call_ratio": 0.98},
        "developer": {"commits_30d": 80, "pr_count": 25, "days_since_last_commit": 3},
        "adoption": {
            "tvl_usd": 1.5e9,
            "active_addresses": 4e5,
            "tx_count_24h": 1e6,
        },
        "tokenomics": {
            "circulating_supply_ratio": 0.45,
            "inflation_apy": 0.06,
            "vesting_unlock_pct_90d": 0.08,
        },
    }


def test_alt_empty_blocks_quality() -> None:
    """1. Boş veri → BLOCK, data_health 0, QUALITY."""
    a: dict = {}
    r = analyze_alternative_data("X/USDT", {}, a, attach_to_analysis=True)

    assert r["trade_permission"] == "BLOCK"
    assert r["data_health"] == 0.0
    assert r["score_type"] == "QUALITY"
    assert r.get("empty_reason") == "no_alt_data"


def test_alt_normal_balanced_allow_alpha_unit_interval() -> None:
    """2. Normal dengeli veri → ALLOW, alpha_score 0–1."""
    np.random.seed(42)
    a: dict = {}
    r = analyze_alternative_data("OK/USDT", _balanced_alt_data(), a, attach_to_analysis=False)

    assert r["trade_permission"] == "ALLOW"
    assert 0.0 <= r["alpha_score"] <= 1.0


def test_alt_high_put_call_raises_skew_and_risk() -> None:
    """3. Yüksek put/call → options_skew_risk yüksek, risk_score artar."""
    np.random.seed(42)
    base = _balanced_alt_data()
    low = {**base, "options_flow": {"put_call_ratio": 0.95}}
    high = {**base, "options_flow": {"put_call_ratio": 2.6}}
    r_low = analyze_alternative_data("L/USDT", low, {}, attach_to_analysis=False)
    r_high = analyze_alternative_data("H/USDT", high, {}, attach_to_analysis=False)

    assert (
        r_high["alternative_data"]["options_flow"]["options_skew_risk"]
        > r_low["alternative_data"]["options_flow"]["options_skew_risk"]
    )
    assert r_high["risk_score"] > r_low["risk_score"]


def test_alt_low_developer_confidence_penalty() -> None:
    """4. Düşük developer aktivitesi → confidence düşük (penalty)."""
    np.random.seed(42)
    base = _balanced_alt_data()
    strong_dev = {
        **base,
        "developer": {"commits_30d": 100, "pr_count": 30, "days_since_last_commit": 2},
    }
    weak_dev = {
        **base,
        "developer": {"commits_30d": 0, "pr_count": 0, "days_since_last_commit": 60},
    }
    r_s = analyze_alternative_data("DS/USDT", strong_dev, {}, attach_to_analysis=False)
    r_w = analyze_alternative_data("DW/USDT", weak_dev, {}, attach_to_analysis=False)

    assert (
        r_w["alternative_data"]["developer"]["low_activity_confidence_penalty"]
        > r_s["alternative_data"]["developer"]["low_activity_confidence_penalty"]
    )
    assert r_w["confidence"] < r_s["confidence"]


def test_alt_bad_inflation_blocks() -> None:
    """5. Kötü tokenomics (yüksek inflation_apy) → tokenomics_block, BLOCK."""
    np.random.seed(42)
    d = {
        **_balanced_alt_data(),
        "tokenomics": {
            "circulating_supply_ratio": 0.5,
            "inflation_apy": 0.35,
            "vesting_unlock_pct_90d": 0.1,
        },
    }
    r = analyze_alternative_data("INF/USDT", d, {}, attach_to_analysis=False)

    assert r["alternative_data"]["tokenomics"]["tokenomics_block"] is True
    assert r["trade_permission"] == "BLOCK"


def test_alt_high_vesting_blocks() -> None:
    """6. Yüksek vesting unlock → BLOCK."""
    np.random.seed(42)
    d = {
        **_balanced_alt_data(),
        "tokenomics": {
            "circulating_supply_ratio": 0.6,
            "inflation_apy": 0.05,
            "vesting_unlock_pct_90d": 0.55,
        },
    }
    r = analyze_alternative_data("VES/USDT", d, {}, attach_to_analysis=False)

    assert r["trade_permission"] == "BLOCK"
    assert r["alternative_data"]["tokenomics"]["tokenomics_block"] is True


def test_alt_strong_adoption_raises_alpha() -> None:
    """7. Güçlü adoption → adoption_score ve alpha_score artar."""
    np.random.seed(42)
    weak = {
        **_balanced_alt_data(),
        "adoption": {"tvl_usd": 1e6, "active_addresses": 100, "tx_count_24h": 500},
    }
    strong = {
        **_balanced_alt_data(),
        "adoption": {
            "tvl_usd": 8e9,
            "active_addresses": 9e6,
            "tx_count_24h": 8e6,
            "active_users": 2e6,
        },
    }
    r_w = analyze_alternative_data("AW/USDT", weak, {}, attach_to_analysis=False)
    r_s = analyze_alternative_data("AS/USDT", strong, {}, attach_to_analysis=False)

    assert (
        r_s["alternative_data"]["adoption"]["adoption_score"]
        > r_w["alternative_data"]["adoption"]["adoption_score"]
    )
    assert r_s["alpha_score"] > r_w["alpha_score"]


def test_alt_force_halt() -> None:
    """8. force_halt True → HALT."""
    np.random.seed(42)
    d = {**_balanced_alt_data(), "force_halt": True}
    r = analyze_alternative_data("HALT/USDT", d, {}, attach_to_analysis=False)
    assert r["trade_permission"] == "HALT"


def test_alt_dict_has_core_metrics() -> None:
    """9. alternative_data: options_skew_risk, adoption_score, tokenomics_block, blend_score."""
    np.random.seed(42)
    r = analyze_alternative_data("K/USDT", _balanced_alt_data(), {}, attach_to_analysis=False)
    ad = r["alternative_data"]

    assert "blend_score" in ad
    assert "options_skew_risk" in ad["options_flow"]
    assert "adoption_score" in ad["adoption"]
    assert "tokenomics_block" in ad["tokenomics"]


def test_alt_phase27_faz27_attached() -> None:
    """10. analysis['phase27'] ve analysis['faz27'] dolu ve aynı nesne."""
    a: dict = {}
    np.random.seed(42)
    analyze_alternative_data("PH/USDT", _balanced_alt_data(), a)

    assert "phase27" in a and "faz27" in a
    assert a["phase27"] is a["faz27"]
    assert a["phase27"]["phase"] == "27"


def test_run_alternative_data_phase_writes_analysis() -> None:
    """11. run_alternative_data_phase çalışır ve phase27 yazar."""
    a: dict = {}
    np.random.seed(42)
    r = run_alternative_data_phase("RUN/USDT", _balanced_alt_data(), a)

    assert r["source"] == "alternative_data_engine"
    assert a.get("phase27") is r
