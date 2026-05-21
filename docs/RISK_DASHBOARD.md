# Risk Dashboard — VaR / CVaR / Basel (VR-23)

Grafana provisioned dashboard for real-time VaR/CVaR risk monitoring.

## Auto-provisioning

Dashboard `risk.json` is auto-loaded via Grafana provisioning:
- Config: `docker/grafana/provisioning/dashboards/default.yml`
- JSON: `docker/grafana/provisioning/dashboards/json/risk.json`
- UID: `risk-var-cvar`
- Folder: "Super Otonom"
- Refresh: 30s

## Panels (14 total, 9 core)

### Row 1 — VaR / CVaR Timeline

| # | Panel | Type | PromQL | Description |
|---|-------|------|--------|-------------|
| 1 | Total VaR Timeline | timeseries | `bot_var_pct{conf, model, scope}` | 3 conf × N model overlay, aggregate highlighted |
| 2 | CVaR Timeline | timeseries | `bot_cvar_pct{conf, model, scope}` | CVaR/ES time series, 97.5% FRTB |

### Row 2 — Position Risk & Stress

| # | Panel | Type | PromQL | Description |
|---|-------|------|--------|-------------|
| 3 | Component VaR Pie | piechart | `bot_component_var_pct{symbol}` | Real-time per-symbol VaR concentration |
| 4 | VaR vs Realized PnL | timeseries | `bot_var_pct` + `bot_pnl_pct` | VaR boundary vs actual PnL, exceedance visual |

### Row 3 — Model Quality & Backtest

| # | Panel | Type | PromQL | Description |
|---|-------|------|--------|-------------|
| 5 | Traffic Light History | timeseries | `bot_var_traffic_light` | GREEN/YELLOW/RED zone with color mapping |
| 6 | Model Dispersion | gauge | `bot_var_model_dispersion_pct` | 0-100% gauge, thresholds at 30/50/80% |
| 7 | Stress Worst PnL | stat | `bot_stress_worst_scenario_pnl_pct` | Worst scenario + stressed VaR + reverse stress |
| 8 | Unexplained PnL | timeseries | `bot_pnl_unexplained_pct` | Bar chart, red > 15 bps |

### Row 4 — Limit Utilization

| # | Panel | Type | PromQL | Description |
|---|-------|------|--------|-------------|
| 9 | Limit Utilization | timeseries | `bot_var_limit_utilisation{level}` | 4-level bar chart, color thresholds 50/70/80/100% |

### Bonus Panels

| # | Panel | Type | Description |
|---|-------|------|-------------|
| 10 | Kill Switch | stat | VaR breach kill-switch status |
| 11 | Kupiec p-value | stat | Backtest validity indicator |
| 12 | Christoffersen CC | stat | Conditional coverage p-value |
| 13 | Summary Stats | stat | VaR 99% / CVaR 97.5% / Stressed VaR |
| 14 | LVaR per Symbol | stat | Liquidity-adjusted VaR |

## Template Variables (Dropdowns)

| Variable | Source | Multi-select | Default |
|----------|--------|-------------|---------|
| `conf` | `label_values(bot_var_pct, conf)` | Yes | All |
| `model` | `label_values(bot_var_pct, model)` | Yes | All |
| `symbol` | `label_values(bot_component_var_pct, symbol)` | Yes | All |
| `horizon` | Custom: 1d, 10d | No | 1d |

## Data Sources

All panels use `prometheus` datasource (uid: `prometheus`).

Metrics exported by `MetricsExporter` in `super_otonom/metrics_exporter.py`:
- VR-21 gauges: `bot_var_pct`, `bot_cvar_pct`, `bot_stressed_var_pct`, `bot_component_var_pct`, `bot_var_model_dispersion_pct`, `bot_var_limit_utilisation`
- VR-19 gauges: `bot_var_breach_kill_switch`, `bot_var_99_current`, `bot_cvar_975_current`
- VR-15 gauges: `bot_var_traffic_light`, `bot_var_traffic_light_exceedances`
- VR-16 gauges: `bot_pnl_unexplained_pct`, `bot_pnl_explained_pct`
- VR-12 gauges: `bot_stress_worst_scenario_pnl_pct`, `bot_reverse_stress_min_btc_shock_pct`
- VR-13 gauges: `bot_kupiec_pvalue`
- VR-14 gauges: `bot_christoffersen_cc_pvalue`
- VR-08 gauges: `bot_var_liquidity_adjusted`

## Color Scheme

- **Traffic light**: GREEN (0) → YELLOW (1) → RED (2)
- **Limit utilization**: green (<50%) → light green (50-70%) → yellow (70-80%) → orange (80-100%) → red (>100%)
- **Model dispersion gauge**: green (<30%) → yellow (30-50%) → orange (50-80%) → red (>80%)
- **Kupiec/CC p-value**: red (<0.05) → yellow (0.05-0.10) → green (>0.10)

## Deployment

```bash
# Docker Compose (standard)
docker-compose up -d grafana

# Dashboard available at:
# http://localhost:3000/d/risk-var-cvar/risk-dashboard
```
