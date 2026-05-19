"""Mutation targets — risk_ontology / risk_manager (mutmut >=80%)."""

from __future__ import annotations

import time

import pytest
from super_otonom.config import RISK
from super_otonom.risk.risk_engine import RiskEngine
from super_otonom.risk_manager import RiskManager
from super_otonom.risk_ontology import (
    _SOD_RESET_SECONDS,
    _SOW_RESET_SECONDS,
    RiskOntology,
)

pytestmark = pytest.mark.fastrun


def _fill_pnl(onto: RiskOntology, n: int = 120) -> None:
    for i in range(n):
        onto.update(nav=10_000.0, realized_pnl_delta=float(-15 + (i % 11)))


# ── RiskOntology ─────────────────────────────────────────────────────────────


def test_ontology_post_init_nav() -> None:
    onto = RiskOntology(initial_nav=5_000.0)
    assert onto.nav == 5_000.0
    assert onto.sod_nav == 5_000.0
    assert onto.peak_nav == 5_000.0


def test_ontology_var_updates_on_pnl_delta() -> None:
    onto = RiskOntology(nav=10_000.0)
    assert onto.var_1d == 0.0
    _fill_pnl(onto, 120)
    assert onto.var_1d != 0.0
    assert onto.var_1d == onto._calc_var()


def test_ontology_no_var_recalc_without_pnl_delta() -> None:
    onto = RiskOntology(nav=10_000.0)
    onto.update(nav=9_900.0, realized_pnl_delta=0.0)
    assert onto.var_1d == 0.0


def test_ontology_calc_var_confidence_99() -> None:
    onto = RiskOntology(nav=10_000.0)
    _fill_pnl(onto, 120)
    v99 = onto._calc_var(confidence=0.99)
    v95 = onto._calc_var(confidence=0.95)
    assert v99 <= v95


def test_ontology_calc_var_min_obs() -> None:
    onto = RiskOntology(nav=10_000.0)
    onto._pnl_history = [float(i) for i in range(99)]
    assert onto._calc_var() == 0.0


def test_ontology_dynamic_limit_from_vol() -> None:
    onto = RiskOntology(nav=10_000.0)
    onto.update(nav=10_000.0, current_vol=0.02)
    assert onto.dynamic_daily_limit == pytest.approx(0.04, abs=0.001)
    onto.update(nav=10_000.0, current_vol=0.10)
    assert onto.dynamic_daily_limit == 0.05
    onto.update(nav=10_000.0, current_vol=0.005)
    assert onto.dynamic_daily_limit == 0.02


def test_ontology_vol_history_trim() -> None:
    onto = RiskOntology(nav=10_000.0)
    for _ in range(250):
        onto.update(nav=10_000.0, current_vol=0.01)
    assert len(onto._vol_history) == 200


def test_ontology_pnl_history_trim() -> None:
    onto = RiskOntology(nav=10_000.0)
    for i in range(520):
        onto.update(nav=10_000.0, realized_pnl_delta=float(i))
    assert len(onto._pnl_history) == 500


def test_ontology_exposure_from_positions() -> None:
    onto = RiskOntology(nav=10_000.0)
    onto.update(
        nav=10_000.0,
        positions={"BTC": {"qty": 2.0, "entry": 1000.0}, "ETH": {"qty": 1.0, "entry": 500.0}},
    )
    assert onto.gross_exp == 2500.0
    assert onto.net_exp == 2500.0
    assert onto.exp_pct == pytest.approx(0.25)


def test_ontology_daily_weekly_loss_pct() -> None:
    onto = RiskOntology(nav=10_000.0)
    onto.update(nav=9_000.0)
    assert onto.daily_loss_pct == pytest.approx(0.1)
    onto.sow_nav = 10_000.0
    onto.nav = 9_000.0
    onto.weekly_loss_pct = max(0.0, (onto.sow_nav - onto.nav) / onto.sow_nav)
    assert onto.weekly_loss_pct == pytest.approx(0.1)


def test_ontology_peak_and_drawdown() -> None:
    onto = RiskOntology(nav=10_000.0)
    onto.update(nav=11_000.0)
    assert onto.peak_nav == 11_000.0
    onto.update(nav=9_900.0)
    assert onto.intraday_dd_pct == pytest.approx((11_000.0 - 9_900.0) / 11_000.0)


def test_ontology_daily_limit_breach() -> None:
    onto = RiskOntology(nav=10_000.0)
    onto.dynamic_daily_limit = 0.05
    onto.daily_loss_pct = 0.06
    assert onto.is_daily_limit_breached() is True
    onto.daily_loss_pct = 0.04
    assert onto.is_daily_limit_breached() is False


def test_ontology_weekly_drawdown_exposure_breach() -> None:
    onto = RiskOntology(nav=10_000.0)
    onto.weekly_loss_pct = 0.20
    assert onto.is_weekly_limit_breached(max_weekly_pct=0.10) is True
    onto.intraday_dd_pct = 0.30
    assert onto.is_drawdown_breached(max_dd=0.15) is True
    onto.exp_pct = 0.96
    assert onto.is_exposure_breached(max_exp_pct=0.95) is True


