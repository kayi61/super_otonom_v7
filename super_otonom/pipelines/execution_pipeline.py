"""v8 — Pozisyon yönetimi: çıkış veya giriş (BotEngine._handle_*)."""
from __future__ import annotations

from typing import Any, Dict

from super_otonom.decision_context import DecisionStage


async def execute_trade_phase(
    engine: Any,
    symbol: str,
    price: float,
    analysis: Dict[str, Any],
    out: Dict[str, Any],
    corr_multiplier: float,
    dctx: Any,
) -> None:
    """Açık pozisyonda çıkış, değilse giriş."""
    final = out["final_signal"]
    conf = float(out.get("ai_confidence") or 0.0)

    if symbol in engine.open_positions:
        dctx.add_trace(DecisionStage.EXIT.value, "open_position")
        await engine._handle_exit(symbol, price, final, out, analysis)
    else:
        await engine._handle_entry(
            symbol,
            price,
            analysis,
            final,
            conf,
            out,
            corr_multiplier=corr_multiplier,
            dctx=dctx,
        )
