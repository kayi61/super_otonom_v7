"""Unified risk engine — VaR / CVaR (VR-01+)."""

from super_otonom.risk.config import RiskConfig
from super_otonom.risk.cvar_models import historical_cvar, mc_cvar, parametric_cvar
from super_otonom.risk.evt import pot_var_cvar
from super_otonom.risk.fhs import fhs_var_cvar
from super_otonom.risk.lvar import bdss_lvar, compute_lvar, time_to_liquidate_lvar
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
from super_otonom.risk.var_decomposition import (
    component_var,
    compute_var_decomposition,
    incremental_var,
    marginal_var,
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
]
