"""
Giriş (BUY) öncesi tek kontrol hattı — risk motoru dışındaki 'hayır' koşulları.

risk.check_risk() BotEngine.tick başında çalışmaya devam eder (portföy/Acil).
Bu modül, yalnızca BUY açılışındaki sinyal / boyut / bakiye / can_open birleşimidir.

`merge_entry_notional()`: `sizer.calculate` (teknik) ile `analysis["ob_safe_size"]`
(emir defteri + validate_and_calculate) — tek tavan: min(ikisi), ob≤0 → giriş yok.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Tuple

from super_otonom.config import RISK

if TYPE_CHECKING:
    from super_otonom.position_sizer import PositionSizer

VALID_BUY = {"BUY"}
_MAX_OPEN = RISK.get("max_open_positions", 1)


def gate_global_trade_disable() -> tuple[bool, str]:
    """
    Operasyon: GLOBAL_TRADE_DISABLE=1 — tick başında, RiskManager'ı tüketmeden tüm yolu kapat.

    Dönüş: (True, "") → serbest; (False, "global_trade_disable") → EMERGENCY_STOP
    """
    v = (os.getenv("GLOBAL_TRADE_DISABLE", "") or "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return False, "global_trade_disable"
    return True, ""


def _min_entry_confidence() -> float:
    import os

    try:
        v = float(
            os.getenv("ENTRY_MIN_CONFIDENCE", str(RISK.get("entry_min_confidence", 0.55)))
            or 0.55
        )
    except ValueError:
        v = 0.55
    return max(0.45, min(0.95, v))


def gate_buy_signal_and_slots(
    signal: str,
    open_position_count: int,
    confidence: float,
) -> Tuple[bool, str]:
    """
    Sinyal BUY değilse (burada) engelleme yok — çağıran sadece BUY yolunda kullanır.
    BUY için: maks. açık pozisyon ve güven eşiği.
    """
    if signal not in VALID_BUY:
        return True, ""
    if open_position_count >= int(_MAX_OPEN):
        return False, "max_open_positions"
    if confidence < _min_entry_confidence():
        return False, "below_entry_confidence"
    return True, ""


def merge_entry_notional(technical_notional: float, ob_safe_size: Any) -> Tuple[float, str, str]:
    """
    Single source: teknik tavan (Kelly/vol) ile tahta-tabanlı güvenli notional (USDT).

    Dönüş: (raw_notional, sizing_source, entry_blocked)
    - entry_blocked: "" → açılabilir; "ob_safe_size_zero" → main_loop defter filtresi kapattı
    - ob_safe_size yok (None) → sadece teknik (test / OB çekilmediyse)
    """
    tech = max(0.0, float(technical_notional))
    if ob_safe_size is None:
        return tech, "technical_only", ""
    try:
        ob = float(ob_safe_size)
    except (TypeError, ValueError):
        return tech, "technical_only_invalid_ob", ""
    if ob <= 0:
        return 0.0, "ob_safe_blocked", "ob_safe_size_zero"
    return min(tech, ob), "min_technical_ob_safe", ""


def gate_buy_size_and_exposure(
    sizer: "PositionSizer",
    symbol: str,
    equity: float,
    size_after_corr: float,
    raw_size: float,
    free_capital: float,
    open_positions: dict,
) -> Tuple[bool, str]:
    """
    Boyut, min notional, serbest bakiye ve toplam exposure tavanı.
    """
    if size_after_corr <= 0 or size_after_corr < sizer.min_notional:
        return False, "size_below_min_notional"
    if size_after_corr > free_capital:
        return False, "insufficient_free_capital"
    if not sizer.can_open(
        size_after_corr, equity, open_positions, max_total_pct=0.80
    ):
        return False, "exposure_cap"
    if raw_size <= 0:
        return False, "raw_size_zero"
    return True, ""
