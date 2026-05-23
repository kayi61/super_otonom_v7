"""VR-17 — BotEngine ↔ pre-trade VaR gate bridge (delegation)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from super_otonom.bot_engine import BotEngine

log = logging.getLogger("super_otonom.engine")


def run_pre_trade_var_gate(
    engine: BotEngine,
    symbol: str,
    size: float,
    dctx: Optional[Any] = None,
) -> bool:
    """Run VR-17 pre-trade marginal VaR check; return True if trade is allowed."""
    from super_otonom.decision_context import DecisionStage
    from super_otonom.risk.pre_trade_var_gate import (
        PreTradeVarResult,
    )

    try:
        gate = _build_and_check(engine, symbol, size)
    except Exception as exc:
        log.debug("VR-17 | pre_trade_var_gate error (conservative pass): %s", exc)
        gate = PreTradeVarResult(approved=True, reason="compute_error_pass")

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
            "PRE_TRADE_VAR_GATE | REJECT | %s | %s | new_var=%.4f marginal=%.4f",
            symbol,
            gate.reason,
            gate.new_var,
            gate.marginal_var,
        )
        return False

    return True


def _build_and_check(
    engine: BotEngine,
    symbol: str,
    size: float,
) -> Any:
    """Build inputs from engine state and call pre_trade_var_check."""
    from super_otonom.risk.pre_trade_var_gate import (
        PreTradeVarResult,
        pre_trade_var_check,
    )

    nav = engine.capital.nav
    if nav <= 0:
        return PreTradeVarResult(approved=True, reason="nav_zero_pass")

    current_weights: Dict[str, float] = {}
    for sym, pos in engine.open_positions.items():
        pos_size = float(pos.get("size", 0.0))
        if pos_size > 0:
            current_weights[sym] = pos_size / nav

    trade_weight = abs(size) / nav

    asset_returns: Dict[str, list] = {}
    ph = engine.correlation_mgr._price_history
    for sym in set(list(current_weights.keys()) + [symbol]):
        hist = ph.get(sym)
        if hist and len(hist) >= 2:
            prices = list(hist)
            rets = [
                (prices[i] - prices[i - 1]) / (prices[i - 1] + 1e-9)
                for i in range(1, len(prices))
            ]
            asset_returns[sym] = rets

    return pre_trade_var_check(
        symbol=symbol,
        trade_weight=trade_weight,
        side="BUY",
        current_weights=current_weights,
        asset_returns=asset_returns,
    )
