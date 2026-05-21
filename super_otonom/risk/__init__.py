"""Unified risk engine — VaR / CVaR (VR-01+)."""

from super_otonom.risk.config import RiskConfig
from super_otonom.risk.cvar_models import historical_cvar, mc_cvar, parametric_cvar
from super_otonom.risk.evt import pot_var_cvar
from super_otonom.risk.fhs import fhs_var_cvar
from super_otonom.risk.lvar import bdss_lvar, compute_lvar, time_to_liquidate_lvar
from super_otonom.risk.pnl_attribution import (
    PNL_DRIFT_THRESHOLD,
    PNL_DRIFT_THRESHOLD_BPS,
    PnLAttribution,
    PnLAttributionSeries,
    SimpleTrade,
    attribute_pnl,
    attribute_pnl_series,
    attribution_to_dict,
    generate_attribution_report,
)
from super_otonom.risk.position_sizer_var import (
    MarginalVarEngine,
    VarAwarePositionSizer,
    VarCapResult,
    size_with_var_cap,
    var_cap_result_to_dict,
)
from super_otonom.risk.pre_trade_var_gate import (
    PreTradeVarLimits,
    PreTradeVarResult,
    gate_result_to_dict,
    pre_trade_var_check,
    pre_trade_var_check_batch,
    simulate_trade_weights,
)
from super_otonom.risk.regime_var import RegimeConditionalVaR
from super_otonom.risk.risk_engine import RiskEngine, RiskMetrics
from super_otonom.risk.stress_scenarios import (
    ForwardStressResult,
    ReverseStressResult,
    StressGridResult,
    StressScenario,
    forward_stress,
    generate_stress_report,
    load_scenarios,
    reverse_stress,
    run_stress_grid,
)
from super_otonom.risk.stressed_var import StressedVaR, compute_stressed_var
from super_otonom.risk.var_backtest import (
    BASEL_WINDOW,
    ChristoffersenResult,
    ConditionalCoverageResult,
    KupiecResult,
    TrafficLightResult,
    basel_traffic_light,
    basel_traffic_light_from_pnl,
    christoffersen_cc,
    christoffersen_ind,
    kupiec_pof,
    run_backtest_suite,
    run_cc_suite,
)
from super_otonom.risk.var_decomposition import (
    component_var,
    compute_var_decomposition,
    incremental_var,
    marginal_var,
)
from super_otonom.risk.var_limits import (
    VaRLimits,
    check_limits,
    load_var_limits,
)
from super_otonom.risk.var_models import (
    cornish_fisher_var,
    historical_var,
    monte_carlo_var,
    parametric_var,
)

__all__ = [
    "RiskConfig",
    "RiskEngine",
    "RiskMetrics",
    "cornish_fisher_var",
    "historical_var",
    "parametric_var",
    "monte_carlo_var",
    "historical_cvar",
    "parametric_cvar",
    "mc_cvar",
    "pot_var_cvar",
    "fhs_var_cvar",
    "bdss_lvar",
    "time_to_liquidate_lvar",
    "compute_lvar",
    "compute_var_decomposition",
    "marginal_var",
    "component_var",
    "incremental_var",
    "RegimeConditionalVaR",
    "StressedVaR",
    "compute_stressed_var",
    "StressScenario",
    "ForwardStressResult",
    "StressGridResult",
    "ReverseStressResult",
    "forward_stress",
    "reverse_stress",
    "run_stress_grid",
    "load_scenarios",
    "generate_stress_report",
    "KupiecResult",
    "kupiec_pof",
    "run_backtest_suite",
    "ChristoffersenResult",
    "ConditionalCoverageResult",
    "christoffersen_ind",
    "christoffersen_cc",
    "run_cc_suite",
    "TrafficLightResult",
    "BASEL_WINDOW",
    "basel_traffic_light",
    "basel_traffic_light_from_pnl",
    "PnLAttribution",
    "PnLAttributionSeries",
    "SimpleTrade",
    "PNL_DRIFT_THRESHOLD",
    "PNL_DRIFT_THRESHOLD_BPS",
    "attribute_pnl",
    "attribute_pnl_series",
    "attribution_to_dict",
    "generate_attribution_report",
    "PreTradeVarLimits",
    "PreTradeVarResult",
    "pre_trade_var_check",
    "pre_trade_var_check_batch",
    "simulate_trade_weights",
    "gate_result_to_dict",
    "MarginalVarEngine",
    "VarAwarePositionSizer",
    "VarCapResult",
    "size_with_var_cap",
    "var_cap_result_to_dict",
    "VaRLimits",
    "load_var_limits",
    "check_limits",
]
