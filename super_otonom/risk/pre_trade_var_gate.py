"""Pre-trade Marginal VaR Gate (VR-17).

Checks whether a proposed trade would breach portfolio VaR limits
**before** the order is sent to the exchange.  Runs after
``gate_buy_size_and_exposure`` in the pre-trade pipeline.

Two limit checks:

    1. **Total VaR**: new portfolio VaR₉₉ must not exceed ``max_var_total_pct``.
    2. **Marginal VaR**: incremental VaR from the trade must not exceed
       ``max_marginal_var_per_trade_pct``.

Target latency: **<30 ms** using cached numpy covariance + historical VaR.

Prometheus:
    ``bot_pre_trade_var_gate_passed``  (1 = passed, 0 = rejected)
    ``bot_pre_trade_var_gate_new_var`` (post-trade VaR₉₉ estimate)
    ``bot_pre_trade_var_gate_marginal_var`` (marginal contribution)

Alerts:
    ``BotPreTradeVarGateReject`` — gate rejecting > 50% of checks for 15m.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Sequence, Tuple

import numpy as np

from super_otonom.risk.var_models import historical_var

log = logging.getLogger("super_otonom.risk.pre_trade_var_gate")

# Sentinel for var_topology detection
pre_trade_var_gate_active = True

# ── Constants ─────────────────────────────────────────────────────────────

GATE_MIN_OBS = 20
"""Minimum observations per symbol to compute VaR."""

GATE_DEFAULT_CONF = 0.99
"""Default confidence level for pre-trade VaR check (99%)."""

_EPS = 1e-12


# ── Limits dataclass ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class PreTradeVarLimits:
    """Risk limits for the pre-trade VaR gate.

    Attributes
    ----------
    max_var_total_pct : float
        Maximum allowed portfolio VaR (fraction, e.g. 0.05 = 5%).
    max_marginal_var_per_trade_pct : float
        Maximum allowed marginal VaR from a single trade (fraction).
    confidence : float
        VaR confidence level (default 0.99).
    """

    max_var_total_pct: float = 0.05
    max_marginal_var_per_trade_pct: float = 0.02
    confidence: float = GATE_DEFAULT_CONF


# ── Result dataclass ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class PreTradeVarResult:
    """Result from pre-trade VaR gate check.

    Attributes
    ----------
    approved : bool
        True if the trade passes all VaR checks.
    reason : str
        Empty if approved, rejection reason otherwise.
    current_var : float
        Portfolio VaR before the trade.
    new_var : float
        Estimated portfolio VaR after the trade.
    marginal_var : float
        Incremental VaR contribution from the trade.
    latency_ms : float
        Computation time in milliseconds.
    symbol : str
        Symbol being traded.
    trade_weight : float
        Weight of the proposed trade in portfolio.
    """

    approved: bool = True
    reason: str = ""
    current_var: float = 0.0
    new_var: float = 0.0
    marginal_var: float = 0.0
    latency_ms: float = 0.0
    symbol: str = ""
    trade_weight: float = 0.0


# ── Portfolio weight simulation ──────────────────────────────────────────

def simulate_trade_weights(
    current_weights: Dict[str, float],
    symbol: str,
    trade_weight: float,
    side: str,
) -> Dict[str, float]:
    """Compute new portfolio weights after a proposed trade.

    Parameters
    ----------
    current_weights:
        Current portfolio weights ``{symbol: weight}``.
        Weights should be positive fractions (long positions).
    symbol:
        Symbol to trade.
    trade_weight:
        Size of the trade as a portfolio weight fraction.
    side:
        ``"BUY"`` or ``"SELL"``.

    Returns
    -------
    Dict[str, float]
        New portfolio weights after the trade.
    """
    new_weights = dict(current_weights)
    delta = abs(trade_weight)

    if side.upper() == "SELL":
        delta = -delta

    new_weights[symbol] = new_weights.get(symbol, 0.0) + delta

    # Remove zero/negative positions (fully closed)
    new_weights = {s: w for s, w in new_weights.items() if w > _EPS}

    return new_weights


# ── Cached covariance VaR helper ─────────────────────────────────────────

def _portfolio_var_from_returns(
    asset_returns: Mapping[str, Sequence[float]],
    weights: Mapping[str, float],
    confidence: float = 0.99,
) -> float:
    """Compute portfolio VaR via historical simulation on weighted returns.

    Uses direct portfolio return reconstruction → historical percentile.
    Fast path: numpy vectorised operations.

    Returns 0.0 if insufficient data.
    """
    symbols = [
        s for s in weights
        if s in asset_returns and len(asset_returns[s]) >= GATE_MIN_OBS
    ]
    if not symbols:
        return 0.0

    n = min(len(asset_returns[s]) for s in symbols)
    if n < GATE_MIN_OBS:
        return 0.0

    # Normalise weights to sum to 1
    raw_w = np.array([abs(weights[s]) for s in symbols], dtype=np.float64)
    w_sum = raw_w.sum()
    if w_sum < _EPS:
        return 0.0
    w = raw_w / w_sum

    # Build return matrix (T x N) and compute portfolio returns
    R = np.column_stack(
        [np.asarray(asset_returns[s][:n], dtype=np.float64) for s in symbols]
    )
    port_returns = R @ w  # (T,) vector

    return historical_var(port_returns.tolist(), confidence, horizon_days=1)


# ── Core gate function ───────────────────────────────────────────────────

def pre_trade_var_check(
    symbol: str,
    trade_weight: float,
    side: str,
    current_weights: Dict[str, float],
    asset_returns: Mapping[str, Sequence[float]],
    limits: Optional[PreTradeVarLimits] = None,
) -> PreTradeVarResult:
    """Check whether a proposed trade would breach VaR limits.

    This is the primary entry point for the pre-trade VaR gate.
    It should be called **after** ``gate_buy_size_and_exposure`` and
    **before** the order is sent to the exchange.

    Parameters
    ----------
    symbol:
        Symbol to trade (e.g. ``"BTCUSDT"``).
    trade_weight:
        Size of the trade as a portfolio weight fraction (positive).
    side:
        ``"BUY"`` or ``"SELL"``.
    current_weights:
        Current portfolio weights ``{symbol: weight}``.
    asset_returns:
        Per-symbol return series ``{symbol: [r1, r2, ...]}``.
    limits:
        VaR limits. Defaults to ``PreTradeVarLimits()`` if not provided.

    Returns
    -------
    PreTradeVarResult
        Contains approval status, rejection reason, VaR metrics,
        and computation latency.
    """
    t0 = time.perf_counter()
    lim = limits or PreTradeVarLimits()

    # Validate inputs
    if trade_weight < 0:
        return PreTradeVarResult(
            approved=False,
            reason="invalid_trade_weight_negative",
            symbol=symbol,
            trade_weight=trade_weight,
            latency_ms=_elapsed_ms(t0),
        )

    if side.upper() not in ("BUY", "SELL"):
        return PreTradeVarResult(
            approved=False,
            reason=f"invalid_side:{side}",
            symbol=symbol,
            trade_weight=trade_weight,
            latency_ms=_elapsed_ms(t0),
        )

    # Check symbol has return data
    if symbol not in asset_returns or len(asset_returns[symbol]) < GATE_MIN_OBS:
        # Insufficient data → conservative pass (can't compute VaR)
        log.warning(
            "Pre-trade VaR gate: insufficient data for %s (%d obs), "
            "allowing trade (conservative pass)",
            symbol,
            len(asset_returns.get(symbol, [])),
        )
        return PreTradeVarResult(
            approved=True,
            reason="insufficient_data_pass",
            symbol=symbol,
            trade_weight=trade_weight,
            latency_ms=_elapsed_ms(t0),
        )

    # 1. Current portfolio VaR
    current_var = _portfolio_var_from_returns(
        asset_returns, current_weights, lim.confidence,
    )

    # 2. Simulated post-trade weights
    new_weights = simulate_trade_weights(
        current_weights, symbol, trade_weight, side,
    )

    # 3. New portfolio VaR
    new_var = _portfolio_var_from_returns(
        asset_returns, new_weights, lim.confidence,
    )

    # 4. Marginal VaR
    marginal = new_var - current_var

    elapsed = _elapsed_ms(t0)

    # 5. Limit checks
    if new_var > lim.max_var_total_pct:
        reason = (
            f"var_limit_breach_total:{new_var:.4f}>"
            f"{lim.max_var_total_pct}"
        )
        log.warning(
            "Pre-trade VaR gate REJECT: %s %s %s — %s "
            "(current=%.4f, new=%.4f, marginal=%.4f, %.1fms)",
            side, symbol, trade_weight, reason,
            current_var, new_var, marginal, elapsed,
        )
        return PreTradeVarResult(
            approved=False,
            reason=reason,
            current_var=current_var,
            new_var=new_var,
            marginal_var=marginal,
            latency_ms=elapsed,
            symbol=symbol,
            trade_weight=trade_weight,
        )

    if marginal > lim.max_marginal_var_per_trade_pct:
        reason = (
            f"var_limit_breach_marginal:{marginal:.4f}>"
            f"{lim.max_marginal_var_per_trade_pct}"
        )
        log.warning(
            "Pre-trade VaR gate REJECT: %s %s %s — %s "
            "(current=%.4f, new=%.4f, marginal=%.4f, %.1fms)",
            side, symbol, trade_weight, reason,
            current_var, new_var, marginal, elapsed,
        )
        return PreTradeVarResult(
            approved=False,
            reason=reason,
            current_var=current_var,
            new_var=new_var,
            marginal_var=marginal,
            latency_ms=elapsed,
            symbol=symbol,
            trade_weight=trade_weight,
        )

    log.debug(
        "Pre-trade VaR gate PASS: %s %s %s "
        "(current=%.4f, new=%.4f, marginal=%.4f, %.1fms)",
        side, symbol, trade_weight,
        current_var, new_var, marginal, elapsed,
    )

    return PreTradeVarResult(
        approved=True,
        reason="",
        current_var=current_var,
        new_var=new_var,
        marginal_var=marginal,
        latency_ms=elapsed,
        symbol=symbol,
        trade_weight=trade_weight,
    )


# ── Batch check helper ───────────────────────────────────────────────────

def pre_trade_var_check_batch(
    trades: Sequence[Tuple[str, float, str]],
    current_weights: Dict[str, float],
    asset_returns: Mapping[str, Sequence[float]],
    limits: Optional[PreTradeVarLimits] = None,
) -> list[PreTradeVarResult]:
    """Run pre-trade VaR gate on multiple trades sequentially.

    Parameters
    ----------
    trades:
        List of ``(symbol, trade_weight, side)`` tuples.
    current_weights:
        Current portfolio weights.
    asset_returns:
        Per-symbol return series.
    limits:
        VaR limits.

    Returns
    -------
    list[PreTradeVarResult]
        One result per trade.  If a trade passes, the portfolio weights
        are updated for the next check (cumulative impact).
    """
    lim = limits or PreTradeVarLimits()
    results: list[PreTradeVarResult] = []
    running_weights = dict(current_weights)

    for sym, tw, sd in trades:
        r = pre_trade_var_check(
            symbol=sym,
            trade_weight=tw,
            side=sd,
            current_weights=running_weights,
            asset_returns=asset_returns,
            limits=lim,
        )
        results.append(r)
        if r.approved and r.reason != "insufficient_data_pass":
            running_weights = simulate_trade_weights(
                running_weights, sym, tw, sd,
            )

    return results


# ── JSON serialization helper ────────────────────────────────────────────

def gate_result_to_dict(result: PreTradeVarResult) -> dict:
    """Convert to JSON-serializable dictionary."""
    return {
        "approved": result.approved,
        "reason": result.reason,
        "current_var": result.current_var,
        "new_var": result.new_var,
        "marginal_var": result.marginal_var,
        "latency_ms": result.latency_ms,
        "symbol": result.symbol,
        "trade_weight": result.trade_weight,
    }


# ── Private helpers ──────────────────────────────────────────────────────

def _elapsed_ms(t0: float) -> float:
    return (time.perf_counter() - t0) * 1000.0
