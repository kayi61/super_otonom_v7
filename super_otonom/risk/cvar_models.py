"""CVaR / Expected Shortfall — historical, parametric (Student-t), Monte Carlo (VR-04)."""

from __future__ import annotations

import math
import random
import statistics
from typing import Literal, Sequence

import numpy as np
from scipy import stats as sp_stats

_EPS = 1e-12
_DEFAULT_SHORT_FALLBACK = 0.12
_STUDENT_T_MIN_OBS = 15
_DF_FALLBACK = 5.0


# ── Historical CVaR ─────────────────────────────────────────────────────────


def historical_cvar(returns: Sequence[float], confidence: float = 0.95) -> float:
    """CVaR as positive loss fraction (mean of tail at or beyond VaR)."""
    ret = [float(x) for x in returns]
    if len(ret) < 3:
        return _DEFAULT_SHORT_FALLBACK
    xs = sorted(ret)
    n = len(xs)
    tail_n = max(1, int(round((1.0 - confidence) * n)))
    worst = xs[:tail_n]
    mean_tail = statistics.mean(worst)
    return max(0.0, float(-mean_tail))


# ── Parametric CVaR (Gaussian + Student-t) ──────────────────────────────────


def _fit_student_t_df(returns: Sequence[float]) -> float:
    """Estimate Student-t df via MLE (shared with var_models)."""
    if len(returns) < _STUDENT_T_MIN_OBS:
        return _DF_FALLBACK
    try:
        arr = np.array(returns, dtype=np.float64)
        df, _loc, _scale = sp_stats.t.fit(arr, method="mle")
        return float(max(2.01, min(200.0, df)))
    except Exception:  # noqa: BLE001
        return _DF_FALLBACK


def parametric_cvar(
    returns: Sequence[float],
    confidence: float = 0.95,
    *,
    dist: Literal["normal", "student_t"] = "student_t",
    df: float | None = None,
) -> float:
    """Parametric CVaR / Expected Shortfall (closed-form).

    Gaussian ES:
        ES = mu + sigma * phi(z) / (1 - conf)

    Student-t ES (Kamdem, 2005):
        ES = mu + sigma * [f_t(t_inv) * (df + t_inv^2) / ((df-1)*(1-conf))]

    where phi = normal pdf, f_t = t pdf, t_inv = t.ppf(1-conf, df).
    """
    ret = [float(x) for x in returns]
    if len(ret) < 3:
        return _DEFAULT_SHORT_FALLBACK

    mu = float(statistics.mean(ret))
    sig = float(statistics.stdev(ret)) if len(ret) > 1 else 0.02
    alpha = 1.0 - confidence  # tail probability

    if dist == "student_t":
        _df = df if df is not None else _fit_student_t_df(ret)
        if _df <= 1.0:
            _df = 2.01
        # Student-t quantile at alpha (left tail, negative)
        t_alpha = float(sp_stats.t.ppf(alpha, _df))
        # Student-t pdf at the quantile
        f_t = float(sp_stats.t.pdf(t_alpha, _df))
        # Closed-form ES for Student-t (Kamdem 2005)
        es = -mu + sig * f_t * (_df + t_alpha**2) / ((_df - 1.0) * alpha)
    else:
        # Gaussian closed-form ES
        z_alpha = float(sp_stats.norm.ppf(alpha))
        phi_z = float(sp_stats.norm.pdf(z_alpha))
        es = -mu + sig * phi_z / alpha

    return max(0.0, min(0.95, float(es)))


# ── Monte Carlo CVaR ────────────────────────────────────────────────────────


def mc_cvar(
    returns: Sequence[float],
    confidence: float = 0.95,
    *,
    draws: int = 600,
    seed: int = 42,
) -> float:
    """Bootstrap Monte Carlo CVaR — average of worst (1-conf)*draws samples.

    Uses single-return bootstrap (same as mc_var fix in VR-02),
    then computes mean of the tail below the VaR percentile.
    """
    ret = [float(x) for x in returns]
    if len(ret) < 3:
        return _DEFAULT_SHORT_FALLBACK
    rnd = random.Random(seed)
    n = len(ret)
    sim = [ret[rnd.randrange(n)] for _ in range(draws)]
    sim_sorted = sorted(sim)
    tail_n = max(1, int(math.floor((1.0 - confidence) * draws)))
    worst = sim_sorted[:tail_n]
    mean_tail = statistics.mean(worst)
    return max(0.0, min(0.95, float(-mean_tail)))
