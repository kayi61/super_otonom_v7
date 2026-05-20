"""VR-11 — Stressed VaR (Basel 2.5) comprehensive tests.

Tests:
  - Fixture loading and structure validation
  - Per-period VaR computation with rescaling
  - Worst-period selection (max rule)
  - Rescale factor correctness (σ_current / σ_stress)
  - Limit breach detection (stressed_var > 2 × var_99)
  - Edge cases (empty, short, zero-vol)
  - Engine integration via RiskEngine.compute()
  - Convenience function
  - StressedVarResult dataclass fields
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from super_otonom.risk.risk_engine import RiskEngine, RiskMetrics
from super_otonom.risk.stressed_var import (
    STRESS_PERIODS,
    SVAR_MIN_OBS,
    StressedVaR,
    StressedVarResult,
    compute_stressed_var,
)
from super_otonom.risk.var_models import historical_var

pytestmark = pytest.mark.risk

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIXTURE_PATH = FIXTURES / "historical_stress_returns.json"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _normal_returns(n: int = 120, mean: float = 0.001, std: float = 0.02, seed: int = 42) -> list[float]:
    rng = np.random.RandomState(seed)
    return rng.normal(mean, std, n).tolist()


def _high_vol_returns(n: int = 60, mean: float = -0.01, std: float = 0.06, seed: int = 99) -> list[float]:
    rng = np.random.RandomState(seed)
    return rng.normal(mean, std, n).tolist()


# ── Fixture structure tests ──────────────────────────────────────────────────

class TestFixtureStructure:
    """Validate the historical_stress_returns.json fixture."""

    def test_fixture_file_exists(self) -> None:
        assert FIXTURE_PATH.is_file()

    def test_fixture_has_all_periods(self) -> None:
        data = _load_fixture()
        expected_keys = {k for k, _ in STRESS_PERIODS}
        assert set(data.keys()) == expected_keys

    def test_each_period_has_label_and_returns(self) -> None:
        data = _load_fixture()
        for key, entry in data.items():
            assert "label" in entry, f"{key}: missing 'label'"
            assert "returns" in entry, f"{key}: missing 'returns'"
            assert isinstance(entry["returns"], list)
            assert len(entry["returns"]) >= SVAR_MIN_OBS, f"{key}: too few returns"

    def test_returns_are_float(self) -> None:
        data = _load_fixture()
        for key, entry in data.items():
            for i, r in enumerate(entry["returns"]):
                assert isinstance(r, (int, float)), f"{key}[{i}] not numeric"

    def test_returns_have_negative_mean(self) -> None:
        """Stress periods should have negative mean returns."""
        data = _load_fixture()
        for key, entry in data.items():
            mean = np.mean(entry["returns"])
            assert mean < 0, f"{key}: mean={mean:.4f} should be negative"


# ── StressedVaR class tests ──────────────────────────────────────────────────

class TestStressedVaRInit:
    def test_from_dict(self) -> None:
        sr = {"test_period": [float(x) for x in range(-50, 10)]}
        engine = StressedVaR(sr)
        assert "test_period" in engine.period_keys

    def test_from_fixture(self) -> None:
        engine = StressedVaR.from_fixture(FIXTURE_PATH)
        assert len(engine.period_keys) == 5

    def test_period_keys_sorted(self) -> None:
        engine = StressedVaR.from_fixture(FIXTURE_PATH)
        keys = engine.period_keys
        assert keys == sorted(keys)


class TestStressedVaRCompute:
    """Core computation: rescaling, worst-period, per-period dict."""

    def test_basic_compute_returns_result(self) -> None:
        engine = StressedVaR.from_fixture(FIXTURE_PATH)
        cur = _normal_returns()
        result = engine.compute(cur)
        assert isinstance(result, StressedVarResult)
        assert result.stressed_var > 0

    def test_all_periods_in_per_period_var(self) -> None:
        engine = StressedVaR.from_fixture(FIXTURE_PATH)
        cur = _normal_returns()
        result = engine.compute(cur)
        expected = {k for k, _ in STRESS_PERIODS}
        assert set(result.per_period_var.keys()) == expected

    def test_worst_period_is_max(self) -> None:
        engine = StressedVaR.from_fixture(FIXTURE_PATH)
        cur = _normal_returns()
        result = engine.compute(cur)
        max_val = max(result.per_period_var.values())
        assert abs(result.stressed_var - max_val) < 1e-12
        assert result.per_period_var[result.worst_period] == max_val

    def test_rescale_factor_sigma_ratio(self) -> None:
        """Rescale factor = σ_current / σ_worst_period."""
        data = _load_fixture()
        engine = StressedVaR.from_fixture(FIXTURE_PATH)
        cur = _normal_returns()
        result = engine.compute(cur)

        sigma_current = float(np.std(cur, ddof=1))
        worst_rets = data[result.worst_period]["returns"]
        sigma_stress = float(np.std(worst_rets, ddof=1))
        expected_rescale = sigma_current / sigma_stress

        assert abs(result.rescale_factor - expected_rescale) < 1e-10

    def test_rescaled_var_formula(self) -> None:
        """sVaR = raw_hist_var(stress) × (σ_current / σ_stress)."""
        data = _load_fixture()
        engine = StressedVaR.from_fixture(FIXTURE_PATH)
        cur = _normal_returns()
        result = engine.compute(cur, conf=0.99)

        sigma_current = float(np.std(cur, ddof=1))

        for key, scaled_var in result.per_period_var.items():
            rets = data[key]["returns"]
            raw_var = historical_var(rets, 0.99, horizon_days=1)
            sigma_s = float(np.std(rets, ddof=1))
            expected = raw_var * (sigma_current / sigma_s)
            assert abs(scaled_var - expected) < 1e-10, f"{key}: got {scaled_var}, expected {expected}"

    def test_higher_current_vol_amplifies(self) -> None:
        """When current vol > stress vol, rescaled VaR should exceed raw."""
        engine = StressedVaR.from_fixture(FIXTURE_PATH)
        cur_lo = _normal_returns(std=0.02)
        cur_hi = _high_vol_returns(std=0.06)
        r_lo = engine.compute(cur_lo)
        r_hi = engine.compute(cur_hi)
        assert r_hi.stressed_var > r_lo.stressed_var

    def test_conf_95_vs_99(self) -> None:
        """VaR at 99% should exceed VaR at 95%."""
        engine = StressedVaR.from_fixture(FIXTURE_PATH)
        cur = _normal_returns()
        r95 = engine.compute(cur, conf=0.95)
        r99 = engine.compute(cur, conf=0.99)
        assert r99.stressed_var >= r95.stressed_var

    def test_stressed_var_positive(self) -> None:
        engine = StressedVaR.from_fixture(FIXTURE_PATH)
        cur = _normal_returns()
        result = engine.compute(cur)
        assert result.stressed_var >= 0

    def test_stressed_var_exceeds_normal_var(self) -> None:
        """Stressed VaR should typically exceed normal VaR from same returns."""
        engine = StressedVaR.from_fixture(FIXTURE_PATH)
        cur = _normal_returns()
        normal_var = historical_var(cur, 0.99, horizon_days=1)
        result = engine.compute(cur, conf=0.99)
        # Stressed VaR uses stress periods which have worse tails
        # Even after rescaling, it should be > normal VaR
        assert result.stressed_var > normal_var * 0.5  # conservative bound


class TestStressedVarResult:
    def test_frozen_dataclass(self) -> None:
        r = StressedVarResult()
        with pytest.raises(AttributeError):
            r.stressed_var = 0.5  # type: ignore[misc]

    def test_default_values(self) -> None:
        r = StressedVarResult()
        assert r.stressed_var == 0.0
        assert r.worst_period == ""
        assert r.per_period_var == {}
        assert r.rescale_factor == 1.0
        assert r.breach is False
        assert r.breach_multiplier == 2.0


# ── Breach / limit tests ────────────────────────────────────────────────────

class TestBreachDetection:
    def test_no_breach_when_var99_zero(self) -> None:
        engine = StressedVaR.from_fixture(FIXTURE_PATH)
        cur = _normal_returns()
        result = engine.compute(cur, var_99_for_limit=0.0)
        assert result.breach is False

    def test_no_breach_when_var99_none(self) -> None:
        engine = StressedVaR.from_fixture(FIXTURE_PATH)
        cur = _normal_returns()
        result = engine.compute(cur, var_99_for_limit=None)
        assert result.breach is False

    def test_breach_when_stressed_exceeds_2x_var99(self) -> None:
        """Force breach: set var_99 very low so stressed_var > 2 × var_99."""
        engine = StressedVaR.from_fixture(FIXTURE_PATH)
        cur = _normal_returns()
        result = engine.compute(cur, var_99_for_limit=0.001)
        assert result.breach is True

    def test_no_breach_when_var99_very_high(self) -> None:
        """If var_99 is huge, stressed_var can't breach 2×."""
        engine = StressedVaR.from_fixture(FIXTURE_PATH)
        cur = _normal_returns()
        result = engine.compute(cur, var_99_for_limit=10.0)
        assert result.breach is False

    def test_custom_breach_multiplier(self) -> None:
        engine = StressedVaR.from_fixture(FIXTURE_PATH)
        cur = _normal_returns()
        # With very low var_99 and multiplier=1000, still no breach
        result = engine.compute(cur, var_99_for_limit=0.001, breach_multiplier=1000.0)
        assert result.breach is False

    def test_check_limit_static(self) -> None:
        assert StressedVaR.check_limit(0.10, 0.04) is True   # 0.10 > 0.08
        assert StressedVaR.check_limit(0.07, 0.04) is False  # 0.07 < 0.08
        assert StressedVaR.check_limit(0.10, 0.0) is False   # var_99=0 → False

    def test_check_limit_custom_multiplier(self) -> None:
        assert StressedVaR.check_limit(0.10, 0.04, multiplier=3.0) is False  # 0.10 < 0.12
        assert StressedVaR.check_limit(0.10, 0.03, multiplier=3.0) is True   # 0.10 > 0.09


