# super_otonom_v7 — Claude Code Project Guide

## Project Overview
Crypto trading bot with institutional-grade risk management. Currently implementing a 27-step VaR/CVaR risk engine upgrade (VR-01 through VR-27) following Basel III/FRTB standards.

**Repo:** https://github.com/kayi61/super_otonom_v7
**Language:** Python 3.12 | **Lint:** ruff | **Test:** pytest | **CI:** GitHub Actions

## Critical User Rules
1. **Her işlem sonunda GitHub PR linkini otomatik gönder** — sormayı bekleme
2. **Token israf etme** — minimum tool call, minimum açıklama, tek seferde bitir
3. **Profesyonel iş yap** — copy-paste değil, gerçek mühendislik

## Development Workflow (Her VR için)
1. `git checkout main && git pull origin main`
2. `git checkout -b feat/vr-XX-kisa-aciklama`
3. Kodu yaz → `ruff check --fix` → `pytest` → commit → push → PR oluştur → **link gönder**
4. CI geçtikten sonra merge → sonraki VR'a geç

## VR Progress Tracker
| VR | Başlık | Durum | PR |
|----|--------|-------|----|
| VR-01 | Unified RiskEngine | ✅ Merged | #18 |
| VR-02 | VaR Models (Hist/Param/MC) | ✅ Merged | #19 |
| VR-03 | Cornish-Fisher VaR | ✅ Merged | #20 |
| VR-04 | CVaR / Expected Shortfall | ✅ Merged | #21 |
| VR-05 | RiskConfig Basel alignment | ✅ Merged | #22 |
| VR-06 | EVT Peaks Over Threshold | ✅ Merged | #23 |
| VR-07 | Filtered Historical Sim (FHS) | ✅ Merged | #24 |
| VR-08 | Liquidity-adjusted VaR (LVaR) | ✅ Merged | #25 |
| VR-09 | Component/Marginal/Incremental VaR decomposition | ✅ Merged | #26 |
| VR-10 | Regime-Conditional VaR | ✅ Merged | #27 |
| VR-11 | Stressed VaR (Basel 2.5) | ✅ Merged | #28 |
| VR-12 | Stress Scenario Library + Reverse Stress Test | ✅ Merged | #29 |
| VR-13 | Kupiec POF Backtest | ✅ Merged | #30 |
| VR-14 | Christoffersen Independence + CC | ✅ Merged | #31 |
| VR-15 | Basel Traffic Light Backtest | ✅ Merged | #32 |
| VR-16 | P&L Attribution + Unexplained PnL Drift | ✅ Merged | #33 |
| VR-17 | Pre-trade Marginal VaR Gate | ✅ Merged | #34 |
| VR-18 | VaR-aware Position Sizing (Kelly + VaR Cap) | ✅ Merged | #35 |
| VR-19 | Kill-switch — VaR/CVaR Breach Trigger | ✅ Merged | #37 |
| VR-20 | VaR Limit Hierarchy (Strategy/Portfolio/Firm) | ✅ Merged | #38 |
| VR-21 | Prometheus VaR/CVaR/Stres Metrikleri — Tam Suite | ✅ Merged | #39 |
| VR-22 | Günlük Risk Raporu — Otomatik Üretim | ✅ Merged | #40 |
| VR-23 | Grafana Risk Dashboard | ✅ Merged | #41 |
| VR-24 | Model Envanteri + Validasyon Yönetişimi | ✅ Merged | #42 |
| VR-25 | Risk Appetite Statement + Escalation Matrisi | ✅ Merged | #43 |
| VR-26 | Property-Based VaR/CVaR Invariants (Hypothesis) | ✅ Merged | #44 |
| VR-27 | Regime Detection Engine (Statistical) | ✅ Merged | #46 |

## Integration Status (Post-VR)
| Faz | Başlık | Durum | PR |
|-----|--------|-------|----|
| Faz A | Acil düzeltmeler (test fix, tracker, exports, stub) | ✅ Merged | #47 |
| Faz B | BotEngine ↔ Risk Engine tam entegrasyon | ✅ Merged | #49 |
| Faz C | 10-day VaR + CI workflows + model governance | ✅ Merged | #50 |
| Faz D | Polish & documentation | ✅ Merged | #51 |

### BotEngine ↔ RiskEngine Wiring (Faz B)
- `BotEngine.__init__`: RiskEngine + RegimeDetector + RegimeConditionalVaR wired
- `BotEngine._tick_impl`: NAV-based return → `risk.record_return()` + regime detection
- VR-21 Prometheus: every 60 ticks → `RiskEngine.compute()` + `record_var_suite()`
- Graceful fallback: risk module errors never crash the bot

### Basel FRTB 10-day VaR (Faz C)
- `RiskMetrics.var_10d_99 = var_for_limits_99 * sqrt(10)`
- `RiskMetrics.cvar_10d_975 = cvar_975_1d * sqrt(10)`
- Prometheus: `bot_var_10d_99_pct`, `bot_cvar_10d_975_pct`

### CI Pipeline (Faz C)
- `nightly-risk-report.yml`: 23:55 UTC daily + model due-date auto-issue
- `ci.yml`: VR-24 model validation + VR-25 risk appetite consistency checks added

