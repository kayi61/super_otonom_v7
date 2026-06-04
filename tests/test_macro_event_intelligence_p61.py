"""PROMPT-6.1 — Makroekonomik Event Tracker + regime/meta_regime entegrasyonu."""

from __future__ import annotations

import json

import pytest
from super_otonom.meta_regime_orchestrator import compute_meta_regime
from super_otonom.signals.macro_event_intelligence import (
    BEARISH,
    BULLISH,
    CRASH_RISK,
    NEUTRAL,
    RISK_OFF,
    TRENDING,
    UNKNOWN,
    MacroCollector,
    analyze_economic_calendar,
    analyze_geopolitical,
    analyze_liquidity,
    analyze_macro,
    analyze_macro_data,
    analyze_macro_indicators,
    macro_regime_hint,
    parse_fred_series,
)

# ── 1) Ekonomik takvim ───────────────────────────────────────────────────────


def test_calendar_dovish_bias_positive() -> None:
    bias, _vol, _s, reasons = analyze_economic_calendar(fed_stance="dovish")
    assert bias > 0 and any("dovish" in r for r in reasons)


def test_calendar_hawkish_bias_negative() -> None:
    bias, _vol, _s, _r = analyze_economic_calendar(fed_stance="hawkish")
    assert bias < 0


def test_calendar_cpi_surprise_volatility() -> None:
    bias, vol, surprise, reasons = analyze_economic_calendar(cpi_actual=3.5, cpi_expected=3.0)
    assert surprise == pytest.approx(0.5)
    assert vol > 0 and bias < 0  # hotter CPI → hawkish/bearish
    assert any("CPI" in r for r in reasons)


# ── 2) Makro indikatörler ────────────────────────────────────────────────────


def test_indicators_dxy_up_bearish() -> None:
    bias, _ro, _risk, reasons = analyze_macro_indicators(dxy_trend="up")
    assert bias < 0 and any("DXY" in r for r in reasons)


def test_indicators_vix_risk_off() -> None:
    bias, risk_off, risk, reasons = analyze_macro_indicators(vix=35)
    assert risk_off is True
    assert risk >= 0.6 and bias < 0
    assert any("VIX" in r for r in reasons)


def test_indicators_dxy_down_bullish() -> None:
    bias, _ro, _risk, _r = analyze_macro_indicators(dxy_trend="down", spx_trend="up")
    assert bias > 0


# ── 3) Likidite ──────────────────────────────────────────────────────────────


def test_liquidity_qe_m2_bullish() -> None:
    bias, reasons = analyze_liquidity(fed_balance_sheet_trend="expanding", m2_trend="up")
    assert bias > 0 and len(reasons) >= 2


def test_liquidity_qt_bearish() -> None:
    bias, _r = analyze_liquidity(fed_balance_sheet_trend="qt", m2_trend="down")
    assert bias < 0


def test_liquidity_rrp_draining_bullish() -> None:
    bias, _r = analyze_liquidity(reverse_repo_trend="draining")
    assert bias > 0


# ── 4) Geopolitik ────────────────────────────────────────────────────────────


def test_geopolitical_war_keyword() -> None:
    risk, bias, reasons = analyze_geopolitical(text="Breaking: military invasion and sanctions")
    assert risk >= 0.6 and bias < 0
    assert any("Geopolitik" in r for r in reasons)


def test_geopolitical_regulation() -> None:
    risk, _b, reasons = analyze_geopolitical(regulation_news=True, regulatory_severity=0.7)
    assert risk >= 0.7 and any("regülasyon" in r for r in reasons)


def test_geopolitical_none() -> None:
    risk, bias, _r = analyze_geopolitical()
    assert risk == 0.0 and bias == 0.0


# ── Birleşik sinyal + kurallar ───────────────────────────────────────────────


def test_macro_bullish_combo() -> None:
    sig = analyze_macro(fed_stance="dovish", dxy_trend="down", m2_trend="up")
    assert sig.environment == BULLISH
    assert sig.regime_hint == TRENDING
    assert sig.alpha_bias > 0


def test_macro_risk_off_combo() -> None:
    sig = analyze_macro(fed_stance="hawkish", dxy_trend="up", vix=35)
    assert sig.environment == RISK_OFF
    assert sig.regime_hint == CRASH_RISK
    assert sig.risk_off is True
    assert sig.risk_score >= 0.75
    assert sig.trade_permission == "BLOCK"


