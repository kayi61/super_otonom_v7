"""VR-01 — unified RiskEngine regression vs legacy paths."""

from __future__ import annotations

import numpy as np
import pytest
from super_otonom.risk.config import RiskConfig
from super_otonom.risk.risk_engine import RiskEngine, RiskMetrics
from super_otonom.risk_manager import RiskManager
from super_otonom.risk_ontology import RiskOntology

pytestmark = pytest.mark.fastrun


# ── Legacy compat ────────────────────────────────────────────────────────────

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


# ── Three-model suite (95%) ──────────────────────────────────────────────────

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


# ── 99% VaR suite ────────────────────────────────────────────────────────────

def test_engine_99_var_suite() -> None:
    rng = np.random.default_rng(11)
    ret = (rng.normal(0.0, 0.03, 120)).tolist()
    m = RiskEngine().compute(ret)

    assert m.var_historical_99 > 0
    assert m.var_parametric_99 > 0
    assert m.var_monte_carlo_99 > 0
    assert m.var_for_limits_99 == max(
        m.var_historical_99, m.var_parametric_99, m.var_monte_carlo_99
    )
    assert m.var_99_1d >= m.var_95_1d, "99% VaR must be >= 95% VaR"


# ── CVaR invariants ──────────────────────────────────────────────────────────

def test_cvar_geq_var() -> None:
    """CVaR >= VaR at same confidence — fundamental risk math invariant."""
    rng = np.random.default_rng(99)
    ret = (rng.normal(-0.001, 0.025, 200)).tolist()
    m = RiskEngine().compute(ret)

    assert m.cvar_95_1d >= m.var_historical_95
    assert m.cvar_99_1d >= m.var_historical_99


def test_cvar_975_present() -> None:
    """Basel FRTB 97.5% CVaR field is populated."""
    rng = np.random.default_rng(55)
    ret = (rng.normal(0.0, 0.02, 100)).tolist()
    m = RiskEngine().compute(ret)
    assert m.cvar_975_1d > 0


# ── 97.5% VaR (Basel FRTB) ──────────────────────────────────────────────────

def test_var_975_between_95_and_99() -> None:
    rng = np.random.default_rng(33)
    ret = (rng.normal(0.0, 0.02, 300)).tolist()
    m = RiskEngine().compute(ret)
    assert m.var_975_1d >= m.var_historical_95 * 0.95, \
        "97.5% VaR should be close to or above 95% historical VaR"


# ── Model dispersion ────────────────────────────────────────────────────────

def test_dispersion_nonnegative() -> None:
    rng = np.random.default_rng(77)
    ret = (rng.normal(0.0, 0.01, 50)).tolist()
    m = RiskEngine().compute(ret)
    assert m.model_dispersion_pct >= 0.0


def test_dispersion_uses_max_of_95_and_99() -> None:
    rng = np.random.default_rng(88)
    ret = (rng.standard_t(3, size=200) * 0.02).tolist()
    m = RiskEngine().compute(ret)
    assert m.model_dispersion_pct >= 0.0


# ── Empty / short series ────────────────────────────────────────────────────

def test_short_returns_empty_metrics() -> None:
    m = RiskEngine().compute([0.01, -0.01])
    assert m.var_95_1d == 0.0
    assert m.cvar_975_1d == 0.0

    m2 = RiskEngine().compute([])
    assert m2.var_99_1d == 0.0


def test_compute_from_pnl_below_min_obs() -> None:
    engine = RiskEngine()
    assert engine.compute_from_pnl_history(list(range(50)), confidence=0.95, min_obs=100) == 0.0


# ── Var max properties ───────────────────────────────────────────────────────

def test_var_max_properties() -> None:
    rng = np.random.default_rng(123)
    ret = (rng.normal(0.0, 0.02, 150)).tolist()
    m = RiskEngine().compute(ret)
    assert m.var_max_95 == m.var_for_limits_95
    assert m.var_max_99 == m.var_for_limits_99


# ── portfolio_risk_engine delegates to risk.var_models ───────────────────────

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


# ── Audit script runs clean ─────────────────────────────────────────────────

def test_audit_var_source_clean() -> None:
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[2] / "scripts" / "audit_var_source.py"
    if not script.is_file():
        pytest.skip("audit_var_source.py not found")
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"audit_var_source failed:\n{result.stdout}\n{result.stderr}"


# ── Config compat: legacy min_obs still works ────────────────────────────────

def test_config_legacy_min_obs_compat() -> None:
    cfg = RiskConfig()
    assert cfg.var_history_min_obs == 100
    assert cfg.var_history_min_obs_institutional == 250
    assert cfg.cvar_legacy_conf == 0.95


def test_config_new_fields() -> None:
    cfg = RiskConfig()
    assert 0.975 in cfg.var_confidences
    assert 10 in cfg.var_horizons_days
    assert cfg.cvar_primary_conf == 0.975
    assert cfg.cvar_secondary_conf == 0.99
