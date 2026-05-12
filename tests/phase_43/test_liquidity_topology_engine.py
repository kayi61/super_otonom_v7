"""Faz 43 — liquidity_topology_engine birim testleri."""

from __future__ import annotations

import numpy as np
import pytest
from phases.phase_43 import liquidity_topology_engine as lt_mod
from phases.phase_43.liquidity_topology_engine import (
    analyze,
    compute_black_hole_score,
    compute_depth_totals,
    compute_ofi_score,
    compute_vacuum_score,
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


def _ob(
    bid_p: float = 100.0,
    ask_p: float = 100.1,
    bid_sz: float = 10.0,
    ask_sz: float = 10.0,
    n: int = 5,
) -> dict:
    bids = [[bid_p - i * 0.01, bid_sz] for i in range(n)]
    asks = [[ask_p + i * 0.01, ask_sz] for i in range(n)]
    return {"exchange": "X", "bids": bids, "asks": asks}


def _base_data(n_venues: int = 3) -> dict:
    return {
        "order_books": [_ob() for _ in range(n_venues)],
        "current_price": 100.0,
    }


def test_analyze_none_quality() -> None:
    r = analyze(None)
    assert r["trade_permission"] == "BLOCK"
    assert r["data_health"] == 0.0
    assert r["score_type"] == "QUALITY"
    assert _schema() <= set(r.keys())


def test_empty_order_books() -> None:
    r = analyze({"order_books": [], "current_price": 1.0})
    assert r["trade_permission"] == "BLOCK"


def test_missing_current_price() -> None:
    r = analyze({"order_books": [_ob()]})
    assert r["trade_permission"] == "BLOCK"


def test_non_positive_price() -> None:
    d = _base_data(1)
    d["current_price"] = 0.0
    r = analyze(d)
    assert r["trade_permission"] == "BLOCK"


def test_no_valid_books() -> None:
    d = {
        "order_books": [
            {"exchange": "A", "bids": [], "asks": [[100.1, 1.0]]},
        ],
        "current_price": 100.0,
    }
    r = analyze(d)
    assert r["trade_permission"] == "BLOCK"


def test_ofi_balanced_near_half() -> None:
    tb, ta, _ = compute_depth_totals([_ob(bid_sz=5.0, ask_sz=5.0)], 10)
    _, ofs = compute_ofi_score(tb, ta)
    assert ofs == pytest.approx(0.5)


def test_ofi_bid_heavy_high_score() -> None:
    ob = {
        "bids": [[100.0, 50.0]] * 10,
        "asks": [[100.2, 5.0]] * 10,
    }
    tb, ta, _ = compute_depth_totals([ob], 10)
    _, ofs = compute_ofi_score(tb, ta)
    assert ofs > 0.75


def test_depth_levels_truncates() -> None:
    ob = _ob(n=20)
    tb_full, ta_full, _ = compute_depth_totals([ob], 10)
    tb_small, ta_small, _ = compute_depth_totals([ob], 3)
    assert tb_full >= tb_small


def test_black_hole_score_formula() -> None:
    bids = [[100.0, 1.0]] * 9 + [[100.0, 100.0]]
    asks = [[100.2, 1.0]] * 10
    ratio, bh = compute_black_hole_score([{"bids": bids, "asks": asks}], 10)
    assert ratio > 14.0
    assert bh >= 0.59


def test_black_hole_blocks() -> None:
    bids = [[100.0, 1.0]] * 9 + [[100.0, 120.0]]
    asks = [[100.2, 1.0]] * 10
    d = {"order_books": [{"bids": bids, "asks": asks}], "current_price": 100.0}
    r = analyze(d)
    assert r["analysis"]["black_hole_score"] >= 0.6
    assert r["trade_permission"] == "BLOCK"
    assert r["reason"] == "liquidity_black_hole"


def test_vacuum_wide_spread() -> None:
    ob = {"bids": [[100.0, 1.0]], "asks": [[100.6, 1.0]]}
    av, vs = compute_vacuum_score([ob], 100.0)
    assert av > 0.004
    assert vs > 0.5


def test_vacuum_tight_spread_low() -> None:
    av, vs = compute_vacuum_score([_ob(100.0, 100.01)], 100.0)
    assert vs < 0.3


def test_alpha_risk_match_spec() -> None:
    d = _base_data(5)
    r = analyze(d)
    a = r["analysis"]
    al = (
        0.5 * a["ofi_score"] + 0.3 * (1.0 - a["vacuum_score"]) + 0.2 * (1.0 - a["black_hole_score"])
    )
    rs = 0.5 * a["black_hole_score"] + 0.3 * a["vacuum_score"] + 0.2 * (1.0 - a["ofi_score"])
    assert r["alpha_score"] == pytest.approx(np.clip(al, 0, 1))
    assert r["risk_score"] == pytest.approx(np.clip(rs, 0, 1))


def test_data_health_five_venues() -> None:
    r = analyze(_base_data(5))
    assert r["data_health"] == pytest.approx(1.0)


def test_data_health_one_venue_clamped() -> None:
    r = analyze(_base_data(1))
    assert r["data_health"] == pytest.approx(0.2)


def test_confidence_formula() -> None:
    r = analyze(_base_data(4))
    dh = r["data_health"]
    rs = r["risk_score"]
    assert r["confidence"] == pytest.approx(float(np.clip(dh * (1.0 - 0.3 * rs), 0, 1)))


def test_half_life_5000() -> None:
    r = analyze(_base_data())
    assert r["half_life_ms"] == 5000


def test_phase_module() -> None:
    r = analyze(_base_data())
    assert r["phase"] == 43
    assert r["module"] == "liquidity_topology_engine"


def test_force_halt() -> None:
    d = _base_data()
    d["force_halt"] = True
    r = analyze(d)
    assert r["trade_permission"] == "HALT"
    assert r["reason"] == "force_halt"


def test_analysis_required_keys() -> None:
    r = analyze(_base_data())
    a = r["analysis"]
    for k in (
        "ofi_score",
        "black_hole_score",
        "vacuum_score",
        "total_bid_depth",
        "total_ask_depth",
        "exchange_count",
    ):
        assert k in a


def test_exchange_count_equals_input_len() -> None:
    d = _base_data(4)
    r = analyze(d)
    assert r["analysis"]["exchange_count"] == 4


def test_validate_ok() -> None:
    ok, err = validate_market_data(_base_data())
    assert ok and err == ""


def test_multi_venue_depth_sums() -> None:
    tb, ta, n = compute_depth_totals([_ob(bid_sz=2.0), _ob(bid_sz=3.0)], 5)
    tb1, _, _ = compute_depth_totals([_ob(bid_sz=2.0)], 5)
    tb2, _, _ = compute_depth_totals([_ob(bid_sz=3.0)], 5)
    assert tb == pytest.approx(tb1 + tb2)


def test_constants() -> None:
    assert lt_mod._BLACK_HOLE_BLOCK == 0.60
    assert lt_mod._HALF_LIFE_MS == 5000


def test_order_book_not_dict_invalid() -> None:
    d = {"order_books": ["bad"], "current_price": 1.0}
    r = analyze(d)
    assert r["trade_permission"] == "BLOCK"


def test_total_depth_non_negative() -> None:
    r = analyze(_base_data())
    assert r["analysis"]["total_bid_depth"] >= 0
    assert r["analysis"]["total_ask_depth"] >= 0


def test_event_ts_float() -> None:
    r = analyze(_base_data())
    assert isinstance(r["event_ts"], float)
    assert r["event_ts"] > 1e12


def test_allow_reason() -> None:
    r = analyze(_base_data())
    if r["trade_permission"] == "ALLOW":
        assert r["reason"] == "conditions_normal"


def test_depth_levels_param() -> None:
    d = _base_data(2)
    d["depth_levels"] = 2
    analyze(d)
    tb10, _, _ = compute_depth_totals(d["order_books"], 10)
    tb2, _, _ = compute_depth_totals(d["order_books"], 2)
    assert tb10 >= tb2


def test_score_type_when_allow() -> None:
    r = analyze(_base_data(5))
    if r["trade_permission"] == "ALLOW":
        assert r["data_health"] >= 0.42


def test_ofi_zero_depth_neutral() -> None:
    _, ofs = compute_ofi_score(0.0, 0.0)
    assert ofs == pytest.approx(0.5)


def test_vacuum_missing_top_prices_fallback() -> None:
    av, vs = compute_vacuum_score([], 100.0)
    assert vs == pytest.approx(1.0)


def test_black_hole_multi_venue_max_ratio() -> None:
    calm = {"bids": [[100.0, 5.0]] * 5, "asks": [[100.1, 5.0]] * 5}
    wild = {"bids": [[100.0, 1.0]] * 9 + [[100.0, 100.0]], "asks": [[100.2, 1.0]] * 10}
    r1, _ = compute_black_hole_score([calm], 10)
    r2, bh = compute_black_hole_score([calm, wild], 10)
    assert r2 >= r1
    assert bh >= _clip_bh(r2)


def _clip_bh(ratio: float) -> float:
    return float(np.clip((ratio - 5.0) / 15.0, 0.0, 1.0))


def test_all_scores_unit_interval() -> None:
    r = analyze(_base_data())
    for k in ("alpha_score", "risk_score", "confidence", "data_health"):
        assert 0.0 <= r[k] <= 1.0


def test_invalid_top_of_book_row() -> None:
    d = {
        "order_books": [{"bids": [[]], "asks": [[100.1, 1.0]]}],
        "current_price": 100.0,
    }
    r = analyze(d)
    assert r["trade_permission"] == "BLOCK"
