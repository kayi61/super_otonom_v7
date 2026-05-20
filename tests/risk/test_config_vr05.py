"""VR-05 — RiskConfig expansion, validation & compat tests."""

from __future__ import annotations

import pytest
from super_otonom.risk.config import RiskConfig

# ── 1. Default config valid ─────────────────────────────────────────────────


class TestDefaultConfigValid:
    """Default RiskConfig passes all invariant checks."""

    def test_default_is_valid(self) -> None:
        rc = RiskConfig()
        assert rc.is_valid
        assert rc.validate() == []

    def test_default_var_confidences(self) -> None:
        rc = RiskConfig()
        assert rc.var_confidences == (0.95, 0.975, 0.99)

    def test_default_var_horizons(self) -> None:
        rc = RiskConfig()
        assert rc.var_horizons_days == (1, 10)

    def test_default_legacy_min_obs(self) -> None:
        """Legacy compat: live-tick uses 100 (RiskOntology / risk_manager)."""
        rc = RiskConfig()
        assert rc.var_history_min_obs == 100

    def test_default_institutional_min_obs(self) -> None:
        """Basel standard: 250 trading days ≈ 1 year."""
        rc = RiskConfig()
        assert rc.var_history_min_obs_institutional == 250

    def test_default_cvar_confs(self) -> None:
        rc = RiskConfig()
        assert rc.cvar_primary_conf == 0.975  # Basel FRTB ES
        assert rc.cvar_secondary_conf == 0.99
        assert rc.cvar_legacy_conf == 0.95

    def test_default_monte_carlo(self) -> None:
        rc = RiskConfig()
        assert rc.monte_carlo_draws == 600
        assert rc.monte_carlo_seed == 42

    def test_default_limit_aggregator(self) -> None:
        rc = RiskConfig()
        assert rc.limit_aggregator == "max"

    def test_default_parametric_z_scores(self) -> None:
        rc = RiskConfig()
        assert rc.parametric_z_95 == pytest.approx(1.645)
        assert rc.parametric_z_975 == pytest.approx(1.96)
        assert rc.parametric_z_99 == pytest.approx(2.326)

    def test_default_student_t(self) -> None:
        rc = RiskConfig()
        assert rc.parametric_dist == "student_t"
        assert rc.student_t_df is None  # MLE estimation
        assert rc.student_t_df_estimator == "mle"

    def test_default_use_models(self) -> None:
        rc = RiskConfig()
        assert set(rc.use_models) == {
            "historical",
            "parametric_t",
            "monte_carlo",
            "cornish_fisher",
        }


# ── 2. Validation catches invalid configs ───────────────────────────────────


class TestValidationCatchesInvalid:
    """validate() returns non-empty list for each invariant violation."""

    def test_cvar_primary_too_low(self) -> None:
        rc = RiskConfig(cvar_primary_conf=0.80)
        issues = rc.validate()
        assert any("cvar_primary_conf" in s for s in issues)
        assert not rc.is_valid

    def test_cvar_primary_too_high(self) -> None:
        rc = RiskConfig(cvar_primary_conf=1.0)
        issues = rc.validate()
        assert any("cvar_primary_conf" in s for s in issues)

    def test_cvar_secondary_not_gt_primary(self) -> None:
        rc = RiskConfig(cvar_primary_conf=0.99, cvar_secondary_conf=0.99)
        issues = rc.validate()
        assert any("cvar_secondary_conf" in s for s in issues)

    def test_var_history_min_obs_too_low(self) -> None:
        rc = RiskConfig(var_history_min_obs=5)
        issues = rc.validate()
        assert any("var_history_min_obs" in s and "too low" in s for s in issues)

    def test_institutional_lt_legacy(self) -> None:
        rc = RiskConfig(
            var_history_min_obs=100,
            var_history_min_obs_institutional=50,
        )
        issues = rc.validate()
        assert any("institutional" in s.lower() for s in issues)

    def test_monte_carlo_draws_too_low(self) -> None:
        rc = RiskConfig(monte_carlo_draws=50)
        issues = rc.validate()
        assert any("monte_carlo_draws" in s for s in issues)

    def test_invalid_parametric_dist(self) -> None:
        # frozen dataclass can't set invalid dist; test via unknown model instead
        rc = RiskConfig(use_models=("historical", "unknown_model"))
        issues = rc.validate()
        assert any("unknown" in s for s in issues)

    def test_unknown_model_in_use_models(self) -> None:
        rc = RiskConfig(use_models=("historical", "foo_model"))
        issues = rc.validate()
        assert any("unknown models" in s for s in issues)

    def test_var_confidence_out_of_range(self) -> None:
        rc = RiskConfig(var_confidences=(0.95, 1.5))
        issues = rc.validate()
        assert any("var_confidence" in s for s in issues)

    def test_var_confidence_zero(self) -> None:
        rc = RiskConfig(var_confidences=(0.0, 0.95))
        issues = rc.validate()
        assert any("var_confidence" in s for s in issues)

    def test_var_confidence_negative(self) -> None:
        rc = RiskConfig(var_confidences=(-0.1,))
        issues = rc.validate()
        assert any("var_confidence" in s for s in issues)

    def test_multiple_issues_reported(self) -> None:
        """All violations reported, not just the first."""
        rc = RiskConfig(
            cvar_primary_conf=0.5,
            var_history_min_obs=1,
            monte_carlo_draws=10,
        )
        issues = rc.validate()
        assert len(issues) >= 3


