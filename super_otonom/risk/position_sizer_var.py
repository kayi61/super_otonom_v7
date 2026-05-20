"""VaR-aware Position Sizing — Kelly + VaR Cap (VR-18).

Wraps the existing ``PositionSizer`` so that every calculated size is
clamped by a marginal VaR constraint:

    final_size = min(kelly_size, var_capped_size)

Binary-search algorithm finds the largest position size whose marginal
VaR contribution does not exceed ``MAX_MARGINAL_VAR_PCT × equity``.

ENV:
    ``MAX_MARGINAL_VAR_PCT`` — default ``0.005`` (0.5 % per trade).

Prometheus:
    ``bot_position_sizer_var_cap_active``  (1 = cap binding, 0 = Kelly smaller)
    ``bot_position_sizer_var_capped_size`` (post-cap size in USDT)

Alerts:
    ``BotVarCapBindingRate`` — cap binding > 80 % of sizing calls for 15 m.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Dict, Mapping, Sequence

import numpy as np

from super_otonom.position_sizer import PositionSizer
from super_otonom.risk.var_models import historical_var

log = logging.getLogger("super_otonom.risk.position_sizer_var")

# Sentinel for var_topology detection
position_sizer_var_cap_active = True

# ── Constants ───────────────────────────────────────────────────────────────

DEFAULT_MAX_MARGINAL_VAR_PCT = 0.005
"""Maximum marginal VaR per trade as fraction of equity (0.5 %)."""

_BISECT_ITERATIONS = 20
"""Binary-search iterations — 2^{-20} ≈ 1e-6 precision."""

_VAR_MIN_OBS = 20
"""Minimum observations per symbol for VaR computation."""

_VAR_CONFIDENCE = 0.99
"""Confidence level for marginal VaR cap (99 %)."""

_EPS = 1e-12


def _env_max_marginal_var_pct() -> float:
    raw = os.environ.get("MAX_MARGINAL_VAR_PCT")
    if raw is None:
        return DEFAULT_MAX_MARGINAL_VAR_PCT
    try:
        v = float(raw)
        if v <= 0 or v >= 1:
            log.warning(
                "MAX_MARGINAL_VAR_PCT=%s degerinin siniri asiliyor, "
                "varsayilan %.4f kullaniliyor.",
                raw,
                DEFAULT_MAX_MARGINAL_VAR_PCT,
            )
            return DEFAULT_MAX_MARGINAL_VAR_PCT
        return v
    except ValueError:
        log.warning(
            "MAX_MARGINAL_VAR_PCT=%s gecersiz, varsayilan %.4f kullaniliyor.",
            raw,
            DEFAULT_MAX_MARGINAL_VAR_PCT,
        )
        return DEFAULT_MAX_MARGINAL_VAR_PCT


# ── Result dataclass ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class VarCapResult:
    """Result of VaR-aware position sizing.

    Attributes
    ----------
    kelly_size : float
        Raw size from PositionSizer (Kelly-based).
    var_capped_size : float
        Size after VaR cap (binary-search output).
    final_size : float
        min(kelly_size, var_capped_size) — the actual trading size.
    cap_binding : bool
        True when VaR cap reduced the Kelly size.
    marginal_var_at_final : float
        Marginal VaR contribution at final_size.
    max_marginal_var : float
        VaR cap threshold (max_marginal_var_pct × equity).
    latency_ms : float
        Computation time in milliseconds.
    """

    kelly_size: float = 0.0
    var_capped_size: float = 0.0
    final_size: float = 0.0
    cap_binding: bool = False
    marginal_var_at_final: float = 0.0
    max_marginal_var: float = 0.0
    latency_ms: float = 0.0


# ── Marginal VaR engine ────────────────────────────────────────────────────


class MarginalVarEngine:
    """Computes marginal VaR for a proposed trade against current positions.

    Uses historical simulation on per-symbol returns to evaluate the
    marginal VaR impact of adding a new position of given notional size.
    """

    def __init__(
        self,
        asset_returns: Mapping[str, Sequence[float]],
        confidence: float = _VAR_CONFIDENCE,
    ):
        self._asset_returns = asset_returns
        self._confidence = confidence

    def marginal_var_for_trade(
        self,
        symbol: str,
        trade_notional: float,
        current_positions: Dict[str, float],
    ) -> float:
        """Compute marginal VaR when adding *trade_notional* of *symbol*.

        Parameters
        ----------
        symbol:
            Asset to trade.
        trade_notional:
            Notional value (USDT) of the proposed position.
        current_positions:
            ``{symbol: notional}`` of existing positions.

        Returns
        -------
        float
            Marginal VaR in absolute terms (USDT-equivalent).
            Returns 0.0 if data is insufficient.
        """
        if trade_notional <= 0:
            return 0.0

        if (
            symbol not in self._asset_returns
            or len(self._asset_returns[symbol]) < _VAR_MIN_OBS
        ):
            return 0.0

        total_before = sum(abs(v) for v in current_positions.values())
        weights_before: Dict[str, float] = {}
        if total_before > _EPS:
            weights_before = {
                s: abs(v) / total_before
                for s, v in current_positions.items()
                if s in self._asset_returns
                and len(self._asset_returns[s]) >= _VAR_MIN_OBS
            }

        total_after = total_before + trade_notional
        weights_after: Dict[str, float] = {}
        if total_after > _EPS:
            for s, v in current_positions.items():
                if (
                    s in self._asset_returns
                    and len(self._asset_returns[s]) >= _VAR_MIN_OBS
                ):
                    weights_after[s] = abs(v) / total_after
            w_existing = weights_after.get(symbol, 0.0)
            weights_after[symbol] = w_existing + trade_notional / total_after

        var_before = self._portfolio_var(weights_before, total_before)
        var_after = self._portfolio_var(weights_after, total_after)

        return max(0.0, var_after - var_before)

    def _portfolio_var(
        self,
        weights: Dict[str, float],
        total_notional: float,
    ) -> float:
        if not weights or total_notional <= _EPS:
            return 0.0

        symbols = [s for s in weights if s in self._asset_returns]
        if not symbols:
            return 0.0

        n = min(len(self._asset_returns[s]) for s in symbols)
        if n < _VAR_MIN_OBS:
            return 0.0

        w_arr = np.array([weights[s] for s in symbols], dtype=np.float64)
        w_sum = w_arr.sum()
        if w_sum < _EPS:
            return 0.0
        w_arr = w_arr / w_sum

        R = np.column_stack(
            [
                np.asarray(self._asset_returns[s][:n], dtype=np.float64)
                for s in symbols
            ]
        )
        port_returns = R @ w_arr

        var_frac = historical_var(
            port_returns.tolist(), self._confidence, horizon_days=1,
        )
        return var_frac * total_notional


# ── Core function ───────────────────────────────────────────────────────────


def size_with_var_cap(
    kelly_size: float,
    symbol: str,
    equity: float,
    var_engine: MarginalVarEngine,
    current_positions: Dict[str, float],
    max_marginal_var_pct: float | None = None,
) -> float:
    """Binary search: find largest size where marginal VaR <= cap.

    Parameters
    ----------
    kelly_size:
        Raw position size from Kelly / PositionSizer.
    symbol:
        Symbol to trade.
    equity:
        Total account equity (USDT).
    var_engine:
        MarginalVarEngine instance with loaded return data.
    current_positions:
        ``{symbol: notional}`` of existing positions.
    max_marginal_var_pct:
        Maximum marginal VaR as fraction of equity.
        ``None`` → reads from ``MAX_MARGINAL_VAR_PCT`` env or default 0.005.

    Returns
    -------
    float
        Capped position size (≤ kelly_size).
    """
    if kelly_size <= 0 or equity <= 0:
        return 0.0

    cap_pct = (
        max_marginal_var_pct
        if max_marginal_var_pct is not None
        else _env_max_marginal_var_pct()
    )
    cap_abs = cap_pct * equity

    mvar_at_full = var_engine.marginal_var_for_trade(
        symbol, kelly_size, current_positions,
    )
    if mvar_at_full <= cap_abs:
        return kelly_size

    lo, hi = 0.0, float(kelly_size)
    for _ in range(_BISECT_ITERATIONS):
        mid = (lo + hi) / 2.0
        mvar = var_engine.marginal_var_for_trade(
            symbol, mid, current_positions,
        )
        if mvar <= cap_abs:
            lo = mid
        else:
            hi = mid

    return lo


# ── Integrated sizer ───────────────────────────────────────────────────────


class VarAwarePositionSizer:
    """Wraps ``PositionSizer`` with a VaR cap layer.

    Usage::

        sizer = VarAwarePositionSizer(
            base_sizer=PositionSizer(...),
            asset_returns={"BTCUSDT": [...], "ETHUSDT": [...]},
        )
        result = sizer.calculate_with_var_cap(
            symbol="BTCUSDT",
            equity=100_000,
            current_positions={"ETHUSDT": 5000},
            volatility=0.02,
            ai_conf=0.7,
        )
        print(result.final_size, result.cap_binding)
    """

    def __init__(
        self,
        base_sizer: PositionSizer,
        asset_returns: Mapping[str, Sequence[float]],
        *,
        max_marginal_var_pct: float | None = None,
        var_confidence: float = _VAR_CONFIDENCE,
    ):
        self._base = base_sizer
        self._var_engine = MarginalVarEngine(asset_returns, var_confidence)
        self._max_marginal_var_pct = (
            max_marginal_var_pct
            if max_marginal_var_pct is not None
            else _env_max_marginal_var_pct()
        )

    @property
    def base_sizer(self) -> PositionSizer:
        return self._base

    @property
    def var_engine(self) -> MarginalVarEngine:
        return self._var_engine

    def calculate_with_var_cap(
        self,
        symbol: str,
        equity: float,
        current_positions: Dict[str, float],
        *,
        max_marginal_var_pct: float | None = None,
        **kwargs,
    ) -> VarCapResult:
        """Calculate position size with both Kelly and VaR cap active.

        Parameters
        ----------
        symbol:
            Trading symbol.
        equity:
            Account equity (USDT).
        current_positions:
            ``{symbol: notional}`` of existing open positions.
        max_marginal_var_pct:
            Override for the per-trade VaR cap. ``None`` → instance default.
        **kwargs:
            Forwarded to ``PositionSizer.calculate()``
            (volatility, ai_conf, etc.).

        Returns
        -------
        VarCapResult
            Contains kelly_size, var_capped_size, final_size, cap_binding.
        """
        t0 = time.perf_counter()

        kelly_size = self._base.calculate(symbol, equity, **kwargs)
        if kelly_size <= 0:
            return VarCapResult(latency_ms=_elapsed_ms(t0))

        cap_pct = max_marginal_var_pct or self._max_marginal_var_pct
        cap_abs = cap_pct * equity

        capped = size_with_var_cap(
            kelly_size=kelly_size,
            symbol=symbol,
            equity=equity,
            var_engine=self._var_engine,
            current_positions=current_positions,
            max_marginal_var_pct=cap_pct,
        )

        final = min(kelly_size, capped)
        binding = final < kelly_size

        mvar_final = self._var_engine.marginal_var_for_trade(
            symbol, final, current_positions,
        )

        elapsed = _elapsed_ms(t0)

        log.debug(
            "VarAwarePositionSizer: symbol=%s kelly=%.2f capped=%.2f "
            "final=%.2f binding=%s mvar=%.4f cap=%.4f (%.1fms)",
            symbol,
            kelly_size,
            capped,
            final,
            binding,
            mvar_final,
            cap_abs,
            elapsed,
        )

        return VarCapResult(
            kelly_size=kelly_size,
            var_capped_size=capped,
            final_size=final,
            cap_binding=binding,
            marginal_var_at_final=mvar_final,
            max_marginal_var=cap_abs,
            latency_ms=elapsed,
        )


def var_cap_result_to_dict(result: VarCapResult) -> dict:
    """Convert to JSON-serializable dictionary."""
    return {
        "kelly_size": result.kelly_size,
        "var_capped_size": result.var_capped_size,
        "final_size": result.final_size,
        "cap_binding": result.cap_binding,
        "marginal_var_at_final": result.marginal_var_at_final,
        "max_marginal_var": result.max_marginal_var,
        "latency_ms": result.latency_ms,
    }


# ── Private helpers ─────────────────────────────────────────────────────────


def _elapsed_ms(t0: float) -> float:
    return (time.perf_counter() - t0) * 1000.0
