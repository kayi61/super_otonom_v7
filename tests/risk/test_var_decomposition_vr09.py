"""VR-09 tests — Component / Marginal / Incremental VaR decomposition."""

from __future__ import annotations

import numpy as np
from super_otonom.risk.risk_engine import RiskEngine, RiskMetrics
from super_otonom.risk.var_decomposition import (
    DECOMP_MIN_OBS,
    component_var,
    compute_var_decomposition,
    incremental_var,
    marginal_var,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────

_RNG = np.random.default_rng(909)
_N = 300

# Correlated asset returns via Cholesky factorisation
_COV_TRUE = np.array([
    [0.0004, 0.00024, 0.00008],
    [0.00024, 0.0009, 0.00012],
    [0.00008, 0.00012, 0.00025],
])
_L = np.linalg.cholesky(_COV_TRUE)
_Z = _RNG.standard_normal((_N, 3))
_RETURNS_MATRIX = (_Z @ _L.T)  # (N, 3) correlated returns

ASSET_RETURNS: dict[str, list[float]] = {
    "BTC": _RETURNS_MATRIX[:, 0].tolist(),
    "ETH": _RETURNS_MATRIX[:, 1].tolist(),
    "SOL": _RETURNS_MATRIX[:, 2].tolist(),
}

WEIGHTS = {"BTC": 0.50, "ETH": 0.30, "SOL": 0.20}

PORTFOLIO_RETURNS = [
    0.50 * ASSET_RETURNS["BTC"][i]
    + 0.30 * ASSET_RETURNS["ETH"][i]
    + 0.20 * ASSET_RETURNS["SOL"][i]
    for i in range(_N)
]

# Pre-computed total VaR for the portfolio (historical, 95%)
from super_otonom.risk.var_models import historical_var as _hvar

_VAR_TOTAL = _hvar(PORTFOLIO_RETURNS, 0.95, horizon_days=1)


# Two uncorrelated assets for isolation tests
_UNCORR_A = _RNG.normal(0.0, 0.02, size=_N).tolist()
_UNCORR_B = _RNG.normal(0.0, 0.02, size=_N).tolist()
UNCORRELATED = {"A": _UNCORR_A, "B": _UNCORR_B}
EQUAL_WEIGHTS = {"A": 0.5, "B": 0.5}


# ═══════════════════════════════════════════════════════════════════════════════
# §1  Euler Invariant — sum(component_var) ≈ total_var
# ═══════════════════════════════════════════════════════════════════════════════


class TestEulerInvariant:
    """The core mathematical property: component VaRs sum to total VaR."""

    def test_sum_equals_total_3_assets(self) -> None:
        comp, _ = compute_var_decomposition(ASSET_RETURNS, WEIGHTS, _VAR_TOTAL)
        assert comp, "decomposition must not be empty"
        total = sum(comp.values())
        assert abs(total - _VAR_TOTAL) < 1e-6, (
            f"sum(component_var)={total:.8f} != var_total={_VAR_TOTAL:.8f}"
        )

    def test_sum_equals_total_equal_weights(self) -> None:
        w = {"BTC": 1 / 3, "ETH": 1 / 3, "SOL": 1 / 3}
        pr = [
            w["BTC"] * ASSET_RETURNS["BTC"][i]
            + w["ETH"] * ASSET_RETURNS["ETH"][i]
            + w["SOL"] * ASSET_RETURNS["SOL"][i]
            for i in range(_N)
        ]
        vt = _hvar(pr, 0.95, horizon_days=1)
        comp, _ = compute_var_decomposition(ASSET_RETURNS, w, vt)
        assert abs(sum(comp.values()) - vt) < 1e-6

    def test_sum_equals_total_2_assets(self) -> None:
        w = {"BTC": 0.70, "ETH": 0.30}
        pr = [
            0.70 * ASSET_RETURNS["BTC"][i] + 0.30 * ASSET_RETURNS["ETH"][i]
            for i in range(_N)
        ]
        vt = _hvar(pr, 0.95, horizon_days=1)
        comp, _ = compute_var_decomposition(ASSET_RETURNS, w, vt)
        assert abs(sum(comp.values()) - vt) < 1e-6

    def test_sum_equals_total_uncorrelated(self) -> None:
        pr = [
            0.5 * UNCORRELATED["A"][i] + 0.5 * UNCORRELATED["B"][i]
            for i in range(_N)
        ]
        vt = _hvar(pr, 0.95, horizon_days=1)
        comp, _ = compute_var_decomposition(UNCORRELATED, EQUAL_WEIGHTS, vt)
        assert abs(sum(comp.values()) - vt) < 1e-6

    def test_sum_invariant_eps(self) -> None:
        """Strict epsilon < 1e-6 as specified in acceptance criteria."""
        comp, _ = compute_var_decomposition(ASSET_RETURNS, WEIGHTS, _VAR_TOTAL)
        residual = abs(sum(comp.values()) - _VAR_TOTAL)
        assert residual < 1e-6, f"residual={residual:.2e} exceeds 1e-6"

    def test_sum_invariant_with_custom_var_total(self) -> None:
        comp, _ = compute_var_decomposition(ASSET_RETURNS, WEIGHTS, 0.15)
        assert abs(sum(comp.values()) - 0.15) < 1e-6

    def test_all_components_present(self) -> None:
        comp, marg = compute_var_decomposition(ASSET_RETURNS, WEIGHTS, _VAR_TOTAL)
        for sym in ["BTC", "ETH", "SOL"]:
            assert sym in comp, f"{sym} missing from component_var"
            assert sym in marg, f"{sym} missing from marginal_var"


# ═══════════════════════════════════════════════════════════════════════════════
# §2  Marginal VaR properties
# ═══════════════════════════════════════════════════════════════════════════════


class TestMarginalVar:
    """dVaR/dw_i — sensitivity of portfolio VaR to weight changes."""

    def test_marginal_positive_for_positive_var(self) -> None:
        _, marg = compute_var_decomposition(ASSET_RETURNS, WEIGHTS, _VAR_TOTAL)
        for sym, mv in marg.items():
            assert mv > 0, f"MVaR({sym})={mv} should be positive"

    def test_higher_vol_asset_higher_marginal(self) -> None:
        """ETH has higher variance than BTC in our fixture → higher marginal."""
        _, marg = compute_var_decomposition(ASSET_RETURNS, WEIGHTS, _VAR_TOTAL)
        assert marg["ETH"] > marg["BTC"], (
            f"ETH(σ²=0.0009) should have higher MVaR than BTC(σ²=0.0004): "
            f"ETH={marg['ETH']:.6f}, BTC={marg['BTC']:.6f}"
        )

    def test_single_symbol_lookup(self) -> None:
        mv = marginal_var("ETH", ASSET_RETURNS, WEIGHTS, _VAR_TOTAL)
        _, marg = compute_var_decomposition(ASSET_RETURNS, WEIGHTS, _VAR_TOTAL)
        assert abs(mv - marg["ETH"]) < 1e-12

    def test_unknown_symbol_returns_zero(self) -> None:
        mv = marginal_var("DOGE", ASSET_RETURNS, WEIGHTS, _VAR_TOTAL)
        assert mv == 0.0

    def test_marginal_scales_with_var_total(self) -> None:
        _, m1 = compute_var_decomposition(ASSET_RETURNS, WEIGHTS, 0.05)
        _, m2 = compute_var_decomposition(ASSET_RETURNS, WEIGHTS, 0.10)
        for sym in ["BTC", "ETH", "SOL"]:
            assert abs(m2[sym] / m1[sym] - 2.0) < 1e-6, (
                "MVaR should scale linearly with var_total"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# §3  Component VaR properties
# ═══════════════════════════════════════════════════════════════════════════════


class TestComponentVar:
    """w_i * MVaR_i — additive decomposition of total VaR."""

    def test_component_positive(self) -> None:
        comp, _ = compute_var_decomposition(ASSET_RETURNS, WEIGHTS, _VAR_TOTAL)
        for sym, cv in comp.items():
            assert cv > 0, f"CVaR({sym})={cv} should be positive for correlated assets"

    def test_dominant_weight_dominant_component(self) -> None:
        comp, _ = compute_var_decomposition(ASSET_RETURNS, WEIGHTS, _VAR_TOTAL)
        assert comp["BTC"] > comp["SOL"], (
            "BTC (w=0.50) should contribute more than SOL (w=0.20)"
        )

    def test_single_symbol_lookup(self) -> None:
        cv = component_var("BTC", ASSET_RETURNS, WEIGHTS, _VAR_TOTAL)
        comp, _ = compute_var_decomposition(ASSET_RETURNS, WEIGHTS, _VAR_TOTAL)
        assert abs(cv - comp["BTC"]) < 1e-12

    def test_unknown_symbol_returns_zero(self) -> None:
        cv = component_var("DOGE", ASSET_RETURNS, WEIGHTS, _VAR_TOTAL)
        assert cv == 0.0

    def test_component_var_ratio(self) -> None:
        """Component VaR / total VaR gives risk contribution percentage."""
        comp, _ = compute_var_decomposition(ASSET_RETURNS, WEIGHTS, _VAR_TOTAL)
        pct = {s: v / _VAR_TOTAL for s, v in comp.items()}
        assert abs(sum(pct.values()) - 1.0) < 1e-6
        for s, p in pct.items():
            assert 0 < p < 1, f"{s} contribution {p:.4f} outside (0,1)"

    def test_concentrated_portfolio(self) -> None:
        """95% in one asset → that asset dominates component VaR."""
        w = {"BTC": 0.95, "ETH": 0.03, "SOL": 0.02}
        pr = [
            w["BTC"] * ASSET_RETURNS["BTC"][i]
            + w["ETH"] * ASSET_RETURNS["ETH"][i]
            + w["SOL"] * ASSET_RETURNS["SOL"][i]
            for i in range(_N)
        ]
        vt = _hvar(pr, 0.95, horizon_days=1)
        comp, _ = compute_var_decomposition(ASSET_RETURNS, w, vt)
        btc_pct = comp["BTC"] / sum(comp.values())
        assert btc_pct > 0.80, f"BTC should dominate: {btc_pct:.2%}"


# ═══════════════════════════════════════════════════════════════════════════════
# §4  Incremental VaR
# ═══════════════════════════════════════════════════════════════════════════════


class TestIncrementalVar:
    """VaR(with trade) − VaR(without trade) — pre-trade impact analysis."""

    def test_basic_incremental(self) -> None:
        w = {"BTC": 0.60, "ETH": 0.40}
        ivar = incremental_var("SOL", 0.10, ASSET_RETURNS, w)
        assert ivar is not None
        assert isinstance(ivar, float)

    def test_adding_uncorrelated_reduces_var(self) -> None:
        """Adding a low-corr asset with lower vol should reduce portfolio VaR."""
        rng = np.random.default_rng(42)
        ar = {
            "HIGH": rng.normal(0.0, 0.04, size=_N).tolist(),
            "LOW": rng.normal(0.0, 0.005, size=_N).tolist(),
        }
        w = {"HIGH": 1.0}
        ivar = incremental_var("LOW", 0.30, ar, w)
        assert ivar is not None
        assert ivar < 0, f"adding low-vol asset should reduce VaR, got {ivar:.6f}"

    def test_adding_high_vol_increases_var(self) -> None:
        rng = np.random.default_rng(42)
        ar = {
            "STABLE": rng.normal(0.0, 0.005, size=_N).tolist(),
            "WILD": rng.normal(0.0, 0.08, size=_N).tolist(),
        }
        w = {"STABLE": 1.0}
        ivar = incremental_var("WILD", 0.30, ar, w)
        assert ivar is not None
        assert ivar > 0, f"adding high-vol asset should increase VaR, got {ivar:.6f}"

    def test_incremental_none_insufficient_data(self) -> None:
        ar = {"BTC": [0.01] * 5, "ETH": [0.02] * 5}
        w = {"BTC": 1.0}
        result = incremental_var("ETH", 0.10, ar, w)
        assert result is None

    def test_incremental_none_unknown_trade(self) -> None:
        result = incremental_var("DOGE", 0.10, ASSET_RETURNS, WEIGHTS)
        assert result is None

    def test_incremental_none_zero_weight(self) -> None:
        result = incremental_var("SOL", 0.0, ASSET_RETURNS, WEIGHTS)
        assert result is None

    def test_incremental_none_weight_too_large(self) -> None:
        result = incremental_var("SOL", 1.0, ASSET_RETURNS, WEIGHTS)
        assert result is None

    def test_adding_existing_symbol(self) -> None:
        """Adding more of an existing asset should work."""
        ivar = incremental_var("ETH", 0.10, ASSET_RETURNS, WEIGHTS)
        assert ivar is not None


# ═══════════════════════════════════════════════════════════════════════════════
# §5  Edge cases & data validation
# ═══════════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Boundary conditions, degenerate inputs, graceful degradation."""

    def test_empty_asset_returns(self) -> None:
        comp, marg = compute_var_decomposition({}, WEIGHTS, 0.05)
        assert comp == {}
        assert marg == {}

    def test_empty_weights(self) -> None:
        comp, marg = compute_var_decomposition(ASSET_RETURNS, {}, 0.05)
        assert comp == {}
        assert marg == {}

    def test_zero_var_total(self) -> None:
        comp, marg = compute_var_decomposition(ASSET_RETURNS, WEIGHTS, 0.0)
        assert comp == {}
        assert marg == {}

    def test_negative_var_total(self) -> None:
        comp, marg = compute_var_decomposition(ASSET_RETURNS, WEIGHTS, -0.05)
        assert comp == {}
        assert marg == {}

    def test_single_asset_skipped(self) -> None:
        """Need >= 2 assets for meaningful decomposition."""
        comp, marg = compute_var_decomposition(
            {"BTC": ASSET_RETURNS["BTC"]}, {"BTC": 1.0}, 0.05,
        )
        assert comp == {}
        assert marg == {}

    def test_insufficient_observations(self) -> None:
        ar = {"BTC": [0.01] * 10, "ETH": [-0.01] * 10}
        comp, marg = compute_var_decomposition(ar, {"BTC": 0.5, "ETH": 0.5}, 0.05)
        assert comp == {}
        assert marg == {}

    def test_min_obs_boundary(self) -> None:
        """Exactly DECOMP_MIN_OBS observations should work."""
        rng = np.random.default_rng(123)
        ar = {
            "X": rng.normal(0.0, 0.02, size=DECOMP_MIN_OBS).tolist(),
            "Y": rng.normal(0.0, 0.03, size=DECOMP_MIN_OBS).tolist(),
        }
        comp, marg = compute_var_decomposition(ar, {"X": 0.5, "Y": 0.5}, 0.05)
        assert len(comp) == 2
        assert abs(sum(comp.values()) - 0.05) < 1e-6

    def test_weight_mismatch_partial(self) -> None:
        """Weights for symbols not in asset_returns are ignored."""
        w = {"BTC": 0.4, "ETH": 0.3, "SOL": 0.2, "DOGE": 0.1}
        comp, _ = compute_var_decomposition(ASSET_RETURNS, w, _VAR_TOTAL)
        assert "DOGE" not in comp
        assert len(comp) == 3
        assert abs(sum(comp.values()) - _VAR_TOTAL) < 1e-6

    def test_zero_variance_asset(self) -> None:
        """Constant returns → zero variance → graceful handling."""
        ar = {
            "FLAT": [0.01] * _N,
            "NORMAL": _RNG.normal(0.0, 0.02, size=_N).tolist(),
        }
        comp, marg = compute_var_decomposition(
            ar, {"FLAT": 0.5, "NORMAL": 0.5}, 0.05,
        )
        assert len(comp) == 2

    def test_negative_weights_normalized(self) -> None:
        """Negative weights are abs()-normalised."""
        w = {"BTC": -0.50, "ETH": 0.30, "SOL": 0.20}
        comp, _ = compute_var_decomposition(ASSET_RETURNS, w, _VAR_TOTAL)
        assert len(comp) == 3
        assert abs(sum(comp.values()) - _VAR_TOTAL) < 1e-6


# ═══════════════════════════════════════════════════════════════════════════════
# §6  RiskEngine integration
# ═══════════════════════════════════════════════════════════════════════════════


class TestRiskEngineIntegration:
    """Decomposition fields populated via RiskEngine.compute()."""

    def test_engine_populates_component_var(self) -> None:
        m = RiskEngine().compute(
            PORTFOLIO_RETURNS,
            positions=WEIGHTS,
            asset_returns=ASSET_RETURNS,
        )
        assert isinstance(m, RiskMetrics)
        assert len(m.component_var_per_position) == 3
        assert len(m.marginal_var_per_position) == 3

    def test_engine_euler_invariant(self) -> None:
        m = RiskEngine().compute(
            PORTFOLIO_RETURNS,
            positions=WEIGHTS,
            asset_returns=ASSET_RETURNS,
        )
        total = sum(m.component_var_per_position.values())
        assert abs(total - m.var_for_limits_95) < 1e-6

    def test_engine_without_decomposition_data(self) -> None:
        """When asset_returns not provided, decomposition fields are empty."""
        m = RiskEngine().compute(PORTFOLIO_RETURNS)
        assert m.component_var_per_position == {}
        assert m.marginal_var_per_position == {}

    def test_engine_positions_only_no_asset_returns(self) -> None:
        """Positions without asset_returns → empty decomposition."""
        m = RiskEngine().compute(PORTFOLIO_RETURNS, positions=WEIGHTS)
        assert m.component_var_per_position == {}

    def test_engine_decomposition_symbols_match(self) -> None:
        m = RiskEngine().compute(
            PORTFOLIO_RETURNS,
            positions=WEIGHTS,
            asset_returns=ASSET_RETURNS,
        )
        expected = {"BTC", "ETH", "SOL"}
        assert set(m.component_var_per_position.keys()) == expected
        assert set(m.marginal_var_per_position.keys()) == expected

    def test_engine_backward_compat_no_args(self) -> None:
        """Existing callers without new kwargs still work."""
        m = RiskEngine().compute(PORTFOLIO_RETURNS)
        assert m.var_95_1d > 0
        assert m.component_var_per_position == {}

    def test_engine_grafana_ready_output(self) -> None:
        """Per-symbol component VaR dict is JSON-serialisable for Grafana."""
        m = RiskEngine().compute(
            PORTFOLIO_RETURNS,
            positions=WEIGHTS,
            asset_returns=ASSET_RETURNS,
        )
        import json

        payload = json.dumps(m.component_var_per_position)
        decoded = json.loads(payload)
        assert isinstance(decoded, dict)
        for sym, val in decoded.items():
            assert isinstance(sym, str)
            assert isinstance(val, float)


# ═══════════════════════════════════════════════════════════════════════════════
# §7  Public API import paths
# ═══════════════════════════════════════════════════════════════════════════════


class TestPublicAPI:
    """Verify exports from the risk package."""

    def test_import_from_package(self) -> None:
        from super_otonom.risk import (  # noqa: F401
            component_var,
            compute_var_decomposition,
            incremental_var,
            marginal_var,
        )

    def test_import_from_module(self) -> None:
        from super_otonom.risk.var_decomposition import (  # noqa: F401
            DECOMP_MIN_OBS,
            component_var,
            compute_var_decomposition,
            incremental_var,
            marginal_var,
        )

    def test_min_obs_constant(self) -> None:
        assert DECOMP_MIN_OBS == 20
