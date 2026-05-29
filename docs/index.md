# super_otonom v7

Institutional-grade crypto trading system with a 27-module Basel III/FRTB risk engine.

## Highlights

| Capability | Detail |
|---|---|
| **VaR Suite** | Historical, Parametric (Student-t), Monte Carlo, Cornish-Fisher |
| **CVaR / ES** | 3 methods at 95/97.5/99% — Basel FRTB aligned |
| **EVT** | GPD Peaks-Over-Threshold with adaptive bootstrap |
| **Stressed VaR** | Basel 2.5 — 5 crypto stress periods + forward-looking scenarios |
| **Backtesting** | Kupiec POF, Christoffersen Independence, Basel Traffic Light |
| **Execution** | TWAP/VWAP algo engine, pre-trade marginal VaR gate |
| **Observability** | Prometheus metrics, Grafana dashboards, daily risk reports |
| **HA** | Redis leader election, state replication |
| **CI** | pytest (1 000+ tests), mutation testing (mutmut), coverage gate |

## Quick Links

- [Developer Onboarding](onboarding.md) — environment setup, first test, PR workflow
- [Architecture Overview](architecture.md) — data flow, module map, risk chain
- [Risk Engine API](api/risk-engine.md) — `RiskEngine.compute()` reference
- [Changelog](CHANGELOG.md) — release history
