# Architecture Overview

## System Context

super_otonom is a crypto trading bot with an institutional-grade risk engine.
It connects to exchanges via CCXT, runs a tick-based trading loop, and enforces
Basel III/FRTB risk limits on every trade decision.

```mermaid
graph LR
    EX[Binance API] -->|WebSocket + REST| BOT[BotEngine]
    BOT -->|returns| RISK[RiskEngine]
    RISK -->|RiskMetrics| BOT
    BOT -->|orders| OE[OrderEngine]
    OE -->|execution| EX
    BOT -->|metrics| PROM[Prometheus]
    PROM --> GRAF[Grafana]
    BOT -->|state| PG[(PostgreSQL)]
    BOT -->|secrets| VAULT[Vault]
    BOT -->|cache/HA| REDIS[(Redis)]
```

## Core Loop (Tick Pipeline)

Each tick follows this pipeline:

```mermaid
sequenceDiagram
    participant ML as MainLoop
    participant BE as BotEngine
    participant AN as Analyzer
    participant RE as RiskEngine
    participant PT as PreTradeGate
    participant PS as PositionSizer
    participant OE as OrderEngine

    ML->>BE: _tick_impl(candle)
    BE->>AN: analyze(candle)
    AN-->>BE: signal (BUY/SELL/HOLD)
    BE->>RE: compute(returns_history)
    RE-->>BE: RiskMetrics
    alt BUY signal
        BE->>PT: pre_trade_var_check(trade, metrics)
        PT-->>BE: allow / reject
        BE->>PS: size_with_var_cap(kelly, metrics)
        PS-->>BE: capped quantity
        BE->>OE: place_order(symbol, qty)
    end
    BE->>BE: record_return(pnl)
    BE->>BE: prometheus.record_var_suite(metrics)
```

## Risk Engine Pipeline

`RiskEngine.compute()` executes this chain on every call:

```mermaid
flowchart TD
    RET[returns_history] --> V95[VaR 95%<br/>hist / param / MC]
    RET --> V99[VaR 99%<br/>hist / param / MC]
    RET --> CF[Cornish-Fisher<br/>VR-03]
    RET --> CVaR[CVaR / ES<br/>VR-04]
    RET --> EVT[EVT / GPD<br/>VR-06]
    RET --> FHS[FHS GARCH<br/>VR-07]

    V95 --> LIM95[var_for_limits_95<br/>max aggregation]
    V99 --> LIM99[var_for_limits_99<br/>max aggregation]

    LIM99 --> SVAR[Stressed VaR<br/>VR-11 Basel 2.5]
    LIM99 --> LVAR[Liquidity VaR<br/>VR-08 BDSS/TTL]
    LIM99 --> DECOMP[VaR Decomposition<br/>VR-09 Euler]
    LIM99 --> REGIME[Regime VaR<br/>VR-10]
    LIM99 --> TEN[10-day VaR<br/>FRTB sqrt 10]

    SVAR --> RM[RiskMetrics]
    LVAR --> RM
    DECOMP --> RM
    REGIME --> RM
    TEN --> RM
    LIM95 --> RM
    LIM99 --> RM
    CF --> RM
    CVaR --> RM
    EVT --> RM
    FHS --> RM
```

## VaR Model Zoo

| # | Model | Module | Key Function |
|---|---|---|---|
| VR-02 | Historical VaR | `var_models.py` | `historical_var()` |
| VR-02 | Parametric VaR (Student-t) | `var_models.py` | `parametric_var()` |
| VR-02 | Monte Carlo VaR | `var_models.py` | `monte_carlo_var()` |
| VR-03 | Cornish-Fisher VaR | `var_models.py` | `cornish_fisher_var()` |
| VR-04 | CVaR (3 methods) | `cvar_models.py` | `historical_cvar()`, `parametric_cvar()`, `mc_cvar()` |
| VR-06 | EVT / GPD | `evt.py` | `pot_var_cvar()` |
| VR-07 | FHS GARCH(1,1) | `fhs.py` | `fhs_var_cvar()` |
| VR-08 | Liquidity VaR | `lvar.py` | `compute_lvar()` |
| VR-09 | VaR Decomposition | `var_decomposition.py` | `compute_var_decomposition()` |
| VR-10 | Regime VaR | `regime_var.py` | `RegimeConditionalVaR` |
| VR-11 | Stressed VaR | `stressed_var.py` | `compute_stressed_var()` |

