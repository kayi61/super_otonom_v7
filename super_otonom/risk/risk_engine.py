"""Unified risk engine — single VaR/CVaR source (VR-01 through VR-11)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence

import numpy as np

from super_otonom.risk.config import RiskConfig
from super_otonom.risk.cvar_models import historical_cvar, mc_cvar, parametric_cvar
from super_otonom.risk.evt import pot_var_cvar
from super_otonom.risk.fhs import fhs_var_cvar
from super_otonom.risk.lvar import compute_lvar
from super_otonom.risk.var_decomposition import compute_var_decomposition
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

    # ── CVaR / Expected Shortfall (max of 3 methods) ──────────────────────
    cvar_95_1d: float = 0.0
    cvar_975_1d: float = 0.0
    cvar_99_1d: float = 0.0

    # ── Per-method CVaR breakdown (95%) ─────────────────────────────────────
    cvar_historical_95: float = 0.0
    cvar_parametric_95: float = 0.0
    cvar_monte_carlo_95: float = 0.0

    # ── Per-method CVaR breakdown (99%) ─────────────────────────────────────
    cvar_historical_99: float = 0.0
    cvar_parametric_99: float = 0.0
    cvar_monte_carlo_99: float = 0.0

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

    # ── EVT Peaks Over Threshold (VR-06) ─────────────────────────────────────
    var_evt_99: Optional[float] = None
    cvar_evt_99: Optional[float] = None

    # ── Filtered Historical Simulation (VR-07) ──────────────────────────────
    var_fhs_95: Optional[float] = None
    var_fhs_99: Optional[float] = None
    cvar_fhs_95: Optional[float] = None
    cvar_fhs_99: Optional[float] = None

    # ── Model risk ───────────────────────────────────────────────────────────
    model_dispersion_pct: float = 0.0

    # ── Stressed VaR (VR-11 Basel 2.5) ────────────────────────────────────
    stressed_var: float = 0.0
    stressed_var_worst_period: str = ""
    stressed_var_breach: bool = False

    # ── Liquidity-adjusted VaR (VR-08) ──────────────────────────────────────
    lvar: float = 0.0
    lvar_data_health: float = 0.0

    # ── Decomposition (VR-09) ──────────────────────────────────────────────
    component_var_per_position: Dict[str, float] = field(default_factory=dict)
    marginal_var_per_position: Dict[str, float] = field(default_factory=dict)

    # ── Regime-conditional VaR (VR-10) ──────────────────────────────────────
    var_regime_conditional_95: Optional[float] = None
    var_regime_conditional_99: Optional[float] = None
    current_regime: Optional[str] = None

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
        *,
        asset_returns: Optional[Mapping[str, Sequence[float]]] = None,
        spread_history: Optional[Sequence[float]] = None,
        position_notional: float = 0.0,
        position_qty: float = 0.0,
        adv: float = 0.0,
        current_regime: Optional[str] = None,
        regime_var: Any = None,
        stress_returns: Optional[Dict[str, Sequence[float]]] = None,
    ) -> RiskMetrics:
        """
        Unified VaR/CVaR suite from return history.

        ``positions`` — weight dict {symbol: weight} for VR-09 decomposition.
        ``asset_returns`` — per-symbol return series for VR-09 decomposition.
        ``prices`` — reserved for future use.
        ``spread_history`` / ``position_notional`` / ``position_qty`` / ``adv``
        are used for LVaR (VR-08).
        ``current_regime`` / ``regime_var`` — VR-10 regime-conditional VaR.
        Limit = max(overall, regime-conditional).
        ``stress_returns`` — VR-11 stressed VaR (Basel 2.5).
        """
        _ = prices
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

        # ── Regime-conditional VaR (VR-10) ──────────────────────────────────
        rc_var95: Optional[float] = None
        rc_var99: Optional[float] = None
        regime_label: Optional[str] = None
        if current_regime and regime_var is not None:
            rc_metrics = regime_var.var_for_current(current_regime, cfg)
            if rc_metrics is not None:
                rc_var95 = rc_metrics.var_for_limits_95
                rc_var99 = rc_metrics.var_for_limits_99
                regime_label = current_regime
                vlim95 = max(vlim95, rc_var95)
                vlim99 = max(vlim99, rc_var99)

        # ── 97.5% (Basel FRTB horizon) ───────────────────────────────────────
        vh975 = historical_var(ret, 0.975, horizon_days=1)

        # ── Cornish-Fisher VaR (VR-03) ──────────────────────────────────────
        cf95 = cornish_fisher_var(ret, 0.95, horizon_days=1)
        cf99 = cornish_fisher_var(ret, 0.99, horizon_days=1)

        # ── CVaR / Expected Shortfall (VR-04: 3 methods) ─────────────────────
        # 95% suite
        cvh95 = historical_cvar(ret, 0.95)
        cvp95 = parametric_cvar(
            ret, 0.95, dist=cfg.parametric_dist, df=cfg.student_t_df,
        )
        cvm95 = mc_cvar(
            ret, 0.95, draws=cfg.monte_carlo_draws, seed=cfg.monte_carlo_seed,
        )
        cv95 = max(cvh95, cvp95, cvm95)

        # 99% suite
        cvh99 = historical_cvar(ret, cfg.cvar_secondary_conf)
        cvp99 = parametric_cvar(
            ret, cfg.cvar_secondary_conf,
            dist=cfg.parametric_dist, df=cfg.student_t_df,
        )
        cvm99 = mc_cvar(
            ret, cfg.cvar_secondary_conf,
            draws=cfg.monte_carlo_draws, seed=cfg.monte_carlo_seed,
        )
        cv99 = max(cvh99, cvp99, cvm99)

        # 97.5% Basel FRTB
        cv975 = max(
            historical_cvar(ret, cfg.cvar_primary_conf),
            parametric_cvar(
                ret, cfg.cvar_primary_conf,
                dist=cfg.parametric_dist, df=cfg.student_t_df,
            ),
            mc_cvar(
                ret, cfg.cvar_primary_conf,
                draws=cfg.monte_carlo_draws, seed=cfg.monte_carlo_seed,
            ),
        )

        # ── EVT Peaks Over Threshold (VR-06) ────────────────────────────────
        evt_var99, evt_cvar99 = pot_var_cvar(ret, conf=0.99, threshold_quantile=0.95)

        # ── Filtered Historical Simulation (VR-07) ──────────────────────────
        fhs_v95, fhs_cv95, fhs_v99, fhs_cv99 = None, None, None, None
        if "fhs" in cfg.use_models:
            fhs_v95, fhs_cv95 = fhs_var_cvar(ret, conf=0.95, seed=cfg.monte_carlo_seed)
            fhs_v99, fhs_cv99 = fhs_var_cvar(ret, conf=0.99, seed=cfg.monte_carlo_seed)

        # ── Liquidity-adjusted VaR (VR-08) ──────────────────────────────────
        lvar_val, lvar_dh = compute_lvar(
            var_market=vlim95,
            position_notional=position_notional,
            spread_history=spread_history,
            position_qty=position_qty,
            adv=adv,
            participation_rate=cfg.lvar_participation_rate,
            method=cfg.lvar_method,
        )

        # ── Stressed VaR — Basel 2.5 (VR-11) ────────────────────────────────
        svar_val = 0.0
        svar_period = ""
        svar_breach = False
        if stress_returns:
            from super_otonom.risk.stressed_var import StressedVaR

            svar_engine = StressedVaR(stress_returns)
            svar_result = svar_engine.compute(
                ret, conf=0.99, var_99_for_limit=vlim99,
            )
            svar_val = svar_result.stressed_var
            svar_period = svar_result.worst_period
            svar_breach = svar_result.breach

        # ── Dispersion ───────────────────────────────────────────────────────
        disp95 = _dispersion(vars95)
        disp99 = _dispersion(vars99)
        dispersion = max(disp95, disp99)

        # ── VaR decomposition (VR-09) ───────────────────────────────────────
        comp_var: Dict[str, float] = {}
        marg_var: Dict[str, float] = {}
        if positions and asset_returns:
            comp_var, marg_var = compute_var_decomposition(
                asset_returns, positions, vlim95,
            )

        return RiskMetrics(
            var_95_1d=vlim95,
            var_99_1d=vlim99,
            var_975_1d=vh975,
            cvar_95_1d=cv95,
            cvar_975_1d=cv975,
            cvar_99_1d=cv99,
            cvar_historical_95=cvh95,
            cvar_parametric_95=cvp95,
            cvar_monte_carlo_95=cvm95,
            cvar_historical_99=cvh99,
            cvar_parametric_99=cvp99,
            cvar_monte_carlo_99=cvm99,
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
            var_evt_99=evt_var99,
            cvar_evt_99=evt_cvar99,
            var_fhs_95=fhs_v95,
            var_fhs_99=fhs_v99,
            cvar_fhs_95=fhs_cv95,
            cvar_fhs_99=fhs_cv99,
            stressed_var=svar_val,
            stressed_var_worst_period=svar_period,
            stressed_var_breach=svar_breach,
            lvar=lvar_val,
            lvar_data_health=lvar_dh,
            model_dispersion_pct=max(0.0, dispersion),
            component_var_per_position=comp_var,
            marginal_var_per_position=marg_var,
            var_regime_conditional_95=rc_var95,
            var_regime_conditional_99=rc_var99,
            current_regime=regime_label,
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
