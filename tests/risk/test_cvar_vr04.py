"""VR-04 tests — CVaR / Expected Shortfall: historical, parametric, MC + Basel FRTB."""

from __future__ import annotations

import json
import statistics
from pathlib import Path

import numpy as np
import pytest
from scipy import stats as sp_stats
from super_otonom.risk.config import RiskConfig
from super_otonom.risk.cvar_models import (
    _DEFAULT_SHORT_FALLBACK,
    historical_cvar,
    mc_cvar,
    parametric_cvar,
)
from super_otonom.risk.risk_engine import RiskEngine, RiskMetrics
from super_otonom.risk.var_models import (
    historical_var,
    monte_carlo_var,
    parametric_var,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────

_RNG = np.random.default_rng(99999)
NORMAL_RETURNS = _RNG.normal(0.0, 0.02, size=2000).tolist()

_T5 = sp_stats.t.rvs(df=5, loc=0.0, scale=0.02, size=2000, random_state=4444)
HEAVY_RETURNS = _T5.tolist()

SHORT_RETURNS = [0.01, -0.02]
TINY_RETURNS = [0.01, -0.02, 0.005]


# ═══════════════════════════════════════════════════════════════════════════════
# §1  CVaR >= VaR invariant (CRITICAL mathematical guarantee)
# ═══════════════════════════════════════════════════════════════════════════════


class TestCVaRGeqVaR:
    """CVaR >= VaR must always hold — it's the conditional expectation beyond VaR."""

    def test_historical_cvar_geq_var_95(self) -> None:
        cvar = historical_cvar(NORMAL_RETURNS, 0.95)
        var = historical_var(NORMAL_RETURNS, 0.95)
        assert cvar >= var - 1e-9

    def test_historical_cvar_geq_var_99(self) -> None:
        cvar = historical_cvar(NORMAL_RETURNS, 0.99)
        var = historical_var(NORMAL_RETURNS, 0.99)
        assert cvar >= var - 1e-9

    def test_parametric_cvar_geq_var_normal_95(self) -> None:
        cvar = parametric_cvar(NORMAL_RETURNS, 0.95, dist="normal")
        var = parametric_var(NORMAL_RETURNS, 0.95, dist="normal")
        assert cvar >= var - 1e-9

    def test_parametric_cvar_geq_var_student_t_95(self) -> None:
        cvar = parametric_cvar(HEAVY_RETURNS, 0.95, dist="student_t")
        var = parametric_var(HEAVY_RETURNS, 0.95, dist="student_t")
        assert cvar >= var - 1e-9

    def test_parametric_cvar_geq_var_student_t_99(self) -> None:
        cvar = parametric_cvar(HEAVY_RETURNS, 0.99, dist="student_t")
        var = parametric_var(HEAVY_RETURNS, 0.99, dist="student_t")
        assert cvar >= var - 1e-9

    def test_mc_cvar_geq_mc_var_95(self) -> None:
        cvar = mc_cvar(NORMAL_RETURNS, 0.95, draws=2000, seed=42)
        var = monte_carlo_var(NORMAL_RETURNS, 0.95, draws=2000, seed=42)
        assert cvar >= var - 1e-9

    def test_mc_cvar_geq_mc_var_99(self) -> None:
        cvar = mc_cvar(NORMAL_RETURNS, 0.99, draws=5000, seed=42)
        var = monte_carlo_var(NORMAL_RETURNS, 0.99, draws=5000, seed=42)
        assert cvar >= var - 1e-9

    def test_engine_cvar_geq_var_95(self) -> None:
        """RiskEngine output: cvar_95 >= var_95."""
        m = RiskEngine().compute(NORMAL_RETURNS)
        assert m.cvar_95_1d >= m.var_95_1d - 1e-9

    def test_engine_cvar_geq_var_99(self) -> None:
        """RiskEngine output: cvar_99 >= var_99."""
        m = RiskEngine().compute(NORMAL_RETURNS)
        assert m.cvar_99_1d >= m.var_99_1d - 1e-9

    def test_engine_cvar_geq_var_975(self) -> None:
        """Basel FRTB: cvar_975 >= var_975."""
        m = RiskEngine().compute(NORMAL_RETURNS)
        assert m.cvar_975_1d >= m.var_975_1d - 1e-9


# ═══════════════════════════════════════════════════════════════════════════════
# §2  Historical CVaR (regression — unchanged from VR-01)
# ═══════════════════════════════════════════════════════════════════════════════


class TestHistoricalCVaR:
    def test_basic(self) -> None:
        v = historical_cvar(NORMAL_RETURNS, 0.95)
        assert 0.01 < v < 0.15

    def test_short_fallback(self) -> None:
        assert historical_cvar(SHORT_RETURNS, 0.95) == _DEFAULT_SHORT_FALLBACK

    def test_99_greater_than_95(self) -> None:
        cv95 = historical_cvar(NORMAL_RETURNS, 0.95)
        cv99 = historical_cvar(NORMAL_RETURNS, 0.99)
        assert cv99 >= cv95

    def test_tail_mean_correct(self) -> None:
        """CVaR = mean of worst (1-conf)*n observations."""
        ret = NORMAL_RETURNS[:100]
        xs = sorted(ret)
        tail_n = max(1, int(round(0.05 * 100)))
        expected = max(0.0, -statistics.mean(xs[:tail_n]))
        assert historical_cvar(ret, 0.95) == pytest.approx(expected, rel=1e-9)


# ═══════════════════════════════════════════════════════════════════════════════
# §3  Parametric CVaR (Student-t closed-form ES)
# ═══════════════════════════════════════════════════════════════════════════════


class TestParametricCVaR:
    def test_student_t_larger_than_gaussian(self) -> None:
        """Student-t ES > Gaussian ES for heavy-tail data."""
        cvt = parametric_cvar(HEAVY_RETURNS, 0.95, dist="student_t")
        cvn = parametric_cvar(HEAVY_RETURNS, 0.95, dist="normal")
        assert cvt > cvn

    def test_gaussian_closed_form(self) -> None:
        """Gaussian ES: -mu + sig * phi(z_alpha) / alpha."""
        ret = NORMAL_RETURNS[:500]
        mu = statistics.mean(ret)
        sig = statistics.stdev(ret)
        alpha = 0.05
        z_alpha = float(sp_stats.norm.ppf(alpha))
        phi_z = float(sp_stats.norm.pdf(z_alpha))
        expected = max(0.0, min(0.95, -mu + sig * phi_z / alpha))
        actual = parametric_cvar(ret, 0.95, dist="normal")
        assert actual == pytest.approx(expected, rel=1e-6)

    def test_student_t_explicit_df(self) -> None:
        """Lower df → larger ES (heavier tails)."""
        cv3 = parametric_cvar(NORMAL_RETURNS, 0.95, dist="student_t", df=3.0)
        cv50 = parametric_cvar(NORMAL_RETURNS, 0.95, dist="student_t", df=50.0)
        assert cv3 > cv50

    def test_99_greater_than_95(self) -> None:
        cv95 = parametric_cvar(HEAVY_RETURNS, 0.95, dist="student_t")
        cv99 = parametric_cvar(HEAVY_RETURNS, 0.99, dist="student_t")
        assert cv99 > cv95

    def test_short_fallback(self) -> None:
        assert parametric_cvar(SHORT_RETURNS, 0.95) == _DEFAULT_SHORT_FALLBACK

    def test_clamp_upper(self) -> None:
        extreme = [-0.99] * 100
        v = parametric_cvar(extreme, 0.99, dist="student_t")
        assert v <= 0.95

    def test_positive_result(self) -> None:
        v = parametric_cvar(NORMAL_RETURNS, 0.95, dist="student_t")
        assert v >= 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# §4  Monte Carlo CVaR
# ═══════════════════════════════════════════════════════════════════════════════


class TestMonteCarloCVaR:
    def test_basic(self) -> None:
        v = mc_cvar(NORMAL_RETURNS, 0.95, draws=2000, seed=42)
        assert 0.01 < v < 0.15

    def test_deterministic_seed(self) -> None:
        v1 = mc_cvar(NORMAL_RETURNS, 0.95, seed=42)
        v2 = mc_cvar(NORMAL_RETURNS, 0.95, seed=42)
        assert v1 == v2

    def test_different_seeds_differ(self) -> None:
        v1 = mc_cvar(NORMAL_RETURNS, 0.95, seed=42)
        v2 = mc_cvar(NORMAL_RETURNS, 0.95, seed=99)
        assert v1 != v2

    def test_99_greater_than_95(self) -> None:
        cv95 = mc_cvar(NORMAL_RETURNS, 0.95, draws=5000, seed=42)
        cv99 = mc_cvar(NORMAL_RETURNS, 0.99, draws=5000, seed=42)
        assert cv99 >= cv95

    def test_short_fallback(self) -> None:
        assert mc_cvar(SHORT_RETURNS, 0.95) == _DEFAULT_SHORT_FALLBACK

    def test_clamp(self) -> None:
        extreme = [-0.99] * 100
        v = mc_cvar(extreme, 0.99, draws=600)
        assert 0.0 <= v <= 0.95

    def test_tail_mean_logic(self) -> None:
        """MC CVaR = mean of worst floor((1-conf)*draws) bootstrap samples."""
        import math
        import random

        ret = NORMAL_RETURNS[:200]
        rnd = random.Random(42)
        n = len(ret)
        sim = [ret[rnd.randrange(n)] for _ in range(600)]
        sim_sorted = sorted(sim)
        tail_n = max(1, int(math.floor(0.05 * 600)))
        expected = max(0.0, -statistics.mean(sim_sorted[:tail_n]))
        actual = mc_cvar(ret, 0.95, draws=600, seed=42)
        assert actual == pytest.approx(expected, rel=1e-9)


# ═══════════════════════════════════════════════════════════════════════════════
# §5  RiskEngine integration
# ═══════════════════════════════════════════════════════════════════════════════


class TestRiskEngineCVaR:
    def _compute(self, returns: list[float], **kw) -> RiskMetrics:
        return RiskEngine(RiskConfig(**kw)).compute(returns)

    def test_three_cvar_methods_populated_95(self) -> None:
        m = self._compute(NORMAL_RETURNS)
        assert m.cvar_historical_95 > 0
        assert m.cvar_parametric_95 > 0
        assert m.cvar_monte_carlo_95 > 0

    def test_three_cvar_methods_populated_99(self) -> None:
        m = self._compute(NORMAL_RETURNS)
        assert m.cvar_historical_99 > 0
        assert m.cvar_parametric_99 > 0
        assert m.cvar_monte_carlo_99 > 0

    def test_cvar_95_is_max_of_three(self) -> None:
        m = self._compute(NORMAL_RETURNS)
        expected = max(m.cvar_historical_95, m.cvar_parametric_95, m.cvar_monte_carlo_95)
        assert m.cvar_95_1d == pytest.approx(expected, rel=1e-9)

    def test_cvar_99_is_max_of_three(self) -> None:
        m = self._compute(NORMAL_RETURNS)
        expected = max(m.cvar_historical_99, m.cvar_parametric_99, m.cvar_monte_carlo_99)
        assert m.cvar_99_1d == pytest.approx(expected, rel=1e-9)

    def test_basel_frtb_975_populated(self) -> None:
        """Basel FRTB: cvar_975_1d must be computed."""
        m = self._compute(NORMAL_RETURNS)
        assert m.cvar_975_1d > 0

    def test_cvar_975_between_95_and_99(self) -> None:
        """97.5% CVaR should be between 95% and 99%."""
        m = self._compute(NORMAL_RETURNS)
        assert m.cvar_95_1d <= m.cvar_975_1d + 1e-6
        assert m.cvar_975_1d <= m.cvar_99_1d + 1e-6

    def test_short_data_defaults(self) -> None:
        m = self._compute([0.01, -0.01, 0.005])
        assert m.cvar_95_1d == 0.0
        assert m.cvar_975_1d == 0.0

    def test_golden_fixture_cvar(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "unified_returns_golden.json"
        data = json.loads(fixture.read_text(encoding="utf-8"))
        m = RiskEngine().compute(data["returns"])
        for field in ["cvar_95_1d", "cvar_975_1d", "cvar_99_1d",
                       "cvar_historical_95", "cvar_parametric_95", "cvar_monte_carlo_95"]:
            assert abs(getattr(m, field) - data[field]) < 1e-6, f"{field} mismatch"

    def test_student_t_cvar_larger_in_engine(self) -> None:
        """Student-t config → parametric CVaR > normal config."""
        mt = self._compute(HEAVY_RETURNS, parametric_dist="student_t")
        mn = self._compute(HEAVY_RETURNS, parametric_dist="normal")
        assert mt.cvar_parametric_95 > mn.cvar_parametric_95
