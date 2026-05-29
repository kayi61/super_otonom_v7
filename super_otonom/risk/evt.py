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


def _bootstrap_gpd_fit(
    exceedances: np.ndarray,
    n_bootstrap: int = EVT_BOOTSTRAP_REPS,
    seed: int = 42,
) -> Tuple[float, float]:
    """Bootstrap-robust GPD parameter estimation.

    Resamples exceedances ``n_bootstrap`` times, fits GPD to each,
    and returns median(shape), median(scale).  Outlier fits (shape > 2
    or scale ≤ 0) are discarded.
    """
    rng = np.random.RandomState(seed)
    n = len(exceedances)
    shapes: list[float] = []
    scales: list[float] = []

    for _ in range(n_bootstrap):
        idx = rng.randint(0, n, size=n)
        sample = exceedances[idx]
        try:
            s, _, sc = genpareto.fit(sample, floc=0)
            # Discard degenerate fits
            if sc > 0 and -1.0 < s < 2.0:
                shapes.append(s)
                scales.append(sc)
        except Exception:  # noqa: BLE001
            continue

    if len(shapes) < 10:
        # Fallback to single MLE fit
        s, _, sc = genpareto.fit(exceedances, floc=0)
        return float(s), float(sc)

    return float(np.median(shapes)), float(np.median(scales))


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