def test_ontology_snapshot_roundtrip() -> None:
    onto = RiskOntology(nav=10_000.0)
    _fill_pnl(onto, 120)
    snap = onto.snapshot()
    assert snap["nav"] == round(onto.nav, 2)
    assert snap["var_1d"] == onto.var_1d
    assert "daily_loss_pct" in snap


def test_ontology_to_dict_from_dict() -> None:
    onto = RiskOntology(nav=10_000.0)
    onto.nav = 10_500.0
    onto.var_1d = 42.0
    onto._pnl_history = [1.0, -2.0, 3.0]
    state = onto.to_dict()
    restored = RiskOntology.from_dict(state)
    assert restored.nav == pytest.approx(10_500.0)
    assert restored._pnl_history == [1.0, -2.0, 3.0]


def test_ontology_day_reset() -> None:
    onto = RiskOntology(nav=10_000.0)
    onto.nav = 9_500.0
    onto._day_start = time.time() - _SOD_RESET_SECONDS - 1
    onto._maybe_reset_day()
    assert onto.sod_nav == 9_500.0


def test_ontology_week_reset() -> None:
    onto = RiskOntology(nav=10_000.0)
    onto.nav = 9_800.0
    onto._week_start = time.time() - _SOW_RESET_SECONDS - 1
    onto._maybe_reset_week()
    assert onto.sow_nav == 9_800.0


def test_ontology_update_resets_sod_sow_after_elapsed() -> None:
    onto = RiskOntology(nav=10_000.0)
    onto._day_start = time.time() - _SOD_RESET_SECONDS - 10
    onto._week_start = time.time() - _SOW_RESET_SECONDS - 10
    onto.update(nav=10_500.0)
    assert onto.sod_nav == pytest.approx(10_500.0)
    assert onto.sow_nav == pytest.approx(10_500.0)


# ── RiskManager ──────────────────────────────────────────────────────────────


def test_risk_manager_record_pnl_syncs_onto() -> None:
    onto = RiskOntology(nav=10_000.0)
    rm = RiskManager(initial_capital=10_000.0)
    rm.set_ontology(onto)
    for i in range(120):
        rm.record_pnl(float(-5 + (i % 7)))
    assert len(rm._onto._pnl_history) >= 100
    assert rm.calculate_var() == onto._calc_var()


def test_risk_manager_record_pnl_loss_accumulation() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm.record_pnl(-100.0)
    rm.record_pnl(-50.0)
    assert rm.daily_loss == pytest.approx(150.0)
    assert rm.weekly_loss == pytest.approx(150.0)
    rm.record_pnl(200.0)
    assert rm.daily_loss == pytest.approx(150.0)


def test_risk_manager_pnl_history_trim() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    for i in range(520):
        rm.record_pnl(float(i))
    assert len(rm._pnl_history) == 500


def test_risk_manager_calculate_var_matches_engine() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    for i in range(120):
        rm.record_pnl(float(-20 + (i % 13)))
    conf = float(RISK["var_confidence"])
    assert rm.calculate_var() == RiskEngine().compute_from_pnl_history(
        rm._pnl_history, confidence=conf, min_obs=100
    )


def test_risk_manager_trailing_stop_logic() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    pct = float(RISK["trailing_stop_pct"])
    assert rm.should_trailing_stop(entry=100.0, current=110.0, peak=120.0) is True
    assert rm.should_trailing_stop(entry=100.0, current=100.0, peak=100.0) is False
    dd = (120.0 - 110.0) / 120.0
    assert rm.should_trailing_stop(entry=100.0, current=110.0, peak=120.0) == (dd >= pct)


def test_risk_manager_update_peak() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm.update_peak(10_500.0)
    assert rm._peak_equity == 10_500.0
    rm.update_peak(10_200.0)
    assert rm._peak_equity == 10_500.0


def test_risk_manager_volatility_spike() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    for v in [0.01, 0.011, 0.012, 0.01, 0.011, 0.012, 0.01, 0.011, 0.012, 0.01]:
        rm.record_volatility(v)
    assert rm.check_volatility_spike(0.05) is False
    assert rm.check_volatility_spike(0.011) is True


def test_risk_manager_check_dynamic_risk() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm.daily_loss = 0.0
    assert rm.check_dynamic_risk(10_000.0, 0.01) is True
    rm.daily_loss = 500.0
    assert rm.check_dynamic_risk(9_500.0, 0.01) is False


def test_risk_manager_reset_emergency() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm.emergency_stop = True
    rm.emergency_reason = "test"
    rm.reset_emergency()
    assert rm.emergency_stop is False
    assert rm.emergency_reason is None


def test_risk_manager_status_dict_with_onto() -> None:
    onto = RiskOntology(nav=10_000.0)
    rm = RiskManager(initial_capital=10_000.0)
    rm.set_ontology(onto)
    onto.nav = 9_800.0
    d = rm.status_dict()
    assert d["onto_active"] is True
    assert d["nav"] == pytest.approx(9_800.0)
    assert "var_1d" in d


def test_risk_manager_status_dict_without_onto() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    d = rm.status_dict()
    assert d["onto_active"] is False
    assert "var_95" in d