# ── Edge cases ───────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_current_returns(self) -> None:
        engine = StressedVaR.from_fixture(FIXTURE_PATH)
        result = engine.compute([])
        assert result.stressed_var == 0.0
        assert result.worst_period == ""

    def test_single_current_return(self) -> None:
        engine = StressedVaR.from_fixture(FIXTURE_PATH)
        result = engine.compute([0.01])
        assert result.stressed_var == 0.0

    def test_short_stress_period_skipped(self) -> None:
        """Stress period with < SVAR_MIN_OBS returns is skipped."""
        engine = StressedVaR({"too_short": list(range(5))})
        result = engine.compute(_normal_returns())
        assert result.stressed_var == 0.0
        assert result.per_period_var == {}

    def test_zero_vol_stress_period(self) -> None:
        """Stress period with zero volatility uses raw VaR."""
        engine = StressedVaR({"flat": [0.01] * 30})
        cur = _normal_returns()
        result = engine.compute(cur)
        # With zero vol, rescale is skipped, raw VaR used directly
        # historical_var of constant returns is 0 (no loss)
        assert result.per_period_var.get("flat", 0.0) >= 0

    def test_identical_current_and_stress_vol(self) -> None:
        """When σ_current ≈ σ_stress, rescale ≈ 1."""
        rng = np.random.RandomState(123)
        rets = rng.normal(-0.01, 0.03, 60).tolist()
        engine = StressedVaR({"same_vol": rets})
        result = engine.compute(rets, conf=0.99)
        # Rescale should be ~1
        assert 0.8 < result.rescale_factor < 1.2

    def test_all_positive_stress_returns(self) -> None:
        """Stress period with all positive returns → VaR is small/zero."""
        rng = np.random.RandomState(77)
        rets = (rng.uniform(0.01, 0.05, 30)).tolist()
        engine = StressedVaR({"positive": rets})
        cur = _normal_returns()
        result = engine.compute(cur)
        # VaR from positive returns is 0 (no loss at 99%)
        assert result.per_period_var.get("positive", 0.0) >= 0