## Project Structure (Risk Engine)
```
super_otonom/risk/
├── __init__.py              # Public exports (all models + all VR modules)
├── config.py                # RiskConfig (frozen dataclass, ~25 fields, validate())
├── var_models.py            # VR-02/03: historical_var, parametric_var, monte_carlo_var, cornish_fisher_var
├── cvar_models.py           # VR-04: historical_cvar, parametric_cvar, mc_cvar
├── evt.py                   # VR-06: pot_var_cvar (GPD Peaks Over Threshold)
├── fhs.py                   # VR-07: fhs_var_cvar (GARCH(1,1) Filtered Historical Sim)
├── lvar.py                  # VR-08: bdss_lvar, time_to_liquidate_lvar, compute_lvar
├── var_decomposition.py     # VR-09: compute_var_decomposition, marginal_var, component_var, incremental_var
├── regime_var.py            # VR-10: RegimeConditionalVaR (deque-backed per-regime buffers)
├── regime_detector.py       # VR-27: RegimeDetector (vol-threshold, z-score change-point)
├── stressed_var.py          # VR-11: StressedVaR (Basel 2.5, 5 stress periods, rescaling)
├── stress_scenarios.py      # VR-12: StressScenarioLibrary, forward_stress, reverse_stress
├── var_backtest.py          # VR-13/14/15: kupiec_pof, christoffersen, basel_traffic_light
├── pnl_attribution.py       # VR-16: attribute_pnl, PnLAttribution, drift detection
├── pre_trade_var_gate.py    # VR-17: pre_trade_var_check, marginal VaR gate (<30ms)
├── position_sizer_var.py    # VR-18: VarAwarePositionSizer, size_with_var_cap (Kelly + VaR Cap)
├── var_limits.py            # VR-20: VaRLimits, load_var_limits, check_limits (3-level hierarchy)
└── risk_engine.py           # RiskEngine.compute() → RiskMetrics (~35 fields)
```

## Key Files Outside Risk Package
- `super_otonom/portfolio_risk_engine.py` — analyze_portfolio_risk() uses risk engine
- `super_otonom/risk_ontology.py` — Legacy, uses min_obs=100 (COMPAT — DO NOT CHANGE)
- `super_otonom/risk_manager.py` — Legacy, uses min_obs=100 (COMPAT — DO NOT CHANGE)
- `super_otonom/deploy_env_check.py` — Pre-deploy validation (RiskConfig invariants)
- `super_otonom/metrics_exporter.py` — Prometheus gauges (bot_var_liquidity_adjusted{symbol})
- `super_otonom/var_topology.py` — VaR topology scanner + manifest writer (audit 11)
- `super_otonom/var_topology_audit.py` — Forbidden VaR claim scanner (allowlist: risk/, metrics_exporter, CLAUDE.md)
- `data/var_topology_manifest.json` — Regenerate: `python -m super_otonom.var_topology --write-manifest`
- `pyproject.toml` — Dependencies (scipy>=1.11.0, arch>=7.0.0)

## Test Structure
```
tests/risk/
├── test_var_models_vr02.py         # 50 tests — VaR models
├── test_cornish_fisher_vr03.py     # 28 tests — CF expansion
├── test_cvar_vr04.py               # 37 tests — CVaR/ES
├── test_config_vr05.py             # 30 tests — RiskConfig
├── test_evt_vr06.py                # 26 tests — EVT/POT
├── test_fhs_vr07.py                # 24 tests — FHS/GARCH
├── test_lvar_vr08.py               # 33 tests — LVaR (BDSS + TTL)
├── test_var_decomposition_vr09.py  # 46 tests — Euler decomposition
├── test_regime_var_vr10.py         # 40 tests — Regime-conditional VaR
├── test_stressed_var_vr11.py       # 42 tests — Stressed VaR (Basel 2.5)
├── test_stress_scenarios_vr12.py   # 49 tests — Stress Scenario Library + Reverse Stress
├── test_var_backtest_vr13.py       # 32 tests — Kupiec POF backtest
├── test_christoffersen_vr14.py    # 44 tests — Christoffersen Independence + CC
├── test_basel_traffic_light_vr15.py # 41 tests — Basel Traffic Light
├── test_pnl_attribution_vr16.py   # 38 tests — P&L Attribution + Drift Detection
├── test_pre_trade_var_gate_vr17.py # 36 tests — Pre-trade Marginal VaR Gate
├── test_position_sizer_var_vr18.py # 52 tests — VaR-aware Position Sizing (Kelly + VaR Cap)
├── test_var_breach_kill_switch_vr19.py # 39 tests — VaR/CVaR Breach Kill-switch
├── test_var_limits_hierarchy_vr20.py # 46 tests — VaR Limit Hierarchy
├── test_prometheus_var_suite_vr21.py # 52 tests — Prometheus VaR/CVaR Full Suite
├── test_daily_risk_report_vr22.py  # 52 tests — Daily Risk Report
├── test_grafana_risk_dashboard_vr23.py # 50 tests — Grafana Risk Dashboard
├── test_model_inventory_vr24.py    # 54 tests — Model Inventory + Validation Governance
├── test_risk_appetite_vr25.py     # 43 tests — Risk Appetite + Escalation Matrix
├── test_var_properties_vr26.py    # 34 tests — Property-Based VaR/CVaR Invariants (Hypothesis)
├── test_regime_detector_vr27.py   # 41 tests — Regime Detection Engine (VR-27)
├── test_risk_engine_unified.py     # 23 tests — Unified engine + legacy compat
└── fixtures/
    ├── unified_returns_golden.json          # 120 returns (dict with "returns" key)
    └── historical_stress_returns.json       # 5 crypto stress periods (VR-11)
tests/test_portfolio_risk_engine.py # 9 tests — portfolio integration
tests/test_var_topology_fastrun.py  # 8 tests — topology + manifest + audit
```
**Total risk tests:** 1099 (all passing)

## Technical Details

### VaR Models (VR-02/03)
- **Historical**: Non-parametric percentile
- **Parametric (Student-t)**: `loss = -(mu + q * sig)`, NO scale adjustment, q from `t.ppf`
- **Monte Carlo**: Single-return bootstrap (NOT mean-of-means), `random.Random(seed)`
- **Cornish-Fisher**: `z_cf = z + (z²-1)S/6 + (z³-3z)K/24 - (2z³-5z)S²/36`, guard: `z_cf >= z`