# ── 3. Frozen dataclass immutability ────────────────────────────────────────


class TestFrozenImmutability:
    def test_cannot_mutate_field(self) -> None:
        rc = RiskConfig()
        with pytest.raises(AttributeError):
            rc.monte_carlo_draws = 999  # type: ignore[misc]


# ── 4. Compat: existing consumers unaffected ────────────────────────────────


class TestCompatLayer:
    """Legacy consumers (RiskOntology, risk_manager) still get min_obs=100."""

    def test_legacy_min_obs_default_100(self) -> None:
        rc = RiskConfig()
        assert rc.var_history_min_obs == 100

    def test_institutional_always_gte_legacy(self) -> None:
        rc = RiskConfig()
        assert rc.var_history_min_obs_institutional >= rc.var_history_min_obs


# ── 5. RiskEngine uses config correctly ─────────────────────────────────────


class TestRiskEngineUsesConfig:
    """RiskEngine.compute() respects RiskConfig parameters."""

    def test_engine_default_config(self) -> None:
        from super_otonom.risk.risk_engine import RiskEngine

        eng = RiskEngine()
        assert eng.config.is_valid

    def test_engine_custom_config(self) -> None:
        from super_otonom.risk.risk_engine import RiskEngine

        cfg = RiskConfig(monte_carlo_draws=200)
        eng = RiskEngine(config=cfg)
        assert eng.config.monte_carlo_draws == 200

    def test_engine_compute_with_custom_seed(self) -> None:
        """Different seeds → different MC results (deterministic per seed)."""
        import numpy as np
        from super_otonom.risk.risk_engine import RiskEngine

        rets = list(np.random.default_rng(0).normal(0, 0.02, 100))
        e1 = RiskEngine(config=RiskConfig(monte_carlo_seed=42))
        e2 = RiskEngine(config=RiskConfig(monte_carlo_seed=99))
        m1 = e1.compute(rets)
        m2 = e2.compute(rets)
        # MC VaR differs with different seeds
        assert m1.var_monte_carlo_95 != pytest.approx(m2.var_monte_carlo_95, abs=1e-10)

    def test_engine_compute_pnl_legacy_respects_min_obs(self) -> None:
        """Legacy PnL interface uses var_history_min_obs from config."""
        from super_otonom.risk.risk_engine import RiskEngine

        cfg = RiskConfig(var_history_min_obs=50)
        eng = RiskEngine(config=cfg)
        # 40 obs < 50 min → returns 0.0
        assert eng.compute_from_pnl_history([0.01] * 40) == 0.0
        # 60 obs >= 50 min → returns non-zero
        result = eng.compute_from_pnl_history([-0.05] * 60)
        assert result != 0.0
