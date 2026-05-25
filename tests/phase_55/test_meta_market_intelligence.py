"""Faz 55 — meta_market_intelligence birim testleri."""

from __future__ import annotations

import pytest
from phases.phase_55.meta_market_intelligence import (
    analyze,
    validate_market_data,
    weighted_mean,
)


def _schema_keys() -> set:
    return {
        "phase", "module", "trade_permission", "alpha_score", "risk_score",
        "score_type", "confidence", "data_health", "event_ts", "half_life_ms",
        "analysis", "reason",
    }


def _phase_output(phase: int, alpha: float = 0.6, risk: float = 0.3,
                  perm: str = "ALLOW", conf: float = 0.7, stype: str = "ALPHA") -> dict:
    return {
        "phase": phase, "alpha_score": alpha, "risk_score": risk,
        "trade_permission": perm, "confidence": conf, "score_type": stype,
    }


def _base_market_data() -> dict:
    outputs = [
        _phase_output(41, 0.7, 0.2, "ALLOW", 0.8),
        _phase_output(42, 0.6, 0.3, "ALLOW", 0.7),
        _phase_output(43, 0.5, 0.4, "ALLOW", 0.6),
        _phase_output(46, 0.8, 0.1, "ALLOW", 0.9),
        _phase_output(48, 0.55, 0.35, "ALLOW", 0.65),
    ]
    return {"phase_outputs": outputs}


class TestWeightedMean:
    def test_basic(self) -> None:
        r = weighted_mean([1.0, 2.0, 3.0], [1.0, 1.0, 1.0])
        assert r == pytest.approx(2.0)

    def test_weighted(self) -> None:
        r = weighted_mean([0.0, 1.0], [0.0, 1.0])
        assert r == pytest.approx(1.0)

    def test_empty(self) -> None:
        assert weighted_mean([], []) == 0.0

    def test_zero_weights_fallback(self) -> None:
        r = weighted_mean([2.0, 4.0], [0.0, 0.0])
        assert r == pytest.approx(3.0)

    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError):
            weighted_mean([1.0], [1.0, 2.0])


class TestValidation:
    def test_none_invalid(self) -> None:
        ok, _ = validate_market_data(None)
        assert not ok

    def test_empty_outputs(self) -> None:
        ok, err = validate_market_data({"phase_outputs": []})
        assert not ok
        assert "empty" in err

    def test_invalid_permission(self) -> None:
        d = _base_market_data()
        d["phase_outputs"][0]["trade_permission"] = "UNKNOWN"
        ok, err = validate_market_data(d)
        assert not ok
        assert "permission" in err

    def test_valid(self) -> None:
        ok, err = validate_market_data(_base_market_data())
        assert ok


class TestAnalyze:
    def test_none_blocked(self) -> None:
        r = analyze(None)
        assert r["trade_permission"] == "BLOCK"
        assert r["phase"] == 55
        assert _schema_keys() <= set(r.keys())

    def test_valid_allow(self) -> None:
        r = analyze(_base_market_data())
        assert r["trade_permission"] == "ALLOW"
        assert 0.0 <= r["alpha_score"] <= 1.0

    def test_halt_overrides(self) -> None:
        d = _base_market_data()
        d["phase_outputs"].append(_phase_output(49, perm="HALT"))
        r = analyze(d)
        assert r["trade_permission"] == "HALT"
        assert r["reason"] == "phase_halt_override"

    def test_block_majority(self) -> None:
        outputs = [_phase_output(i, perm="BLOCK") for i in range(41, 46)]
        outputs.append(_phase_output(46, perm="ALLOW"))
        r = analyze({"phase_outputs": outputs})
        assert r["trade_permission"] == "BLOCK"
        assert "block_majority" in r["reason"]

    def test_whale_mm_phases_detected(self) -> None:
        d = _base_market_data()
        r = analyze(d)
        assert "whale_mm_composite" in r["analysis"]
        assert r["analysis"]["whale_mm_composite"] > 0.0

    def test_synergy_score(self) -> None:
        d = _base_market_data()
        r = analyze(d)
        assert r["analysis"]["synergy_score"] > 0.0

    def test_all_blocked_zero_synergy(self) -> None:
        outputs = [_phase_output(i, perm="BLOCK") for i in range(41, 55)]
        r = analyze({"phase_outputs": outputs})
        assert r["analysis"]["synergy_score"] == pytest.approx(0.0)
        assert r["analysis"]["allow_count"] == 0

    def test_data_health_scales(self) -> None:
        outputs = [_phase_output(i) for i in range(41, 55)]
        r = analyze({"phase_outputs": outputs})
        assert r["data_health"] > 0.9
