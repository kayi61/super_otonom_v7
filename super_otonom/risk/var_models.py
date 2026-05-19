"""VaR models — historical, parametric, Monte Carlo, Cornish-Fisher (VR-02/03)."""

from __future__ import annotations

import math
import random
import statistics
from typing import Literal, Sequence

import numpy as np
from scipy import stats as sp_stats

_EPS = 1e-12
_DEFAULT_SHORT_FALLBACK = 0.09

# Student-t MLE: minimum observations before attempting fit
_STUDENT_T_MIN_OBS = 15
# Degrees-of-freedom bounds for Student-t MLE
_DF_MIN = 2.01
_DF_MAX = 200.0
_DF_FALLBACK = 5.0  # crypto fat-tail default when MLE fails or n < threshold


def _percentile_loss(sorted_returns: Sequence[float], tail_pct: float) -> float:
    """Return positive VaR loss at the given left-tail percentile."""
    if not sorted_returns:
        return 0.10
    xs = sorted(float(x) for x in sorted_returns)
    k = max(0, min(len(xs) - 1, int(math.floor(tail_pct * (len(xs) - 1)))))
    q = xs[k]
    return max(0.0, float(-q))


# ── Historical VaR ──────────────────────────────────────────────────────────


def historical_var(
    returns: Sequence[float],
    confidence: float = 0.95,
    *,
    horizon_days: int = 1,
) -> float:
    """Historical VaR as positive loss fraction; horizon scaled via sqrt(T)."""
    ret = [float(x) for x in returns]
    if len(ret) < 3:
        return _DEFAULT_SHORT_FALLBACK
    tail = 1.0 - confidence
    loss = _percentile_loss(ret, tail)
    if horizon_days > 1:
        loss *= math.sqrt(float(horizon_days))
    return max(0.0, min(0.95, loss))


# ── Parametric VaR (Gaussian + Student-t) ────────────────────────────────────


def _fit_student_t_df(returns: Sequence[float]) -> float:
    """Estimate Student-t degrees of freedom via MLE; clamp to [_DF_MIN, _DF_MAX]."""
    if len(returns) < _STUDENT_T_MIN_OBS:
        return _DF_FALLBACK
    try:
        arr = np.array(returns, dtype=np.float64)
        df, _loc, _scale = sp_stats.t.fit(arr, method="mle")
        return float(max(_DF_MIN, min(_DF_MAX, df)))
    except Exception:  # noqa: BLE001 — MLE can diverge on degenerate data
        return _DF_FALLBACK


def parametric_var(
    returns: Sequence[float],
    confidence: float = 0.95,
    *,
    horizon_days: int = 1,
    z: float | None = None,
    dist: Literal["normal", "student_t"] = "student_t",
    df: float | None = None,
) -> float:
    """Parametric VaR — Gaussian or Student-t (default: student_t for crypto fat-tails).

    Parameters
    ----------
    dist : "normal" | "student_t"
        Distribution family. ``student_t`` (default) captures heavy tails.
    df : float | None
        Student-t degrees of freedom. ``None`` → estimate via MLE.
    z : float | None
        Z-score override (Gaussian mode). Ignored when *dist* = ``student_t``.
    """
    ret = [float(x) for x in returns]
    if len(ret) < 3:
        return _DEFAULT_SHORT_FALLBACK

    mu = float(statistics.mean(ret))
    sig = float(statistics.stdev(ret)) if len(ret) > 1 else 0.02

    if dist == "student_t":
        # Student-t quantile: heavier tail → larger multiplier than Gaussian z
        # t_ppf(0.05, df=3) ≈ -2.35 vs normal ppf(0.05) = -1.645
        _df = df if df is not None else _fit_student_t_df(ret)
        # Left-tail quantile (negative value)
        q = float(sp_stats.t.ppf(1.0 - confidence, _df))
        # VaR = -(mu + q * sigma)  — standard quant-finance convention
        # No scale adjustment: sample sigma used directly; the heavier tail
        # quantile (|q| > |z|) is what captures fat-tail risk.
        loss = -(mu + q * sig)
    else:
        # Gaussian parametric VaR (legacy)
        if z is None:
            z = 1.645 if confidence >= 0.94 else 1.28
        loss = -(mu - z * sig)

    if horizon_days > 1:
        loss *= math.sqrt(float(horizon_days))
    return max(0.0, min(0.95, loss))


