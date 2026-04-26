"""
v8 — İşlem modu durum makinesi (AGGRESSIVE / DEFENSIVE / NO_TRADE / EMERGENCY).

Otomatik geçiş kuralları yalnızca *okuma* ile hesaplanır; kalıcı state BotEngine
içinde risk ve acil bayraklarıyla zaten tutulur. Bu modül tek tick görünümü üretir.
"""
from __future__ import annotations

import os
from enum import Enum
from typing import Any


class TradingState(str, Enum):
    AGGRESSIVE = "AGGRESSIVE"
    DEFENSIVE = "DEFENSIVE"
    NO_TRADE = "NO_TRADE"
    EMERGENCY = "EMERGENCY"


def _global_trade_blocked() -> bool:
    v = (os.getenv("GLOBAL_TRADE_DISABLE", "") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def compute_trading_state(engine: Any, analysis: dict) -> TradingState:
    """
    Otomatik geçiş kuralları (öncelik sırası):
      1) emergency_stop veya EMERGENCY_STOP içeren kod → EMERGENCY
      2) GLOBAL_TRADE_DISABLE → NO_TRADE
      3) Yüksek oynaklık veya sıkı OMEGA kalite → DEFENSIVE
      4) Aksi halde AGGRESSIVE
    """
    if getattr(engine.risk, "emergency_stop", False):
        return TradingState.EMERGENCY
    if _global_trade_blocked():
        return TradingState.NO_TRADE
    vol = float((analysis or {}).get("volatility", 0.0) or 0.0)
    if vol >= 0.08:
        return TradingState.DEFENSIVE
    tighten = int(getattr(engine.risk, "_omega_qmin_tighten", 0) or 0)
    if tighten >= 15:
        return TradingState.DEFENSIVE
    return TradingState.AGGRESSIVE
