"""Faz 44 — behavioral_finance_engine birim testleri."""

from __future__ import annotations

import numpy as np
import pytest
from phases.phase_44 import behavioral_finance_engine as bf_mod
from phases.phase_44.behavioral_finance_engine import (
    analyze,
    compute_alpha_components,
    compute_disposition_score,
    compute_narrative_score,
    compute_reflexivity,
    compute_wyckoff_phase,
    validate_market_data,
)


def _schema() -> set:
    return {
        "phase",
        "module",
        "trade_permission",
        "alpha_score",
        "risk_score",
        "score_type",
        "confidence",
        "data_health",
        "event_ts",
        "half_life_ms",
        "analysis",
        "reason",
    }


def _series_markup_like(n: int = 25) -> tuple[list[float], list[float]]:
    prices = np.linspace(90.0, 115.0, n).tolist()
    vols = np.linspace(1e6, 2e6, n).tolist()
    return prices, vols


def _base(**kwargs: float | list) -> dict:
    ph, vh = _series_markup_like()
    d = {
        "price_history": kwargs.get("price_history", ph),
        "volume_history": kwargs.get("volume_history", vh),
        "sentiment_score": float(kwargs.get("sentiment_score", 0.5)),
        "rsi": float(kwargs.get("rsi", 50.0)),
        "funding_rate": float(kwargs.get("funding_rate", 0.0)),
    }
    return d


def test_analyze_none_blocked() -> None:
    r = analyze(None)
    assert r["trade_permission"] == "BLOCK"
    assert r["data_health"] == 0.0
    assert r["score_type"] == "QUALITY"
    assert _schema() <= set(r.keys())


def test_short_history_invalid() -> None:
    r = analyze(
        {
            "price_history": [1] * 10,
            "volume_history": [1] * 10,
            "sentiment_score": 0.5,
            "rsi": 50,
            "funding_rate": 0,
        }
    )
    assert r["trade_permission"] == "BLOCK"


def test_mismatched_lengths() -> None:
    d = _base()
    d["volume_history"] = d["volume_history"][:-1]
    r = analyze(d)
    assert r["trade_permission"] == "BLOCK"


def test_sentiment_out_of_range() -> None:
    d = _base()
    d["sentiment_score"] = 1.5
    r = analyze(d)
    assert r["trade_permission"] == "BLOCK"


def test_rsi_out_of_range() -> None:
    d = _base()
    d["rsi"] = 101.0
    r = analyze(d)
    assert r["trade_permission"] == "BLOCK"


def test_missing_field() -> None:
    d = _base()
    del d["funding_rate"]
    r = analyze(d)
    assert r["trade_permission"] == "BLOCK"


def test_risk_equals_one_minus_alpha() -> None:
    d = _base()
    r = analyze(d)
    assert r["risk_score"] == pytest.approx(1.0 - r["alpha_score"], abs=1e-9)


def test_data_health_clip() -> None:
    ph = list(np.linspace(100, 101, 20))
    vh = list(np.ones(20) * 1e6)
    r = analyze(_base(price_history=ph, volume_history=vh))
    assert r["data_health"] == pytest.approx(1.0)


def test_data_health_minimum_floor() -> None:
    ph = list(np.linspace(100, 101, 20))
    vh = list(np.ones(20))
    r = analyze(_base(price_history=ph, volume_history=vh))
    assert r["data_health"] >= 0.1
    assert r["data_health"] == pytest.approx(np.clip(20.0 / 20.0, 0.1, 1.0))


def test_confidence_formula() -> None:
    d = _base()
    r = analyze(d)
    dh = r["data_health"]
    rs = r["risk_score"]
    assert r["confidence"] == pytest.approx(float(np.clip(dh * (1.0 - 0.2 * rs), 0, 1)))


def test_half_life_30000() -> None:
    assert analyze(_base())["half_life_ms"] == 30000


def test_phase_module() -> None:
    r = analyze(_base())
    assert r["phase"] == 44
    assert r["module"] == "behavioral_finance_engine"


def test_force_halt() -> None:
    d = _base()
    d["force_halt"] = True
    r = analyze(d)
    assert r["trade_permission"] == "HALT"
    assert r["reason"] == "force_halt"


def test_analysis_keys() -> None:
    r = analyze(_base())
    a = r["analysis"]
    for k in (
        "wyckoff_phase",
        "wyckoff_alpha",
        "reflexivity_score",
        "disposition_score",
        "narrative_score",
        "rsi",
        "funding_rate",
    ):
        assert k in a


def test_disposition_formula() -> None:
    assert compute_disposition_score(50.0) == pytest.approx(1.0)
    assert compute_disposition_score(0.0) == pytest.approx(0.0)
    assert compute_disposition_score(100.0) == pytest.approx(0.0)


def test_narrative_funding_positive_risk() -> None:
    ns = compute_narrative_score(0.002)
    assert ns < 0.5


