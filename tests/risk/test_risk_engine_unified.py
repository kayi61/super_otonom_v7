"""VR-01 — unified RiskEngine regression vs legacy paths."""

from __future__ import annotations

import numpy as np
import pytest
from super_otonom.risk.config import RiskConfig
from super_otonom.risk.risk_engine import RiskEngine
from super_otonom.risk_manager import RiskManager
from super_otonom.risk_ontology import RiskOntology

pytestmark = pytest.mark.fastrun


def test_pnl_var_matches_legacy_percentile() -> None:
    rng = np.random.default_rng(42)
    pnl = (rng.normal(-5.0, 20.0, 120)).tolist()
    engine = RiskEngine(RiskConfig(var_history_min_obs=100))
    legacy = float(np.percentile(pnl, 5.0))
    assert engine.compute_from_pnl_history(pnl, confidence=0.95, min_obs=100) == round(legacy, 2)


def test_risk_ontology_uses_engine() -> None:
    onto = RiskOntology(nav=10_000.0)
    for x in range(1, 121):
        onto.update(nav=10_000.0, realized_pnl_delta=float(-10 + (x % 7)))
    assert onto.var_1d != 0.0
    assert onto.var_1d == RiskEngine().compute_from_pnl_history(
        onto._pnl_history, confidence=0.95, min_obs=100
    )


def test_risk_manager_calculate_var_with_ontology() -> None:
    onto = RiskOntology(nav=10_000.0)
    for x in range(1, 121):
        onto.update(nav=10_000.0, realized_pnl_delta=float(-8 + (x % 5)))
    rm = RiskManager(initial_capital=10_000.0)
    rm._onto = onto
    assert rm.calculate_var() == onto._calc_var()


def test_engine_three_models_and_dispersion() -> None:
    rng = np.random.default_rng(7)
    ret = (rng.normal(0.0, 0.02, 80)).tolist()
    m = RiskEngine().compute(ret)
    assert m.var_historical_95 > 0
    assert m.var_parametric_95 > 0
    assert m.var_monte_carlo_95 > 0
    assert m.var_for_limits_95 == max(
        m.var_historical_95, m.var_parametric_95, m.var_monte_carlo_95
    )
    assert m.cvar_95_1d >= m.var_historical_95


def test_portfolio_wrappers_delegate() -> None:
    from super_otonom.portfolio_risk_engine import (
        cvar_expected_shortfall,
        var_historical,
        var_monte_carlo,
        var_parametric,
    )

    ret = [-0.02, 0.01, -0.03, 0.005, -0.01, 0.02, -0.015] * 5
    assert var_parametric(ret) > 0
    assert var_historical(ret) > 0
    assert var_monte_carlo(ret) > 0
    assert cvar_expected_shortfall(ret) >= var_historical(ret)
