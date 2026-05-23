"""VR-17/19/21/27 — BotEngine ↔ RiskEngine tick-level bridge (delegation)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from super_otonom.bot_engine import BotEngine

log = logging.getLogger("super_otonom.engine")


# ── VR-17 — Pre-trade marginal VaR gate ─────────────────────────────────


def run_pre_trade_var_gate(
    engine: BotEngine,
    symbol: str,
    size: float,
    dctx: Optional[Any] = None,
) -> bool:
    """Run VR-17 pre-trade marginal VaR check.  Return True = trade allowed."""
    from super_otonom.decision_context import DecisionStage
    from super_otonom.risk.pre_trade_var_gate import PreTradeVarResult

    try:
        gate = _build_and_run_var_gate(engine, symbol, size)
    except Exception as exc:
        log.debug("VR-17 | pre_trade_var_gate error (conservative pass): %s", exc)
        gate = PreTradeVarResult(approved=True, reason="compute_error_pass")

    # Prometheus
    if hasattr(engine.metrics, "record_pre_trade_var_gate"):
        engine.metrics.record_pre_trade_var_gate(
            approved=gate.approved,
            new_var=gate.new_var,
            marginal_var=gate.marginal_var,
        )

    if not gate.approved and gate.reason != "insufficient_data_pass":
        if dctx is not None:
            dctx.entry_blocked = f"PRE_TRADE_VAR:{gate.reason}"
            dctx.add_trace(DecisionStage.ENTRY.value, f"var_gate:{gate.reason}")
        log.warning(
            "VR-17 | PRE_TRADE_GATE REJECTED | %s | reason=%s | "
            "new_var=%.4f marginal=%.4f",
            symbol,
            gate.reason,
            gate.new_var,
            gate.marginal_var,
        )
        return False

    return True


def _build_and_run_var_gate(
    engine: BotEngine,
    symbol: str,
    size: float,
) -> Any:
    """Derive weights + returns from engine state → call pre_trade_var_check."""
    from super_otonom.risk.pre_trade_var_gate import (
        PreTradeVarResult,
        pre_trade_var_check,
    )

    nav = engine.capital.nav
    if nav <= 0:
        return PreTradeVarResult(approved=True, reason="nav_zero_pass")

    # Current portfolio weights from open positions
    current_weights: Dict[str, float] = {}
    for sym, pos in engine.open_positions.items():
        pos_size = float(pos.get("size", 0.0))
        if pos_size > 0:
            current_weights[sym] = pos_size / nav

    trade_weight = abs(size) / nav

    # Per-symbol returns from correlation manager price history
    asset_returns: Dict[str, list] = {}
    ph = engine.correlation_mgr._price_history
    for sym in set(list(current_weights.keys()) + [symbol]):
        hist = ph.get(sym)
        if hist and len(hist) >= 2:
            prices = list(hist)
            asset_returns[sym] = [
                (prices[i] - prices[i - 1]) / (prices[i - 1] + 1e-9)
                for i in range(1, len(prices))
            ]

    return pre_trade_var_check(
        symbol=symbol,
        trade_weight=trade_weight,
        side="BUY",
        current_weights=current_weights,
        asset_returns=asset_returns,
    )


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
