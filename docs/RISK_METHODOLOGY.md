# Risk Methodology — super_otonom v7

## 1. VaR Confidence Levels

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `var_confidences` | (0.95, 0.975, 0.99) | Industry standard triple: 95% for day-to-day limits, 97.5% for Basel FRTB ES, 99% for stress/regulatory capital |

## 2. VaR Horizons

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `var_horizons_days` | (1, 10) | 1-day for intraday risk; 10-day for Basel FRTB capital requirement (square-root-of-time scaling) |

## 3. Minimum Observations

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `var_history_min_obs` | 100 | Legacy compat — live-tick consumers (`RiskOntology`, `risk_manager`) use 100 obs for real-time VaR updates |
| `var_history_min_obs_institutional` | 250 | Basel III standard: 250 trading days (approx. 1 calendar year) for institutional-grade VaR estimation |

The dual-parameter design preserves backward compatibility: existing live-tick pipelines
continue to operate with 100 observations while institutional reporting enforces the
regulatory 250-day minimum.

## 4. CVaR / Expected Shortfall

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `cvar_primary_conf` | 0.975 | Basel FRTB (2019): Expected Shortfall at 97.5% replaces VaR as the primary risk measure |
| `cvar_secondary_conf` | 0.99 | Supplementary tail risk; captures extreme scenarios beyond primary ES |
| `cvar_legacy_conf` | 0.95 | Backward compat with pre-FRTB consumers that expect ES at 95% |

Three CVaR methods are computed at each confidence level and the **maximum** is used
(conservative aggregation):

1. **Historical CVaR** — non-parametric tail mean
2. **Parametric CVaR (Student-t)** — Kamdem (2005) closed-form ES
3. **Monte Carlo CVaR** — bootstrap tail mean (seed=42 for reproducibility)

## 5. Monte Carlo Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `monte_carlo_draws` | 600 | Balances estimation precision vs. compute cost; >500 gives stable 95/99% quantiles for single-asset bootstrap |
| `monte_carlo_seed` | 42 | Fixed seed for deterministic CI/CD; production may override for ensemble runs |

## 6. Limit Aggregation

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `limit_aggregator` | "max" | Conservative: `var_for_limits = max(historical, parametric, MC)`. Prevents model arbitrage where the lowest estimate is cherry-picked |

## 7. Parametric Z-Scores

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `parametric_z_95` | 1.645 | `norm.ppf(0.95)` rounded to 3 decimal places (industry convention) |
| `parametric_z_975` | 1.96 | `norm.ppf(0.975)` — Basel FRTB reference quantile |
| `parametric_z_99` | 2.326 | `norm.ppf(0.99)` — regulatory capital quantile |

These are used only in Gaussian mode (`parametric_dist="normal"`).

## 8. Student-t Distribution

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `parametric_dist` | "student_t" | Default to heavy-tailed distribution — crypto returns exhibit excess kurtosis; Gaussian underestimates tail risk |
| `student_t_df` | None (MLE) | Degrees-of-freedom estimated from data via `scipy.stats.t.fit(method="mle")`; clamped to [2.01, 200] |
| `student_t_df_estimator` | "mle" | Maximum Likelihood Estimation — statistically efficient for df estimation |

## 9. Model Selection

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `use_models` | (historical, parametric_t, monte_carlo, cornish_fisher) | Full model suite for cross-validation and model risk monitoring |

- **Historical**: Non-parametric, assumption-free
- **Parametric (Student-t)**: Captures heavy tails analytically
- **Monte Carlo**: Bootstrap resampling, flexible for complex portfolios
- **Cornish-Fisher**: Semi-parametric skewness/kurtosis adjustment (VR-03)

Model dispersion (`max/min - 1`) is tracked to flag when models diverge significantly.

## 10. Validation Invariants

`RiskConfig.validate()` enforces:

- `cvar_primary_conf` in [0.90, 0.999]
- `cvar_secondary_conf > cvar_primary_conf`
- `var_history_min_obs >= 10`
- `var_history_min_obs_institutional >= var_history_min_obs`
- `monte_carlo_draws >= 100`
- `parametric_dist` in {"normal", "student_t"}
- All `var_confidences` in (0, 1) exclusive
- All `use_models` entries are known model names

`deploy_env_check.py` validates these invariants before accepting `LIVE_CONFIRM=YES`.

## References

- Basel Committee (2019). *Minimum capital requirements for market risk* (FRTB).
- Kamdem, J.S. (2005). *Value-at-Risk and Expected Shortfall for linear portfolios with elliptically distributed risk factors*.
- McNeil, Frey & Embrechts (2015). *Quantitative Risk Management*, Ch. 2 & 5.
