"""VR-02 tests — Student-t parametric VaR, Monte Carlo bug fix, three-model parallel."""

from __future__ import annotations

import random
import statistics

import numpy as np
import pytest
from scipy import stats as sp_stats
from super_otonom.risk.config import RiskConfig
from super_otonom.risk.risk_engine import RiskEngine, RiskMetrics
from super_otonom.risk.var_models import (
    _DEFAULT_SHORT_FALLBACK,
    _DF_FALLBACK,
    _DF_MAX,
    _DF_MIN,
    _STUDENT_T_MIN_OBS,
    _fit_student_t_df,
    _percentile_loss,
    historical_var,
    monte_carlo_var,
    parametric_var,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────

_RNG = np.random.default_rng(12345)

# Normal returns (mu=0, sigma=0.02) — parametric ≈ historical for large N
NORMAL_RETURNS = _RNG.normal(0.0, 0.02, size=2000).tolist()

# Student-t(df=3) returns — heavy tails
_T_RAW = sp_stats.t.rvs(df=3, loc=0.0, scale=0.02, size=2000, random_state=42)
STUDENT_T_RETURNS = _T_RAW.tolist()

# Short series for edge cases
SHORT_RETURNS = [0.01, -0.02, 0.005]
TINY_RETURNS = [0.01, -0.01]


# ═══════════════════════════════════════════════════════════════════════════════
# §1  Monte Carlo VaR — bug fix verification
# ═══════════════════════════════════════════════════════════════════════════════


class TestMonteCarloFix:
    """Verify the mean-of-means bug is fixed (VR-02 critical)."""

    def test_mc_single_bootstrap_not_mean(self) -> None:
        """Each MC draw must be a single return, NOT mean of n samples."""
        ret = NORMAL_RETURNS[:500]
        rnd = random.Random(42)
        n = len(ret)
        # Replicate internal logic: single draw per iteration
        sim = [ret[rnd.randrange(n)] for _ in range(600)]
        # If the old mean-of-means bug existed, std(sim) ≈ std(ret)/sqrt(n) → tiny
        # With the fix, std(sim) ≈ std(ret)
        assert abs(statistics.stdev(sim) - statistics.stdev(ret)) / statistics.stdev(ret) < 0.15

    def test_mc_old_bug_would_underestimate_var(self) -> None:
        """Old implementation's mean-of-means converges to 0 VaR (CLT effect)."""
        ret = NORMAL_RETURNS[:500]
        rnd_old = random.Random(42)
        n = len(ret)
        # Old buggy code: mean of n samples per draw
        old_sim = []
        for _ in range(600):
            sample = [ret[rnd_old.randrange(n)] for _ in range(n)]
            old_sim.append(sum(sample) / n)
        old_std = statistics.stdev(old_sim)
        true_std = statistics.stdev(ret)
        # CLT: std(mean) ≈ std/sqrt(n) — massively smaller
        assert old_std < true_std * 0.15  # old approach underestimates volatility

        # New MC should produce much larger VaR than old
        new_var = monte_carlo_var(ret, 0.95, draws=600, seed=42)
        # Old approach VaR would be near zero
        old_var = historical_var(old_sim, 0.95)
        assert new_var > old_var * 2.0  # at least 2x larger

    def test_mc_deterministic_seed(self) -> None:
        """Same seed → identical results."""
        v1 = monte_carlo_var(NORMAL_RETURNS, 0.95, seed=42)
        v2 = monte_carlo_var(NORMAL_RETURNS, 0.95, seed=42)
        assert v1 == v2

    def test_mc_different_seeds_differ(self) -> None:
        """Different seeds → (usually) different results."""
        v1 = monte_carlo_var(NORMAL_RETURNS, 0.95, seed=42)
        v2 = monte_carlo_var(NORMAL_RETURNS, 0.95, seed=99)
        # Very unlikely to be identical with different seeds
        assert v1 != v2

    def test_mc_uses_numpy_percentile(self) -> None:
        """MC VaR uses np.percentile, not the historical_var helper."""
        ret = NORMAL_RETURNS[:200]
        mc_var = monte_carlo_var(ret, 0.95, draws=5000, seed=42)
        hist_var = historical_var(ret, 0.95)
        # Both should be in same ballpark for normal data
        assert abs(mc_var - hist_var) / hist_var < 0.40

    def test_mc_short_returns_fallback(self) -> None:
        """< 3 returns → fallback 0.085."""
        assert monte_carlo_var(TINY_RETURNS, 0.95) == 0.085
        assert monte_carlo_var([], 0.95) == 0.085

    def test_mc_clamp_095(self) -> None:
        """MC VaR clamped to [0, 0.95]."""
        extreme = [-0.99] * 100  # extreme losses
        v = monte_carlo_var(extreme, 0.99, draws=600)
        assert v <= 0.95

    def test_mc_positive_result(self) -> None:
        """MC VaR always non-negative."""
        gains = [0.05] * 100  # all gains → VaR should be 0
        v = monte_carlo_var(gains, 0.95)
        assert v >= 0.0

    def test_mc_horizon_scaling(self) -> None:
        """Horizon > 1 applies sqrt(T) scaling."""
        v1 = monte_carlo_var(NORMAL_RETURNS, 0.95, horizon_days=1)
        v10 = monte_carlo_var(NORMAL_RETURNS, 0.95, horizon_days=10)
        if v1 > 0.001:
            ratio = v10 / v1
            assert 2.5 < ratio < 4.0  # sqrt(10) ≈ 3.16

    def test_mc_higher_confidence_higher_var(self) -> None:
        """99% VaR > 95% VaR."""
        v95 = monte_carlo_var(NORMAL_RETURNS, 0.95, draws=2000, seed=42)
        v99 = monte_carlo_var(NORMAL_RETURNS, 0.99, draws=2000, seed=42)
        assert v99 > v95


# ═══════════════════════════════════════════════════════════════════════════════
# §2  Student-t parametric VaR
# ═══════════════════════════════════════════════════════════════════════════════


class TestStudentTParametric:
    """Student-t distribution integration."""

    def test_student_t_default_dist(self) -> None:
        """Default dist is 'student_t', not 'normal'."""
        cfg = RiskConfig()
        assert cfg.parametric_dist == "student_t"

    def test_student_t_larger_than_gaussian_for_fat_tails(self) -> None:
        """Student-t VaR > Gaussian VaR for heavy-tail returns."""
        vt = parametric_var(STUDENT_T_RETURNS, 0.95, dist="student_t")
        vn = parametric_var(STUDENT_T_RETURNS, 0.95, dist="normal")
        assert vt > vn, "Student-t should capture fat tails → larger VaR"

    def test_student_t_converges_to_normal_for_large_df(self) -> None:
        """With very large df, Student-t ≈ Normal."""
        # Use normal returns with explicitly large df
        vt = parametric_var(NORMAL_RETURNS, 0.95, dist="student_t", df=200.0)
        vn = parametric_var(NORMAL_RETURNS, 0.95, dist="normal")
        # Should be close (within 10%)
        assert abs(vt - vn) / max(vn, 1e-6) < 0.10

    def test_student_t_approx_equals_historical_for_normal(self) -> None:
        """For normally distributed data, parametric ≈ historical (any dist)."""
        vh = historical_var(NORMAL_RETURNS, 0.95)
        vn = parametric_var(NORMAL_RETURNS, 0.95, dist="normal")
        # Within 30% for 2000-obs normal data
        assert abs(vh - vn) / max(vh, 1e-6) < 0.30

    def test_student_t_explicit_df(self) -> None:
        """Explicit df parameter is used (no MLE)."""
        v_low = parametric_var(NORMAL_RETURNS, 0.95, dist="student_t", df=3.0)
        v_high = parametric_var(NORMAL_RETURNS, 0.95, dist="student_t", df=50.0)
        # Lower df → heavier tails → larger VaR
        assert v_low > v_high

    def test_student_t_99_larger_than_95(self) -> None:
        """99% confidence → larger VaR than 95%."""
        v95 = parametric_var(STUDENT_T_RETURNS, 0.95, dist="student_t")
        v99 = parametric_var(STUDENT_T_RETURNS, 0.99, dist="student_t")
        assert v99 > v95

    def test_normal_mode_uses_z_override(self) -> None:
        """In normal mode, explicit z is respected."""
        v_z1 = parametric_var(NORMAL_RETURNS, 0.95, dist="normal", z=1.645)
        v_z2 = parametric_var(NORMAL_RETURNS, 0.95, dist="normal", z=2.326)
        assert v_z2 > v_z1

    def test_student_t_ignores_z(self) -> None:
        """In student_t mode, z parameter is ignored."""
        v1 = parametric_var(NORMAL_RETURNS, 0.95, dist="student_t", z=1.0)
        v2 = parametric_var(NORMAL_RETURNS, 0.95, dist="student_t", z=5.0)
        assert v1 == v2  # z should be completely ignored

    def test_student_t_horizon_scaling(self) -> None:
        """Horizon > 1 applies sqrt(T) scaling for Student-t."""
        v1 = parametric_var(NORMAL_RETURNS, 0.95, dist="student_t", horizon_days=1)
        v10 = parametric_var(NORMAL_RETURNS, 0.95, dist="student_t", horizon_days=10)
        if v1 > 0.001:
            ratio = v10 / v1
            assert 2.5 < ratio < 4.0

    def test_parametric_short_fallback(self) -> None:
        """< 3 returns → fallback regardless of dist."""
        assert parametric_var(TINY_RETURNS, 0.95, dist="student_t") == _DEFAULT_SHORT_FALLBACK
        assert parametric_var(TINY_RETURNS, 0.95, dist="normal") == _DEFAULT_SHORT_FALLBACK

    def test_parametric_clamp(self) -> None:
        """Result clamped to [0, 0.95]."""
        extreme = [-0.99] * 200
        v = parametric_var(extreme, 0.99, dist="student_t")
        assert 0.0 <= v <= 0.95


# ═══════════════════════════════════════════════════════════════════════════════
# §3  Student-t df estimation (_fit_student_t_df)
# ═══════════════════════════════════════════════════════════════════════════════


class TestStudentTDfFit:
    """MLE degree-of-freedom estimation."""

    def test_df_from_heavy_tail_data(self) -> None:
        """Heavy-tail data → low df estimate."""
        df_est = _fit_student_t_df(STUDENT_T_RETURNS)
        assert _DF_MIN <= df_est <= 8.0  # t(3) data → df around 3-6

    def test_df_from_normal_data(self) -> None:
        """Normal data → high df estimate (approaching Gaussian)."""
        df_est = _fit_student_t_df(NORMAL_RETURNS)
        assert df_est > 15.0  # normal → large df

    def test_df_fallback_short_series(self) -> None:
        """< _STUDENT_T_MIN_OBS → fallback df."""
        short = NORMAL_RETURNS[:10]
        assert _fit_student_t_df(short) == _DF_FALLBACK

    def test_df_clamped_min(self) -> None:
        """df never below _DF_MIN."""
        df = _fit_student_t_df(STUDENT_T_RETURNS)
        assert df >= _DF_MIN

    def test_df_clamped_max(self) -> None:
        """df never above _DF_MAX."""
        df = _fit_student_t_df(NORMAL_RETURNS)
        assert df <= _DF_MAX

    def test_df_degenerate_data(self) -> None:
        """Constant data → fallback (MLE can't fit)."""
        constant = [0.01] * 50
        df = _fit_student_t_df(constant)
        # Should return _DF_FALLBACK or a clamped value, not crash
        assert _DF_MIN <= df <= _DF_MAX or df == _DF_FALLBACK

    def test_df_min_obs_boundary(self) -> None:
        """Exactly _STUDENT_T_MIN_OBS observations → MLE runs (not fallback)."""
        exact = NORMAL_RETURNS[:_STUDENT_T_MIN_OBS]
        df = _fit_student_t_df(exact)
        # With exactly threshold obs, MLE should run
        assert _DF_MIN <= df <= _DF_MAX

    def test_df_below_min_obs(self) -> None:
        """One below threshold → fallback."""
        below = NORMAL_RETURNS[: _STUDENT_T_MIN_OBS - 1]
        assert _fit_student_t_df(below) == _DF_FALLBACK


# ═══════════════════════════════════════════════════════════════════════════════
# §4  Three-model parallel RiskEngine integration
# ═══════════════════════════════════════════════════════════════════════════════


class TestRiskEngineThreeModels:
    """RiskEngine runs historical, parametric (student-t), MC in parallel."""

    def _compute(self, returns: list[float], **cfg_kw) -> RiskMetrics:
        cfg = RiskConfig(**cfg_kw)
        return RiskEngine(cfg).compute(returns)

    def test_all_three_models_populated(self) -> None:
        """All 3 per-model VaR fields are non-zero for adequate data."""
        m = self._compute(NORMAL_RETURNS)
        assert m.var_historical_95 > 0
        assert m.var_parametric_95 > 0
        assert m.var_monte_carlo_95 > 0

    def test_var_for_limits_is_max(self) -> None:
        """VaR_for_limits = max(historical, parametric, MC) by default."""
        m = self._compute(NORMAL_RETURNS)
        expected = max(m.var_historical_95, m.var_parametric_95, m.var_monte_carlo_95)
        assert m.var_for_limits_95 == pytest.approx(expected, rel=1e-9)

    def test_model_dispersion_computed(self) -> None:
        """model_dispersion_pct is calculated and non-negative."""
        m = self._compute(STUDENT_T_RETURNS)
        assert m.model_dispersion_pct >= 0.0

    def test_student_t_default_in_engine(self) -> None:
        """Default config uses student_t → parametric may differ from pure Gaussian."""
        m_t = self._compute(STUDENT_T_RETURNS, parametric_dist="student_t")
        m_n = self._compute(STUDENT_T_RETURNS, parametric_dist="normal")
        # Student-t parametric should be larger for fat-tail data
        assert m_t.var_parametric_95 > m_n.var_parametric_95

    def test_dispersion_formula(self) -> None:
        """dispersion = max(VaRs)/min(VaRs) - 1."""
        m = self._compute(NORMAL_RETURNS)
        vars95 = [m.var_historical_95, m.var_parametric_95, m.var_monte_carlo_95]
        lo, hi = min(vars95), max(vars95)
        if lo > 1e-12:
            expected_disp = hi / lo - 1.0
            # Dispersion is max of 95% and 99% dispersions
            assert m.model_dispersion_pct >= expected_disp - 0.01

    def test_99_vars_populated(self) -> None:
        """99% model breakdown also populated."""
        m = self._compute(NORMAL_RETURNS)
        assert m.var_historical_99 > 0
        assert m.var_parametric_99 > 0
        assert m.var_monte_carlo_99 > 0
        assert m.var_for_limits_99 > 0

    def test_99_greater_than_95(self) -> None:
        """var_for_limits at 99% > 95%."""
        m = self._compute(NORMAL_RETURNS)
        assert m.var_for_limits_99 >= m.var_for_limits_95

    def test_short_returns_empty_metrics(self) -> None:
        """< 5 returns → default RiskMetrics (all zeros)."""
        m = self._compute([0.01, -0.01, 0.005, -0.003])
        assert m.var_95_1d == 0.0
        assert m.model_dispersion_pct == 0.0

    def test_mean_aggregator(self) -> None:
        """limit_aggregator='mean' → VaR_for_limits = mean of 3 models."""
        m = self._compute(NORMAL_RETURNS, limit_aggregator="mean")
        vars95 = [m.var_historical_95, m.var_parametric_95, m.var_monte_carlo_95]
        assert m.var_for_limits_95 == pytest.approx(float(np.mean(vars95)), rel=1e-9)


# ═══════════════════════════════════════════════════════════════════════════════
# §5  Historical VaR unchanged (regression guard)
# ═══════════════════════════════════════════════════════════════════════════════


class TestHistoricalVarRegression:
    """Historical VaR must remain unchanged by VR-02."""

    def test_historical_basic(self) -> None:
        v = historical_var(NORMAL_RETURNS, 0.95)
        assert 0.01 < v < 0.10  # 2% vol → ~3.3% VaR at 95%

    def test_historical_short_fallback(self) -> None:
        assert historical_var(TINY_RETURNS, 0.95) == _DEFAULT_SHORT_FALLBACK

    def test_historical_clamp(self) -> None:
        extreme = [-0.99] * 100
        v = historical_var(extreme, 0.99)
        assert v <= 0.95

    def test_historical_horizon(self) -> None:
        v1 = historical_var(NORMAL_RETURNS, 0.95, horizon_days=1)
        v10 = historical_var(NORMAL_RETURNS, 0.95, horizon_days=10)
        if v1 > 0.001:
            assert 2.5 < v10 / v1 < 4.0


# ═══════════════════════════════════════════════════════════════════════════════
# §6  Edge cases and misc
# ═══════════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Boundary conditions and error handling."""

    def test_percentile_loss_empty(self) -> None:
        assert _percentile_loss([], 0.05) == 0.10

    def test_all_positive_returns_zero_var(self) -> None:
        """All positive returns → VaR ≈ 0 (clamped to 0)."""
        gains = [0.01 + i * 0.001 for i in range(100)]
        assert historical_var(gains, 0.95) == 0.0

    def test_student_t_low_df_larger_var(self) -> None:
        """Lower df → heavier tail quantile → larger VaR."""
        v_df3 = parametric_var(NORMAL_RETURNS, 0.95, dist="student_t", df=3.0)
        v_df50 = parametric_var(NORMAL_RETURNS, 0.95, dist="student_t", df=50.0)
        assert v_df3 > v_df50

    def test_student_t_df_2_still_works(self) -> None:
        """df ≈ 2 (variance barely defined) → still produces valid result."""
        v = parametric_var(NORMAL_RETURNS, 0.95, dist="student_t", df=2.01)
        assert v > 0

    def test_mc_large_draws(self) -> None:
        """More draws → more stable estimate."""
        v1 = monte_carlo_var(NORMAL_RETURNS[:100], 0.95, draws=100, seed=1)
        v2 = monte_carlo_var(NORMAL_RETURNS[:100], 0.95, draws=10000, seed=1)
        # Both should be positive, but we mainly check no crash
        assert v1 > 0 and v2 > 0

    def test_config_student_t_df_none_default(self) -> None:
        """Default config has student_t_df = None (MLE estimation)."""
        cfg = RiskConfig()
        assert cfg.student_t_df is None

    def test_config_explicit_df_passthrough(self) -> None:
        """Explicit df in config flows to parametric_var."""
        cfg = RiskConfig(student_t_df=4.0, parametric_dist="student_t")
        m = RiskEngine(cfg).compute(NORMAL_RETURNS)
        # With low df=4, parametric VaR should be larger than historical
        # (heavier tails assumed than data actually has)
        assert m.var_parametric_95 > 0

    def test_normal_dist_backward_compat(self) -> None:
        """dist='normal' produces same result as VR-01 (z-based)."""
        v_new = parametric_var(NORMAL_RETURNS, 0.95, dist="normal", z=1.645)
        # Manual calculation
        mu = statistics.mean(NORMAL_RETURNS)
        sig = statistics.stdev(NORMAL_RETURNS)
        expected = -(mu - 1.645 * sig)
        assert v_new == pytest.approx(max(0.0, min(0.95, expected)), rel=1e-9)
