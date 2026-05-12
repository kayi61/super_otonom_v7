"""Faz 41 — market_maker_intelligence birim testleri."""

from __future__ import annotations

import numpy as np
import pytest
from phases.phase_41 import market_maker_intelligence as mm_mod
from phases.phase_41.market_maker_intelligence import (
    analyze,
    compute_inventory_pressure,
    compute_quote_stuffing,
    compute_stop_hunt_risk,
    compute_vpin,
    validate_market_data,
)


def _base_valid() -> dict:
    return {
        "buy_volumes": [10.0, 12.0, 11.0, 10.5] * 5,
        "sell_volumes": [9.5, 11.0, 10.5, 10.0] * 5,
        "cancel_count": 40.0,
        "fill_count": 200.0,
        "current_price": 100.0,
        "recent_low": 98.0,
        "recent_high": 102.0,
        "atr": 1.0,
        "mm_long_ratio": 0.5,
    }


def _schema_keys() -> set:
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


def test_analyze_none_blocked_quality() -> None:
    r = analyze(None)
    assert r["trade_permission"] == "BLOCK"
    assert r["data_health"] == 0.0
    assert r["confidence"] == 0.0
    assert r["score_type"] == "QUALITY"
    assert r["alpha_score"] == 0.0
    assert _schema_keys() <= set(r.keys())


def test_analyze_missing_buy_volumes() -> None:
    d = _base_valid()
    del d["buy_volumes"]
    r = analyze(d)
    assert r["trade_permission"] == "BLOCK"
    assert "missing_field" in r["reason"]


def test_analyze_missing_sell_volumes() -> None:
    d = _base_valid()
    del d["sell_volumes"]
    r = analyze(d)
    assert r["trade_permission"] == "BLOCK"


def test_analyze_volume_length_mismatch() -> None:
    d = _base_valid()
    d["buy_volumes"] = [1.0, 2.0]
    d["sell_volumes"] = [1.0]
    r = analyze(d)
    assert r["trade_permission"] == "BLOCK"
    assert "mismatch" in r["reason"]


def test_analyze_empty_buy_volumes() -> None:
    d = _base_valid()
    d["buy_volumes"] = []
    r = analyze(d)
    assert r["trade_permission"] == "BLOCK"


def test_analyze_empty_sell_volumes() -> None:
    d = _base_valid()
    d["sell_volumes"] = []
    r = analyze(d)
    assert r["trade_permission"] == "BLOCK"


def test_analyze_fill_count_zero_invalid() -> None:
    d = _base_valid()
    d["fill_count"] = 0.0
    r = analyze(d)
    assert r["trade_permission"] == "BLOCK"
    assert "fill" in r["reason"]


def test_analyze_atr_non_positive() -> None:
    d = _base_valid()
    d["atr"] = 0.0
    r = analyze(d)
    assert r["trade_permission"] == "BLOCK"


def test_analyze_high_below_low_invalid() -> None:
    d = _base_valid()
    d["recent_low"] = 105.0
    d["recent_high"] = 100.0
    r = analyze(d)
    assert r["trade_permission"] == "BLOCK"


def test_vpin_block_threshold() -> None:
    d = _base_valid()
    d["buy_volumes"] = [100.0] * 20
    d["sell_volumes"] = [0.0] * 20
    r = analyze(d)
    assert r["analysis"]["vpin"] >= 0.70
    assert r["trade_permission"] == "BLOCK"
    assert r["reason"] == "vpin_toxic_flow"


def test_quote_stuffing_block_threshold() -> None:
    d = _base_valid()
    d["cancel_count"] = 5.0 * 200.0
    d["fill_count"] = 200.0
    assert compute_quote_stuffing(d["cancel_count"], d["fill_count"]) >= 0.9
    r = analyze(d)
    assert r["trade_permission"] == "BLOCK"
    assert r["reason"] == "quote_stuffing"


def test_aggregate_risk_block() -> None:
    # VPIN < 0.70, QS < 0.90 ama toplam risk >= 0.70 (aggregate_risk nedeni)
    d = _base_valid()
    d["buy_volumes"] = [67.0] * 20
    d["sell_volumes"] = [33.0] * 20
    d["cancel_count"] = 896.0
    d["fill_count"] = 200.0
    d["mm_long_ratio"] = 1.0
    d["current_price"] = 98.0
    d["recent_low"] = 98.0
    d["recent_high"] = 110.0
    r = analyze(d)
    assert r["analysis"]["vpin"] < 0.70
    assert r["analysis"]["quote_stuffing_score"] < 0.90
    assert r["risk_score"] >= 0.70
    assert r["trade_permission"] == "BLOCK"
    assert r["reason"] == "aggregate_risk"


