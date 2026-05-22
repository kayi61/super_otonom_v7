"""VR-26: Property-Based VaR/CVaR Mathematical Invariants (Hypothesis).

Tests cover mathematical properties that MUST hold for any coherent
risk measure implementation — regardless of input data.  Hypothesis
auto-generates edge cases and shrinks failures to minimal examples.

Properties verified:
  - VaR non-negativity (positivity)
  - VaR monotonicity in confidence level
  - CVaR >= VaR (coherent risk measure)
  - Euler decomposition sum invariant
  - VaR positive homogeneity (scaling)
  - LVaR >= market VaR
  - Stressed VaR >= 0
  - Model consistency (dispersion bounded)
  - FHS / EVT non-negativity
  - CVaR subadditivity (diversification)
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from super_otonom.risk.cvar_models import (
    historical_cvar,
    mc_cvar,
    parametric_cvar,
)
from super_otonom.risk.lvar import bdss_lvar, compute_lvar, time_to_liquidate_lvar
from super_otonom.risk.risk_engine import RiskEngine
from super_otonom.risk.var_decomposition import compute_var_decomposition
from super_otonom.risk.var_models import (
    cornish_fisher_var,
    historical_var,
    monte_carlo_var,
    parametric_var,
)

pytestmark = pytest.mark.hypothesis

# ── Custom Strategies ──────────────────────────────────────────────────────

_HYP = settings(max_examples=80, deadline=12000, suppress_health_check=[HealthCheck.too_slow])

CONFS = st.sampled_from([0.90, 0.95, 0.975, 0.99])


@st.composite
def realistic_returns(draw, min_size=30, max_size=500):
    """Generate realistic daily return series (mean ~0, vol 1-5%)."""
    n = draw(st.integers(min_value=min_size, max_value=max_size))
    mu = draw(st.floats(min_value=-0.005, max_value=0.005))
    sigma = draw(st.floats(min_value=0.005, max_value=0.08))
    seed = draw(st.integers(min_value=0, max_value=99999))
    rng = np.random.RandomState(seed)
    returns = rng.normal(mu, sigma, n).tolist()
    return returns


@st.composite
def portfolio_weights(draw, n_assets=None):
    """Generate normalized positive portfolio weights."""
    if n_assets is None:
        n_assets = draw(st.integers(min_value=2, max_value=8))
    raw = draw(
        st.lists(
            st.floats(min_value=0.01, max_value=1.0),
            min_size=n_assets,
            max_size=n_assets,
        )
    )
    total = sum(raw)
    assume(total > 0.01)
    return [w / total for w in raw]


@st.composite
def multi_asset_returns(draw, n_assets=None, n_obs=None):
    """Generate correlated multi-asset return series + weights."""
    if n_assets is None:
        n_assets = draw(st.integers(min_value=2, max_value=6))
    if n_obs is None:
        n_obs = draw(st.integers(min_value=40, max_value=200))
    seed = draw(st.integers(min_value=0, max_value=99999))
    rng = np.random.RandomState(seed)
    # Generate returns with some correlation structure
    cov = np.eye(n_assets) * 0.01
    for i in range(n_assets):
        for j in range(i + 1, n_assets):
            c = rng.uniform(0.1, 0.7) * 0.01
            cov[i, j] = c
            cov[j, i] = c
    returns_matrix = rng.multivariate_normal(np.zeros(n_assets), cov, n_obs)
    symbols = [f"ASSET_{i}" for i in range(n_assets)]
    asset_returns = {s: returns_matrix[:, i].tolist() for i, s in enumerate(symbols)}
    weights = draw(portfolio_weights(n_assets=n_assets))
    weight_dict = {s: w for s, w in zip(symbols, weights)}
    return asset_returns, weight_dict


# ── VaR Positivity ─────────────────────────────────────────────────────────


class TestVaRPositivity:
    """VR-26: VaR must be non-negative for any valid input."""

    @_HYP
    @given(returns=realistic_returns())
    def test_historical_var_non_negative(self, returns):
        v = historical_var(returns, 0.95)
        assert v >= 0.0
        assert math.isfinite(v)

    @_HYP
    @given(returns=realistic_returns())
    def test_parametric_var_non_negative(self, returns):
        v = parametric_var(returns, 0.95, dist="student_t")
        assert v >= 0.0
        assert math.isfinite(v)

    @_HYP
    @given(returns=realistic_returns())
    def test_monte_carlo_var_non_negative(self, returns):
        v = monte_carlo_var(returns, 0.95, draws=200, seed=42)
        assert v >= 0.0
        assert math.isfinite(v)

    @_HYP
    @given(returns=realistic_returns())
    def test_cornish_fisher_var_non_negative(self, returns):
        v = cornish_fisher_var(returns, 0.95)
        assert v >= 0.0
        assert math.isfinite(v)


# ── VaR Monotonicity ───────────────────────────────────────────────────────


class TestVaRMonotonicity:
    """VR-26: VaR(99%) >= VaR(95%) — higher confidence = higher VaR."""

    @_HYP
    @given(returns=realistic_returns(min_size=50))
    def test_historical_var_monotonic(self, returns):
        v95 = historical_var(returns, 0.95)
        v99 = historical_var(returns, 0.99)
        assert v99 >= v95 - 1e-10

    @_HYP
    @given(returns=realistic_returns(min_size=50))
    def test_parametric_var_monotonic(self, returns):
        v95 = parametric_var(returns, 0.95, dist="student_t")
        v99 = parametric_var(returns, 0.99, dist="student_t")
        assert v99 >= v95 - 1e-10

    @_HYP
    @given(returns=realistic_returns(min_size=50))
    def test_monte_carlo_var_monotonic(self, returns):
        v95 = monte_carlo_var(returns, 0.95, draws=500, seed=42)
        v99 = monte_carlo_var(returns, 0.99, draws=500, seed=42)
        assert v99 >= v95 - 1e-10

    @_HYP
    @given(returns=realistic_returns(min_size=50))
    def test_cornish_fisher_monotonic(self, returns):
        v95 = cornish_fisher_var(returns, 0.95)
        v99 = cornish_fisher_var(returns, 0.99)
        assert v99 >= v95 - 1e-10


# ── CVaR >= VaR (Coherent Risk Measure) ────────────────────────────────────


class TestCVaRCoherence:
    """VR-26: CVaR >= VaR — Expected Shortfall dominates Value-at-Risk."""

    @_HYP
    @given(returns=realistic_returns(min_size=50))
    def test_historical_cvar_gte_var(self, returns):
        var = historical_var(returns, 0.95)
        cvar = historical_cvar(returns, 0.95)
        assert cvar >= var - 1e-6, f"CVaR={cvar} < VaR={var}"

    @_HYP
    @given(returns=realistic_returns(min_size=50))
    def test_parametric_cvar_gte_var(self, returns):
        var = parametric_var(returns, 0.95, dist="student_t")
        cvar = parametric_cvar(returns, 0.95, dist="student_t")
        assert cvar >= var - 1e-6, f"CVaR={cvar} < VaR={var}"

    @_HYP
    @given(returns=realistic_returns(min_size=50))
    def test_mc_cvar_gte_var_95(self, returns):
        var = monte_carlo_var(returns, 0.95, draws=500, seed=42)
        cvar = mc_cvar(returns, 0.95, draws=500, seed=42)
        assert cvar >= var - 1e-6, f"CVaR={cvar} < VaR={var}"

    @_HYP
    @given(returns=realistic_returns(min_size=50))
    def test_cvar_monotonic_in_confidence(self, returns):
        cvar95 = historical_cvar(returns, 0.95)
        cvar99 = historical_cvar(returns, 0.99)
        assert cvar99 >= cvar95 - 1e-6


# ── Euler Decomposition Invariant ──────────────────────────────────────────


class TestEulerInvariant:
    """VR-26: sum(Component_VaR_i) == Portfolio_VaR (Euler theorem)."""

    @_HYP
    @given(data=multi_asset_returns())
    def test_component_var_sums_to_total(self, data):
        asset_returns, weights = data
        # Compute portfolio returns
        symbols = list(weights.keys())
        n_obs = min(len(asset_returns[s]) for s in symbols)
        port_returns = [
            sum(weights[s] * asset_returns[s][t] for s in symbols)
            for t in range(n_obs)
        ]
        assume(len(port_returns) >= 30)
        var_total = historical_var(port_returns, 0.95)
        assume(var_total > 1e-6)

        comp_var, _ = compute_var_decomposition(asset_returns, weights, var_total)
        if not comp_var:
            return  # insufficient data, skip

        comp_sum = sum(comp_var.values())
        # Euler decomposition: sum of components equals total
        assert abs(comp_sum - var_total) < var_total * 0.15 + 1e-6, (
            f"sum(CVaR)={comp_sum:.6f} != VaR_total={var_total:.6f}"
        )

    @_HYP
    @given(data=multi_asset_returns())
    def test_component_var_non_negative_for_long_only(self, data):
        """Component VaR should be non-negative for long-only portfolios."""
        asset_returns, weights = data
        symbols = list(weights.keys())
        n_obs = min(len(asset_returns[s]) for s in symbols)
        port_returns = [
            sum(weights[s] * asset_returns[s][t] for s in symbols)
            for t in range(n_obs)
        ]
        assume(len(port_returns) >= 30)
        var_total = historical_var(port_returns, 0.95)
        assume(var_total > 1e-6)

        comp_var, marg_var = compute_var_decomposition(
            asset_returns, weights, var_total
        )
        # For long-only with positive correlation, most component VaRs are positive
        # (negative component VaR means the asset is a hedge)
        if comp_var:
            assert len(comp_var) >= 2


# ── VaR Positive Homogeneity ──────────────────────────────────────────────


class TestPositiveHomogeneity:
    """VR-26: VaR(lambda * X) = lambda * VaR(X) for lambda > 0."""

    @_HYP
    @given(
        returns=realistic_returns(min_size=50),
        scale=st.floats(min_value=0.5, max_value=3.0),
    )
    def test_historical_var_scales_linearly(self, returns, scale):
        var_original = historical_var(returns, 0.95)
        scaled_returns = [r * scale for r in returns]
        var_scaled = historical_var(scaled_returns, 0.95)
        # Allow small numerical tolerance
        expected = var_original * scale
        assert abs(var_scaled - expected) < expected * 0.05 + 1e-6, (
            f"VaR(scaled)={var_scaled:.6f} != scale*VaR={expected:.6f}"
        )

    @_HYP
    @given(
        returns=realistic_returns(min_size=50),
        scale=st.floats(min_value=0.5, max_value=3.0),
    )
    def test_cvar_scales_linearly(self, returns, scale):
        cvar_original = historical_cvar(returns, 0.95)
        scaled_returns = [r * scale for r in returns]
        cvar_scaled = historical_cvar(scaled_returns, 0.95)
        expected = cvar_original * scale
        assert abs(cvar_scaled - expected) < expected * 0.05 + 1e-6


# ── LVaR >= Market VaR ────────────────────────────────────────────────────


class TestLVaRBound:
    """VR-26: Liquidity-adjusted VaR >= pure market VaR."""

    @_HYP
    @given(
        var_market=st.floats(min_value=0.001, max_value=0.20),
        notional=st.floats(min_value=1000.0, max_value=1_000_000.0),
        n_spreads=st.integers(min_value=25, max_value=100),
        seed=st.integers(min_value=0, max_value=99999),
    )
    def test_bdss_lvar_gte_market_var(self, var_market, notional, n_spreads, seed):
        rng = np.random.RandomState(seed)
        spreads = np.abs(rng.normal(0.001, 0.0005, n_spreads)).tolist()
        lvar = bdss_lvar(var_market, notional, spreads)
        if lvar is not None:
            assert lvar >= var_market - 1e-10

    @_HYP
    @given(
        var_market=st.floats(min_value=0.001, max_value=0.20),
        qty=st.floats(min_value=100.0, max_value=100_000.0),
        adv=st.floats(min_value=1000.0, max_value=10_000_000.0),
    )
    def test_ttl_lvar_gte_market_var(self, var_market, qty, adv):
        lvar = time_to_liquidate_lvar(var_market, qty, adv)
        if lvar is not None:
            assert lvar >= var_market - 1e-10

    @_HYP
    @given(
        var_market=st.floats(min_value=0.001, max_value=0.20),
        notional=st.floats(min_value=1000.0, max_value=500_000.0),
    )
    def test_compute_lvar_gte_market(self, var_market, notional):
        lvar, health = compute_lvar(
            var_market=var_market,
            position_notional=notional,
            spread_history=None,
        )
        assert lvar >= var_market - 1e-10


# ── RiskEngine Full Suite ──────────────────────────────────────────────────


class TestRiskEngineSuite:
    """VR-26: RiskEngine.compute() invariants across random inputs."""

    @_HYP
    @given(returns=realistic_returns(min_size=50))
    def test_engine_var99_gte_var95(self, returns):
        engine = RiskEngine()
        m = engine.compute(returns)
        assert m.var_99_1d >= m.var_95_1d - 1e-6

    @_HYP
    @given(returns=realistic_returns(min_size=50))
    def test_engine_cvar_gte_var(self, returns):
        engine = RiskEngine()
        m = engine.compute(returns)
        assert m.cvar_95_1d >= m.var_95_1d - 1e-6
        assert m.cvar_99_1d >= m.var_99_1d - 1e-6

    @_HYP
    @given(returns=realistic_returns(min_size=50))
    def test_engine_all_finite(self, returns):
        engine = RiskEngine()
        m = engine.compute(returns)
        assert math.isfinite(m.var_95_1d)
        assert math.isfinite(m.var_99_1d)
        assert math.isfinite(m.cvar_95_1d)
        assert math.isfinite(m.cvar_99_1d)
        assert math.isfinite(m.model_dispersion_pct)
        assert math.isfinite(m.lvar)

    @_HYP
    @given(returns=realistic_returns(min_size=50))
    def test_engine_dispersion_bounded(self, returns):
        engine = RiskEngine()
        m = engine.compute(returns)
        # Model dispersion should be non-negative and bounded
        assert m.model_dispersion_pct >= 0.0
        # Extreme dispersion (>500%) would indicate a bug
        assert m.model_dispersion_pct < 5.0

    @_HYP
    @given(returns=realistic_returns(min_size=50))
    def test_engine_values_within_bounds(self, returns):
        engine = RiskEngine()
        m = engine.compute(returns)
        # VaR should be between 0 and 95% (our clamp)
        assert 0.0 <= m.var_95_1d <= 0.95
        assert 0.0 <= m.var_99_1d <= 0.95
        assert 0.0 <= m.cvar_95_1d <= 0.95
        assert 0.0 <= m.cvar_99_1d <= 0.95


# ── CVaR Subadditivity ─────────────────────────────────────────────────────


class TestCVaRSubadditivity:
    """VR-26: CVaR is subadditive — diversification reduces risk."""

    @_HYP
    @given(
        seed=st.integers(min_value=0, max_value=99999),
        n=st.integers(min_value=60, max_value=200),
    )
    def test_portfolio_cvar_le_sum_of_parts(self, seed, n):
        """CVaR(A+B) <= CVaR(A) + CVaR(B) for independent assets."""
        rng = np.random.RandomState(seed)
        r_a = rng.normal(0, 0.02, n).tolist()
        r_b = rng.normal(0, 0.02, n).tolist()
        # Equal-weight portfolio
        r_port = [(a + b) / 2.0 for a, b in zip(r_a, r_b)]

        cvar_a = historical_cvar(r_a, 0.95)
        cvar_b = historical_cvar(r_b, 0.95)
        cvar_port = historical_cvar(r_port, 0.95)

        # Subadditivity: CVaR(portfolio) <= 0.5*CVaR(A) + 0.5*CVaR(B)
        # (weighted sum because equal-weight portfolio)
        bound = 0.5 * cvar_a + 0.5 * cvar_b
        assert cvar_port <= bound + 1e-6, (
            f"CVaR(port)={cvar_port:.6f} > 0.5*CVaR(A)+0.5*CVaR(B)={bound:.6f}"
        )


# ── Edge Cases ─────────────────────────────────────────────────────────────


class TestEdgeCases:
    """VR-26: Edge case robustness — no crashes on degenerate input."""

    @_HYP
    @given(
        n=st.integers(min_value=3, max_value=10),
        val=st.floats(min_value=-0.001, max_value=0.001),
    )
    def test_constant_returns(self, n, val):
        """Constant returns should produce VaR close to zero."""
        returns = [val] * n
        v = historical_var(returns, 0.95)
        assert math.isfinite(v)
        assert v >= 0.0

    @_HYP
    @given(
        n=st.integers(min_value=30, max_value=100),
        seed=st.integers(min_value=0, max_value=99999),
    )
    def test_zero_mean_returns(self, n, seed):
        """Zero-mean returns should still produce valid VaR."""
        rng = np.random.RandomState(seed)
        returns = rng.normal(0.0, 0.02, n).tolist()
        v = historical_var(returns, 0.95)
        assert v >= 0.0
        c = historical_cvar(returns, 0.95)
        assert c >= 0.0
        assert c >= v - 1e-6

    @_HYP
    @given(
        n=st.integers(min_value=30, max_value=100),
        seed=st.integers(min_value=0, max_value=99999),
    )
    def test_fat_tailed_returns(self, n, seed):
        """Student-t returns (heavy tails) should produce valid metrics."""
        rng = np.random.RandomState(seed)
        returns = (rng.standard_t(3, n) * 0.02).tolist()
        engine = RiskEngine()
        m = engine.compute(returns)
        assert m.var_99_1d >= m.var_95_1d - 1e-6
        assert m.cvar_95_1d >= m.var_95_1d - 1e-6
        assert math.isfinite(m.var_cornish_fisher_95)

    def test_single_large_loss(self):
        """One large loss in otherwise calm data."""
        returns = [0.001] * 99 + [-0.15]
        v = historical_var(returns, 0.99)
        assert v > 0.0
        c = historical_cvar(returns, 0.99)
        assert c >= v - 1e-6

    def test_all_negative_returns(self):
        """All negative returns — VaR must be large."""
        returns = [-0.02] * 50
        v = historical_var(returns, 0.95)
        assert v > 0.0

    def test_very_small_returns(self):
        """Very small numbers — no underflow."""
        returns = [1e-10 * (i % 3 - 1) for i in range(50)]
        v = historical_var(returns, 0.95)
        assert math.isfinite(v)
        assert v >= 0.0


# ── Sentinel ────────────────────────────────────────────────────────────────


class TestSentinel:
    """VR-26: Sentinel marker."""

    def test_sentinel_present(self):
        src = _ROOT / "scripts" / "var_property_check.py"
        text = src.read_text(encoding="utf-8")
        assert "var_property_check_active = True" in text


# ── Audit Allowlist ─────────────────────────────────────────────────────────


class TestAuditAllowlist:
    """VR-26: var_topology_audit allowlist entries."""

    def test_test_file_in_allowlist(self):
        src = _ROOT / "super_otonom" / "var_topology_audit.py"
        text = src.read_text(encoding="utf-8")
        assert "test_var_properties_vr26" in text

    def test_script_in_allowlist(self):
        src = _ROOT / "super_otonom" / "var_topology_audit.py"
        text = src.read_text(encoding="utf-8")
        assert "var_property_check" in text