### CVaR Methods (VR-04)
- **Historical**: Tail mean of sorted returns
- **Parametric (Student-t)**: Kamdem 2005 closed-form: `es = -mu + sig * f_t * (df + t²) / ((df-1) * α)`
- **Monte Carlo**: Bootstrap tail mean

### EVT (VR-06)
- **GPD Peaks Over Threshold**: Loss-space formulation (negated returns), threshold = 95th percentile of losses
- Skip if sample < 500 (EVT_MIN_SAMPLE) or exceedances < 10
- `RiskMetrics`: `var_evt_99`, `cvar_evt_99` (Optional[float], None when skipped)

### Filtered Historical Simulation (VR-07)
- **GARCH(1,1)**: `arch.arch_model(returns*100, vol="Garch", p=1, q=1, mean="Constant")`
- Standardized residuals z_t = eps_t / sigma_t, rescaled by forecasted sigma_{t+1}
- Skip if sample < 250 (FHS_MIN_SAMPLE) or GARCH fit fails
- Only runs when `"fhs" in cfg.use_models` (default: enabled)
- `RiskMetrics`: `var_fhs_95/99`, `cvar_fhs_95/99` (Optional[float])

### Liquidity-adjusted VaR (VR-08)
- **BDSS**: `var + 0.5 * notional * (spread_mean + alpha * spread_std)` (alpha = norm.ppf(0.99))
- **Time-to-liquidate**: `var * sqrt(T_liq / horizon)`, T_liq = qty / (participation_rate * ADV)
- **max_of_both**: Conservative max of BDSS and TTL
- Fallback: no spread data → lvar = var_market, data_health = 0.0
- Min spread obs: 20 (LVAR_MIN_SPREAD_OBS)
- `RiskEngine.compute()` kwargs: `spread_history`, `position_notional`, `position_qty`, `adv`
- `RiskMetrics`: `lvar`, `lvar_data_health`
- Prometheus: `bot_var_liquidity_adjusted{symbol=...}`

### VaR Decomposition (VR-09)
- **Euler decomposition** via variance-covariance: `component_i = w_i × (Σw)_i / σ_p × VaR_total`
- `compute_var_decomposition(asset_returns, weights, var_total)` → (component_dict, marginal_dict)
- Sum invariant: `Σ component_var_i ≈ var_total` (eps < 1e-6)
- `marginal_var(symbol)`, `component_var(symbol)`, `incremental_var(new_trade)`
- DECOMP_MIN_OBS = 20
- `RiskMetrics`: `component_var_per_position`, `marginal_var_per_position`

### Regime-Conditional VaR (VR-10)
- **RegimeConditionalVaR** class with `deque(maxlen=2000)` per regime
- `record(return_t, regime_t)`, `bulk_load(returns, regimes)`, `var_for_current(current_regime, config)`
- Deferred import of RiskEngine to avoid circular dependency
- Conservative limit aggregation: `vlim = max(overall_var, regime_conditional_var)`
- Contains `regime_conditional_var = True` sentinel for var_topology detection
- `RiskMetrics`: `var_regime_conditional_95/99`, `current_regime`

### Stressed VaR (VR-11)
- **Basel 2.5 stress-period rescaling**: 5 canonical crypto stress periods
- Periods: 2020_covid, 2021_china_ban, 2022_luna, 2022_ftx, 2024_yen_carry
- Formula per period: `sVaR_p = hist_var(stress_p, 0.99) × (σ_current / σ_stress_p)`
- Final: `stressed_var = max(sVaR_p)` across all periods
- Limit rule: `stressed_var > 2 × var_99 → stressed_var_breach = True`
- `StressedVaR.from_fixture()` loads from `historical_stress_returns.json`
- `StressedVaR.check_limit(stressed_var, var_99, multiplier)` static method
- `compute_stressed_var()` convenience function
- Contains `stressed_var_engine = True` sentinel for var_topology detection
- `RiskMetrics`: `stressed_var`, `stressed_var_worst_period`, `stressed_var_breach`
- `RiskEngine.compute()` kwarg: `stress_returns` (Dict[str, Sequence[float]])

### Stress Scenario Library (VR-12)
- **5+ predefined scenarios** in `data/var_stress_grid_default.json`
- Scenarios: BTC_crash_30pct, USDT_depeg_5pct, binance_outage_24h, funding_spike, flash_crash_10pct
- `forward_stress(portfolio, scenario)` → PnL fraction (negative = loss)
- `reverse_stress(portfolio, target_loss_pct)` → minimum shock vector + scaling factor
- Shock resolution priority: exact asset → uppercase → "alts" category → "all" fallback
- `run_stress_grid(portfolio, scenarios)` → StressGridResult with worst scenario
- `generate_stress_report()` → `docs/stress_reports/stress_YYYY-MM-DD.md`
- Contains `institutional_stress_grid = True` sentinel for var_topology detection
- Prometheus: `bot_stress_worst_scenario_pnl_pct`, `bot_reverse_stress_min_btc_shock_pct`
- Alert: `BotStressLossHigh` — worst scenario > 15% NAV loss
- Manifest: `institutional_stress_grid_present=true`

### Kupiec POF Backtest (VR-13)
- **Kupiec (1995) Proportion of Failures** likelihood-ratio test
- LR = -2 [(n-x)·ln(1-p_exp) + x·ln(p_exp) - (n-x)·ln(1-p_obs) - x·ln(p_obs)]
- LR ~ χ²(1), `model_valid = (p_value > 0.05)`
- `kupiec_pof(realized_pnl, predicted_var, conf)` → `KupiecResult`
- `run_backtest_suite(pnl, {conf: var_series})` → multi-confidence
- `generate_backtest_report()` → `docs/backtest_reports/kupiec_YYYY-MM-DD.md`
- `KUPIEC_MIN_OBS = 50` — skip if insufficient data
- Boundary: zero or all exceedances → p_value=1.0, model_valid=True
- Nightly CI: `.github/workflows/nightly-kupiec.yml` (02:00 UTC)
- CI failure → auto-opens GitHub issue with `risk` label
- CLI: `python -m super_otonom.risk.var_backtest --json`
- Prometheus: `bot_kupiec_pvalue`, `bot_kupiec_exceedances`
- Alert: `BotKupiecModelInvalid` — p_value < 0.05 for 1h
- Contains `var_backtest_kupiec = True` sentinel

