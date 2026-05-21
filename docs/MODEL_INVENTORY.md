# Model Inventory — VaR / CVaR / Risk Engine (VR-24)

Model envanteri, Basel III / FRTB model risk yönetişimi çerçevesinde
tüm risk modellerini, geliştirici/validatör atamalarını ve validasyon
takvimini takip eder.

**KURAL:** Model developer ≠ Model validator (bağımsız validasyon ilkesi).

## Model Registry

| Model ID | Model Name | VR | Module | Type | Developer | Validator | Last Validated | Next Due | Status |
|----------|------------|-----|--------|------|-----------|-----------|---------------|----------|--------|
| MR-VAR-HIST | Historical VaR | VR-02 | `risk/var_models.py` | VaR | quant-dev | risk-review | 2026-04-01 | 2026-10-01 | Active |
| MR-VAR-PARAM | Parametric VaR (Student-t) | VR-02 | `risk/var_models.py` | VaR | quant-dev | risk-review | 2026-04-01 | 2026-10-01 | Active |
| MR-VAR-MC | Monte Carlo VaR | VR-02 | `risk/var_models.py` | VaR | quant-dev | risk-review | 2026-04-01 | 2026-10-01 | Active |
| MR-VAR-CF | Cornish-Fisher VaR | VR-03 | `risk/var_models.py` | VaR | quant-dev | risk-review | 2026-04-01 | 2026-10-01 | Active |
| MR-CVAR-HIST | Historical CVaR / ES | VR-04 | `risk/cvar_models.py` | CVaR | quant-dev | risk-review | 2026-04-01 | 2026-10-01 | Active |
| MR-CONFIG | RiskConfig Basel Alignment | VR-05 | `risk/config.py` | Config | quant-dev | risk-review | 2026-04-01 | 2026-10-01 | Active |
| MR-CVAR-PARAM | Parametric CVaR (Student-t) | VR-04 | `risk/cvar_models.py` | CVaR | quant-dev | risk-review | 2026-04-01 | 2026-10-01 | Active |
| MR-CVAR-MC | Monte Carlo CVaR | VR-04 | `risk/cvar_models.py` | CVaR | quant-dev | risk-review | 2026-04-01 | 2026-10-01 | Active |
| MR-EVT | EVT Peaks Over Threshold | VR-06 | `risk/evt.py` | VaR/CVaR | quant-dev | risk-review | 2026-04-01 | 2026-10-01 | Active |
| MR-FHS | Filtered Historical Sim | VR-07 | `risk/fhs.py` | VaR/CVaR | quant-dev | risk-review | 2026-04-01 | 2026-10-01 | Active |
| MR-LVAR | Liquidity-adjusted VaR | VR-08 | `risk/lvar.py` | LVaR | quant-dev | risk-review | 2026-04-01 | 2026-10-01 | Active |
| MR-DECOMP | VaR Decomposition (Euler) | VR-09 | `risk/var_decomposition.py` | Decomp | quant-dev | risk-review | 2026-04-01 | 2026-10-01 | Active |
| MR-REGIME | Regime-Conditional VaR | VR-10 | `risk/regime_var.py` | VaR | quant-dev | risk-review | 2026-04-01 | 2026-10-01 | Active |
| MR-SVAR | Stressed VaR (Basel 2.5) | VR-11 | `risk/stressed_var.py` | SVaR | quant-dev | risk-review | 2026-04-01 | 2026-10-01 | Active |
| MR-STRESS | Stress Scenario Library | VR-12 | `risk/stress_scenarios.py` | Stress | quant-dev | risk-review | 2026-04-01 | 2026-10-01 | Active |
| MR-KUPIEC | Kupiec POF Backtest | VR-13 | `risk/var_backtest.py` | Backtest | quant-dev | risk-review | 2026-04-01 | 2026-10-01 | Active |
| MR-CHRIST | Christoffersen CC | VR-14 | `risk/var_backtest.py` | Backtest | quant-dev | risk-review | 2026-04-01 | 2026-10-01 | Active |
| MR-BASEL-TL | Basel Traffic Light | VR-15 | `risk/var_backtest.py` | Backtest | quant-dev | risk-review | 2026-04-01 | 2026-10-01 | Active |
| MR-PNL | P&L Attribution | VR-16 | `risk/pnl_attribution.py` | Attribution | quant-dev | risk-review | 2026-04-01 | 2026-10-01 | Active |
| MR-GATE | Pre-trade VaR Gate | VR-17 | `risk/pre_trade_var_gate.py` | Gate | quant-dev | risk-review | 2026-04-01 | 2026-10-01 | Active |
| MR-SIZER | VaR-aware Position Sizer | VR-18 | `risk/position_sizer_var.py` | Sizer | quant-dev | risk-review | 2026-04-01 | 2026-10-01 | Active |
| MR-KILL | VaR Breach Kill-switch | VR-19 | `risk_manager.py` | Control | quant-dev | risk-review | 2026-04-01 | 2026-10-01 | Active |
| MR-LIMITS | VaR Limit Hierarchy | VR-20 | `risk/var_limits.py` | Limits | quant-dev | risk-review | 2026-04-01 | 2026-10-01 | Active |

