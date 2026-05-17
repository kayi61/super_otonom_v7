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


def test_ontology_var_updates_on_pnl_delta() -> None:
    onto = RiskOntology(nav=10_000.0)
    assert onto.var_1d == 0.0
    _fill_pnl(onto, 120)
    assert onto.var_1d != 0.0
    assert onto.var_1d == onto._calc_var()


def test_ontology_calc_var_confidence_99() -> None:
    onto = RiskOntology(nav=10_000.0)
    _fill_pnl(onto, 120)
    v99 = onto._calc_var(confidence=0.99)
    v95 = onto._calc_var(confidence=0.95)
    assert v99 <= v95


def test_ontology_dynamic_limit_from_vol() -> None:
    onto = RiskOntology(nav=10_000.0)
    onto.update(nav=10_000.0, current_vol=0.02)
    assert 0.02 <= onto.dynamic_daily_limit <= 0.05
    onto.update(nav=10_000.0, current_vol=0.10)
    assert onto.dynamic_daily_limit == 0.05


def test_ontology_exposure_from_positions() -> None:
    onto = RiskOntology(nav=10_000.0)
    onto.update(
        nav=10_000.0,
        positions={"BTC": {"qty": 2.0, "entry": 1000.0}, "ETH": {"qty": 1.0, "entry": 500.0}},
    )
    assert onto.gross_exp == 2500.0
    assert onto.exp_pct == pytest.approx(0.25)


def test_ontology_daily_limit_breach() -> None:
    onto = RiskOntology(nav=10_000.0)
    onto.dynamic_daily_limit = 0.05
    onto.daily_loss_pct = 0.06
    assert onto.is_daily_limit_breached() is True
    onto.daily_loss_pct = 0.04
    assert onto.is_daily_limit_breached() is False


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


def test_risk_manager_record_pnl_syncs_onto() -> None:
    onto = RiskOntology(nav=10_000.0)
    rm = RiskManager(initial_capital=10_000.0)
    rm.set_ontology(onto)
    for i in range(120):
        rm.record_pnl(float(-5 + (i % 7)))
    assert len(rm._onto._pnl_history) >= 100
    assert rm.calculate_var() == onto._calc_var()


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
    assert rm.should_trailing_stop(entry=100.0, current=110.0, peak=120.0) is True
    assert rm.should_trailing_stop(entry=100.0, current=100.0, peak=100.0) is False