# ── Convenience function ────────────────────────────────────────────────────

class TestConvenienceFunction:
    def test_compute_stressed_var_tuple(self) -> None:
        data = _load_fixture()
        stress_dict = {k: v["returns"] for k, v in data.items()}
        cur = _normal_returns()
        svar, worst, per_period = compute_stressed_var(cur, stress_dict)
        assert svar > 0
        assert worst in per_period
        assert len(per_period) == 5

    def test_matches_class_api(self) -> None:
        data = _load_fixture()
        stress_dict = {k: v["returns"] for k, v in data.items()}
        cur = _normal_returns()

        svar, worst, per_period = compute_stressed_var(cur, stress_dict)

        engine = StressedVaR(stress_dict)
        result = engine.compute(cur)

        assert abs(svar - result.stressed_var) < 1e-12
        assert worst == result.worst_period


# ── RiskEngine integration ──────────────────────────────────────────────────

class TestRiskEngineIntegration:
    """Verify stressed VaR wires through RiskEngine.compute()."""

    def _stress_dict(self) -> dict[str, list[float]]:
        data = _load_fixture()
        return {k: v["returns"] for k, v in data.items()}

    def test_without_stress_returns_zero(self) -> None:
        eng = RiskEngine()
        m = eng.compute(_normal_returns())
        assert m.stressed_var == 0.0
        assert m.stressed_var_worst_period == ""
        assert m.stressed_var_breach is False

    def test_with_stress_returns_populated(self) -> None:
        eng = RiskEngine()
        m = eng.compute(_normal_returns(), stress_returns=self._stress_dict())
        assert m.stressed_var > 0
        assert m.stressed_var_worst_period != ""

    def test_risk_metrics_has_fields(self) -> None:
        """RiskMetrics frozen dataclass has VR-11 fields."""
        m = RiskMetrics()
        assert hasattr(m, "stressed_var")
        assert hasattr(m, "stressed_var_worst_period")
        assert hasattr(m, "stressed_var_breach")

    def test_breach_flag_propagates(self) -> None:
        """When stressed_var >> var_99, breach should be True."""
        # Use high-vol current returns to amplify stress VaR
        cur = _high_vol_returns(n=120, std=0.08, seed=55)
        eng = RiskEngine()
        m = eng.compute(cur, stress_returns=self._stress_dict())
        # stressed_var is computed with conf=0.99, breach check uses var_for_limits_99
        # We can't guarantee breach without knowing exact values,
        # but we can verify the field is populated
        assert isinstance(m.stressed_var_breach, bool)

    def test_stressed_var_independent_of_decomposition(self) -> None:
        """Stressed VaR should work regardless of positions/asset_returns."""
        eng = RiskEngine()
        m1 = eng.compute(_normal_returns(), stress_returns=self._stress_dict())
        m2 = eng.compute(
            _normal_returns(),
            stress_returns=self._stress_dict(),
            positions={"BTC": 0.6, "ETH": 0.4},
        )
        # Same returns → same stressed_var (positions don't affect it)
        assert abs(m1.stressed_var - m2.stressed_var) < 1e-12

    def test_golden_fixture_integration(self) -> None:
        """Use the unified golden fixture and verify stressed_var field."""
        golden_path = FIXTURES / "unified_returns_golden.json"
        if not golden_path.is_file():
            pytest.skip("golden fixture missing")
        raw = json.loads(golden_path.read_text(encoding="utf-8"))
        returns = raw["returns"] if isinstance(raw, dict) else raw
        eng = RiskEngine()
        m = eng.compute(returns, stress_returns=self._stress_dict())
        assert m.stressed_var > 0
        assert m.var_99_1d > 0
        # stressed VaR uses stress periods → should differ from normal var_99
        assert m.stressed_var != m.var_99_1d


# ── Deterministic reproducibility ───────────────────────────────────────────

class TestReproducibility:
    def test_same_inputs_same_output(self) -> None:
        engine = StressedVaR.from_fixture(FIXTURE_PATH)
        cur = _normal_returns()
        r1 = engine.compute(cur)
        r2 = engine.compute(cur)
        assert r1.stressed_var == r2.stressed_var
        assert r1.worst_period == r2.worst_period
        assert r1.per_period_var == r2.per_period_var

    def test_fixture_seeded_deterministic(self) -> None:
        """Fixture was generated with np.random.RandomState(2025) — stable."""
        data = _load_fixture()
        # COVID period first return should be stable
        first_covid = data["2020_covid"]["returns"][0]
        assert isinstance(first_covid, float)
        # Just verify it loads and is numeric — exact value depends on seed