### Christoffersen Independence + CC (VR-14)
- **Christoffersen (1998) first-order Markov** independence test
- Transition matrix: n00, n01, n10, n11 from exceedance series
- LR_ind = -2 [L_restricted - L_unrestricted] ~ χ²(1)
- `independent = (p_value_ind > 0.05)`
- `christoffersen_ind(exceedance_series)` → `ChristoffersenResult`
- **Conditional Coverage (CC)**: LR_cc = LR_pof + LR_ind ~ χ²(2)
- `christoffersen_cc(pnl, var, conf)` → `ConditionalCoverageResult`
- `model_valid = kupiec.model_valid AND independence.independent`
- `run_cc_suite(pnl, {conf: var})` → multi-confidence CC
- `generate_backtest_report()` updated: Independence + CC tables when CC results
- Boundary: pi=0/1 or log(0) → default independent=True (conservative)
- Prometheus: `bot_christoffersen_ind_pvalue`, `bot_christoffersen_cc_pvalue`
- Alert: `BotChristoffersenCluster` — ind p_value < 0.05 for 1h
- Lives in same `var_backtest.py` as VR-13 (shared module)

### Basel Traffic Light Backtest (VR-15)
- **Basel Committee** supervisory backtesting framework (January 1996)
- Rolling 250 trading-day window, 99% VaR, exceedance count → zone
- GREEN (0-4): model valid, capital add-on = 0.0
- YELLOW (5-9): graduated add-on: 5→+0.40, 6→+0.50, 7→+0.65, 8→+0.75, 9→+0.85
- RED (10+): model rejected, capital add-on = 1.0
- `basel_traffic_light(exceedances, conf, window)` → `TrafficLightResult`
- `basel_traffic_light_from_pnl(pnl, var, conf, window)` → uses last `window` obs
- `generate_backtest_report()` now accepts optional `traffic_light=` kwarg
- `BASEL_WINDOW = 250` constant
- Prometheus: `bot_var_traffic_light` (0=GREEN, 1=YELLOW, 2=RED), `bot_var_traffic_light_exceedances`, `bot_var_traffic_light_capital_addon`
- `record_traffic_light(zone, exceedances, capital_addon)` on MetricsExporter
- Alerts: `BotVaRTrafficLightYellow` (warning, 5m), `BotVaRTrafficLightRed` (critical, 1m)
- Negative exceedance input clamped to 0 → GREEN
- Short series (< 250 obs): uses all available data, window field reflects actual count
- Lives in same `var_backtest.py` as VR-13/14 (shared module)

### P&L Attribution + Drift Detection (VR-16)
- **Decomposition**: actual_pnl = explained + trades + unexplained
- **Explained**: mark-to-market on opening positions: Σ(p_end - p_start) × qty_start
- **Trades**: sum of realized PnL from intraday trades (TradeLike.pnl)
- **Unexplained**: residual = actual - explained - trades (fees, funding, slippage, data lag)
- **Drift threshold**: |unexplained_pct| > 10 bps of total capital
- `PNL_DRIFT_THRESHOLD_BPS = 10`, `PNL_DRIFT_THRESHOLD = 0.001`
- `attribute_pnl(pos_start, pos_end, prices_start, prices_end, trades, capital)` → `PnLAttribution`
- `attribute_pnl_series(daily_snapshots, capital)` → `PnLAttributionSeries`
- `generate_attribution_report()` → `docs/pnl_reports/pnl_attribution_YYYY-MM-DD.md`
- `attribution_to_dict()` → JSON-serializable dict
- `TradeLike` Protocol (`.pnl` attribute), `SimpleTrade` frozen dataclass helper
- `PnLAttribution`: explained, trades, unexplained, actual_pnl, unexplained_pct, unexplained_bps, drift_detected, total_capital, n_positions, n_trades
- `PnLAttributionSeries`: daily list, total_explained/trades/unexplained, max_abs_unexplained_bps, drift_days
- Series accepts dict trades: `{"pnl": float}` → auto-wrapped in SimpleTrade
- Contains `pnl_attribution_active = True` sentinel for var_topology detection
- Prometheus: `bot_pnl_explained_pct`, `bot_pnl_unexplained_pct`, `bot_pnl_attribution_health` (1=healthy, 0=drift)
- `record_pnl_attribution(explained_pct, unexplained_pct, health)` on MetricsExporter
- Alert: `BotPnLDriftHigh` — attribution_health == 0 for 15m
- Standalone module: `super_otonom/risk/pnl_attribution.py` (not in var_backtest.py)

### Pre-trade Marginal VaR Gate (VR-17)
- **Two limit checks** before order submission:
  1. Total VaR: new portfolio VaR₉₉ ≤ `max_var_total_pct` (default 5%)
  2. Marginal VaR: incremental VaR from trade ≤ `max_marginal_var_per_trade_pct` (default 2%)
