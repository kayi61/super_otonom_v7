"""VR-08 — Liquidity-adjusted VaR (LVaR): BDSS and time-to-liquidate methods.

var_topology marker: ``liquidity_adjusted_var`` — active implementation.
"""

from __future__ import annotations

from typing import Literal, Optional, Sequence

import numpy as np
from scipy.stats import norm

LVAR_MIN_SPREAD_OBS = 20


def bdss_lvar(
    var_market: float,
    position_notional: float,
    spread_history: Sequence[float],
    alpha_spread_quantile: float = 0.99,
) -> Optional[float]:
    """BDSS liquidity-adjusted VaR: market VaR + worst-case half-spread cost.

    Returns ``None`` if spread history is too short (< 20 observations).
    """
    spreads = np.asarray(spread_history, dtype=float).ravel()
    if len(spreads) < LVAR_MIN_SPREAD_OBS:
        return None

    spread_mean = float(np.mean(spreads))
    spread_std = float(np.std(spreads, ddof=1))
    alpha = float(norm.ppf(alpha_spread_quantile))
    liquidity_cost = 0.5 * position_notional * (spread_mean + alpha * spread_std)
    return var_market + max(liquidity_cost, 0.0)


def time_to_liquidate_lvar(
    var_market: float,
    position_qty: float,
    adv: float,
    participation_rate: float = 0.10,
    horizon_days: int = 1,
) -> Optional[float]:
    """Time-to-liquidate LVaR: scales market VaR by sqrt(T_liq / horizon).

    T_liq = position_qty / (participation_rate * ADV).
    Returns ``None`` if ADV is zero or participation_rate is invalid.
    """
    if adv <= 0 or participation_rate <= 0:
        return None
    t_liq = abs(position_qty) / (participation_rate * adv)
    if t_liq <= 0:
        return None
    scaling = np.sqrt(max(t_liq, horizon_days) / horizon_days)
    return var_market * float(scaling)


def compute_lvar(
    var_market: float,
    position_notional: float,
    spread_history: Optional[Sequence[float]],
    position_qty: float = 0.0,
    adv: float = 0.0,
    participation_rate: float = 0.10,
    method: Literal["bdss", "time_to_liquidate", "max_of_both"] = "bdss",
    alpha_spread_quantile: float = 0.99,
) -> tuple[float, float]:
    """Unified LVaR entry point. Returns ``(lvar, data_health)``.

    ``data_health`` is 1.0 when spread data is available, 0.0 when missing
    (fallback: multiplier=1.0, i.e. lvar == var_market).
    """
    has_spread = spread_history is not None and len(spread_history) >= LVAR_MIN_SPREAD_OBS
    has_adv = adv > 0 and position_qty != 0

    if method == "bdss":
        if has_spread:
            result = bdss_lvar(var_market, position_notional, spread_history, alpha_spread_quantile)
            if result is not None:
                return result, 1.0
        return var_market, 0.0

    if method == "time_to_liquidate":
        if has_adv:
            result = time_to_liquidate_lvar(var_market, position_qty, adv, participation_rate)
            if result is not None:
                return result, 1.0
        return var_market, 0.0

    # max_of_both
    lvar_bdss = None
    lvar_ttl = None
    health = 0.0

    if has_spread:
        lvar_bdss = bdss_lvar(var_market, position_notional, spread_history, alpha_spread_quantile)
    if has_adv:
        lvar_ttl = time_to_liquidate_lvar(var_market, position_qty, adv, participation_rate)

    candidates = [v for v in (lvar_bdss, lvar_ttl) if v is not None]
    if candidates:
        health = 1.0 if lvar_bdss is not None else 0.5
        return max(candidates), health

    return var_market, 0.0
