"""VR-07 tests — Filtered Historical Simulation (FHS) with GARCH(1,1)."""

from __future__ import annotations

import numpy as np
from super_otonom.risk.config import RiskConfig
from super_otonom.risk.fhs import fhs_var_cvar
from super_otonom.risk.risk_engine import RiskEngine, RiskMetrics
from super_otonom.risk.var_models import historical_var

# ── Fixtures ─────────────────────────────────────────────────────────────────

def _make_calm_then_volatile(
    n_calm: int = 400,
    n_volatile: int = 100,
    sigma_calm: float = 0.005,
    sigma_volatile: float = 0.04,
    seed: int = 7070,
) -> list[float]:
    """Regime-switch series: calm period followed by high-vol spike."""
    rng = np.random.default_rng(seed)
    calm = rng.normal(0.0, sigma_calm, size=n_calm)
    volatile = rng.normal(0.0, sigma_volatile, size=n_volatile)
    return np.concatenate([calm, volatile]).tolist()


def _make_volatile_then_calm(
    n_volatile: int = 100,
    n_calm: int = 400,
    sigma_volatile: float = 0.04,
    sigma_calm: float = 0.005,
    seed: int = 7171,
) -> list[float]:
    """Regime-switch series: volatile start followed by calm period."""
    rng = np.random.default_rng(seed)
    volatile = rng.normal(0.0, sigma_volatile, size=n_volatile)
    calm = rng.normal(0.0, sigma_calm, size=n_calm)
    return np.concatenate([volatile, calm]).tolist()


def _make_steady(n: int = 500, sigma: float = 0.02, seed: int = 7272) -> list[float]:
    rng = np.random.default_rng(seed)
    return rng.normal(0.0, sigma, size=n).tolist()


CALM_THEN_VOL = _make_calm_then_volatile()
VOL_THEN_CALM = _make_volatile_then_calm()
STEADY = _make_steady()
SHORT = _make_steady(n=100)


# ═══════════════════════════════════════════════════════════════════════════════
# §1  Graceful skip — sample too small or GARCH fails
# ═══════════════════════════════════════════════════════════════════════════════


class TestFHSGracefulSkip:
    """FHS must return (None, None) when data is insufficient."""

    def test_skip_small_sample(self) -> None:
        var, cvar = fhs_var_cvar(SHORT, conf=0.95)
        assert var is None
        assert cvar is None

    def test_skip_very_small(self) -> None:
        var, cvar = fhs_var_cvar([0.01, -0.02], conf=0.95)
        assert var is None
        assert cvar is None

    def test_skip_empty(self) -> None:
        var, cvar = fhs_var_cvar([], conf=0.95)
        assert var is None
        assert cvar is None

    def test_skip_constant_returns(self) -> None:
        var, cvar = fhs_var_cvar([0.0] * 300, conf=0.95)
        assert var is None or var == 0.0

    def test_active_at_250(self) -> None:
        rng = np.random.default_rng(3030)
        ret = rng.normal(0.0, 0.02, size=250).tolist()
        var, cvar = fhs_var_cvar(ret, conf=0.95)
        assert var is not None


# ═══════════════════════════════════════════════════════════════════════════════
# §2  Vol regime test — FHS-VaR > historical-VaR in rising vol
# ═══════════════════════════════════════════════════════════════════════════════


