"""Unified risk engine — single VaR/CVaR source (VR-01/02/03)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Sequence

import numpy as np

from super_otonom.risk.config import RiskConfig
from super_otonom.risk.cvar_models import historical_cvar
from super_otonom.risk.var_models import (
    cornish_fisher_var,
    historical_var,
    monte_carlo_var,
    parametric_var,
)


@dataclass(frozen=True)
class RiskMetrics:
    """Portfolio / limit metrics (fractions unless noted)."""

    # ── Core VaR (max of 3 models) ───────────────────────────────────────────
    var_95_1d: float = 0.0
    var_99_1d: float = 0.0
    var_975_1d: float = 0.0

    # ── CVaR / Expected Shortfall ────────────────────────────────────────────
    cvar_95_1d: float = 0.0
    cvar_975_1d: float = 0.0
    cvar_99_1d: float = 0.0

    # ── Per-model breakdown (95%) ────────────────────────────────────────────
    var_historical_95: float = 0.0
    var_parametric_95: float = 0.0
    var_monte_carlo_95: float = 0.0
    var_for_limits_95: float = 0.0

    # ── Per-model breakdown (99%) ────────────────────────────────────────────
    var_historical_99: float = 0.0
    var_parametric_99: float = 0.0
    var_monte_carlo_99: float = 0.0
    var_for_limits_99: float = 0.0

    # ── Cornish-Fisher VaR (VR-03 placeholder) ──────────────────────────────
    var_cornish_fisher_95: float = 0.0
    var_cornish_fisher_99: float = 0.0

    # ── Model risk ───────────────────────────────────────────────────────────
    model_dispersion_pct: float = 0.0

    # ── Stress / liquidity (VR-08/11 placeholders) ──────────────────────────
    stressed_var: float = 0.0
    lvar: float = 0.0

    # ── Decomposition (VR-09 placeholder) ────────────────────────────────────
    component_var_per_position: Dict[str, float] = field(default_factory=dict)
    marginal_var_per_position: Dict[str, float] = field(default_factory=dict)

    # ── Legacy compat (live tick PnL-based) ──────────────────────────────────
    pnl_var_95: float = 0.0

    @property
    def var_max_95(self) -> float:
        return self.var_for_limits_95

    @property
    def var_max_99(self) -> float:
        return self.var_for_limits_99


def _dispersion(values: Sequence[float]) -> float:
    lo = min(values)
    hi = max(values)
    if lo < 1e-12:
        return 0.0
    return hi / lo - 1.0


class RiskEngine:
    """Compute VaR suite from returns or PnL history."""

    def __init__(self, config: Optional[RiskConfig] = None) -> None:
        self.config = config or RiskConfig()

    # ── Primary interface ────────────────────────────────────────────────────

    def compute(
        self,
        returns_history: np.ndarray | Sequence[float],
        positions: Optional[Mapping[str, float]] = None,
        prices: Optional[Mapping[str, float]] = None,
        config: Optional[RiskConfig] = None,
    ) -> RiskMetrics:
        """
        Unified VaR/CVaR suite from return history.

        ``positions`` / ``prices`` reserved for VR-09 decomposition; ignored in VR-01.
        """
        _ = positions, prices
        ret = [float(x) for x in np.asarray(returns_history, dtype=float).ravel().tolist()]
        cfg = config if config is not None else self.config

        if len(ret) < 5:
            return RiskMetrics()

        # ── 95% suite ────────────────────────────────────────────────────────
        vh95 = historical_var(ret, 0.95, horizon_days=1)
        vp95 = parametric_var(
            ret, 0.95, horizon_days=1,
            z=cfg.parametric_z_95,
            dist=cfg.parametric_dist,
            df=cfg.student_t_df,
        )
        vm95 = monte_carlo_var(
            ret, 0.95, horizon_days=1,
            draws=cfg.monte_carlo_draws, seed=cfg.monte_carlo_seed,
        )
        vars95 = [vh95, vp95, vm95]
        vlim95 = max(vars95) if cfg.limit_aggregator == "max" else float(np.mean(vars95))

        # ── 99% suite ────────────────────────────────────────────────────────
        vh99 = historical_var(ret, 0.99, horizon_days=1)
        vp99 = parametric_var(
            ret, 0.99, horizon_days=1,
            z=cfg.parametric_z_99,
            dist=cfg.parametric_dist,
            df=cfg.student_t_df,
        )
        vm99 = monte_carlo_var(
            ret, 0.99, horizon_days=1,
            draws=cfg.monte_carlo_draws, seed=cfg.monte_carlo_seed,
        )
        vars99 = [vh99, vp99, vm99]
        vlim99 = max(vars99) if cfg.limit_aggregator == "max" else float(np.mean(vars99))

        # ── 97.5% (Basel FRTB horizon) ───────────────────────────────────────
        vh975 = historical_var(ret, 0.975, horizon_days=1)

        # ── Cornish-Fisher VaR (VR-03) ──────────────────────────────────────
        cf95 = cornish_fisher_var(ret, 0.95, horizon_days=1)
        cf99 = cornish_fisher_var(ret, 0.99, horizon_days=1)

        # ── CVaR ─────────────────────────────────────────────────────────────
        cv95 = historical_cvar(ret, 0.95)
        cv975 = historical_cvar(ret, cfg.cvar_primary_conf)
        cv99 = historical_cvar(ret, cfg.cvar_secondary_conf)

        # ── Dispersion ───────────────────────────────────────────────────────
        disp95 = _dispersion(vars95)
        disp99 = _dispersion(vars99)
        dispersion = max(disp95, disp99)

        return RiskMetrics(
            var_95_1d=vlim95,
            var_99_1d=vlim99,
            var_975_1d=vh975,
            cvar_95_1d=cv95,
            cvar_975_1d=cv975,
            cvar_99_1d=cv99,
            var_historical_95=vh95,
            var_parametric_95=vp95,
            var_monte_carlo_95=vm95,
            var_for_limits_95=vlim95,
            var_historical_99=vh99,
            var_parametric_99=vp99,
            var_monte_carlo_99=vm99,
            var_for_limits_99=vlim99,
            var_cornish_fisher_95=cf95,
            var_cornish_fisher_99=cf99,
            model_dispersion_pct=max(0.0, dispersion),
        )

    # ── Legacy live-tick interface (RiskOntology compat) ─────────────────────

    def compute_from_pnl_history(
        self,
        pnl_history: Sequence[float],
        *,
        confidence: float = 0.95,
        min_obs: Optional[int] = None,
    ) -> float:
        """
        Live tick legacy: signed PnL at percentile (risk_ontology var_1d).
        Not a return fraction — preserves pre-VR-01 semantics.
        """
        min_n = min_obs if min_obs is not None else self.config.var_history_min_obs
        hist = list(pnl_history)
        if len(hist) < min_n:
            return 0.0
        return round(float(np.percentile(hist, (1.0 - confidence) * 100.0)), 2)
