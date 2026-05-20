"""Regime-conditional VaR — VaR from regime-filtered returns (VR-10).

Accumulates returns partitioned by market regime (TRENDING / RANGING /
CRASH_RISK) and computes the full VaR suite for the current regime.
When the regime buffer is too short, the caller falls back to global VaR.

Integration: ``RiskEngine.compute()`` accepts ``current_regime`` and
``regime_var`` kwargs.  Limit = ``max(overall_var, regime_var)``
(conservative).
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Optional, Sequence

from super_otonom.risk.config import RiskConfig

if TYPE_CHECKING:
    from super_otonom.risk.risk_engine import RiskMetrics

REGIME_VAR_DEFAULT_MAXLEN = 2000
KNOWN_REGIMES = ("TRENDING", "RANGING", "CRASH_RISK")

# sentinel so var_topology detects the feature
regime_conditional_var = True  # noqa: N816 — topology marker


class RegimeConditionalVaR:
    """Accumulate returns by regime and compute regime-filtered VaR.

    Usage (live-tick)::

        rcv = RegimeConditionalVaR()
        for tick in stream:
            rcv.record(tick.return_pct, tick.regime)
        metrics = rcv.var_for_current("CRASH_RISK")
    """

    def __init__(self, maxlen: int = REGIME_VAR_DEFAULT_MAXLEN) -> None:
        self._maxlen = maxlen
        self._returns_by_regime: dict[str, deque[float]] = {}

    # ── State inspection ────────────────────────────────────────────────────

    @property
    def regimes(self) -> list[str]:
        return list(self._returns_by_regime.keys())

    def regime_count(self, regime: str) -> int:
        buf = self._returns_by_regime.get(regime)
        return len(buf) if buf else 0

    def returns_for(self, regime: str) -> list[float]:
        buf = self._returns_by_regime.get(regime)
        return list(buf) if buf else []

    # ── Recording ───────────────────────────────────────────────────────────

    def record(self, return_t: float, regime_t: str) -> None:
        if regime_t not in self._returns_by_regime:
            self._returns_by_regime[regime_t] = deque(maxlen=self._maxlen)
        self._returns_by_regime[regime_t].append(float(return_t))

    def bulk_load(
        self,
        returns: Sequence[float],
        regimes: Sequence[str],
    ) -> None:
        if len(returns) != len(regimes):
            raise ValueError("returns and regimes must have equal length")
        for r, reg in zip(returns, regimes):
            self.record(float(r), reg)

    # ── VaR computation ─────────────────────────────────────────────────────

    def var_for_current(
        self,
        current_regime: str,
        config: Optional[RiskConfig] = None,
    ) -> Optional[RiskMetrics]:
        """Full VaR suite from regime-filtered returns.

        Returns ``None`` when the regime has fewer observations than
        ``config.var_history_min_obs`` (default 100).
        """
        from super_otonom.risk.risk_engine import RiskEngine

        history = self.returns_for(current_regime)
        cfg = config or RiskConfig()

        if len(history) < cfg.var_history_min_obs:
            return None

        return RiskEngine(cfg).compute(history)

    # ── Housekeeping ────────────────────────────────────────────────────────

    def reset(self) -> None:
        self._returns_by_regime.clear()

    def reset_regime(self, regime: str) -> None:
        self._returns_by_regime.pop(regime, None)