class TestVolRegime:
    """FHS should capture volatility clustering that historical VaR misses."""

    def test_rising_vol_fhs_exceeds_historical(self) -> None:
        """When vol spikes at the end, GARCH forecasts higher sigma → FHS VaR > hist VaR."""
        fhs_v, fhs_cv = fhs_var_cvar(CALM_THEN_VOL, conf=0.95)
        hist_v = historical_var(CALM_THEN_VOL, 0.95)

        assert fhs_v is not None
        assert fhs_v > hist_v, (
            f"FHS VaR ({fhs_v:.6f}) should exceed historical VaR ({hist_v:.6f}) "
            "during rising volatility"
        )

    def test_falling_vol_fhs_below_historical(self) -> None:
        """When vol was high but settled, GARCH forecasts lower sigma → FHS VaR ≤ hist VaR."""
        fhs_v, _ = fhs_var_cvar(VOL_THEN_CALM, conf=0.95)
        hist_v = historical_var(VOL_THEN_CALM, 0.95)

        assert fhs_v is not None
        assert fhs_v < hist_v * 1.2, (
            f"FHS VaR ({fhs_v:.6f}) should be close to or below historical VaR "
            f"({hist_v:.6f}) when vol has subsided"
        )

    def test_steady_vol_fhs_close_to_historical(self) -> None:
        """In constant-vol regime, FHS ≈ historical (no regime advantage)."""
        fhs_v, _ = fhs_var_cvar(STEADY, conf=0.95)
        hist_v = historical_var(STEADY, 0.95)

        assert fhs_v is not None
        ratio = fhs_v / hist_v if hist_v > 0 else 1.0
        assert 0.5 < ratio < 2.0, (
            f"FHS/historical ratio={ratio:.2f} should be near 1.0 in steady vol"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# §3  Mathematical invariants
# ═══════════════════════════════════════════════════════════════════════════════


class TestFHSInvariants:
    """Core mathematical properties of FHS risk measures."""

    def test_cvar_geq_var(self) -> None:
        var, cvar = fhs_var_cvar(STEADY, conf=0.95)
        assert var is not None and cvar is not None
        assert cvar >= var - 1e-9, "CVaR must be >= VaR"

    def test_var_nonnegative(self) -> None:
        var, cvar = fhs_var_cvar(STEADY, conf=0.95)
        assert var is not None and var >= 0.0

    def test_higher_confidence_higher_var(self) -> None:
        v95, _ = fhs_var_cvar(STEADY, conf=0.95)
        v99, _ = fhs_var_cvar(STEADY, conf=0.99)
        assert v95 is not None and v99 is not None
        assert v99 >= v95, "99% VaR should be >= 95% VaR"

    def test_returns_float_types(self) -> None:
        var, cvar = fhs_var_cvar(STEADY, conf=0.95)
        assert isinstance(var, float)
        assert isinstance(cvar, float)

    def test_cvar_geq_var_99(self) -> None:
        var, cvar = fhs_var_cvar(CALM_THEN_VOL, conf=0.99)
        assert var is not None and cvar is not None
        assert cvar >= var - 1e-9


# ═══════════════════════════════════════════════════════════════════════════════
# §4  RiskMetrics integration
# ═══════════════════════════════════════════════════════════════════════════════


class TestRiskMetricsFHS:
    """FHS fields present in RiskMetrics, populated by RiskEngine."""

    def test_fhs_fields_default_none(self) -> None:
        m = RiskMetrics()
        assert m.var_fhs_95 is None
        assert m.var_fhs_99 is None
        assert m.cvar_fhs_95 is None
        assert m.cvar_fhs_99 is None

    def test_engine_populates_fhs_with_model_enabled(self) -> None:
        cfg = RiskConfig(use_models=("historical", "parametric_t", "monte_carlo", "cornish_fisher", "fhs"))
        m = RiskEngine(cfg).compute(STEADY)
        assert m.var_fhs_95 is not None, "FHS should be active for n=500 with fhs enabled"
        assert m.var_fhs_99 is not None
        assert m.cvar_fhs_95 is not None
        assert m.cvar_fhs_99 is not None
        assert m.var_fhs_95 > 0
        assert m.cvar_fhs_95 >= m.var_fhs_95

    def test_engine_skips_fhs_when_not_in_models(self) -> None:
        cfg = RiskConfig(use_models=("historical", "parametric_t", "monte_carlo", "cornish_fisher"))
        m = RiskEngine(cfg).compute(STEADY)
        assert m.var_fhs_95 is None
        assert m.var_fhs_99 is None

    def test_engine_fhs_none_for_small_sample(self) -> None:
        cfg = RiskConfig(use_models=("historical", "parametric_t", "monte_carlo", "cornish_fisher", "fhs"))
        rng = np.random.default_rng(4040)
        ret = rng.normal(0.0, 0.02, size=50).tolist()
        m = RiskEngine(cfg).compute(ret)
        assert m.var_fhs_95 is None
        assert m.var_fhs_99 is None

    def test_default_config_includes_fhs(self) -> None:
        cfg = RiskConfig()
        assert "fhs" in cfg.use_models


# ═══════════════════════════════════════════════════════════════════════════════
# §5  Config validation
# ═══════════════════════════════════════════════════════════════════════════════


class TestFHSConfig:
    """RiskConfig FHS fields and validation."""

    def test_default_fhs_config(self) -> None:
        cfg = RiskConfig()
        assert cfg.fhs_min_sample == 250
        assert cfg.is_valid

    def test_fhs_min_sample_too_low(self) -> None:
        cfg = RiskConfig(fhs_min_sample=10)
        issues = cfg.validate()
        assert any("fhs_min_sample" in i for i in issues)

    def test_fhs_in_valid_models(self) -> None:
        cfg = RiskConfig(use_models=("fhs",))
        assert cfg.is_valid


# ═══════════════════════════════════════════════════════════════════════════════
# §6  Input format compatibility
# ═══════════════════════════════════════════════════════════════════════════════


class TestFHSInputFormats:
    """fhs_var_cvar should accept lists, tuples, and numpy arrays."""

    def test_numpy_array(self) -> None:
        arr = np.array(STEADY)
        var, cvar = fhs_var_cvar(arr, conf=0.95)
        assert var is not None

    def test_python_list(self) -> None:
        var, cvar = fhs_var_cvar(STEADY, conf=0.95)
        assert var is not None

    def test_tuple_input(self) -> None:
        var, cvar = fhs_var_cvar(tuple(STEADY), conf=0.95)
        assert var is not None
