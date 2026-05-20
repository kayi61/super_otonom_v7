"""VR-06 tests — EVT Peaks Over Threshold (POT) with GPD tail estimation."""

from __future__ import annotations

import numpy as np
import pytest
from scipy.stats import genpareto
from super_otonom.risk.config import RiskConfig
from super_otonom.risk.evt import pot_var_cvar
from super_otonom.risk.risk_engine import RiskEngine, RiskMetrics

# ── Fixtures ─────────────────────────────────────────────────────────────────

_RNG = np.random.default_rng(606)
NORMAL_RETURNS_1000 = _RNG.normal(0.0, 0.02, size=1000).tolist()
NORMAL_RETURNS_300 = _RNG.normal(0.0, 0.02, size=300).tolist()

_HEAVY_RNG = np.random.default_rng(707)
HEAVY_RETURNS_1000 = (_HEAVY_RNG.standard_t(4, size=1000) * 0.02).tolist()


def _make_gpd_sample(
    shape: float,
    scale: float,
    n_total: int = 2000,
    threshold_frac: float = 0.05,
    seed: int = 42,
) -> list[float]:
    """Synthetic returns with GPD-distributed left tail."""
    rng = np.random.default_rng(seed)
    n_tail = int(n_total * threshold_frac)
    n_body = n_total - n_tail
    body = rng.normal(0.0, 0.01, size=n_body)
    excesses = genpareto.rvs(shape, scale=scale, size=n_tail, random_state=rng)
    tail = -(excesses + np.quantile(body, threshold_frac))
    return np.concatenate([body, tail]).tolist()


# ═══════════════════════════════════════════════════════════════════════════════
# §1  Graceful skip — sample < 500
# ═══════════════════════════════════════════════════════════════════════════════


class TestEVTGracefulSkip:
    """EVT must return (None, None) when data is insufficient."""

    def test_skip_small_sample(self) -> None:
        var, cvar = pot_var_cvar(NORMAL_RETURNS_300, conf=0.99)
        assert var is None
        assert cvar is None

    def test_skip_very_small(self) -> None:
        var, cvar = pot_var_cvar([0.01, -0.02, 0.005], conf=0.99)
        assert var is None
        assert cvar is None

    def test_skip_empty(self) -> None:
        var, cvar = pot_var_cvar([], conf=0.99)
        assert var is None
        assert cvar is None

    def test_skip_exactly_499(self) -> None:
        rng = np.random.default_rng(111)
        ret = rng.normal(0.0, 0.02, size=499).tolist()
        var, cvar = pot_var_cvar(ret, conf=0.99)
        assert var is None
        assert cvar is None

    def test_active_at_500(self) -> None:
        rng = np.random.default_rng(222)
        ret = rng.normal(0.0, 0.02, size=500).tolist()
        var, cvar = pot_var_cvar(ret, conf=0.99)
        assert var is not None
        assert cvar is not None


# ═══════════════════════════════════════════════════════════════════════════════
# §2  GPD MLE accuracy — synthetic GPD sample, fitted params near true params
# ═══════════════════════════════════════════════════════════════════════════════