## Model Categories

### Value-at-Risk (VaR)
- **MR-VAR-HIST**: Non-parametric percentile, no distribution assumption
- **MR-VAR-PARAM**: Student-t MLE fit, `loss = -(mu + q * sig)`, no scale adjustment
- **MR-VAR-MC**: Single-return bootstrap, `random.Random(seed)` for reproducibility
- **MR-VAR-CF**: Cornish-Fisher expansion with `z_cf >= z` guard

### Conditional VaR / Expected Shortfall (CVaR)
- **MR-CVAR-HIST**: Tail mean of sorted returns
- **MR-CVAR-PARAM**: Kamdem 2005 closed-form for Student-t
- **MR-CVAR-MC**: Bootstrap tail mean

### Advanced Models
- **MR-EVT**: GPD Peaks Over Threshold (min 500 obs, 10+ exceedances)
- **MR-FHS**: GARCH(1,1) filtered simulation (min 250 obs, arch package)
- **MR-LVAR**: BDSS + Time-to-liquidate, conservative max
- **MR-DECOMP**: Euler variance-covariance decomposition, sum invariant
- **MR-REGIME**: Deque-backed per-regime buffers, conservative limit aggregation
- **MR-SVAR**: Basel 2.5 stress-period rescaling, 5 crypto stress periods

### Backtesting & Validation
- **MR-KUPIEC**: Kupiec (1995) POF likelihood-ratio test, χ²(1)
- **MR-CHRIST**: Christoffersen (1998) independence + conditional coverage, χ²(2)
- **MR-BASEL-TL**: Basel Committee traffic light (GREEN/YELLOW/RED zones)

### Operational Risk Controls
- **MR-PNL**: Decomposition with 10 bps drift threshold
- **MR-GATE**: Pre-trade marginal VaR check (<30ms latency target)
- **MR-SIZER**: Kelly criterion + VaR cap position sizing
- **MR-KILL**: 3-trigger emergency stop (VaR 99 / CVaR 97.5 / Stressed VaR)
- **MR-LIMITS**: 3-level hierarchy (Strategy → Portfolio → Firm)
- **MR-STRESS**: 5+ predefined scenarios, forward + reverse stress test

## Validation Cycle

- **Frequency**: Every 6 months (semi-annual) or after material change
- **Material change triggers**: Algorithm modification, new data source, parameter recalibration, confidence level change
- **Escalation**: 30 days before due → CI warning, 0 days → GitHub issue auto-created
- **Independence**: Model developer and model validator must be different roles/persons
- **Template**: See `docs/MODEL_VALIDATION_TEMPLATE.md`

## Governance

| Role | Responsibility |
|------|---------------|
| **quant-dev** | Model development, implementation, unit tests |
| **risk-review** | Independent validation, backtesting review, sign-off |
| **risk-committee** | Approval of new models, exception handling |

## Change Log

| Date | Model ID | Change | Approved By |
|------|----------|--------|------------|
| 2026-04-01 | ALL | Initial inventory creation (VR-01 to VR-20) | risk-committee |
