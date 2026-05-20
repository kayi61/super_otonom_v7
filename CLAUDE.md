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
| VR-01 | Unified RiskEngine | ✅ Merged | — |
| VR-02 | VaR Models (Hist/Param/MC) | ✅ Merged | — |
| VR-03 | Cornish-Fisher VaR | ✅ Merged | — |
| VR-04 | CVaR / Expected Shortfall | ✅ Merged | — |
| VR-05 | RiskConfig Basel alignment | ✅ Merged | — |
| VR-06 | EVT Peaks Over Threshold | ✅ Merged | #23 |
| VR-07 | Filtered Historical Sim (FHS) | ✅ Merged | #24 |
| VR-08 | Liquidity-adjusted VaR (LVaR) | ✅ Merged | #25 |
| VR-09 | Component/Marginal/Incremental VaR decomposition | ✅ Merged | #26 |
| VR-10 | Regime-Conditional VaR | ✅ Merged | #27 |
| VR-11 | Stressed VaR (Basel 2.5) | ✅ PR Open | #28 |
| VR-12 | Stress Scenario Library + Reverse Stress Test | ✅ PR Open | — |
| VR-13 | VaR horizon scaling (√t rule + Basel 10d) | ⬜ Beklemede | — |

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
├── stressed_var.py          # VR-11: StressedVaR (Basel 2.5, 5 stress periods, rescaling)
├── stress_scenarios.py      # VR-12: StressScenarioLibrary, forward_stress, reverse_stress
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
├── test_risk_engine_unified.py     # 23 tests — Unified engine + legacy compat
└── fixtures/
    ├── unified_returns_golden.json          # 120 returns (dict with "returns" key)
    └── historical_stress_returns.json       # 5 crypto stress periods (VR-11)
tests/test_portfolio_risk_engine.py # 9 tests — portfolio integration
tests/test_var_topology_fastrun.py  # 8 tests — topology + manifest + audit
```
**Total risk tests:** 445 (all passing)

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
- Sentinels detected: `regime_conditional_var`, `stressed_var_engine`, `liquidity_adjusted_var`
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

## Dependencies
- Python 3.12, numpy, scipy>=1.11.0, arch>=7.0.0, pytest, ruff
- GitHub CLI (`gh`) for PR creation
