# Risk Engine

The unified VaR/CVaR computation engine. One call to `compute()` returns all
risk metrics — VaR at multiple confidences, CVaR, EVT, FHS, stressed VaR,
liquidity VaR, and decomposition.

## RiskMetrics

::: super_otonom.risk.risk_engine.RiskMetrics
    options:
      show_source: false
      members: false

### Fields

| Field | Type | VR | Description |
|---|---|---|---|
| `var_95_1d` / `var_99_1d` | `float` | 02 | Max-of-3-models VaR |
| `cvar_95_1d` / `cvar_975_1d` / `cvar_99_1d` | `float` | 04 | Max-of-3-methods CVaR |
| `var_cornish_fisher_95/99` | `float` | 03 | Cornish-Fisher expansion |
| `var_evt_99` / `cvar_evt_99` | `Optional[float]` | 06 | EVT GPD (None if < 200 obs) |
| `var_fhs_95/99` / `cvar_fhs_95/99` | `Optional[float]` | 07 | FHS GARCH (None if < 250 obs) |
| `stressed_var` | `float` | 11 | Basel 2.5 stressed VaR |
| `lvar` / `lvar_data_health` | `float` | 08 | Liquidity-adjusted VaR |
| `component_var_per_position` | `Dict[str, float]` | 09 | Euler decomposition |
| `var_regime_conditional_95/99` | `Optional[float]` | 10 | Regime-conditional VaR |
| `var_10d_99` / `cvar_10d_975` | `float` | FRTB | 10-day Basel scaling |

## RiskEngine

::: super_otonom.risk.risk_engine.RiskEngine
    options:
      members:
        - __init__
        - compute
