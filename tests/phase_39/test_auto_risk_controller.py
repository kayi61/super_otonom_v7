"""Faz 39 — auto_risk_controller birim testleri."""

from __future__ import annotations

import numpy as np
import pytest
from phases.phase_39 import auto_risk_controller as arc_mod
from phases.phase_39.auto_risk_controller import (
    analyze,
    compute_drawdown,
    compute_kelly,
    count_consecutive_losses,
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


def _base(**kw: object) -> dict:
    return {
        "equity_curve": kw.get("equity_curve", [1000.0 + i * 10 for i in range(120)]),
        "recent_trades": kw.get("recent_trades", [{"pnl": 10.0}, {"pnl": -5.0}]),
        "win_rate": float(kw.get("win_rate", 0.55)),
        "avg_win": float(kw.get("avg_win", 100.0)),
        "avg_loss": float(kw.get("avg_loss", 80.0)),
        "max_drawdown_pct": float(kw.get("max_drawdown_pct", 0.25)),
        "consecutive_loss_limit": int(kw.get("consecutive_loss_limit", 5)),
    }


def test_analyze_none_blocked() -> None:
    r = analyze(None)
    assert r["trade_permission"] == "BLOCK"
    assert r["data_health"] == 0.0
    assert r["score_type"] == "QUALITY"
    assert _schema() <= set(r.keys())


def test_empty_equity_curve() -> None:
    r = analyze({**_base(), "equity_curve": []})
    assert r["trade_permission"] == "BLOCK"


def test_missing_required_field() -> None:
    d = _base()
    del d["win_rate"]
    r = analyze(d)
    assert r["trade_permission"] == "BLOCK"


def test_win_rate_out_of_range() -> None:
    r = analyze(_base(win_rate=1.5))
    assert r["trade_permission"] == "BLOCK"


def test_max_drawdown_pct_out_of_range() -> None:
    r = analyze(_base(max_drawdown_pct=1.5))
    assert r["trade_permission"] == "BLOCK"


def test_consecutive_loss_limit_invalid() -> None:
    r = analyze(_base(consecutive_loss_limit=0))
    assert r["trade_permission"] == "BLOCK"


def test_kelly_half_formula() -> None:
    k, h = compute_kelly(0.55, 100.0, 80.0)
    assert h == pytest.approx(k * 0.5)
    assert 0.0 <= k <= 0.25


def test_kelly_capped_at_quarter() -> None:
    k, _ = compute_kelly(0.99, 10_000.0, 1.0)
    assert k == pytest.approx(0.25)


def test_kelly_zero_when_unfavorable() -> None:
    k, _ = compute_kelly(0.1, 10.0, 1000.0)
    assert k == 0.0


def test_compute_drawdown_at_peak() -> None:
    dd, peak = compute_drawdown([100.0, 110.0, 105.0])
    assert peak == pytest.approx(110.0)
    assert dd == pytest.approx((110.0 - 105.0) / 110.0)


def test_compute_drawdown_flat() -> None:
    dd, _ = compute_drawdown([50.0])
    assert dd == pytest.approx(0.0)


def test_drawdown_gate_blocks() -> None:
    ec = [1000.0, 1200.0, 900.0]
    r = analyze(
        _base(
            equity_curve=ec,
            max_drawdown_pct=0.15,
            recent_trades=[{"pnl": 1.0}],
            consecutive_loss_limit=99,
        )
    )
    peak = 1200.0
    cur = 900.0
    dd = (peak - cur) / peak
    assert dd >= 0.15
    assert r["trade_permission"] == "BLOCK"
    assert r["reason"] == "drawdown_gate"


def test_consecutive_loss_breaker_blocks() -> None:
    trades = [{"pnl": -1.0}] * 5
    r = analyze(_base(recent_trades=trades, consecutive_loss_limit=5, equity_curve=[1000.0] * 50))
    assert r["analysis"]["consecutive_losses"] == 5
    assert r["trade_permission"] == "BLOCK"
    assert r["reason"] == "consecutive_loss_breaker"


def test_drawdown_takes_precedence_over_loss() -> None:
    trades = [{"pnl": -1.0}] * 10
    ec = [1000.0, 2000.0, 1200.0]
    r = analyze(
        _base(
            equity_curve=ec,
            recent_trades=trades,
            max_drawdown_pct=0.3,
            consecutive_loss_limit=3,
        )
    )
    assert r["trade_permission"] == "BLOCK"
    assert r["reason"] == "drawdown_gate"


def test_risk_score_formula() -> None:
    ec = [1000.0] * 100
    r = analyze(
        _base(
            equity_curve=ec,
            recent_trades=[{"pnl": 1.0}],
            max_drawdown_pct=0.2,
            consecutive_loss_limit=10,
        )
    )
    a = r["analysis"]
    exp = 0.6 * a["drawdown_score"] + 0.4 * a["loss_streak_score"]
    assert r["risk_score"] == pytest.approx(np.clip(exp, 0, 1))


def test_alpha_is_double_kelly() -> None:
    r = analyze(_base())
    k = r["analysis"]["kelly_fraction"]
    assert r["alpha_score"] == pytest.approx(min(1.0, max(0.0, k * 2.0)))


def test_data_health_clip() -> None:
    r = analyze(_base(equity_curve=[1000.0] * 50))
    assert r["data_health"] == pytest.approx(np.clip(50 / 100.0, 0.1, 1.0))


def test_confidence_formula() -> None:
    r = analyze(_base())
    dh = r["data_health"]
    rs = r["risk_score"]
    assert r["confidence"] == pytest.approx(float(np.clip(dh * (1.0 - 0.5 * rs), 0, 1)))


def test_half_life_10000() -> None:
    assert analyze(_base())["half_life_ms"] == 10000


def test_count_consecutive_losses_sequence() -> None:
    assert count_consecutive_losses([{"pnl": -1}, {"pnl": -2}, {"pnl": 5}, {"pnl": -3}]) == 1


def test_count_consecutive_empty_trades() -> None:
    assert count_consecutive_losses([]) == 0


def test_count_stops_at_non_negative() -> None:
    assert count_consecutive_losses([{"pnl": -1}, {"pnl": 0.0}, {"pnl": 5.0}]) == 0


def test_non_dict_trade_breaks_chain() -> None:
    assert count_consecutive_losses([{"pnl": -1}, "bad", {"pnl": -1}]) == 1


def test_analysis_required_keys() -> None:
    r = analyze(_base())
    a = r["analysis"]
    for k in (
        "kelly_fraction",
        "half_kelly",
        "current_drawdown",
        "drawdown_breach",
        "consecutive_losses",
        "drawdown_score",
        "loss_streak_score",
    ):
        assert k in a


def test_validate_ok() -> None:
    ok, err = validate_market_data(_base())
    assert ok and err == ""


def test_avg_loss_uses_abs_in_kelly() -> None:
    k_pos, _ = compute_kelly(0.6, 100.0, 50.0)
    k_neg, _ = compute_kelly(0.6, 100.0, -50.0)
    assert k_pos == pytest.approx(k_neg)


def test_allow_when_safe() -> None:
    ec = [10000.0 + i for i in range(100)]
    tr = [{"pnl": 10.0}] * 3
    r = analyze(
        _base(equity_curve=ec, recent_trades=tr, max_drawdown_pct=0.5, consecutive_loss_limit=10)
    )
    assert r["analysis"]["drawdown_breach"] is False
    assert r["analysis"]["consecutive_losses"] == 0
    assert r["trade_permission"] == "ALLOW"


def test_loss_one_below_limit_allow() -> None:
    tr = [{"pnl": -1.0}] * 4
    r = analyze(_base(recent_trades=tr, consecutive_loss_limit=5, equity_curve=[1000.0] * 100))
    assert r["analysis"]["consecutive_losses"] == 4
    assert r["trade_permission"] == "ALLOW"


def test_drawdown_exactly_at_threshold_breaches() -> None:
    ec = [100.0, 200.0, 170.0]
    dd = (200.0 - 170.0) / 200.0
    r = analyze(
        _base(
            equity_curve=ec,
            max_drawdown_pct=dd,
            recent_trades=[{"pnl": 1.0}],
            consecutive_loss_limit=99,
        )
    )
    assert r["analysis"]["drawdown_breach"] is True


def test_constants() -> None:
    assert arc_mod._HALF_LIFE_MS == 10000
    assert arc_mod._KELLY_CAP == 0.25


def test_phase_module_fields() -> None:
    r = analyze(_base())
    assert r["phase"] == 39
    assert r["module"] == "auto_risk_controller"


def test_all_top_scores_unit_interval() -> None:
    r = analyze(_base())
    for k in ("alpha_score", "risk_score", "confidence", "data_health"):
        assert 0.0 <= r[k] <= 1.0


def test_event_ts_positive() -> None:
    r = analyze(_base())
    assert r["event_ts"] > 1e12


def test_loss_streak_score_one_at_limit() -> None:
    tr = [{"pnl": -1.0}] * 5
    r = analyze(_base(recent_trades=tr, consecutive_loss_limit=5, equity_curve=[500.0] * 100))
    assert r["analysis"]["loss_streak_score"] == pytest.approx(1.0)


def test_drawdown_score_normalized() -> None:
    ec = [100.0, 200.0, 150.0]
    mdd = 0.25
    r = analyze(
        _base(
            equity_curve=ec,
            max_drawdown_pct=mdd,
            recent_trades=[{"pnl": 1.0}],
            consecutive_loss_limit=99,
        )
    )
    dd = r["analysis"]["current_drawdown"]
    assert r["analysis"]["drawdown_score"] == pytest.approx(np.clip(dd / mdd, 0, 1))


def test_recent_trades_not_list_invalid() -> None:
    d = _base()
    d["recent_trades"] = "nope"
    assert analyze(d)["trade_permission"] == "BLOCK"


def test_equity_must_be_numeric_sequence() -> None:
    d = _base()
    d["equity_curve"] = ["x"]
    r = analyze(d)
    assert r["trade_permission"] == "BLOCK"


def test_high_win_rate_raises_kelly() -> None:
    k_low, _ = compute_kelly(0.52, 100.0, 100.0)
    k_high, _ = compute_kelly(0.65, 100.0, 100.0)
    assert k_high >= k_low


def test_halving_kelly_half_vs_full() -> None:
    k, h = compute_kelly(0.6, 200.0, 100.0)
    assert h == pytest.approx(k / 2.0)


def test_single_trade_loss_only() -> None:
    assert count_consecutive_losses([{"pnl": -50.0}]) == 1


def test_schema_reason_on_invalid() -> None:
    r = analyze({"equity_curve": [1.0]})
    assert r["reason"] != ""