- `pre_trade_var_check(symbol, trade_weight, side, weights, returns, limits)` → `PreTradeVarResult`
- `pre_trade_var_check_batch(trades, weights, returns, limits)` → cumulative impact check
- `simulate_trade_weights(weights, symbol, trade_weight, side)` → new portfolio weights
- `PreTradeVarLimits`: max_var_total_pct, max_marginal_var_per_trade_pct, confidence
- `PreTradeVarResult`: approved, reason, current_var, new_var, marginal_var, latency_ms
- `gate_result_to_dict()` → JSON-serializable dict
- VaR computation: historical percentile on weighted portfolio returns (numpy vectorised)
- Target latency: **<30ms** (tested on 2-asset and 10-asset portfolios)
- Insufficient data → conservative pass (can't compute VaR, allows trade)
- Integration: runs after `gate_buy_size_and_exposure`, before order dispatch
- Contains `pre_trade_var_gate_active = True` sentinel for var_topology detection
- `GATE_MIN_OBS = 20`, `GATE_DEFAULT_CONF = 0.99`
- Prometheus: `bot_pre_trade_var_gate_passed` (1=pass, 0=reject), `bot_pre_trade_var_gate_new_var`, `bot_pre_trade_var_gate_marginal_var`
- `record_pre_trade_var_gate(approved, new_var, marginal_var)` on MetricsExporter
- Alert: `BotPreTradeVarGateReject` — approval rate < 50% for 15m
- Standalone module: `super_otonom/risk/pre_trade_var_gate.py`

### VaR/CVaR Breach Kill-switch (VR-19)
- **3 breach triggers** in `check_risk()` chain (step 5, after loss/drawdown, before exposure):
  1. `var_99_1d > max_var_99_pct` (default 6%) → `emergency_stop`
  2. `cvar_975_1d > max_cvar_975_pct` (default 10%) → `emergency_stop`
  3. `stressed_var > 2 × var_99_1d` → `emergency_stop`
- **Model dispersion warning**: `model_dispersion_pct > 50%` → `log.critical` (no kill)
- `_check_var_breach()` in `RiskManager` — uses `RiskEngine.compute()` on return history
- `set_risk_engine(engine)`: BotEngine __init__ sonrası çağrılır
- `record_return(ret)`: Her tick'te portföy return'ü kaydedilir (deque 500)
- Skip conditions: engine not set, < 20 returns, compute error → conservative pass
- Config keys (env override): `MAX_VAR_99_PCT`, `MAX_CVAR_975_PCT`, `MAX_MODEL_DISPERSION_PCT`
- Contains `var_breach_kill_switch = True` sentinel for var_topology detection
- Prometheus: `bot_var_breach_kill_switch` (0=normal, 1=var_99, 2=cvar_975, 3=stressed_var), `bot_var_99_current`, `bot_cvar_975_current`, `bot_model_dispersion_current`
- `record_var_breach(breach_code, var_99, cvar_975, model_dispersion)` on MetricsExporter
- Alert: `BotVarBreachKillSwitch` — breach_code != 0 for 1m
- Lives in `super_otonom/risk_manager.py` (extends existing class, not standalone module)

### VaR Limit Hierarchy (VR-20)
- **3-level limit system**: Strategy (per-strategy) → Portfolio (aggregate) → Firm (stressed)
- `VaRLimits` frozen dataclass: 8 fields covering strategy/portfolio/trade/concentration/liquidity
- **Override chain**: `env > config/var_limits.yaml > dataclass defaults`
- `load_var_limits(yaml_path, skip_env)` → merges all 3 layers into VaRLimits
- `check_limits(limits, metrics)` → returns list of breaches against RiskMetrics
- `validate()` invariants:
  - All limits in (0, 1]
  - `strategy_var < portfolio_var < stressed_var`
  - `strategy_cvar < portfolio_cvar`
  - `marginal_var < strategy_var`
- `deploy_env_check` integration: VaRLimits invariant validation at deploy time
- YAML fallback parser: works without PyYAML (simple key: value)
- Env override: field name upper-cased → `MAX_VAR_TOTAL_PCT=0.08`
- Contains `var_limit_hierarchy_active = True` sentinel for var_topology detection
- Standalone module: `super_otonom/risk/var_limits.py`
- Config file: `config/var_limits.yaml`

### Prometheus VaR/CVaR Full Suite (VR-21)
- **Multi-labeled gauges**: `bot_var_pct{conf, model, scope}`, `bot_cvar_pct{conf, model, scope}`
- 15 VaR series: historical/parametric_t/monte_carlo/cornish_fisher/aggregate at 95%/99%, plus evt/fhs/regime
- 12 CVaR series: historical/parametric/monte_carlo at 95%/99%, plus aggregate 95%/975%/99%, evt/fhs
- `bot_stressed_var_pct` — Basel 2.5 stressed VaR
- `bot_component_var_pct{symbol}` — component VaR concentration per position
- `bot_var_model_dispersion_pct` — model dispersion ratio
- `bot_var_limit_utilisation{level}` — current / limit ratio (4 levels: var_99, cvar_975, stressed_var, lvar)
- `record_var_suite(metrics, limits=, component_var=)` — tek çağrıda tüm metrikleri yazar
- Division guard: var_for_limits_95=0 → component_var_pct=0.0 (ZeroDivisionError koruması)
- **7 new alert rules** in `docker/prometheus/alerts.yml`:
  - `BotVaRApproachingLimit` (warning 5min, utilisation > 0.8)
  - `BotVaRLimitBreach` (critical 1min, utilisation >= 1.0)
  - `BotCVaRLimitBreach` (critical 1min)
  - `BotModelDispersionHigh` (warning 15min, > 0.5)
  - `BotPnLUnexplainedHigh` (warning 15min, > 15 bps)
  - `BotStressedVaRApproachingLimit` (warning 5min)
  - `BotLVaRLimitBreach` (warning 5min)
- Contains `_prometheus_var_full_suite = True` sentinel for var_topology detection
- Lives in `super_otonom/metrics_exporter.py` (extends existing MetricsExporter class)

### Daily Risk Report (VR-22)
- **10-section automated daily risk report** in Markdown format
- Output: `docs/risk_reports/risk_YYYY-MM-DD.md` (cron 23:55 UTC)
- Sections:
  1. Özet (capital, NAV, exposure, leverage)
  2. VaR matrisi (7 models × 2 confidence levels)
  3. CVaR matrisi (6 models × 2 confidence + 97.5% FRTB)
  4. Stressed VaR (Basel 2.5) with breach status
  5. Top 10 positions + component VaR
  6. Stress scenario results (worst 5)
  7. VaR backtest (Kupiec / Christoffersen CC / Basel traffic light)
  8. P&L attribution with drift detection
  9. Limit breach log
  10. Manual review flags (auto-detected)
- `generate_report(report_date=)` → Markdown string
- `generate_report_json(report_date=)` → structured dict
- CLI: `--date`, `--out`, `--json`, `--stdout`
- Data sources: `data/capital_journal.jsonl`, `data/realized_pnl.json`, `data/positions.json`, `data/breach_log.jsonl`, `data/pnl_attribution_latest.json`
- Real RiskEngine integration: runs `RiskEngine.compute()` on loaded returns
- Backtest integration: Kupiec POF, Christoffersen CC, Basel traffic light (min 50 obs)
- Bonus: `scripts/risk_report_to_pdf.py` — Markdown → PDF (weasyprint > pdfkit fallback)
- Contains `daily_risk_report_active = True` sentinel for var_topology detection
- Scripts: `scripts/generate_daily_risk_report.py`, `scripts/risk_report_to_pdf.py`

### Grafana Risk Dashboard (VR-23)
- **14-panel Grafana dashboard** provisioned via JSON
- UID: `risk-var-cvar`, auto-loaded from `docker/grafana/provisioning/dashboards/json/risk.json`
- **9 core panels**: VaR timeline, CVaR timeline, Component VaR pie, VaR vs PnL overlay, Traffic light history, Model dispersion gauge, Stress worst PnL, Unexplained PnL bars, Limit utilization heatmap
- **5 bonus panels**: Kill switch status, Kupiec p-value, Christoffersen CC, Summary stats, LVaR per symbol
- **4 template variables** (dropdowns): `conf`, `model`, `symbol`, `horizon`
- Multi-select on conf/model/symbol, PromQL `label_values()` queries
- Color themes: traffic light (GREEN/YELLOW/RED), limit utilization (5 steps), dispersion gauge (4 steps)
- All queries use `prometheus` datasource (uid: `prometheus`)
- Refresh: 30s, timezone: UTC, default range: 7d
- Documentation: `docs/RISK_DASHBOARD.md`

### Model Inventory + Validation Governance (VR-24)
- **22 risk models** registered in `docs/MODEL_INVENTORY.md` (MR-VAR-HIST through MR-LIMITS)
- Covers VR-02 through VR-20 (all implemented risk modules)
- **Independence rule**: model developer ≠ model validator (enforced in CI)
- **Semi-annual validation cycle** (6 months), 30-day early warning
- `docs/MODEL_VALIDATION_TEMPLATE.md`: 9-section structured validation report template
- `scripts/check_model_validation_due.py`: CI due-date checker
  - `parse_inventory()` — regex-based Markdown table parser
  - `check_due(entries, today=, warn_days=30)` → `List[ValidationAlert]`
  - `_open_github_issue(alert)` — auto-creates GitHub issue via `gh` CLI
  - CLI: `--ci` (auto-open issues), `--json`, `--date`, `--warn-days`
  - Exit code 1 when any model is within 30 days or overdue
- `ModelEntry` frozen dataclass: model_id, name, vr, module, developer, validator, dates, status
- `ValidationAlert` frozen dataclass: model_id, days_remaining, overdue, governance_violation
- `developer_equals_validator` property: case-insensitive check for independence violation
- Contains `model_validation_governance_active = True` sentinel for var_topology detection
- Governance roles: `quant-dev` (developer), `risk-review` (validator), `risk-committee` (approval)

### Risk Appetite Statement + Escalation Matrix (VR-25)
- **4 risk categories**: Market, Liquidity, Operational, Counterparty — each with GREEN/AMBER/RED/CRITICAL zones
- **Tolerance levels**: GREEN (normal), AMBER (warning, bot continues), RED (defensive mode), CRITICAL (halt all)
- **VaRLimits cross-reference table**: 8 limits mapped to `var_limits.py` defaults with appetite zones
- **Escalation matrix (L1–L4)**:
  - L1 AMBER: on-call notify, bot full capacity
  - L2 RED single: defensive mode (size %50, no new pairs)
  - L3 RED multiple: `emergency_stop`, all positions closed
  - L4 CRITICAL: halt all systems, post-mortem 24h required
- **Approval levels**: <2% desk, 2–5% risk manager, >5% committee
- **Quarterly board review** cycle documented
- `scripts/risk_appetite_check.py`: CI consistency checker
  - `parse_appetite_limits()` — regex Markdown table parser for cross-ref section
  - `check_appetite_vs_limits(entries, limits)` → drift detection
  - `check_escalation_matrix()`, `check_approval_levels()`, `check_quarterly_review()`
  - `_parse_pct()` — handles `6%` → 0.06, `0.5%` → 0.005 correctly
  - CLI: `--json`, exit code 1 on mismatch
- Contains `risk_appetite_check_active = True` sentinel
- Documentation: `docs/RISK_APPETITE.md`

### Aggregation
- `var_for_limits = max(historical, parametric, MC)` (conservative)
- After regime VaR: `vlim = max(vlim, regime_conditional)` (VR-10)
- `cvar = max(3 methods)` at each confidence level

### RiskConfig Defaults (current)
- `var_confidences`: (0.95, 0.975, 0.99)
- `var_history_min_obs`: 100 (legacy), 250 (institutional/Basel)
- `cvar_primary_conf`: 0.975 (Basel FRTB ES)
- `parametric_dist`: "student_t" (MLE df estimation)
- `monte_carlo_draws`: 600, `seed`: 42
- `use_models`: (historical, parametric_t, monte_carlo, cornish_fisher, fhs)
- `evt_min_sample`: 500, `evt_threshold_quantile`: 0.95
- `fhs_min_sample`: 250
- `lvar_method`: "bdss", `lvar_participation_rate`: 0.10

### RiskMetrics Fields (frozen dataclass, ~35 fields)
Core: var_95/99/975_1d, cvar_95/975/99_1d
Per-method CVaR: cvar_historical/parametric/monte_carlo at 95%/99%
Per-model VaR: var_historical/parametric/monte_carlo at 95%/99%, var_for_limits_95/99
Cornish-Fisher: var_cornish_fisher_95/99
EVT: var_evt_99, cvar_evt_99 (Optional)
FHS: var_fhs_95/99, cvar_fhs_95/99 (Optional)
Stressed VaR: stressed_var, stressed_var_worst_period, stressed_var_breach (VR-11)
LVaR: lvar, lvar_data_health
Decomposition: component_var_per_position, marginal_var_per_position (VR-09)
Regime: var_regime_conditional_95/99, current_regime (VR-10)
Model risk: model_dispersion_pct
10-day Basel FRTB: var_10d_99, cvar_10d_975 (sqrt(10) scaling)
Legacy: pnl_var_95
Properties: var_max_95, var_max_99

### RiskEngine.compute() Signature
```python
def compute(
    self,
    returns_history,
    positions=None,          # VR-09: weight dict {symbol: weight}
    prices=None,             # reserved
    config=None,
    *,
    asset_returns=None,      # VR-09: per-symbol return series
    spread_history=None,     # VR-08: LVaR
    position_notional=0.0,   # VR-08: LVaR
    position_qty=0.0,        # VR-08: LVaR
    adv=0.0,                 # VR-08: LVaR
    current_regime=None,     # VR-10: regime label
    regime_var=None,         # VR-10: RegimeConditionalVaR instance
    stress_returns=None,     # VR-11: Dict[str, Seq[float]] stress period returns
) -> RiskMetrics
```

### Computation Order in RiskEngine.compute()
1. 95% suite (hist/param/MC) → vlim95
2. 99% suite (hist/param/MC) → vlim99
3. Regime-conditional VaR (VR-10) → updates vlim95/vlim99 via max()
4. 97.5% historical (Basel FRTB)
5. Cornish-Fisher 95%/99%
6. CVaR 95%/99%/97.5% (3 methods each)
7. EVT POT (VR-06)
8. FHS GARCH (VR-07)
9. LVaR (VR-08) — uses vlim95
10. Stressed VaR (VR-11) — uses vlim99 for breach check
11. Dispersion
12. Decomposition (VR-09) — uses vlim95
13. Return RiskMetrics

### var_topology System (Audit 11)
- `var_topology.py`: scans risk/ package for sentinel markers
- Sentinels detected: `regime_conditional_var`, `stressed_var_engine`, `liquidity_adjusted_var`, `pnl_attribution_active`, `pre_trade_var_gate_active`
- `VarTopology` dataclass: `regime_conditional_var_present`, `stressed_var_engine_present`, `liquidity_adjusted_var_present`, etc.
- `var_disclosure()`: returns limitations list (items removed when feature is present)
- `institutional_var_claim_allowed` always `False`
- `_INSTITUTIONAL_GAP_MARKERS` in `var_topology.py` — catches unauthorized VaR claims outside risk/
- `var_topology_audit.py`: forbidden claim scanner with allowlist
  - `_ALLOWLIST_FILES`: risk/, test files, CLAUDE.md, methodology docs
  - `_ALLOW_SUBSTR`: sentinel names, metadata terms
- Manifest regeneration: `python -m super_otonom.var_topology --write-manifest`

## Common Pitfalls
- **Ruff I001**: Her yeni test dosyasında import sıralama hatası olur → `ruff check --fix`
- **Student-t scale**: `sqrt((df-2)/df)` adjustment KULLANMA — raw sigma + t-quantile
- **CF expansion**: Extreme skew/kurtosis'te breakdown olur → `z_cf >= z` guard şart
- **Portfolio tests**: CVaR değişiklikleri `test_portfolio_risk_engine.py` threshold'larını kırabilir
- **Windows CI**: Bazen transient failure olur, re-run yeterli
- **min_obs=100**: `RiskOntology` ve `risk_manager` bu değere bağlı, değiştirme
- **Golden fixture**: 120 returns dict with "returns" key → `raw["returns"]` ile yükle. EVT/FHS skip (< 500/250)
- **var_topology_audit**: `risk/`, `metrics_exporter.py`, `CLAUDE.md` allowlist'te — false positive önlenir
- **var_topology_audit allowlist**: Yeni test dosyası eklediğinde `_ALLOWLIST_FILES`'a da ekle (örn: `"test_stressed_var_vr11"`)
- **var_topology_audit allow substr**: Yeni sentinel eklediğinde `_ALLOW_SUBSTR`'a da ekle (örn: `"stressed_var_engine"`, `"stressed_var"`)
- **use_models default**: `"fhs"` VR-07'den beri default'ta — test_config_vr05.py set'i güncelle
- **FHS returns*100**: arch paketi yüzde bazlı input bekler, sonuç /100 ile normalize edilir
- **LVaR sign convention**: Tüm VaR pozitif (loss fraction), lvar.py loss-space'te çalışır
- **Manifest regeneration**: var_topology değişikliklerinde `python -m super_otonom.var_topology --write-manifest`
- **Circular imports**: regime_var.py → risk_engine.py bağımlılığı deferred import ile çözüldü (fonksiyon içinde import)
- **Bimodal Student-t inflation**: Karma rejim return'leri (LOW_VOL+HIGH_VOL) Student-t MLE'yi düşük df'e iterek parametrik VaR'ı şişirir — test'lerde asimetrik split veya rejim-arası karşılaştırma kullan
- **Stressed VaR rescaling**: `sVaR = raw_var × (σ_current / σ_stress)` — düşük current vol stressed VaR'ı küçültür (bu doğru davranış)
- **Stress fixture format**: `{"period_key": {"label": "...", "returns": [...]}}` — `from_fixture()` `returns` key'ini çıkarır
- **Stress grid JSON format**: `[{"name":"...", "shocks":{...}, "horizon_h":N}]` — `load_scenarios()` ile yüklenir
- **Shock resolution**: exact match > uppercase > "alts" (non-major) > "all" — `_MAJOR_ASSETS` = BTC, ETH, BNB, USDT, USDC
- **Reverse stress linear scaling**: k_needed = target_loss / |base_pnl| — lineer shock modeli, doğrudan çarpan
- **Kupiec boundary**: p_obs=0 veya p_obs=1 → LR tanımsız, p_value=1.0 döner (conservative)
- **Kupiec min obs**: n < 50 → test atlanır, default valid döner
- **Kupiec VaR sign convention**: predicted_var pozitif (loss fraction), realized_pnl negatif (loss)
- **Christoffersen boundary**: pi=0/1, pi_01=0/1, pi_11=0/1 → log(0) guard, default independent=True
- **Christoffersen min obs**: Same as Kupiec — n < 50 → default result returned
- **CC additivity**: LR_cc = LR_pof + LR_ind, df=2 — her zaman ayrı compute edip topla
- **Two consecutive exceedances**: 100 obs'de bile 2 ardışık exceedance pi_11=0.5 vs pi_01≈0.01 divergence yaratır — istatistiksel olarak anlamlı kümelenme
- **Basel traffic light window**: Varsayılan 250 işlem günü, kısa serilerde tüm veri kullanılır (window alanı gerçek sayıyı yansıtır)
- **Basel traffic light from_pnl**: Son `window` gözlemi alır, VaR vektörünü de son `window`'dan keser
- **Graduated add-ons**: Yellow zone'da sabit 0.4 değil, Basel tablosundaki kademeli değerler (0.40-0.85)
- **Negatif exceedance**: basel_traffic_light(-N) → 0'a clamp, GREEN döner
- **PnL drift bps math**: extra_cost / total_capital × 10000 = bps. 2.0 / 10000 = 2 bps (NOT 20). Need >1.0 USDT for >10 bps on 10000 capital
- **PnL attribution double-counting**: End prices are used in BOTH explained and actual NAV calc — adjust end quantity, not end price, to inject unexplained
- **PnL attribution total_capital**: Must be > 0, raises ValueError otherwise
- **PnL attribution missing price**: Treated as 0.0 (dict.get default), not error
- **Pre-trade VaR gate insufficient data**: Symbol with < 20 obs → conservative pass (allows trade), NOT reject
- **Pre-trade VaR gate total vs marginal**: Total VaR check runs FIRST — tight limits can reject a diversifier even if marginal VaR is negative
- **Pre-trade VaR gate weight normalization**: Weights are normalised to sum=1 internally for VaR calculation, but stored as-is in portfolio
- **Pre-trade VaR gate latency**: numpy vectorised path is critical — avoid Python loops over return series
- **VR-19 kill-switch chain order**: VaR breach step 5'te — loss/drawdown (2-4) sonrası, exposure/vol (6-7) öncesi. Drawdown emergency + VaR breach aynı anda olursa drawdown ilk yakalar
- **VR-19 skip conditions**: engine=None veya returns<20 → None döner (conservative pass), emergency_stop AÇMAZ
- **VR-19 breach priority**: var_99 → cvar_975 → stressed_var sırayla kontrol — ilk breach emergency'yi latch eder
- **VR-19 stressed_var=0**: Stress fixture yoksa stressed_var=0.0 — 0>0 kontrolünden geçmez, breach olmaz
- **VR-19 model_dispersion**: Log uyarısı, kill YOK — sadece manuel review tetikler
- **VR-19 config override**: Test'lerde RISK dict'i değiştirirsen try/finally ile geri al — global state
- **VR-20 override priority**: env > YAML > defaults — env her zaman kazanır, YAML kısmen override edebilir
- **VR-20 YAML parser**: PyYAML yoksa basit key: value parser kullanılır — nested YAML desteklemez
- **VR-20 validate strict >**: strategy_var == portfolio_var invalid — strict less-than gerekli
- **VR-20 check_limits component**: component_var / var_for_limits_95 oranı — var_total=0 olursa division guard var
- **VR-20 deploy_env_check**: VaRLimits invariant ihlali deploy'u engeller (exit code 1)

- **VR-21 var_total falsy guard**: `0.0 or 1.0` evaluates to `1.0` — explicit None/zero check gerekli
- **VR-21 label cardinality**: conf×model×scope label'lar Prometheus'ta high-cardinality oluşturabilir — scope şimdilik sadece "portfolio"
- **VR-21 limit utilisation zero limit**: limit=0.0 durumunda utilisation=0.0 döner (division guard)
- **VR-21 record_var_suite idempotent**: Birden fazla çağrı güvenli — her çağrı gauge'ları set() ile üzerine yazar
- **VR-21 component_var_pct ratio**: abs(cv)/abs(var_total) — raw component değil, toplam VaR'a göre oran

## Dependencies
- Python 3.12, numpy, scipy>=1.11.0, arch>=7.0.0, pytest, ruff
- GitHub CLI (`gh`) for PR creation
