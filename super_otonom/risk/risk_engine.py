"""Unified risk engine — single VaR/CVaR source (VR-01)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Sequence

import numpy as np

from super_otonom.risk.config import RiskConfig
from super_otonom.risk.cvar_models import historical_cvar
from super_otonom.risk.var_models import historical_var, monte_carlo_var, parametric_var


@dataclass(frozen=True)
class RiskMetrics:
    """Portfolio / limit metrics (fractions unless noted)."""

    var_95_1d: float = 0.0
    var_99_1d: float = 0.0
    cvar_95_1d: float = 0.0
    cvar_99_1d: float = 0.0
    var_historical_95: float = 0.0
    var_parametric_95: float = 0.0
    var_monte_carlo_95: float = 0.0
    var_for_limits_95: float = 0.0
    model_dispersion_pct: float = 0.0
    stressed_var: float = 0.0
    lvar: float = 0.0
    component_var_per_position: Dict[str, float] = field(default_factory=dict)
    marginal_var_per_position: Dict[str, float] = field(default_factory=dict)
    pnl_var_95: float = 0.0


class RiskEngine:
    """Compute VaR suite from returns or PnL history."""

    def __init__(self, config: Optional[RiskConfig] = None) -> None:
        self.config = config or RiskConfig()

    def compute(
        self,
        returns_history: np.ndarray | Sequence[float],
        *,
        positions: Optional[Mapping[str, float]] = None,
        prices: Optional[Mapping[str, float]] = None,
    ) -> RiskMetrics:
        _ = positions, prices
        ret = [float(x) for x in np.asarray(returns_history, dtype=float).ravel().tolist()]
        cfg = self.config

        if len(ret) < 5:
            return RiskMetrics()

        vh95 = historical_var(ret, 0.95, horizon_days=1)
        vp95 = parametric_var(
            ret,
            0.95,
            horizon_days=1,
            z=cfg.parametric_z_95,
        )
        vm95 = monte_carlo_var(
            ret,
            0.95,
            horizon_days=1,
            draws=cfg.monte_carlo_draws,
            seed=cfg.monte_carlo_seed,
        )
        vars95 = [vh95, vp95, vm95]
        vlim95 = max(vars95) if cfg.limit_aggregator == "max" else float(np.mean(vars95))
        lo, hi = min(vars95), max(vars95)
        dispersion = (hi / lo - 1.0) if lo > 1e-12 else 0.0

        vh99 = historical_var(ret, 0.99, horizon_days=1)
        cv95 = historical_cvar(ret, cfg.cvar_primary_conf)
        cv99 = historical_cvar(ret, 0.99)

        return RiskMetrics(
            var_95_1d=vlim95,
            var_99_1d=vh99,
            cvar_95_1d=cv95,
            cvar_99_1d=cv99,
            var_historical_95=vh95,
            var_parametric_95=vp95,
            var_monte_carlo_95=vm95,
            var_for_limits_95=vlim95,
            model_dispersion_pct=max(0.0, dispersion),
        )

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
