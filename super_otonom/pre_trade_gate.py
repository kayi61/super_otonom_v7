"""
Giriş (BUY) öncesi tek kontrol hattı — risk motoru dışındaki 'hayır' koşulları.

risk.check_risk() BotEngine.tick başında çalışmaya devam eder (portföy/Acil).
Bu modül, yalnızca BUY açılışındaki sinyal / boyut / bakiye / can_open birleşimidir.

`merge_entry_notional()`: `sizer.calculate` (teknik) ile `analysis["ob_safe_size"]`
(emir defteri + validate_and_calculate) — tek tavan: min(ikisi), ob≤0 → giriş yok.
"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from super_otonom.config import RISK

if TYPE_CHECKING:
    from super_otonom.position_sizer import PositionSizer

log = logging.getLogger("super_otonom.pre_trade_gate")

VALID_BUY = {"BUY"}
_MAX_OPEN = RISK.get("max_open_positions", 1)

# ── Faz 3 sabitleri ────────────────────────────────────────────────────────
_MAX_NOTIONAL_PER_ORDER: float = float(RISK.get("max_notional_per_order", 50_000.0))
_MAX_SPREAD_PCT:         float = float(RISK.get("max_spread_pct", 0.005))   # %0.5
_MIN_OB_DEPTH:           float = float(RISK.get("min_ob_depth", 1_000.0))   # USDT


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


# ── Faz 3: Fat-finger check ───────────────────────────────────────────────

def fat_finger_check(
    size: float,
    max_notional: Optional[float] = None,
) -> Tuple[bool, str]:
    """
    Tek order için maksimum notional üst sınırı.
    Yanlışlıkla çok büyük emir gönderilmesini engeller.

    Dönüş: (True, "") → geçti | (False, neden) → engellendi
    """
    limit = max_notional if max_notional is not None else _MAX_NOTIONAL_PER_ORDER
    if size >= limit:
        log.warning(
            "FAT_FINGER | size=%.2f > max_notional=%.2f | emir engellendi",
            size, limit,
        )
        return False, f"fat_finger_max_notional:{limit:.0f}"
    return True, ""


# ── Faz 3: Spread threshold ───────────────────────────────────────────────

def spread_check(
    order_book: Dict[str, Any],
    max_spread_pct: Optional[float] = None,
) -> Tuple[bool, str]:
    """
    Bid-ask spread çok genişse giriş engellenir.
    spread_pct = (ask - bid) / mid_price

    Dönüş: (True, "") → spread normal | (False, neden) → çok geniş
    """
    limit = max_spread_pct if max_spread_pct is not None else _MAX_SPREAD_PCT
    try:
        best_bid = float(order_book["bids"][0][0])
        best_ask = float(order_book["asks"][0][0])
    except (KeyError, IndexError, TypeError, ValueError):
        return True, ""   # OB verisi yoksa geç — engelleme

    if best_bid <= 0 or best_ask <= 0:
        return True, ""

    mid   = (best_bid + best_ask) / 2.0
    spread_pct = (best_ask - best_bid) / mid

    if spread_pct > limit:
        log.warning(
            "SPREAD_WIDE | bid=%.6f ask=%.6f spread=%.4f%% > limit=%.4f%% | engellendi",
            best_bid, best_ask, spread_pct * 100, limit * 100,
        )
        return False, f"spread_too_wide:{spread_pct:.4f}"
    return True, ""


# ── Faz 3: OB depth check ─────────────────────────────────────────────────

def ob_depth_check(
    order_book: Dict[str, Any],
    order_size: float,
    min_depth: Optional[float] = None,
) -> Tuple[bool, str]:
    """
    Ask tarafı toplam derinliği order_size'dan yeterince büyük olmalı.
    min_depth: ask tarafında bulunması gereken minimum toplam USDT.

    Dönüş: (True, "") → yeterli | (False, neden) → yetersiz likidite
    """
    depth_limit = min_depth if min_depth is not None else _MIN_OB_DEPTH
    try:
        asks = order_book.get("asks", [])
        if not asks:
            return True, ""   # veri yoksa geç
        total_ask_depth = sum(float(p) * float(q) for p, q in asks[:20])
    except (TypeError, ValueError):
        return True, ""

    # Emir boyutunun en az depth_limit kadar likidite gerektirdiğini kontrol et
    required = max(depth_limit, order_size * 2.0)
    if total_ask_depth < required:
        log.warning(
            "OB_DEPTH_LOW | depth=%.2f < required=%.2f | emir=%0.2f | engellendi",
            total_ask_depth, required, order_size,
        )
        return False, f"ob_depth_insufficient:{total_ask_depth:.0f}"
    return True, ""


# ── Faz 3: Same-bar duplicate koruması ───────────────────────────────────

def same_bar_guard(
    symbol: str,
    bar_timestamp_ms: float,
    last_order_ts: Dict[str, float],
) -> Tuple[bool, str]:
    """
    Aynı bar içinde aynı sembol için ikinci emir engellenir.
    bar_timestamp_ms: mevcut mumun açılış timestamp'i (ms).
    last_order_ts: {symbol: bar_timestamp_ms} — BotEngine tarafından tutulur.

    Dönüş: (True, "") → yeni bar, geçebilir | (False, neden) → aynı bar
    """
    last = last_order_ts.get(symbol, -1.0)
    if last == bar_timestamp_ms:
        log.warning(
            "SAME_BAR_GUARD | %s | bar_ts=%.0f | duplicate emir engellendi",
            symbol, bar_timestamp_ms,
        )
        return False, "same_bar_duplicate"
    return True, ""


def gate_buy_size_and_exposure(
    sizer: "PositionSizer",
    symbol: str,  # NOSONAR — API uyumu için tutuldu, gelecekte kullanılacak
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
