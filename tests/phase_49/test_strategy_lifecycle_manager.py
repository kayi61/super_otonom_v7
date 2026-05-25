"""Faz 49 — strategy_lifecycle_manager birim testleri."""

from __future__ import annotations

import pytest
from phases.phase_49.strategy_lifecycle_manager import (
    analyze,
    strategy_score,
    validate_market_data,
)


def _schema_keys() -> set:
    return {
        "phase", "module", "trade_permission", "alpha_score", "risk_score",
        "score_type", "confidence", "data_health", "event_ts", "half_life_ms",
        "analysis", "reason",
    }


def _strategy(name: str, sharpe: float, dd: float, wr: float, tc: int, ver: str) -> dict:
    return {
        "name": name, "sharpe": sharpe, "max_drawdown": dd,
        "win_rate": wr, "trade_count": tc, "version": ver,
    }


def _base_market_data() -> dict:
    return {
        "champion": _strategy("champ", 1.5, 0.10, 0.60, 100, "v1.0"),
        "challenger": _strategy("chall", 1.8, 0.08, 0.65, 50, "v2.0"),
        "rolling_backtest_scores": [1.0, 1.2, 0.9, 1.1, 1.3],
    }


class TestStrategyScore:
    def test_high_sharpe_high_score(self) -> None:
        s = strategy_score(3.0, 0.0, 1.0)
        assert s == pytest.approx(1.0, abs=0.01)

    def test_zero_all(self) -> None:
        s = strategy_score(0.0, 1.0, 0.0)
        assert s == pytest.approx(0.0, abs=0.01)

    def test_moderate(self) -> None:
        s = strategy_score(1.5, 0.10, 0.55)
        assert 0.3 < s < 0.8


class TestValidation:
    def test_none_invalid(self) -> None:
        ok, _ = validate_market_data(None)
        assert not ok

    def test_missing_champion(self) -> None:
        d = _base_market_data()
        del d["champion"]
        ok, _ = validate_market_data(d)
        assert not ok

    def test_empty_rolling(self) -> None:
        d = _base_market_data()
        d["rolling_backtest_scores"] = []
        ok, err = validate_market_data(d)
        assert not ok
        assert "empty" in err

    def test_valid(self) -> None:
        ok, err = validate_market_data(_base_market_data())
        assert ok

    def test_negative_min_trade_count(self) -> None:
        d = _base_market_data()
        d["min_trade_count"] = -1
        ok, err = validate_market_data(d)
        assert not ok


class TestAnalyze:
    def test_none_blocked(self) -> None:
        r = analyze(None)
        assert r["trade_permission"] == "BLOCK"
        assert r["phase"] == 49
        assert _schema_keys() <= set(r.keys())

    def test_valid_allow(self) -> None:
        r = analyze(_base_market_data())
        assert r["trade_permission"] == "ALLOW"
        assert 0.0 <= r["alpha_score"] <= 1.0

    def test_promotion_candidate(self) -> None:
        d = _base_market_data()
        d["challenger"]["sharpe"] = 3.0
        d["challenger"]["trade_count"] = 100
        r = analyze(d)
        assert r["analysis"]["promotion_candidate"] is True

    def test_insufficient_trades_no_promotion(self) -> None:
        d = _base_market_data()
        d["challenger"]["sharpe"] = 3.0
        d["challenger"]["trade_count"] = 5
        r = analyze(d)
        assert r["analysis"]["promotion_candidate"] is False

    def test_negative_rolling_blocks(self) -> None:
        d = _base_market_data()
        d["rolling_backtest_scores"] = [-0.5, -0.3, -0.2]
        r = analyze(d)
        assert r["trade_permission"] == "BLOCK"
        assert r["reason"] == "rolling_mean_negative"

    def test_weak_champion_blocks(self) -> None:
        d = _base_market_data()
        d["champion"]["sharpe"] = 0.01
        d["champion"]["win_rate"] = 0.1
        d["champion"]["max_drawdown"] = 0.9
        r = analyze(d)
        assert r["trade_permission"] == "BLOCK"
        assert "champion" in r["reason"]
