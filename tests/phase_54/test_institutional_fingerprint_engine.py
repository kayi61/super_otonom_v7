"""Faz 54 — institutional_fingerprint_engine birim testleri."""

from __future__ import annotations

import pytest
from phases.phase_54.institutional_fingerprint_engine import analyze, validate_market_data


def _schema_keys() -> set:
    return {
        "phase", "module", "trade_permission", "alpha_score", "risk_score",
        "score_type", "confidence", "data_health", "event_ts", "half_life_ms",
        "analysis", "reason",
    }


def _trade(size: float, price: float, side: str, ts: float) -> dict:
    return {"size": size, "price": price, "side": side, "ts": ts}


def _snapshot(ts: float, bb: float, ba: float, bd: float, ad: float) -> dict:
    return {"ts": ts, "best_bid": bb, "best_ask": ba, "bid_depth": bd, "ask_depth": ad}


def _base_market_data() -> dict:
    trades = [_trade(10.0, 50000.0 + i, "buy" if i % 2 == 0 else "sell", float(i * 100))
              for i in range(20)]
    snaps = [_snapshot(float(i * 100), 49999.0, 50001.0, 5e5, 4e5) for i in range(5)]
    return {
        "trades": trades,
        "order_book_snapshots": snaps,
        "current_price": 50000.0,
        "session_end_ts": 1e13,
        "current_ts": 1e12,
    }


class TestValidation:
    def test_none_invalid(self) -> None:
        ok, _ = validate_market_data(None)
        assert not ok

    def test_too_few_trades(self) -> None:
        d = _base_market_data()
        d["trades"] = [_trade(10.0, 50000.0, "buy", 1.0)]
        ok, err = validate_market_data(d)
        assert not ok
        assert "insufficient" in err

    def test_empty_snapshots(self) -> None:
        d = _base_market_data()
        d["order_book_snapshots"] = []
        ok, _ = validate_market_data(d)
        assert not ok

    def test_zero_price(self) -> None:
        d = _base_market_data()
        d["current_price"] = 0.0
        ok, err = validate_market_data(d)
        assert not ok
        assert "non_positive" in err

    def test_invalid_trade_side(self) -> None:
        d = _base_market_data()
        d["trades"][0]["side"] = "LONG"
        ok, _ = validate_market_data(d)
        assert not ok

    def test_valid(self) -> None:
        ok, err = validate_market_data(_base_market_data())
        assert ok


class TestAnalyze:
    def test_none_blocked(self) -> None:
        r = analyze(None)
        assert r["trade_permission"] == "BLOCK"
        assert r["phase"] == 54
        assert _schema_keys() <= set(r.keys())

    def test_valid_allow(self) -> None:
        r = analyze(_base_market_data())
        assert r["trade_permission"] == "ALLOW"
        assert 0.0 <= r["alpha_score"] <= 1.0

    def test_twap_fingerprint_regular_trades(self) -> None:
        d = _base_market_data()
        d["trades"] = [_trade(10.0, 50000.0, "buy", float(i * 100)) for i in range(30)]
        r = analyze(d)
        assert r["analysis"]["twap_fingerprint"] > 0.5

    def test_nav_pressure_near_close(self) -> None:
        d = _base_market_data()
        d["session_end_ts"] = 1000.0
        d["current_ts"] = 999.0
        r = analyze(d)
        assert r["analysis"]["nav_pressure"] > 0.9

    def test_nav_pressure_blocks_near_close(self) -> None:
        d = _base_market_data()
        d["session_end_ts"] = 1000.0
        d["current_ts"] = 999.0
        r = analyze(d)
        assert r["trade_permission"] == "BLOCK"
        assert "nav" in r["reason"]

    def test_nav_pressure_zero_far_from_close(self) -> None:
        d = _base_market_data()
        r = analyze(d)
        assert r["analysis"]["nav_pressure"] == pytest.approx(0.0, abs=0.01)

    def test_iceberg_score_computed(self) -> None:
        r = analyze(_base_market_data())
        assert "iceberg_score" in r["analysis"]
        assert 0.0 <= r["analysis"]["iceberg_score"] <= 1.0