class TestGPDFitAccuracy:
    """MLE on synthetic GPD data should recover approximate parameters."""

    @pytest.mark.parametrize(
        "true_shape,true_scale",
        [
            (0.1, 0.005),
            (0.2, 0.01),
            (0.3, 0.008),
        ],
    )
    def test_gpd_mle_recovers_params(
        self, true_shape: float, true_scale: float
    ) -> None:
        rng = np.random.default_rng(333)
        excesses = genpareto.rvs(
            true_shape, scale=true_scale, size=5000, random_state=rng
        )
        fitted_shape, _, fitted_scale = genpareto.fit(excesses, floc=0)
        assert abs(fitted_shape - true_shape) < 0.08, (
            f"shape: fitted={fitted_shape:.4f}, true={true_shape}"
        )
        assert abs(fitted_scale - true_scale) / true_scale < 0.15, (
            f"scale: fitted={fitted_scale:.6f}, true={true_scale}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# §3  POT VaR/CVaR mathematical invariants
# ═══════════════════════════════════════════════════════════════════════════════


class TestPOTInvariants:
    """Core mathematical properties of POT-based risk measures."""

    def test_cvar_geq_var(self) -> None:
        var, cvar = pot_var_cvar(NORMAL_RETURNS_1000, conf=0.99)
        assert var is not None and cvar is not None
        assert cvar >= var - 1e-9, "CVaR must be >= VaR"

    def test_var_positive(self) -> None:
        var, cvar = pot_var_cvar(NORMAL_RETURNS_1000, conf=0.99)
        assert var is not None and var > 0

    def test_higher_confidence_higher_var(self) -> None:
        var95, _ = pot_var_cvar(NORMAL_RETURNS_1000, conf=0.95)
        var99, _ = pot_var_cvar(NORMAL_RETURNS_1000, conf=0.99)
        assert var95 is not None and var99 is not None
        assert var99 > var95, "99% VaR should exceed 95% VaR"

    def test_heavy_tails_larger_var(self) -> None:
        var_normal, _ = pot_var_cvar(NORMAL_RETURNS_1000, conf=0.99)
        var_heavy, _ = pot_var_cvar(HEAVY_RETURNS_1000, conf=0.99)
        assert var_normal is not None and var_heavy is not None
        assert var_heavy > var_normal * 0.8, (
            "Heavy-tailed returns should produce comparable or larger EVT VaR"
        )

    def test_returns_float_types(self) -> None:
        var, cvar = pot_var_cvar(NORMAL_RETURNS_1000, conf=0.99)
        assert isinstance(var, float)
        assert isinstance(cvar, float)


# ═══════════════════════════════════════════════════════════════════════════════
# §4  Synthetic GPD tail — end-to-end POT accuracy
# ═══════════════════════════════════════════════════════════════════════════════


class TestPOTEndToEnd:
    """POT on synthetic GPD-tailed data should produce sensible estimates."""

    def test_pot_on_gpd_sample(self) -> None:
        sample = _make_gpd_sample(shape=0.15, scale=0.008, n_total=3000, seed=555)
        var, cvar = pot_var_cvar(sample, conf=0.99, threshold_quantile=0.95)
        assert var is not None and cvar is not None
        assert var > 0
        assert cvar >= var

    def test_pot_reasonable_magnitude(self) -> None:
        rng = np.random.default_rng(666)
        ret = rng.normal(0.0, 0.02, size=2000).tolist()
        var, cvar = pot_var_cvar(ret, conf=0.99)
        assert var is not None
        assert 0.001 < var < 0.20, f"VaR={var} outside reasonable range for sigma=0.02"


# ═══════════════════════════════════════════════════════════════════════════════
# §5  RiskMetrics integration
# ═══════════════════════════════════════════════════════════════════════════════


class TestRiskMetricsEVT:
    """EVT fields present in RiskMetrics, populated by RiskEngine."""

    def test_evt_fields_default_none(self) -> None:
        m = RiskMetrics()
        assert m.var_evt_99 is None
        assert m.cvar_evt_99 is None

    def test_engine_populates_evt_large_sample(self) -> None:
        rng = np.random.default_rng(808)
        ret = rng.normal(0.0, 0.02, size=1000).tolist()
        m = RiskEngine().compute(ret)
        assert m.var_evt_99 is not None, "EVT should be active for n=1000"
        assert m.cvar_evt_99 is not None
        assert m.var_evt_99 > 0
        assert m.cvar_evt_99 >= m.var_evt_99

    def test_engine_skips_evt_small_sample(self) -> None:
        rng = np.random.default_rng(909)
        ret = rng.normal(0.0, 0.02, size=200).tolist()
        m = RiskEngine().compute(ret)
        assert m.var_evt_99 is None
        assert m.cvar_evt_99 is None

    def test_engine_evt_cvar_geq_var(self) -> None:
        rng = np.random.default_rng(1010)
        ret = (rng.standard_t(5, size=800) * 0.02).tolist()
        m = RiskEngine().compute(ret)
        if m.var_evt_99 is not None:
            assert m.cvar_evt_99 is not None
            assert m.cvar_evt_99 >= m.var_evt_99 - 1e-9


# ═══════════════════════════════════════════════════════════════════════════════
# §6  Config validation — EVT parameters
# ═══════════════════════════════════════════════════════════════════════════════


class TestEVTConfig:
    """RiskConfig EVT fields and validation."""

    def test_default_evt_config(self) -> None:
        cfg = RiskConfig()
        assert cfg.evt_min_sample == 500
        assert cfg.evt_threshold_quantile == 0.95
        assert cfg.is_valid

    def test_evt_min_sample_too_low(self) -> None:
        cfg = RiskConfig(evt_min_sample=10)
        issues = cfg.validate()
        assert any("evt_min_sample" in i for i in issues)

    def test_evt_threshold_out_of_range(self) -> None:
        cfg = RiskConfig(evt_threshold_quantile=0.50)
        issues = cfg.validate()
        assert any("evt_threshold_quantile" in i for i in issues)

    def test_evt_threshold_valid_range(self) -> None:
        cfg = RiskConfig(evt_threshold_quantile=0.90)
        assert cfg.is_valid


# ═══════════════════════════════════════════════════════════════════════════════
# §7  Numpy array input compatibility
# ═══════════════════════════════════════════════════════════════════════════════


class TestInputFormats:
    """pot_var_cvar should accept lists, tuples, and numpy arrays."""

    def test_numpy_array(self) -> None:
        arr = np.array(NORMAL_RETURNS_1000)
        var, cvar = pot_var_cvar(arr, conf=0.99)
        assert var is not None

    def test_python_list(self) -> None:
        var, cvar = pot_var_cvar(NORMAL_RETURNS_1000, conf=0.99)
        assert var is not None

    def test_tuple_input(self) -> None:
        var, cvar = pot_var_cvar(tuple(NORMAL_RETURNS_1000), conf=0.99)
        assert var is not None
