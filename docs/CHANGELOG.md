# Changelog

Full release history is maintained automatically by
[Release Please](https://github.com/google-github-opensource/release-please).

See the canonical [CHANGELOG.md](https://github.com/kayi61/super_otonom_v7/blob/main/CHANGELOG.md)
in the repository root for all entries from v5.0.0 through v7.3.0+.

## Release Summary

| Version | Date | Highlights |
|---|---|---|
| **7.3.0** | 2026-05-29 | EVT adaptive threshold, forward-looking stress scenarios, MC 2000 draws |
| **7.2.0** | 2026-05-28 | Flat package refactor (core/trading/analysis/monitoring/audit), BotEngine decomposition |
| **7.1.1** | 2026-05-27 | Nightly Kupiec CI fix for missing input files |
| **7.1.0** | 2026-05-26 | VR-01 through VR-27 complete, Faz A-D integration, Prompts 3-14 |
| **7.0.0** | 2026-04-25 | Version unification, VR roadmap launch |
| **6.1.0** | 2026-04-24 | main_loop rewrite, exchange_async, risk_manager format fix |
| **6.0.0** | 2026-04-24 | Correlation + Sentiment layer |
| **5.1.0** | 2026-04-24 | 3-layer safety filter, dynamic risk, 4H trend |
| **5.0.0** | 2026-04-23 | Hurst regime, CircuitBreaker, Prometheus, AI reasoning |

## VR Roadmap (v7.0.0 → v7.3.0)

All 27 VaR/CVaR modules shipped across v7.0.0 through v7.1.0:

| VR | Module | PR |
|---|---|---|
| VR-01 | Unified RiskEngine | #18 |
| VR-02 | VaR Models (Hist/Param/MC) | #19 |
| VR-03 | Cornish-Fisher VaR | #20 |
| VR-04 | CVaR / Expected Shortfall | #21 |
| VR-05 | RiskConfig Basel alignment | #22 |
| VR-06 | EVT Peaks Over Threshold | #23 |
| VR-07 | Filtered Historical Sim (FHS) | #24 |
| VR-08 | Liquidity-adjusted VaR (LVaR) | #25 |
| VR-09 | VaR Decomposition (Component/Marginal/Incremental) | #26 |
| VR-10 | Regime-Conditional VaR | #27 |
| VR-11 | Stressed VaR (Basel 2.5) | #28 |
| VR-12 | Stress Scenario Library + Reverse Stress | #29 |
| VR-13 | Kupiec POF Backtest | #30 |
| VR-14 | Christoffersen Independence + CC | #31 |
| VR-15 | Basel Traffic Light Backtest | #32 |
| VR-16 | P&L Attribution + Drift Detection | #33 |
| VR-17 | Pre-trade Marginal VaR Gate | #34 |
| VR-18 | VaR-aware Position Sizing (Kelly + VaR Cap) | #35 |
| VR-19 | Kill-switch (VaR/CVaR Breach Trigger) | #37 |
| VR-20 | VaR Limit Hierarchy (Strategy/Portfolio/Firm) | #38 |
| VR-21 | Prometheus VaR/CVaR/Stress Metrics | #39 |
| VR-22 | Daily Risk Report | #40 |
| VR-23 | Grafana Risk Dashboard | #41 |
| VR-24 | Model Inventory + Validation Governance | #42 |
| VR-25 | Risk Appetite + Escalation Matrix | #43 |
| VR-26 | Property-Based VaR/CVaR Invariants (Hypothesis) | #44 |
| VR-27 | Regime Detection Engine | #46 |

## Integration Phases (v7.1.0)

| Phase | PR | Content |
|---|---|---|
| Faz A | #47 | Acil test fixes, tracker, exports, stubs |
| Faz B | #49 | BotEngine ↔ RiskEngine full wiring |
| Faz C | #50 | 10-day VaR, CI workflows, model governance |
| Faz D | #51 | Polish & documentation |

## Prompt Releases (v7.1.0 → v7.3.0)

| Prompt | Version | PR | Content |
|---|---|---|---|
| Prompt 03 | 7.1.0 | #83 | Backup/DR automation |
| Prompt 04 | 7.2.0 | #87 | Flat package refactor |
| Prompt 05 | 7.2.0 | #89 | BotEngine god-class decomposition |
| Prompt 06 | 7.3.0 | #91 | Integration tests + phase coverage |
| Prompt 07 | 7.3.0 | #93 | EVT adaptive threshold + forward-looking stress |
