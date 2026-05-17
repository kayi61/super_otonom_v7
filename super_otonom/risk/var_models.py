"""VaR models — historical, parametric, Monte Carlo (VR-01/02)."""

from __future__ import annotations

import math
import random
import statistics
from typing import List, Sequence

_EPS = 1e-12
_DEFAULT_SHORT_FALLBACK = 0.09


def _percentile_loss(sorted_returns: Sequence[float], tail_pct: float) -> float:
    if not sorted_returns:
        return 0.10
    xs = sorted(float(x) for x in sorted_returns)
    k = max(0, min(len(xs) - 1, int(math.floor(tail_pct * (len(xs) - 1)))))
    q = xs[k]
    return max(0.0, float(-q))


def historical_var(
    returns: Sequence[float],
    confidence: float = 0.95,
    *,
    horizon_days: int = 1,
) -> float:
    """Historical VaR as positive loss fraction; horizon via sqrt(T)."""
    ret = [float(x) for x in returns]
    if len(ret) < 3:
        return _DEFAULT_SHORT_FALLBACK
    tail = 1.0 - confidence
    loss = _percentile_loss(ret, tail)
    if horizon_days > 1:
        loss *= math.sqrt(float(horizon_days))
    return max(0.0, min(0.95, loss))


def parametric_var(
    returns: Sequence[float],
    confidence: float = 0.95,
    *,
    horizon_days: int = 1,
    z: float | None = None,
) -> float:
    """Gaussian parametric VaR (student-t in VR-02)."""
    ret = [float(x) for x in returns]
    if len(ret) < 3:
        return _DEFAULT_SHORT_FALLBACK
    mu = float(statistics.mean(ret))
    sig = float(statistics.stdev(ret)) if len(ret) > 1 else 0.02
    if z is None:
        z = 1.645 if confidence >= 0.94 else 1.28
    loss = -(mu - z * sig)
    if horizon_days > 1:
        loss *= math.sqrt(float(horizon_days))
    return max(0.0, min(0.95, loss))


def monte_carlo_var(
    returns: Sequence[float],
    confidence: float = 0.95,
    *,
    horizon_days: int = 1,
    draws: int = 600,
    seed: int = 42,
) -> float:
    """Bootstrap mean-return simulation (deterministic seed)."""
    ret = [float(x) for x in returns]
    if len(ret) < 3:
        return 0.085
    rnd = random.Random(seed)
    n = len(ret)
    sim: List[float] = []
    for _ in range(draws):
        sample = [ret[rnd.randrange(n)] for _ in range(n)]
        sim.append(sum(sample) / n)
    loss = historical_var(sim, confidence, horizon_days=1)
    if horizon_days > 1:
        loss *= math.sqrt(float(horizon_days))
    return max(0.0, min(0.95, loss))
