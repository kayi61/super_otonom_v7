"""Faz 42 — whale_behavior_engine birim testleri."""
from __future__ import annotations

import numpy as np
import pytest

from phases.phase_42 import whale_behavior_engine as wb_mod
from phases.phase_42.whale_behavior_engine import (
    analyze,
    compute_wash_trade_score,
    compute_whale_metrics,
    compute_wyckoff,
    validate_market_data,
)


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


def _trade(size: float, price: float, side: str, ts: float = 1.0) -> dict:
    return {"size": size, "price": price, "side": side, "ts": ts}


def _base_market_data(*, n_trades: int = 50) -> dict:
    trades = []
    for i in range(n_trades):
        side = "buy" if i % 2 == 0 else "sell"
        trades.append(_trade(5000.0 + i * 10.0, 100.0 + i * 0.01, side, float(i)))
    ph = [100.0 - i * 0.05 for i in range(20)]
    vh = [1e6 + i * 5000.0 for i in range(20)]
    return {
        "trades": trades,
        "whale_threshold": 50_000.0,
        "price_history": ph,
        "volume_history": vh,
    }


def test_analyze_none_blocked_quality() -> None:
    r = analyze(None)
    assert r["trade_permission"] == "BLOCK"
    assert r["data_health"] == 0.0
    assert r["confidence"] == 0.0
    assert r["score_type"] == "QUALITY"
    assert _schema_keys() <= set(r.keys())


def test_analyze_empty_trades() -> None:
    d = _base_market_data(n_trades=50)
    d["trades"] = []
    r = analyze(d)
    assert r["trade_permission"] == "BLOCK"


def test_missing_whale_threshold() -> None:
    d = _base_market_data()
    del d["whale_threshold"]
    r = analyze(d)
    assert r["trade_permission"] == "BLOCK"


def test_whale_threshold_non_positive() -> None:
    d = _base_market_data()
    d["whale_threshold"] = 0.0
    r = analyze(d)
    assert r["trade_permission"] == "BLOCK"


def test_history_length_mismatch() -> None:
    d = _base_market_data()
    d["volume_history"] = [1.0, 2.0]
    r = analyze(d)
    assert r["trade_permission"] == "BLOCK"


def test_history_too_short() -> None:
    d = _base_market_data()
    d["price_history"] = [1.0]
    d["volume_history"] = [1.0]
    r = analyze(d)
    assert r["trade_permission"] == "BLOCK"


def test_trade_missing_side() -> None:
    d = _base_market_data()
    d["trades"][0] = {"size": 1.0, "price": 1.0}
    r = analyze(d)
    assert r["trade_permission"] == "BLOCK"


def test_whale_cluster_score_buy_bias() -> None:
    trades = [_trade(120_000.0, 100.0, "buy", float(i)) for i in range(30)]
    wr, wd, wcs, _, _ = compute_whale_metrics(trades, 50_000.0)
    assert wr > 0
    assert wd > 0.9
    assert wcs > 0.95


def test_whale_cluster_score_sell_bias() -> None:
    trades = [_trade(120_000.0, 100.0, "sell", float(i)) for i in range(30)]
    _, wd, wcs, _, _ = compute_whale_metrics(trades, 50_000.0)
    assert wd < -0.9
    assert wcs < 0.08


def test_whale_ratio_formula() -> None:
    trades = [_trade(60_000.0, 100.0, "buy", float(i)) for i in range(40)]
    wr, _, _, _, _ = compute_whale_metrics(trades, 50_000.0)
    assert wr == pytest.approx(40 / 40)


def test_wash_trade_score_clip() -> None:
    trades = []
    for _ in range(10):
        trades.append(_trade(10_000.0, 100.0, "buy", 1.0))
        trades.append(_trade(10_000.0, 100.0, "sell", 2.0))
    _, wts = compute_wash_trade_score(trades)
    assert wts == pytest.approx(1.0)


def test_wash_trade_blocks_at_threshold() -> None:
    trades = []
    for _ in range(25):
        trades.append(_trade(5000.0, 50.0, "buy", 1.0))
        trades.append(_trade(5000.0, 50.0, "sell", 2.0))
    ph = list(np.linspace(100, 99, 15))
    vh = list(np.linspace(1e6, 1.1e6, 15))
    d = {"trades": trades, "whale_threshold": 10_000.0, "price_history": ph, "volume_history": vh}
    r = analyze(d)
    assert r["analysis"]["wash_trade_score"] >= 0.7
    assert r["trade_permission"] == "BLOCK"
    assert r["reason"] == "wash_trade_manipulation"


def test_alpha_risk_formulas_match_spec() -> None:
    d = _base_market_data(n_trades=50)
    r = analyze(d)
    a = r["analysis"]
    alpha_e = (
        0.5 * a["whale_cluster_score"]
        + 0.3 * a["accumulation_score"]
        + 0.2 * (1.0 - a["wash_trade_score"])
    )
    risk_e = 0.6 * a["wash_trade_score"] + 0.4 * (1.0 - a["whale_cluster_score"])
    assert r["alpha_score"] == pytest.approx(np.clip(alpha_e, 0, 1))
    assert r["risk_score"] == pytest.approx(np.clip(risk_e, 0, 1))


