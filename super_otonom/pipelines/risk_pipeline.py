"""v8 — Risk ön kontrolleri (kill switch, fiyat spike, portföy risk, FORCE_ALL_CLOSE)."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

from super_otonom.decision_context import DecisionStage

log = logging.getLogger("super_otonom.pipelines.risk")


def force_all_close_requested() -> bool:
    """Ortam: FORCE_ALL_CLOSE=1 — açık pozisyonları kapat, yeni girişleri engelle."""
    v = (os.getenv("FORCE_ALL_CLOSE", "") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def tick_kill_switch_and_spike(
    engine: Any,
    symbol: str,
    price: float,
    dctx: Any,
    out: Dict[str, Any],
) -> bool:
    """
    Global kill + fiyat spike. True dönerse tick erken çıkmalıdır.
    """
    from super_otonom.hard_safety_contract import enforce_global_trade_allowed

    g_ok, g_code = enforce_global_trade_allowed()
    if not g_ok:
        dctx.risk_passed = False
        dctx.emergency_code = f"EMERGENCY_STOP:{g_code}"
        dctx.add_trace("kill_switch", g_code)
        out["decision_context"] = dctx.to_dict()
        log.critical("EMERGENCY_STOP | code=%s | symbol=%s", g_code, symbol)
        return True

    p_spike = engine._hard_limits.check_price_tick(symbol, price)
    if p_spike and symbol not in engine.open_positions:
        engine.risk.trigger_emergency(p_spike, silent=True)
        dctx.risk_passed = False
        dctx.emergency_code = f"EMERGENCY_STOP:{p_spike}"
        dctx.add_trace("kill_switch", p_spike)
        out["decision_context"] = dctx.to_dict()
        log.critical(
            "EMERGENCY_STOP | code=%s | symbol=%s | close=%.6f (fiyat_sapma)",
            p_spike,
            symbol,
            price,
        )
        return True
    if p_spike and symbol in engine.open_positions:
        dctx.add_trace("kill_switch", f"{p_spike}_ignored_open_position")
        log.warning("KILL | %s bariyer yoksay (acik_poz) | %s", p_spike, symbol)
    return False


def tick_portfolio_risk(
    engine: Any,
    symbol: str,
    exposure: float,
    current_vol: float,
    dctx: Any,
    out: Dict[str, Any],
) -> bool:
    """
    RiskManager.check_risk. False → tick erken çık.
    """
    import super_otonom.bot_engine as be_mod

    if not engine.risk.check_risk(engine.equity, open_exposure=exposure, current_vol=current_vol):
        dctx.risk_passed = False
        den = engine.risk.get_last_deny()
        dctx.add_trace(
            DecisionStage.RISK.value,
            den or "check_risk blocked",
        )
        dctx.final_signal = "HOLD"
        if engine.risk.emergency_stop and getattr(engine.risk, "emergency_reason", None):
            dctx.emergency_code = f"EMERGENCY_STOP:{engine.risk.emergency_reason}"
        elif engine.risk.emergency_stop:
            dctx.emergency_code = "EMERGENCY_STOP:unknown"
        out["decision_context"] = dctx.to_dict()
        eng_log = be_mod.log
        if dctx.emergency_code:
            eng_log.critical(
                "EMERGENCY_STOP | context=%s | symbol=%s | eq=%.2f | acik_tutar=%.2f",
                dctx.emergency_code,
                symbol,
                engine.equity,
                exposure,
            )
        else:
            eng_log.info(
                "GIRIS | risk_capali | symbol=%s | eq=%.2f | acik_tutar=%.2f | reason=%s",
                symbol,
                engine.equity,
                exposure,
                den or "?",
            )
        return False
    dctx.add_trace(DecisionStage.RISK.value, "ok")
    return True