def test_alpha_equals_one_minus_risk_valid() -> None:
    d = _base_valid()
    r = analyze(d)
    assert abs(r["alpha_score"] + r["risk_score"] - 1.0) < 1e-9


def test_data_health_formula() -> None:
    d = _base_valid()
    n = len(d["buy_volumes"])
    r = analyze(d)
    assert abs(r["data_health"] - min(n, 20) / 20.0) < 1e-9


def test_confidence_formula() -> None:
    d = _base_valid()
    r = analyze(d)
    dh = r["data_health"]
    rs = r["risk_score"]
    exp = float(np.clip(dh * (1.0 - 0.3 * rs), 0.0, 1.0))
    assert abs(r["confidence"] - exp) < 1e-9


def test_inventory_pressure_mid_is_zero() -> None:
    assert compute_inventory_pressure(0.5) == pytest.approx(0.0, abs=1e-9)


def test_inventory_pressure_extremes() -> None:
    assert compute_inventory_pressure(0.0) == pytest.approx(1.0)
    assert compute_inventory_pressure(1.0) == pytest.approx(1.0)


def test_stop_hunt_near_low_high() -> None:
    r = compute_stop_hunt_risk(100.0, 100.0, 110.0, 1.0)
    assert r > 0.9


def test_stop_hunt_far_from_bounds() -> None:
    r = compute_stop_hunt_risk(104.0, 98.0, 106.0, 1.0)
    assert r < 0.35


def test_vpin_balanced_near_zero() -> None:
    b = np.ones(20) * 50.0
    s = np.ones(20) * 50.0
    assert compute_vpin(b, s) == pytest.approx(0.0, abs=1e-6)


def test_vpin_definition_manual() -> None:
    b = np.array([10.0, 4.0, 8.0])
    s = np.array([8.0, 10.0, 8.0])
    manual = float(np.mean(np.abs(b - s)) / (np.mean(b + s) + 1e-12))
    assert compute_vpin(b, s) == pytest.approx(np.clip(manual, 0.0, 1.0))


def test_quote_stuffing_normalization_cap() -> None:
    assert compute_quote_stuffing(25.0, 10.0) == pytest.approx(0.5)
    assert compute_quote_stuffing(500.0, 100.0) == pytest.approx(1.0)


def test_half_life_ms_constant() -> None:
    r = analyze(_base_valid())
    assert r["half_life_ms"] == 8000


def test_phase_module_fields() -> None:
    r = analyze(_base_valid())
    assert r["phase"] == 41
    assert r["module"] == "market_maker_intelligence"


def test_force_halt_halts() -> None:
    d = _base_valid()
    d["force_halt"] = True
    r = analyze(d)
    assert r["trade_permission"] == "HALT"
    assert r["reason"] == "force_halt"


def test_nested_analysis_has_metrics() -> None:
    r = analyze(_base_valid())
    a = r["analysis"]
    for k in ("vpin", "quote_stuffing_score", "stop_hunt_risk", "inventory_pressure"):
        assert k in a
        assert 0.0 <= a[k] <= 1.0


def test_all_scores_clipped_unit_interval() -> None:
    r = analyze(_base_valid())
    for k in ("alpha_score", "risk_score", "confidence", "data_health"):
        assert 0.0 <= r[k] <= 1.0


def test_event_ts_positive_float() -> None:
    r = analyze(_base_valid())
    assert isinstance(r["event_ts"], float)
    assert r["event_ts"] > 1e12


def test_validate_market_data_ok() -> None:
    ok, err = validate_market_data(_base_valid())
    assert ok is True
    assert err == ""


def test_compute_vpin_mismatched_returns_zero() -> None:
    assert compute_vpin(np.array([1.0]), np.array([1.0, 2.0])) == 0.0


def test_mm_constants_exported() -> None:
    assert mm_mod._VPIN_BLOCK == 0.70
    assert mm_mod._QS_BLOCK == 0.90
    assert mm_mod._RISK_BLOCK == 0.70


def test_score_type_alpha_when_balanced_allow() -> None:
    r = analyze(_base_valid())
    assert r["data_health"] >= 0.42
    if r["trade_permission"] == "ALLOW":
        assert r["score_type"] == "ALPHA"


def test_allow_reason_when_clean() -> None:
    r = analyze(_base_valid())
    if r["trade_permission"] == "ALLOW":
        assert r["reason"] == "conditions_normal"


def test_inventory_pressure_clipped_input() -> None:
    assert compute_inventory_pressure(1.5) <= 1.0
    assert compute_inventory_pressure(-0.5) >= 0.0
