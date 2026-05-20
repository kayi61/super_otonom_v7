"""VR-06 — Extreme Value Theory: Peaks Over Threshold (POT) with GPD fitting."""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

import numpy as np
from scipy.stats import genpareto

EVT_MIN_SAMPLE = 500
EVT_MIN_EXCEEDANCES = 10


def pot_var_cvar(
    returns: np.ndarray | Sequence[float],
    conf: float = 0.99,
    threshold_quantile: float = 0.95,
) -> Tuple[Optional[float], Optional[float]]:
    """Compute VaR and CVaR using Peaks Over Threshold + Generalized Pareto.

    Works in loss space (negated returns) so output is a positive loss
    fraction, consistent with the rest of the risk engine.

    Returns ``(None, None)`` when the sample is too small (< 500) or
    when fewer than 10 exceedances exist above the threshold.
    """
    arr = np.asarray(returns, dtype=float).ravel()
    if len(arr) < EVT_MIN_SAMPLE:
        return None, None

    losses = -arr
    u = float(np.quantile(losses, threshold_quantile))
    exceedances = losses[losses > u] - u

    if len(exceedances) < EVT_MIN_EXCEEDANCES:
        return None, None

    shape, _, scale = genpareto.fit(exceedances, floc=0)

    n_total = len(arr)
    n_exc = len(exceedances)
    tail_prob = n_total / n_exc * (1.0 - conf)

    var_evt = u + (scale / shape) * (tail_prob ** (-shape) - 1.0)
    cvar_evt = var_evt / (1.0 - shape) + (scale - shape * u) / (1.0 - shape)

    return float(var_evt), float(cvar_evt)