def test_data_health_clip_range() -> None:
    d = _base_market_data(n_trades=5)
    r = analyze(d)
    assert r["data_health"] == pytest.approx(0.1)


def test_data_health_at_fifty_trades() -> None:
    d = _base_market_data(n_trades=50)
    r = analyze(d)
    assert r["data_health"] == pytest.approx(1.0)


def test_confidence_formula() -> None:
    d = _base_market_data()
    r = analyze(d)
    dh = r["data_health"]
    rs = r["risk_score"]
    assert r["confidence"] == pytest.approx(float(np.clip(dh * (1.0 - 0.3 * rs), 0, 1)))


def test_half_life_ms_15000() -> None:
    r = analyze(_base_market_data())
    assert r["half_life_ms"] == 15000


def test_phase_module_fields() -> None:
    r = analyze(_base_market_data())
    assert r["phase"] == 42
    assert r["module"] == "whale_behavior_engine"


def test_force_halt() -> None:
    d = _base_market_data()
    d["force_halt"] = True
    r = analyze(d)
    assert r["trade_permission"] == "HALT"
    assert r["reason"] == "force_halt"


def test_analysis_nested_required_keys() -> None:
    r = analyze(_base_market_data())
    a = r["analysis"]
    for k in (
        "whale_cluster_score",
        "wash_trade_score",
        "wyckoff_signal",
        "accumulation_score",
        "whale_direction",
        "whale_ratio",
    ):
        assert k in a


def test_wyckoff_accumulation_signal() -> None:
    ph = [110.0, 108.0, 105.0, 102.0, 99.0]
    vh = [1e6, 1.02e6, 1.05e6, 1.08e6, 1.12e6]
    sig, acc = compute_wyckoff(ph, vh, 0.8, 0.9)
    assert sig == "ACCUMULATION"
    assert 0.0 <= acc <= 1.0


def test_wyckoff_distribution_signal() -> None:
    ph = [90.0, 93.0, 96.0, 99.0, 103.0]
    vh = [1e6, 1.03e6, 1.06e6, 1.09e6, 1.15e6]
    sig, acc = compute_wyckoff(ph, vh, -0.85, 0.07)
    assert sig == "DISTRIBUTION"
    assert acc <= 1.0


def test_all_scores_unit_interval() -> None:
    r = analyze(_base_market_data())
    for k in ("alpha_score", "risk_score", "confidence", "data_health"):
        assert 0.0 <= r[k] <= 1.0


def test_event_ts_reasonable() -> None:
    r = analyze(_base_market_data())
    assert r["event_ts"] > 1e12


def test_validate_ok() -> None:
    ok, err = validate_market_data(_base_market_data())
    assert ok and err == ""


def test_compute_whale_empty_trades() -> None:
    wr, wd, wcs, bw, sw = compute_whale_metrics([], 50_000.0)
    assert wr == 0 and wcs == 0.5 and bw == 0 and sw == 0


def test_wash_clean_different_prices_low_score() -> None:
    trades = [_trade(5000.0, 100.0 + i * 2.0, "buy", float(i)) for i in range(30)]
    wratio, wts = compute_wash_trade_score(trades)
    assert wratio == 0.0
    assert wts == 0.0


def test_constants_exported() -> None:
    assert wb_mod._WASH_BLOCK == 0.70
    assert wb_mod._WASH_RATIO_CAP == 0.3


def test_whale_direction_zero_when_no_whale_volume_split() -> None:
    trades = [_trade(1000.0, 100.0, "buy", float(i)) for i in range(20)]
    _, wd, wcs, _, _ = compute_whale_metrics(trades, 500_000.0)
    assert wd == pytest.approx(0.0)
    assert wcs == pytest.approx(0.5)


def test_score_type_alpha_when_allow() -> None:
    r = analyze(_base_market_data())
    if r["trade_permission"] == "ALLOW":
        assert r["data_health"] >= 0.42
        assert r["score_type"] == "ALPHA"


def test_rounded_price_groups_wash() -> None:
    px = 100.12345678
    t = [
        _trade(1e5, px, "buy", 1.0),
        _trade(1e5, px + 1e-9, "sell", 2.0),
    ]
    wr, wts = compute_wash_trade_score(t)
    assert wr == 1.0
    assert wts > 0.9


def test_analyze_reason_allow_path() -> None:
    r = analyze(_base_market_data())
    if r["trade_permission"] == "ALLOW":
        assert r["reason"] == "conditions_normal"


def test_neutral_wyckoff_flat_price() -> None:
    ph = [100.0, 100.0, 100.0]
    vh = [1e6, 1e6, 1e6]
    sig, acc = compute_wyckoff(ph, vh, 0.0, 0.5)
    assert sig == "NEUTRAL"
    assert 0.0 <= acc <= 1.0


def test_trades_not_dict_invalid() -> None:
    d = _base_market_data()
    d["trades"] = [1, 2, 3]
    r = analyze(d)
    assert r["trade_permission"] == "BLOCK"
