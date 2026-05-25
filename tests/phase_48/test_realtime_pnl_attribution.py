"""Faz 48 — realtime_pnl_attribution birim testleri."""

from __future__ import annotations

import pytest
from phases.phase_48.realtime_pnl_attribution import analyze, validate_market_data


def _schema_keys() -> set:
    return {
        "phase", "module", "trade_permission", "alpha_score", "risk_score",
        "score_type", "confidence", "data_health", "event_ts", "half_life_ms",
        "analysis", "reason",
    }


def _record(phase: int, pnl: float, enabled: bool = True, weight: float = 1.0) -> dict:
    return {"phase": phase, "pnl": pnl, "enabled": enabled, "weight": weight}


def _base_market_data() -> dict:
    recs = [_record(41, 0.05), _record(42, 0.03), _record(43, -0.01)]
    return {
        "phase_pnl_records": recs,
        "total_pnl": 0.07,
        "benchmark_pnl": 0.02,
    }


class TestValidation:
    def test_none_invalid(self) -> None:
        ok, _ = validate_market_data(None)
        assert not ok

    def test_empty_records(self) -> None:
        ok, err = validate_market_data({"phase_pnl_records": [], "total_pnl": 0, "benchmark_pnl": 0})
        assert not ok
        assert "empty" in err

    def test_missing_pnl_fields(self) -> None:
        ok, err = validate_market_data({"phase_pnl_records": [_record(1, 0.1)]})
        assert not ok

    def test_valid(self) -> None:
        ok, err = validate_market_data(_base_market_data())
        assert ok

    def test_weight_out_of_range(self) -> None:
        d = _base_market_data()
        d["phase_pnl_records"][0]["weight"] = 1.5
        ok, err = validate_market_data(d)
        assert not ok
        assert "weight" in err

    def test_rolling_window_negative(self) -> None:
        d = _base_market_data()
        d["rolling_window"] = -1
        ok, err = validate_market_data(d)
        assert not ok


class TestAnalyze:
    def test_none_blocked(self) -> None:
        r = analyze(None)
        assert r["trade_permission"] == "BLOCK"
        assert r["phase"] == 48
        assert _schema_keys() <= set(r.keys())

    def test_valid_allow(self) -> None:
        r = analyze(_base_market_data())
        assert r["trade_permission"] == "ALLOW"
        assert 0.0 <= r["alpha_score"] <= 1.0

    def test_positive_excess_return(self) -> None:
        d = _base_market_data()
        d["total_pnl"] = 0.10
        d["benchmark_pnl"] = 0.02
        r = analyze(d)
        assert r["alpha_score"] > 0.3

    def test_negative_excess_increases_risk(self) -> None:
        d = _base_market_data()
        d["total_pnl"] = -0.05
        d["benchmark_pnl"] = 0.02
        r = analyze(d)
        assert r["risk_score"] > 0.4

    def test_disabled_records_excluded(self) -> None:
        d = _base_market_data()
        d["phase_pnl_records"].append(_record(44, 0.10, enabled=False))
        r = analyze(d)
        contrib = r["analysis"]["top_contributors"]
        phases = [c["phase"] for c in contrib]
        assert 44 not in phases

    def test_rolling_window_applied(self) -> None:
        recs = [_record(i, 0.01) for i in range(50)]
        d = {"phase_pnl_records": recs, "total_pnl": 0.5, "benchmark_pnl": 0.1, "rolling_window": 5}
        r = analyze(d)
        assert r["trade_permission"] == "ALLOW"

    def test_analysis_has_contributors(self) -> None:
        r = analyze(_base_market_data())
        assert "top_contributors" in r["analysis"]
        assert "top_detractors" in r["analysis"]
