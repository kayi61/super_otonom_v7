"""VaR decomposition — Component / Marginal / Incremental (VR-09).

Euler decomposition via variance-covariance approach:

    MVaR_i  = VaR_p * (Σw)_i / σ_p²     (marginal)
    CVaR_i  = w_i * MVaR_i                (component)
    Σ CVaR_i = VaR_p                      (invariant)

Incremental VaR uses full revaluation (historical) for pre-trade analysis.
"""

from __future__ import annotations

from typing import Mapping, Optional, Sequence, Tuple

import numpy as np

from super_otonom.risk.var_models import historical_var

DECOMP_MIN_OBS = 20
_EPS = 1e-12


def _build_aligned_matrix(
    asset_returns: Mapping[str, Sequence[float]],
    weights: Mapping[str, float],
    min_obs: int = DECOMP_MIN_OBS,
) -> Tuple[list[str], np.ndarray, np.ndarray]:
    """Align asset returns into (T, N) matrix and normalised (N,) weight vector.

    Returns ``(symbols, R, w)`` — empty when insufficient data.
    """
    symbols = [
        s
        for s in weights
        if s in asset_returns and len(asset_returns[s]) >= min_obs
    ]
    if len(symbols) < 2:
        return [], np.empty((0, 0)), np.empty(0)

    n = min(len(asset_returns[s]) for s in symbols)
    if n < min_obs:
        return [], np.empty((0, 0)), np.empty(0)

    R = np.column_stack(
        [np.array(asset_returns[s][:n], dtype=np.float64) for s in symbols]
    )

    raw_w = np.array([abs(weights[s]) for s in symbols], dtype=np.float64)
    w_sum = raw_w.sum()
    if w_sum < _EPS:
        return [], np.empty((0, 0)), np.empty(0)
    w = raw_w / w_sum

    return symbols, R, w


# ── Batch computation (used by RiskEngine) ──────────────────────────────────


def compute_var_decomposition(
    asset_returns: Mapping[str, Sequence[float]],
    weights: Mapping[str, float],
    var_total: float,
) -> Tuple[dict[str, float], dict[str, float]]:
    """Component and marginal VaR for every portfolio position.

    Returns ``(component_var_dict, marginal_var_dict)``.

    Invariant: ``sum(component_var_dict.values()) ≈ var_total``.
    """
    if var_total <= 0:
        return {}, {}

    symbols, R, w = _build_aligned_matrix(asset_returns, weights)
    if not symbols:
        return {}, {}

    cov = np.cov(R, rowvar=False, ddof=1)
    port_var = float(w @ cov @ w)
    if port_var < _EPS:
        return (
            {s: 0.0 for s in symbols},
            {s: 0.0 for s in symbols},
        )

    cov_w = cov @ w

    mvar_arr = var_total * cov_w / port_var
    cvar_arr = w * mvar_arr

    marginal = {s: float(mvar_arr[i]) for i, s in enumerate(symbols)}
    component = {s: float(cvar_arr[i]) for i, s in enumerate(symbols)}

    return component, marginal


# ── Per-symbol helpers ──────────────────────────────────────────────────────


def marginal_var(
    symbol: str,
    asset_returns: Mapping[str, Sequence[float]],
    weights: Mapping[str, float],
    var_total: float,
) -> float:
    """dVaR/dw_i — sensitivity of portfolio VaR to weight change in *symbol*."""
    _, mvars = compute_var_decomposition(asset_returns, weights, var_total)
    return mvars.get(symbol, 0.0)


def component_var(
    symbol: str,
    asset_returns: Mapping[str, Sequence[float]],
    weights: Mapping[str, float],
    var_total: float,
) -> float:
    """w_i * MVaR_i — *symbol*'s additive contribution to total VaR."""
    cvars, _ = compute_var_decomposition(asset_returns, weights, var_total)
    return cvars.get(symbol, 0.0)


# ── Incremental VaR (pre-trade analysis) ────────────────────────────────────


def incremental_var(
    new_trade_symbol: str,
    new_trade_weight: float,
    asset_returns: Mapping[str, Sequence[float]],
    current_weights: Mapping[str, float],
    confidence: float = 0.95,
) -> Optional[float]:
    """VaR(portfolio + trade) − VaR(portfolio) via historical revaluation.

    *new_trade_weight* is the target allocation (0 < w < 1); existing
    positions are scaled down proportionally to make room.

    Returns ``None`` when data is insufficient.
    """
    curr_symbols = [
        s
        for s in current_weights
        if s in asset_returns and len(asset_returns[s]) >= DECOMP_MIN_OBS
    ]
    if not curr_symbols:
        return None

    n = min(len(asset_returns[s]) for s in curr_symbols)
    if n < DECOMP_MIN_OBS:
        return None

    raw_w = {s: abs(current_weights[s]) for s in curr_symbols}
    w_sum = sum(raw_w.values())
    if w_sum < _EPS:
        return None
    curr_w = {s: v / w_sum for s, v in raw_w.items()}

    curr_ret = [
        sum(curr_w[s] * float(asset_returns[s][i]) for s in curr_symbols)
        for i in range(n)
    ]
    var_before = historical_var(curr_ret, confidence, horizon_days=1)

    trade_w = abs(new_trade_weight)
    if trade_w < _EPS or trade_w >= 1.0:
        return None

    if (
        new_trade_symbol not in asset_returns
        or len(asset_returns[new_trade_symbol]) < DECOMP_MIN_OBS
    ):
        return None

    new_symbols = list(set(curr_symbols + [new_trade_symbol]))
    n_new = min(len(asset_returns[s]) for s in new_symbols)
    n_new = min(n_new, n)
    if n_new < DECOMP_MIN_OBS:
        return None

    scale = 1.0 - trade_w
    new_w: dict[str, float] = {s: curr_w[s] * scale for s in curr_symbols}
    new_w[new_trade_symbol] = new_w.get(new_trade_symbol, 0.0) + trade_w

    new_ret = [
        sum(new_w[s] * float(asset_returns[s][i]) for s in new_w)
        for i in range(n_new)
    ]
    var_after = historical_var(new_ret, confidence, horizon_days=1)

    return var_after - var_before
