"""risk_manager.py — mutmut kill-rate (>=80%). Sınır ve dallanma testleri."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from super_otonom.config import RISK
from super_otonom.risk.risk_engine import RiskEngine
from super_otonom.risk_manager import RiskManager
from super_otonom.risk_ontology import RiskOntology

pytestmark = pytest.mark.fastrun

_DAY_SEC = 86_400
_WEEK_SEC = 604_800


# ── OMEGA / init ──────────────────────────────────────────────────────────────


def test_omega_tighten_on_loss_and_relax_on_profit() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm.record_omega_trade_outcome(-10.0)
    assert rm._omega_qmin_tighten == 2
    rm.record_omega_trade_outcome(5.0)
    assert rm._omega_qmin_tighten == 1
    rm.record_omega_trade_outcome(0.0)
    assert rm._omega_qmin_tighten == 0


def test_omega_tighten_caps_at_25() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    for _ in range(20):
        rm.record_omega_trade_outcome(-1.0)
    assert rm._omega_qmin_tighten == 25


def test_get_omega_effective_qmin_clamped() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm._omega_qmin_tighten = 10
    assert rm.get_omega_effective_qmin(50) == 60
    rm._omega_qmin_tighten = 100
    assert rm.get_omega_effective_qmin(95) == 90
    rm._omega_qmin_tighten = 0
    assert rm.get_omega_effective_qmin(-5) == 0


# ── emergency / deny ──────────────────────────────────────────────────────────


def test_trigger_emergency_latches_reason() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm.trigger_emergency("first")
    rm.trigger_emergency("second")
    assert rm.emergency_reason == "first"
    assert rm.emergency_stop is True


def test_check_risk_blocked_when_emergency_latched() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm.emergency_stop = True
    rm.emergency_reason = "latched"
    assert rm.check_risk(10_000.0) is False
    assert rm.get_last_deny() == "latched"


def test_get_last_deny_empty_when_none() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    assert rm.get_last_deny() == ""


def test_reset_emergency_clears_flags() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm.trigger_emergency("x")
    rm.reset_emergency()
    assert rm.emergency_stop is False
    assert rm.emergency_reason is None


# ── zamanlayıcı ───────────────────────────────────────────────────────────────


def test_maybe_reset_day_at_literal_86400(monkeypatch: pytest.MonkeyPatch) -> None:
    t0 = 10_000.0
    rm = RiskManager(initial_capital=10_000.0)
    rm.daily_loss = 500.0
    rm._day_start = t0
    monkeypatch.setattr(time, "time", lambda: t0 + _DAY_SEC)
    rm._maybe_reset()
    assert rm.daily_loss == 0.0


def test_maybe_reset_week_at_literal_604800(monkeypatch: pytest.MonkeyPatch) -> None:
    t0 = 20_000.0
    rm = RiskManager(initial_capital=10_000.0)
    rm.weekly_loss = 300.0
    rm._week_start = t0
    monkeypatch.setattr(time, "time", lambda: t0 + _WEEK_SEC)
    rm._maybe_reset()
    assert rm.weekly_loss == 0.0


def test_maybe_reset_not_before_day_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    t0 = 30_000.0
    rm = RiskManager(initial_capital=10_000.0)
    rm.daily_loss = 100.0
    rm._day_start = t0
    monkeypatch.setattr(time, "time", lambda: t0 + _DAY_SEC - 1)
    rm._maybe_reset()
    assert rm.daily_loss == 100.0


# ── record_pnl / peak / vol ───────────────────────────────────────────────────


def test_record_pnl_positive_does_not_add_loss() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm.record_pnl(50.0)
    assert rm.daily_loss == 0.0
    assert rm.weekly_loss == 0.0


def test_record_pnl_negative_accumulates() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm.record_pnl(-40.0)
    rm.record_pnl(-10.0)
    assert rm.daily_loss == pytest.approx(50.0)
    assert rm.weekly_loss == pytest.approx(50.0)


def test_record_pnl_trim_at_501() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    for i in range(501):
        rm.record_pnl(float(i))
    assert len(rm._pnl_history) == 500
    assert rm._pnl_history[0] == pytest.approx(1.0)


def test_update_peak_strict_gt() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm.update_peak(10_500.0)
    rm.update_peak(10_500.0)
    assert rm._peak_equity == 10_500.0


def test_vol_history_trim_at_201() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    for i in range(201):
        rm.record_volatility(0.01 + i * 1e-6)
    assert len(rm._vol_history) == 200


def test_vol_spike_short_history_returns_true() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    assert rm.check_volatility_spike(0.5, history_vols=[0.01] * 5) is True


def test_vol_spike_zero_avg_returns_true() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    assert rm.check_volatility_spike(0.1, history_vols=[0.0] * 12) is True


def test_vol_spike_triggers_false() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    hist = [0.01] * 12
    assert rm.check_volatility_spike(0.05, history_vols=hist, spike_multiplier=2.0) is False


# ── check_dynamic_risk ───────────────────────────────────────────────────────


def test_check_dynamic_risk_invalid_capital() -> None:
    rm = RiskManager(initial_capital=0.0)
    assert rm.check_dynamic_risk(10_000.0, 0.02) is False


@pytest.mark.parametrize(
    "vol, expected_limit",
    [(0.001, 0.02), (0.015, 0.03), (0.04, 0.05)],
)
def test_check_dynamic_risk_limit_clamp(vol: float, expected_limit: float) -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm.daily_loss = 0.0
    assert rm.check_dynamic_risk(10_000.0, vol) is True
    assert rm._last_dynamic_limit == pytest.approx(expected_limit)


def test_check_dynamic_risk_breach_triggers_emergency() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm.daily_loss = 600.0
    assert rm.check_dynamic_risk(10_000.0, 0.01) is False
    assert rm.emergency_stop is True
    assert rm.emergency_reason == "dynamic_daily_loss"


def test_check_dynamic_risk_uses_current_equity_base() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm.daily_loss = 400.0
    assert rm.check_dynamic_risk(20_000.0, 0.02) is True


# ── check_risk + ontology ─────────────────────────────────────────────────────


def test_warn_if_onto_missing_only_once() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm.check_risk(10_000.0)
    assert rm._onto_warned is True
    rm.check_risk(10_000.0)
    assert rm._onto_warned is True


def test_check_risk_with_onto_daily_breach() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    rm = RiskManager(initial_capital=10_000.0)
    rm.set_ontology(onto)
    onto.daily_loss_pct = 0.10
    onto.dynamic_daily_limit = 0.05
    assert rm.check_risk(10_000.0) is False
    assert rm.get_last_deny() == "dynamic_daily_loss"


def test_check_risk_with_onto_weekly_breach() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    rm = RiskManager(initial_capital=10_000.0)
    rm.set_ontology(onto)
    onto.weekly_loss_pct = 0.20
    onto.dynamic_daily_limit = 1.0
    assert rm.check_risk(10_000.0) is False
    assert rm.get_last_deny() == "weekly_loss"


def test_check_risk_with_onto_drawdown_breach() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    rm = RiskManager(initial_capital=10_000.0)
    rm.set_ontology(onto)
    onto.intraday_dd_pct = 0.30
    onto.dynamic_daily_limit = 1.0
    onto.weekly_loss_pct = 0.0
    assert rm.check_risk(10_000.0) is False
    assert rm.get_last_deny() == "max_drawdown"


def test_check_risk_without_onto_static_daily() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm.daily_loss = RISK["max_daily_loss_pct"] * 10_000.0 + 100.0
    assert rm.check_risk(10_000.0, current_vol=0.0) is False
    assert rm.get_last_deny() == "static_daily_loss"


def test_check_risk_without_onto_weekly() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm.weekly_loss = RISK["max_weekly_loss_pct"] * 10_000.0 + 50.0
    assert rm.check_risk(10_000.0, current_vol=0.0) is False
    assert rm.get_last_deny() == "weekly_loss"


def test_check_risk_without_onto_drawdown() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm._peak_equity = 20_000.0
    eq = 20_000.0 * (1.0 - RISK["max_total_drawdown"] - 0.05)
    assert rm.check_risk(eq, current_vol=0.0) is False
    assert rm.get_last_deny() == "max_drawdown"


def test_check_risk_exposure_breach() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    exp = 10_000.0 * RISK["max_exposure_pct"] * 1.1
    assert rm.check_risk(10_000.0, open_exposure=exp, current_vol=0.0) is False
    assert rm.get_last_deny() == "max_exposure"


def test_check_risk_ok_clean() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    assert rm.check_risk(10_000.0, open_exposure=0.0, current_vol=0.0) is True
    assert rm.get_last_deny() == ""


# ── VaR / trailing / status ───────────────────────────────────────────────────


def test_calculate_var_delegates_to_onto() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    for i in range(120):
        onto._pnl_history.append(float(-5 + (i % 7)))
    rm = RiskManager(initial_capital=10_000.0)
    rm.set_ontology(onto)
    with patch.object(type(onto), "_calc_var", return_value=99.0) as mock_var:
        assert rm.calculate_var() == 99.0
        mock_var.assert_called_once()


def test_calculate_var_without_onto_uses_engine() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    for i in range(120):
        rm.record_pnl(float(-10 + (i % 5)))
    expected = RiskEngine().compute_from_pnl_history(
        rm._pnl_history, confidence=float(RISK["var_confidence"]), min_obs=100
    )
    assert rm.calculate_var() == expected


def test_trailing_stop_peak_not_above_entry() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    assert rm.should_trailing_stop(100.0, 95.0, 100.0) is False


def test_trailing_stop_at_threshold() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    peak, current = 120.0, 110.0
    dd = (peak - current) / peak
    assert rm.should_trailing_stop(100.0, current, peak) == (dd >= RISK["trailing_stop_pct"])


def test_status_dict_without_onto_keys() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    d = rm.status_dict()
    assert d["onto_active"] is False
    assert "var_95" in d
    assert "nav" not in d


def test_status_dict_with_onto_overrides() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    onto.nav = 9_500.0
    onto.var_1d = 12.5
    rm = RiskManager(initial_capital=10_000.0)
    rm.set_ontology(onto)
    d = rm.status_dict()
    assert d["onto_active"] is True
    assert d["nav"] == pytest.approx(9_500.0)
    assert d["var_1d"] == 12.5


def test_record_pnl_syncs_onto_var() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    rm = RiskManager(initial_capital=10_000.0)
    rm.set_ontology(onto)
    with patch.object(type(onto), "_calc_var", return_value=55.0) as mock_var:
        rm.record_pnl(-1.0)
        mock_var.assert_called()
        assert onto.var_1d == 55.0
