"""VR-07 — Filtered Historical Simulation: GARCH(1,1) volatility-adjusted VaR/CVaR."""

from __future__ import annotations

import warnings
from typing import Optional, Sequence, Tuple

import numpy as np

FHS_MIN_SAMPLE = 250


def fhs_var_cvar(
    returns: np.ndarray | Sequence[float],
    conf: float = 0.95,
    horizon_days: int = 1,
    seed: int = 42,
) -> Tuple[Optional[float], Optional[float]]:
    """Compute VaR and CVaR via Filtered Historical Simulation.

    1. Fit GARCH(1,1) to the return series.
    2. Extract standardized residuals z_t = eps_t / sigma_t.
    3. Forecast sigma_{t+1} and rescale: sim_t = z_t * sigma_{t+1}.
    4. VaR / CVaR = percentile / tail-mean of the simulated distribution.

    Returns ``(None, None)`` when sample < 250 or GARCH fit fails.
    """
    from arch import arch_model

    arr = np.asarray(returns, dtype=float).ravel()
    if len(arr) < FHS_MIN_SAMPLE:
        return None, None

    scaled = arr * 100.0

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            am = arch_model(scaled, vol="Garch", p=1, q=1, mean="Constant", dist="normal")
            res = am.fit(disp="off", show_warning=False)
    except Exception:
        return None, None

    std_resid = res.std_resid
    cond_vol = res.conditional_volatility

    if std_resid is None or cond_vol is None:
        return None, None

    std_resid = np.asarray(std_resid, dtype=float)
    cond_vol = np.asarray(cond_vol, dtype=float)

    valid = np.isfinite(std_resid) & np.isfinite(cond_vol) & (cond_vol > 1e-12)
    std_resid = std_resid[valid]
    if len(std_resid) < 30:
        return None, None

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fcast = res.forecast(horizon=horizon_days)
        sigma_next = float(np.sqrt(fcast.variance.iloc[-1, 0]))
    except Exception:
        sigma_next = float(cond_vol[-1])

    if sigma_next < 1e-12 or not np.isfinite(sigma_next):
        return None, None

    sim_returns = std_resid * sigma_next / 100.0

    losses = -sim_returns
    losses_sorted = np.sort(losses)[::-1]

    n_tail = max(1, int(len(losses_sorted) * (1.0 - conf)))
    var_fhs = float(losses_sorted[n_tail - 1])
    cvar_fhs = float(np.mean(losses_sorted[:n_tail]))

    var_fhs = max(var_fhs, 0.0)
    cvar_fhs = max(cvar_fhs, var_fhs)

    return var_fhs, cvar_fhs
