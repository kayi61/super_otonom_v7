"""CVaR / expected shortfall (VR-01 subset; VR-04 expands)."""

from __future__ import annotations

import statistics
from typing import Sequence


def historical_cvar(returns: Sequence[float], confidence: float = 0.95) -> float:
    """CVaR as positive loss fraction (mean of tail at or beyond VaR)."""
    ret = [float(x) for x in returns]
    if len(ret) < 3:
        return 0.12
    xs = sorted(ret)
    n = len(xs)
    tail_n = max(1, int(round((1.0 - confidence) * n)))
    worst = xs[:tail_n]
    mean_tail = statistics.mean(worst)
    return max(0.0, float(-mean_tail))
