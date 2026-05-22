"""VR-19/21/27 — BotEngine ↔ RiskEngine tick-level bridge (delegation)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from super_otonom.bot_engine import BotEngine

log = logging.getLogger("super_otonom.engine")


def tick_record_return_and_regime(engine: BotEngine) -> None:
    """Record NAV-based return + update regime detector (VR-19/27)."""
    cur_nav = engine.capital.nav
    prev_nav = engine._prev_nav

    if prev_nav > 0 and cur_nav > 0:
        tick_ret = (cur_nav - prev_nav) / prev_nav
        engine.risk.record_return(tick_ret)

        if engine._regime_detector is not None:
            try:
                rh = engine.risk._returns_history
                if len(rh) >= 60 and not engine._regime_fitted:
                    engine._regime_detector.fit(rh)
                    engine._regime_fitted = True
                elif engine._regime_fitted:
                    regime = engine._regime_detector.update(tick_ret)
                    engine._regime_var.record(tick_ret, regime)
            except Exception:
                pass

    engine._prev_nav = cur_nav


def tick_record_var_suite(engine: BotEngine) -> None:
    """Record VaR/CVaR full suite to Prometheus (VR-21)."""
    if engine._risk_engine is None:
        return
    if engine._tick_counter % engine._var_suite_interval != 0:
        return
    if len(engine.risk._returns_history) < 20:
        return

    try:
        regime_label: Optional[str] = None
        rv: Any = None
        if engine._regime_fitted and engine._regime_detector is not None:
            rs = engine._regime_detector.current_regime()
            if rs is not None:
                regime_label = rs.regime
                rv = engine._regime_var

        rm = engine._risk_engine.compute(
            engine.risk._returns_history,
            current_regime=regime_label,
            regime_var=rv,
        )
        if hasattr(engine.metrics, "record_var_suite"):
            engine.metrics.record_var_suite(rm)
    except Exception as exc:
        log.debug("VR-21 | VaR suite Prometheus yazım hatası: %s", exc)
