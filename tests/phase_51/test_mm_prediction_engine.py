"""Faz 51 — mm_prediction_engine birim testleri."""

from __future__ import annotations

import pytest
from phases.phase_51.mm_prediction_engine import (
    analyze,
    expected_mm_direction_from_flow,
    inventory_direction,
    validate_market_data,
)


def _schema_keys() -> set:
    return {
        "phase", "module", "trade_permission", "alpha_score", "risk_score",
        "score_type", "confidence", "data_health", "event_ts", "half_life_ms",
        "analysis", "reason",
    }


def _quote(bid: float, ask: float, ts: float = 1.0) -> dict:
    return {"bid": bid, "ask": ask, "ts": ts}


def _flow(size: float, side: str, ts: float = 1.0) -> dict:
    return {"size": size, "side": side, "ts": ts}


def _base_market_data() -> dict:
    quotes = [_quote(99.99, 100.01, float(i)) for i in range(15)]
    flows = [_flow(100.0, "buy" if i % 2 == 0 else "sell", float(i)) for i in range(10)]
    return {
        "mm_inventory_ratio": 0.1,
        "quote_history": quotes,
        "trade_flow": flows,
        "mid_price": 100.0,
        "volatility": 0.02,
    }


class TestInventoryDirection:
    def test_long_heavy(self) -> None:
        assert inventory_direction(0.5) == "LONG_HEAVY"

    def test_short_heavy(self) -> None:
        assert inventory_direction(-0.5) == "SHORT_HEAVY"

    def test_balanced(self) -> None:
        assert inventory_direction(0.0) == "BALANCED"


class TestExpectedDirection:
    def test_will_buy(self) -> None:
        assert expected_mm_direction_from_flow(-0.5) == "WILL_BUY"

    def test_will_sell(self) -> None:
        assert expected_mm_direction_from_flow(0.5) == "WILL_SELL"

    def test_neutral(self) -> None:
        assert expected_mm_direction_from_flow(0.0) == "NEUTRAL"


class TestValidation:
    def test_none_invalid(self) -> None:
        ok, _ = validate_market_data(None)
        assert not ok

    def test_missing_field(self) -> None:
        d = _base_market_data()
        del d["mid_price"]
        ok, _ = validate_market_data(d)
        assert not ok

    def test_zero_mid_price(self) -> None:
        d = _base_market_data()
        d["mid_price"] = 0.0
        ok, err = validate_market_data(d)
        assert not ok
        assert "non_positive" in err

    def test_empty_quotes(self) -> None:
        d = _base_market_data()
        d["quote_history"] = []
        ok, _ = validate_market_data(d)
        assert not ok

    def test_invalid_trade_side(self) -> None:
        d = _base_market_data()
        d["trade_flow"] = [_flow(100.0, "INVALID")]
        ok, err = validate_market_data(d)
        assert not ok
        assert "side" in err

    def test_valid(self) -> None:
        ok, err = validate_market_data(_base_market_data())
        assert ok


class TestAnalyze:
    def test_none_blocked(self) -> None:
        r = analyze(None)
        assert r["trade_permission"] == "BLOCK"
        assert r["phase"] == 51
        assert _schema_keys() <= set(r.keys())

    def test_valid_allow(self) -> None:
        r = analyze(_base_market_data())
        assert r["trade_permission"] == "ALLOW"
        assert 0.0 <= r["alpha_score"] <= 1.0

    def test_high_inventory_blocks(self) -> None:
        d = _base_market_data()
        d["mm_inventory_ratio"] = 0.9
        r = analyze(d)
        assert r["trade_permission"] == "BLOCK"
        assert "inventory" in r["reason"]

    def test_spread_widening_detected(self) -> None:
        d = _base_market_data()
        early = [_quote(99.90, 100.10, float(i)) for i in range(5)]
        mid = [_quote(99.90, 100.10, float(i + 5)) for i in range(5)]
        late = [_quote(99.00, 101.00, float(i + 10)) for i in range(5)]
        d["quote_history"] = early + mid + late
        r = analyze(d)
        assert r["analysis"]["spread_widening"] is True

    def test_high_volatility_penalty(self) -> None:
        d = _base_market_data()
        d["volatility"] = 0.10
        r = analyze(d)
        assert r["risk_score"] > 0.2
