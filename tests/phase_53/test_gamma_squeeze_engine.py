"""Faz 53 — gamma_squeeze_engine birim testleri."""

from __future__ import annotations

import pytest
from phases.phase_53.gamma_squeeze_engine import analyze, validate_market_data


def _schema_keys() -> set:
    return {
        "phase", "module", "trade_permission", "alpha_score", "risk_score",
        "score_type", "confidence", "data_health", "event_ts", "half_life_ms",
        "analysis", "reason",
    }


def _option(strike: float, expiry: int, call_oi: float, put_oi: float,
            call_gamma: float = 0.05, put_gamma: float = 0.03) -> dict:
    return {
        "strike": strike, "expiry_days": expiry,
        "call_oi": call_oi, "put_oi": put_oi,
        "call_gamma": call_gamma, "put_gamma": put_gamma,
    }


def _base_market_data() -> dict:
    chain = [
        _option(48000, 7, 500, 300),
        _option(50000, 7, 800, 600),
        _option(52000, 7, 300, 900),
    ]
    return {
        "options_chain": chain,
        "current_price": 50000.0,
        "spot_price": 49900.0,
        "dealer_gamma": -500.0,
    }


class TestValidation:
    def test_none_invalid(self) -> None:
        ok, _ = validate_market_data(None)
        assert not ok

    def test_missing_field(self) -> None:
        d = _base_market_data()
        del d["spot_price"]
        ok, _ = validate_market_data(d)
        assert not ok

    def test_empty_chain(self) -> None:
        d = _base_market_data()
        d["options_chain"] = []
        ok, err = validate_market_data(d)
        assert not ok
        assert "empty" in err

    def test_missing_option_field(self) -> None:
        d = _base_market_data()
        del d["options_chain"][0]["call_oi"]
        ok, err = validate_market_data(d)
        assert not ok
        assert "call_oi" in err

    def test_valid(self) -> None:
        ok, err = validate_market_data(_base_market_data())
        assert ok


class TestAnalyze:
    def test_none_blocked(self) -> None:
        r = analyze(None)
        assert r["trade_permission"] == "BLOCK"
        assert r["phase"] == 53
        assert _schema_keys() <= set(r.keys())

    def test_valid_allow(self) -> None:
        r = analyze(_base_market_data())
        assert 0.0 <= r["alpha_score"] <= 1.0
        assert 0.0 <= r["risk_score"] <= 1.0

    def test_high_squeeze_risk_blocks(self) -> None:
        d = _base_market_data()
        d["dealer_gamma"] = -5000.0
        r = analyze(d)
        assert r["trade_permission"] == "BLOCK"
        assert "squeeze" in r["reason"]

    def test_max_pain_strike_computed(self) -> None:
        r = analyze(_base_market_data())
        assert "max_pain_strike" in r["analysis"]
        assert r["analysis"]["max_pain_strike"] > 0

    def test_gamma_imbalance_range(self) -> None:
        r = analyze(_base_market_data())
        assert -1.0 <= r["analysis"]["gamma_imbalance"] <= 1.0

    def test_positive_dealer_gamma_low_risk(self) -> None:
        d = _base_market_data()
        d["dealer_gamma"] = 500.0
        r = analyze(d)
        assert r["analysis"]["gamma_squeeze_risk"] == pytest.approx(0.0, abs=0.01)

    def test_data_health_scales_with_chain_size(self) -> None:
        d = _base_market_data()
        d["options_chain"] = [_option(50000, 7, 100, 100)] * 20
        r = analyze(d)
        assert r["data_health"] == pytest.approx(1.0, abs=0.01)
