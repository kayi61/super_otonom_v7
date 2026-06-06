"""VR-06 — Extreme Value Theory: Peaks Over Threshold (POT) with GPD fitting.

Supports adaptive thresholds:
  - ``EVT_MIN_SAMPLE = 500`` (legacy default)
  - ``EVT_MIN_SAMPLE_ADAPTIVE = 200`` (bootstrap-robust for smaller samples)

When the sample size is in [200, 500) and bootstrap mode is enabled
(``adaptive=True``), a bootstrap-based GPD estimation is used: the fitting
is repeated ``n_bootstrap`` times on resampled exceedances, and the median
shape/scale is taken.  This produces robust estimates even with limited data.
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

import numpy as np
from scipy.stats import genpareto

# Legacy threshold (backward compat)
EVT_MIN_SAMPLE = 500

# Adaptive threshold for bootstrap-robust GPD
EVT_MIN_SAMPLE_ADAPTIVE = 200

EVT_MIN_EXCEEDANCES = 10
EVT_BOOTSTRAP_REPS = 500


def _gpd_pwm(sorted_samples: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Vectorised Probability-Weighted Moments GPD estimator (Hosking & Wallis 1987).

    ``sorted_samples`` shape ``(reps, n)``, ascending along axis=1. Returns
    ``(shape, scale)`` arrays of length ``reps`` in scipy ``genpareto`` ``c``
    convention (``c = ξ``, ``loc = 0``).

    PWM is closed-form (no optimisation) and is the standard small-sample GPD
    estimator — it replaces the per-resample scipy MLE (Nelder-Mead) that made
    the bootstrap cost ~40s. Derivation (verified for the exponential ξ=0 case):
        a0 = mean(x);  b1 = mean((i-1)/(n-1) · x_(i));  a1 = a0 - b1
        denom = a0 - 2·a1
        shape c = 2 - a0/denom;   scale = 2·a0·a1/denom
    """
    n = sorted_samples.shape[1]
    weights = np.arange(n, dtype=float) / (n - 1)  # (i-1)/(n-1), i=1..n
    a0 = sorted_samples.mean(axis=1)
    b1 = (sorted_samples * weights).mean(axis=1)
    a1 = a0 - b1
    denom = a0 - 2.0 * a1
    with np.errstate(divide="ignore", invalid="ignore"):
        shape = 2.0 - a0 / denom
        scale = 2.0 * a0 * a1 / denom
    return shape, scale


def _bootstrap_gpd_fit(
    exceedances: np.ndarray,
    n_bootstrap: int = EVT_BOOTSTRAP_REPS,
    seed: int = 42,
) -> Tuple[float, float]:
    """Bootstrap-robust GPD parameter estimation (vectorised PWM).

    Resamples exceedances ``n_bootstrap`` times, estimates GPD params for each
    resample via closed-form PWM, and returns median(shape), median(scale).
    Degenerate fits (scale ≤ 0 or shape outside (-1, 2)) are discarded.

    Previously each resample ran ``scipy.stats.genpareto.fit`` (Nelder-Mead),
    so 500 resamples cost ~40 s and blocked the trading loop on 250-day inputs
    (institutional profile). PWM is closed-form and fully vectorised: the same
    500 resamples now cost a few milliseconds with equivalent robustness.
    """
    n = len(exceedances)
    if n < 2:
        s, _, sc = genpareto.fit(exceedances, floc=0)
        return float(s), float(sc)

    rng = np.random.RandomState(seed)
    idx = rng.randint(0, n, size=(n_bootstrap, n))
    samples = np.sort(exceedances[idx], axis=1)  # (reps, n) ascending

    shapes, scales = _gpd_pwm(samples)
    mask = (
        np.isfinite(shapes)
        & np.isfinite(scales)
        & (scales > 0.0)
        & (shapes > -1.0)
        & (shapes < 2.0)
    )

    if int(mask.sum()) < 10:
        # Too many degenerate resamples — fall back to a single MLE fit.
        s, _, sc = genpareto.fit(exceedances, floc=0)
        return float(s), float(sc)

    return float(np.median(shapes[mask])), float(np.median(scales[mask]))


def pot_var_cvar(
    returns: np.ndarray | Sequence[float],
    conf: float = 0.99,
    threshold_quantile: float = 0.95,
    *,
    adaptive: bool = True,
    n_bootstrap: int = EVT_BOOTSTRAP_REPS,
    seed: int = 42,
) -> Tuple[Optional[float], Optional[float]]:
    """Compute VaR and CVaR using Peaks Over Threshold + Generalized Pareto.

    Works in loss space (negated returns) so output is a positive loss
    fraction, consistent with the rest of the risk engine.

    Parameters
    ----------
    returns:
        Return series (negative = loss).
    conf:
        Confidence level (e.g. 0.99).
    threshold_quantile:
        Quantile of the loss distribution for the POT threshold.
    adaptive:
        When *True* and sample size is in [200, 500), use bootstrap-based
        GPD estimation for robustness on smaller samples.
    n_bootstrap:
        Number of bootstrap repetitions (only used in adaptive mode).
    seed:
        Random seed for bootstrap reproducibility.

    Returns
    -------
    (var, cvar) or (None, None)
        ``None`` when the sample is too small or too few exceedances exist.
    """
    arr = np.asarray(returns, dtype=float).ravel()

    # Determine minimum sample based on mode
    min_sample = EVT_MIN_SAMPLE_ADAPTIVE if adaptive else EVT_MIN_SAMPLE
    if len(arr) < min_sample:
        return None, None

    losses = -arr
    u = float(np.quantile(losses, threshold_quantile))
    exceedances = losses[losses > u] - u

    if len(exceedances) < EVT_MIN_EXCEEDANCES:
        return None, None

    # Choose fitting method based on sample size
    use_bootstrap = adaptive and len(arr) < EVT_MIN_SAMPLE
    if use_bootstrap:
        shape, scale = _bootstrap_gpd_fit(exceedances, n_bootstrap, seed)
    else:
        shape, _, scale = genpareto.fit(exceedances, floc=0)

    n_total = len(arr)
    n_exc = len(exceedances)
    tail_prob = n_total / n_exc * (1.0 - conf)

    var_evt = u + (scale / shape) * (tail_prob ** (-shape) - 1.0)
    cvar_evt = var_evt / (1.0 - shape) + (scale - shape * u) / (1.0 - shape)

    return float(var_evt), float(cvar_evt)