# ── Monte Carlo VaR ─────────────────────────────────────────────────────────


def monte_carlo_var(
    returns: Sequence[float],
    confidence: float = 0.95,
    *,
    horizon_days: int = 1,
    draws: int = 600,
    seed: int = 42,
) -> float:
    """Bootstrap single-return simulation with deterministic seed.

    VR-02 FIX: Previous implementation computed mean-of-means
    (``sum(sample)/n``) — this converges to the sample mean by CLT
    and is **NOT** a VaR estimate.  Correct approach: each draw is
    a single bootstrapped return; VaR is the percentile of draws.
    """
    ret = [float(x) for x in returns]
    if len(ret) < 3:
        return 0.085
    rnd = random.Random(seed)
    n = len(ret)
    # Each draw: single bootstrapped return (NOT mean of n samples)
    sim = [ret[rnd.randrange(n)] for _ in range(draws)]
    # VaR = negative percentile at (1-confidence)
    sim_arr = np.array(sim, dtype=np.float64)
    loss = float(-np.percentile(sim_arr, (1.0 - confidence) * 100.0))
    if horizon_days > 1:
        loss *= math.sqrt(float(horizon_days))
    return max(0.0, min(0.95, loss))


# ── Cornish-Fisher VaR (VR-03) ──────────────────────────────────────────────

# Minimum observations for reliable skewness/kurtosis estimation
_CF_MIN_OBS = 20


def cornish_fisher_var(
    returns: Sequence[float],
    confidence: float = 0.95,
    *,
    horizon_days: int = 1,
) -> float:
    """Cornish-Fisher expansion VaR — adjusts Gaussian quantile for skew & kurtosis.

    Uses the 4th-order Cornish-Fisher expansion:

        z_cf = z + (z**2-1)*S/6 + (z**3-3z)*K/24 - (2z**3-5z)*S**2/36

    where *z* = normal PPF, *S* = sample skewness, *K* = excess kurtosis (Fisher).
    For symmetric normal data (S=0, K=0) this reduces to plain Gaussian VaR.
    For negatively skewed / leptokurtic crypto returns it produces a **larger**
    VaR than the Gaussian, capturing tail asymmetry without a full distribution fit.
    """
    ret = [float(x) for x in returns]
    if len(ret) < _CF_MIN_OBS:
        return _DEFAULT_SHORT_FALLBACK

    arr = np.array(ret, dtype=np.float64)
    mu = float(np.mean(arr))
    sig = float(np.std(arr, ddof=1))
    if sig < _EPS:
        return 0.0

    # Sample skewness and excess kurtosis (Fisher definition, bias=True for MLE)
    s = float(sp_stats.skew(arr, bias=True))
    k = float(sp_stats.kurtosis(arr, fisher=True, bias=True))

    # Gaussian quantile (right-tail, positive value for conf > 0.5)
    z = float(sp_stats.norm.ppf(confidence))

    # Cornish-Fisher adjusted quantile
    z_cf = (
        z
        + (z**2 - 1.0) * s / 6.0
        + (z**3 - 3.0 * z) * k / 24.0
        - (2.0 * z**3 - 5.0 * z) * s**2 / 36.0
    )

    # Guard: CF expansion can become non-monotone for extreme moments.
    # If adjusted quantile is below the Gaussian (shouldn't decrease for
    # leptokurtic data) or is negative, fall back to Gaussian z.
    if z_cf < z:
        z_cf = z

    loss = -(mu - z_cf * sig)
    if horizon_days > 1:
        loss *= math.sqrt(float(horizon_days))
    return max(0.0, min(0.95, loss))