def test_macro_bearish() -> None:
    sig = analyze_macro(dxy_trend="up", spx_trend="down", regulation_news=True, regulatory_severity=0.5)
    assert sig.environment in (BEARISH, RISK_OFF)
    assert sig.alpha_bias < 0


def test_macro_neutral() -> None:
    sig = analyze_macro(fomc_sentiment=0.0)
    assert sig.environment == NEUTRAL
    assert sig.regime_hint == UNKNOWN


def test_macro_cpi_surprise_volatility() -> None:
    sig = analyze_macro(cpi_actual=4.0, cpi_expected=3.2)
    assert sig.volatility_expectation > 0


# ── Köprü + regime hint ──────────────────────────────────────────────────────


def test_analyze_macro_data_block() -> None:
    sig = analyze_macro_data({"macro": {"fed_stance": "dovish", "dxy_trend": "down", "m2_trend": "up"}})
    assert sig is not None and sig.environment == BULLISH


def test_analyze_macro_data_flat() -> None:
    sig = analyze_macro_data({"vix": 36, "dxy_trend": "up", "fed_stance": "hawkish"})
    assert sig is not None and sig.environment == RISK_OFF


def test_analyze_macro_data_empty_none() -> None:
    assert analyze_macro_data({}) is None
    assert analyze_macro_data("nope") is None


def test_macro_regime_hint() -> None:
    assert macro_regime_hint({"fed_stance": "dovish", "dxy_trend": "down", "m2_trend": "up"}) == TRENDING
    assert macro_regime_hint({"vix": 40, "fed_stance": "hawkish", "dxy_trend": "up"}) == CRASH_RISK
    assert macro_regime_hint({}) == UNKNOWN


# ── Parser + Collector ───────────────────────────────────────────────────────


def test_parse_fred_series() -> None:
    payload = {"observations": [{"date": "2026-05-01", "value": "5.33"}, {"date": "2026-06-01", "value": "."}]}
    assert parse_fred_series(json.dumps(payload)) == pytest.approx(5.33)


def test_parse_fred_garbage() -> None:
    assert parse_fred_series("not json") is None
    assert parse_fred_series({"no_obs": 1}) is None


def test_collector_no_key(monkeypatch) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    col = MacroCollector(http_get=lambda u, t: "{}")
    assert col.fetch_fred_series("DFF") is None


def test_collector_fetches(monkeypatch) -> None:
    monkeypatch.setenv("FRED_API_KEY", "x")
    payload = json.dumps({"observations": [{"value": "2.5"}]})
    col = MacroCollector(http_get=lambda u, t: payload)
    assert col.fetch_fred_series("M2SL") == pytest.approx(2.5)


# ── meta_regime_orchestrator (A9) entegrasyonu ───────────────────────────────


def test_meta_regime_macro_fallback_when_omega_missing() -> None:
    """Omega rejimi yoksa makro ipucu rejimi doldurur."""
    analysis = {"fed_stance": "dovish", "dxy_trend": "down", "m2_trend": "up"}  # omega yok
    payload = compute_meta_regime(analysis, {"faz71": {}}, base_confidence=0.6, mode="shadow")
    assert payload["regime"] == TRENDING
    assert payload["regime_source"] == "macro_hint"
    assert payload["macro_regime_hint"] == TRENDING


def test_meta_regime_omega_takes_precedence() -> None:
    """Omega mevcutsa makro ipucu DEVREYE GİRMEZ (eski davranış korunur)."""
    analysis = {"omega_regime": "RANGING", "fed_stance": "dovish", "dxy_trend": "down", "m2_trend": "up"}
    payload = compute_meta_regime(analysis, {"faz71": {}}, base_confidence=0.6, mode="shadow")
    assert payload["regime"] == "RANGING"
    assert payload["regime_source"] == "omega_regime"
    assert payload["macro_regime_hint"] is None


def test_meta_regime_backward_compat_unknown_no_macro() -> None:
    """Omega bilinmeyen + makro yok → UNKNOWN/missing (eski davranış)."""
    payload = compute_meta_regime({"omega_regime": "BULL"}, {"faz71": {}}, base_confidence=0.6)
    assert payload["regime"] == UNKNOWN
    assert payload["regime_source"] == "missing"
    assert payload["macro_regime_hint"] is None