## Limit Enforcement Chain

```mermaid
flowchart LR
    TICK[Tick] --> VL[VaR Limits<br/>VR-20: Strategy / Portfolio / Firm]
    VL -->|breach| KS[Kill-switch<br/>VR-19]
    KS -->|liquidate| OE[OrderEngine]
    VL -->|ok| PTG[Pre-trade Gate<br/>VR-17]
    PTG -->|reject| HOLD[Hold]
    PTG -->|allow| PS[Position Sizer<br/>VR-18 Kelly + VaR Cap]
    PS --> OE
```

## Backtesting & Validation

| Test | Module | Standard |
|---|---|---|
| Kupiec POF | `var_backtest.py` | Kupiec (1995) |
| Christoffersen CC | `var_backtest.py` | Christoffersen (1998) |
| Basel Traffic Light | `var_backtest.py` | Basel Committee |
| P&L Attribution | `pnl_attribution.py` | Unexplained drift detection |
| Property-based | `test_var_properties_vr26.py` | Hypothesis invariants |
| Mutation testing | CI (mutmut) | 80% kill-rate gate |

## Observability Stack

```mermaid
graph TD
    BOT[BotEngine] -->|push| PROM[Prometheus<br/>VR-21 gauges]
    PROM --> GRAF[Grafana<br/>VR-23 dashboards]
    PROM --> AM[AlertManager]
    AM --> TG[Telegram Bridge]
    BOT -->|daily| RPT[Risk Report<br/>VR-22]
    RPT --> GH[GitHub Issue<br/>nightly CI]
```

### Key Prometheus Metrics

- `bot_var_99_pct`, `bot_cvar_975_pct` — core risk
- `bot_var_10d_99_pct`, `bot_cvar_10d_975_pct` — Basel FRTB
- `bot_stressed_var_pct` — Basel 2.5
- `bot_var_liquidity_adjusted` — LVaR per symbol
- `bot_kupiec_pvalue` — backtest health
- `bot_stress_worst_scenario_pnl_pct` — stress grid

## Package Layout

```text
super_otonom_v7/
├── super_otonom/           # Main package (102 modules)
│   ├── core/               # BotEngine, MainLoop, Config, StateMachine
│   ├── trading/            # OrderEngine, PositionSizer, StagedExit
│   ├── risk/               # 18 modules — VaR/CVaR/EVT/FHS/LVaR/...
│   ├── execution/          # TWAP, VWAP
│   ├── signals/            # 12 signal modules
│   ├── ha/                 # Leader election, health, replication
│   ├── infra/              # Redis, Vault, Timescale, logging
│   ├── analysis/           # Analyzer, CorrelationManager
│   ├── monitoring/         # Prometheus, AlertManager, deploy checks
│   ├── audit/              # Topology audits, drift checks
│   └── pipelines/          # Data pipelines
├── tests/                  # 1000+ tests
│   ├── risk/               # 27 VR test files + fixtures
│   └── branch/             # Branch-matrix mutation tests
├── docs/                   # Documentation (this site)
├── data/                   # Fixtures, manifests, stress grids
├── scripts/                # Mutation gates, backup, DR
├── .github/workflows/      # 9 CI/CD workflows
├── docker-compose.yml      # Full stack
└── pyproject.toml          # Build config
```

## CI Pipeline

```mermaid
flowchart LR
    PR[Pull Request] --> CQ[ci-quick<br/>ruff + smoke]
    PR --> PF[pytest-full]
    PR --> COV[coverage<br/>3.10 + 3.12]
    PR --> INT[integration-test]
    PR --> GO[go-build]
    PR --> KD[kanon-drift]
    PR --> WIN[release-gate<br/>windows]
    PR --> MUT[mutation-testing<br/>if risk/ changed]
    PR --> SEC[security<br/>pip-audit]

    CQ & PF & COV & INT & GO & KD & WIN --> MERGE[Merge]
    MERGE --> RP[Release Please]
    RP --> CD[CD: Docker + Deploy]
```