def test_narrative_funding_negative_opportunity() -> None:
    ns = compute_narrative_score(-0.002)
    assert ns > 0.5


def test_reflexivity_bounds() -> None:
    ph = list(np.linspace(100, 110, 25))
    ref, rs, pm = compute_reflexivity(ph, 1.0)
    assert -1.0 <= ref <= 1.0
    assert 0.0 <= rs <= 1.0
    assert -1.0 <= pm <= 1.0


def test_wyckoff_markup_detection() -> None:
    n = 25
    ph = np.linspace(80.0, 110.0, n).tolist()
    vh = np.concatenate([np.ones(15) * 1e6, np.ones(10) * 3e6]).tolist()
    phase, wa = compute_wyckoff_phase(ph, vh)
    assert phase in ("MARKUP", "NEUTRAL", "DISTRIBUTION")
    assert 0.0 <= wa <= 1.0


def test_wyckoff_alpha_mapping() -> None:
    assert bf_mod._WYCKOFF_ALPHA["MARKUP"] == 0.9
    assert bf_mod._WYCKOFF_ALPHA["ACCUMULATION"] == 0.8


def test_validate_ok() -> None:
    ok, err = validate_market_data(_base())
    assert ok and err == ""


def test_compute_alpha_overheated_reflexivity() -> None:
    low_reflex_term = compute_alpha_components(0.8, 0.85, 50.0, 0.5)
    high_reflex_good = compute_alpha_components(0.8, 0.5, 50.0, 0.5)
    assert low_reflex_term < high_reflex_good


def test_all_scores_unit_interval() -> None:
    r = analyze(_base())
    for k in ("alpha_score", "risk_score", "confidence", "data_health"):
        assert 0.0 <= r[k] <= 1.0


def test_event_ts_reasonable() -> None:
    r = analyze(_base())
    assert r["event_ts"] > 1e12


def test_rsi_piecewise_more_aggressive_near_50_than_deep_oversold() -> None:
    """Parça: rsi<=50 için rsi_term = rsi/50*0.8 → 50'ye yakın daha yüksek."""
    a_48 = compute_alpha_components(0.5, 0.5, 48.0, 0.5)
    a_25 = compute_alpha_components(0.5, 0.5, 25.0, 0.5)
    assert a_48 > a_25


def test_rsi_high_reduces_alpha_component() -> None:
    a_high = compute_alpha_components(0.5, 0.5, 85.0, 0.5)
    a_mid = compute_alpha_components(0.5, 0.5, 50.0, 0.5)
    assert a_high < a_mid


def test_wyckoff_neutral_short_series() -> None:
    ph = [100.0, 101.0]
    vh = [1.0, 1.0]
    p, w = compute_wyckoff_phase(ph, vh)
    assert p == "NEUTRAL"
    assert w == 0.5


def test_narrative_clip_extreme_funding() -> None:
    assert compute_narrative_score(0.02) == pytest.approx(0.0)
    assert compute_narrative_score(-0.02) == pytest.approx(1.0)


def test_allow_has_reason() -> None:
    r = analyze(_base())
    if r["trade_permission"] == "ALLOW":
        assert r["reason"] == "conditions_normal"


def test_disposition_in_analysis_matches_rsi() -> None:
    d = _base(rsi=60.0)
    r = analyze(d)
    assert r["analysis"]["disposition_score"] == pytest.approx(compute_disposition_score(60.0))


def test_funding_echo_in_analysis() -> None:
    d = _base(funding_rate=-0.0005)
    r = analyze(d)
    assert r["analysis"]["funding_rate"] == pytest.approx(-0.0005)


def test_volume_history_must_match_price_len() -> None:
    d = _base()
    d["volume_history"] = list(np.ones(21))
    r = analyze(d)
    assert r["trade_permission"] == "BLOCK"


def test_sentiment_zero_reflexivity() -> None:
    ph = list(np.linspace(100, 120, 25))
    ref, rs, _ = compute_reflexivity(ph, 0.0)
    assert ref == pytest.approx(0.0)
    assert rs == pytest.approx(0.5)


def test_alpha_components_clip() -> None:
    a = compute_alpha_components(1.0, 1.0, 100.0, 1.0)
    assert 0.0 <= a <= 1.0


def test_phase_detect_accumulation_pattern() -> None:
    n = 25
    ph = np.linspace(110.0, 95.0, n).tolist()
    vh = np.concatenate([np.ones(10) * 1e6 * 0.8, np.ones(15) * 1e6 * 1.5]).tolist()
    phase, wa = compute_wyckoff_phase(ph, vh)
    assert phase in ("ACCUMULATION", "MARKDOWN", "NEUTRAL")
    assert wa == bf_mod._WYCKOFF_ALPHA[phase]


def test_constants_half_life() -> None:
    assert bf_mod._HALF_LIFE_MS == 30000
