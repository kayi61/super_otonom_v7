"""Risk engine configuration (VR-05 Basel + compat layer)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, get_args

LvarMethod = Literal["bdss", "time_to_liquidate", "max_of_both"]
_VALID_LVAR_METHODS = get_args(LvarMethod)


@dataclass(frozen=True)
class RiskConfig:
    """Unified risk configuration — Basel III/FRTB aligned defaults.

    Compat: ``var_history_min_obs`` stays at 100 for live-tick legacy
    (``RiskOntology`` / ``risk_manager``). Institutional pipelines should
    use ``var_history_min_obs_institutional`` (250 = 1yr daily).
    """

    # ── Confidence levels ───────────────────────────────────────────────────
    var_confidences: tuple[float, ...] = (0.95, 0.975, 0.99)
    var_horizons_days: tuple[int, ...] = (1, 10)  # Basel FRTB: 1d + 10d

    # ── Minimum observations ────────────────────────────────────────────────
    # Legacy compat: live-tick (risk_ontology/risk_manager) uses 100
    var_history_min_obs: int = 100
    # Institutional: 250 trading days ≈ 1 year (Basel standard)
    var_history_min_obs_institutional: int = 250

    # ── CVaR / Expected Shortfall ───────────────────────────────────────────
    # Basel FRTB: ES at 97.5% is the regulatory standard
    cvar_primary_conf: float = 0.975
    cvar_secondary_conf: float = 0.99
    cvar_legacy_conf: float = 0.95

    # ── Monte Carlo ─────────────────────────────────────────────────────────
    monte_carlo_draws: int = 600
    monte_carlo_seed: int = 42

    # ── Limit aggregation ───────────────────────────────────────────────────
    # "max" = conservative (largest of 3 models); "mean" for average
    limit_aggregator: str = "max"

    # ── Parametric VaR z-scores (Gaussian mode) ─────────────────────────────
    parametric_z_95: float = 1.645
    parametric_z_975: float = 1.96
    parametric_z_99: float = 2.326

    # ── Student-t parametric (VR-02) ────────────────────────────────────────
    parametric_dist: Literal["normal", "student_t"] = "student_t"
    student_t_df: float | None = None  # None → MLE estimation
    student_t_df_estimator: Literal["mle"] = "mle"

    # ── EVT Peaks Over Threshold (VR-06) ──────────────────────────────────
    evt_min_sample: int = 500
    evt_threshold_quantile: float = 0.95

    # ── FHS GARCH(1,1) (VR-07) ────────────────────────────────────────────
    fhs_min_sample: int = 250

    # ── Liquidity-adjusted VaR (VR-08) ─────────────────────────────────────
    lvar_method: LvarMethod = "bdss"
    lvar_participation_rate: float = 0.10

    # ── Model selection (VR-05) ─────────────────────────────────────────────
    use_models: tuple[str, ...] = (
        "historical",
        "parametric_t",
        "monte_carlo",
        "cornish_fisher",
        "fhs",
    )

    def validate(self) -> list[str]:
        """Return list of invariant violations (empty = valid)."""
        issues: list[str] = []

        if self.cvar_primary_conf < 0.90 or self.cvar_primary_conf > 0.999:
            issues.append(
                f"cvar_primary_conf={self.cvar_primary_conf} outside [0.90, 0.999]"
            )
        if self.cvar_secondary_conf <= self.cvar_primary_conf:
            issues.append(
                f"cvar_secondary_conf={self.cvar_secondary_conf} must be > "
                f"cvar_primary_conf={self.cvar_primary_conf}"
            )
        if self.var_history_min_obs < 10:
            issues.append(
                f"var_history_min_obs={self.var_history_min_obs} too low (min 10)"
            )
        if self.var_history_min_obs_institutional < self.var_history_min_obs:
            issues.append(
                f"institutional min_obs ({self.var_history_min_obs_institutional}) "
                f"< legacy min_obs ({self.var_history_min_obs})"
            )
        if self.monte_carlo_draws < 100:
            issues.append(
                f"monte_carlo_draws={self.monte_carlo_draws} too low (min 100)"
            )
        if self.parametric_dist not in ("normal", "student_t"):
            issues.append(f"parametric_dist={self.parametric_dist!r} invalid")

        if self.fhs_min_sample < 50:
            issues.append(
                f"fhs_min_sample={self.fhs_min_sample} too low (min 50)"
            )

        if self.lvar_method not in _VALID_LVAR_METHODS:
            issues.append(f"lvar_method={self.lvar_method!r} invalid")
        if not (0.0 < self.lvar_participation_rate <= 1.0):
            issues.append(
                f"lvar_participation_rate={self.lvar_participation_rate} "
                "outside (0, 1]"
            )

        if self.evt_min_sample < 50:
            issues.append(
                f"evt_min_sample={self.evt_min_sample} too low (min 50)"
            )
        if not (0.80 <= self.evt_threshold_quantile <= 0.99):
            issues.append(
                f"evt_threshold_quantile={self.evt_threshold_quantile} "
                "outside [0.80, 0.99]"
            )

        valid_models = {"historical", "parametric_t", "monte_carlo", "cornish_fisher", "fhs"}
        unknown = set(self.use_models) - valid_models
        if unknown:
            issues.append(f"unknown models in use_models: {unknown}")

        for conf in self.var_confidences:
            if conf <= 0.0 or conf >= 1.0:
                issues.append(f"var_confidence={conf} outside (0, 1)")

        return issues

    @property
    def is_valid(self) -> bool:
        """True if all invariants hold."""
        return len(self.validate()) == 0
