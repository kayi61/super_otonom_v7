"""Kademeli çıkış — ATR tabanlı eşikler, rejim/trailing, kademe erteleme."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from super_otonom.config import RISK, STAGED_EXIT

log = logging.getLogger("super_otonom.staged_exit")


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _atr_pct(analysis: Dict[str, Any], price: float) -> float:
    atr = float(analysis.get("atr", 0.0) or 0.0)
    if atr <= 0 or price <= 0:
        return 0.0
    return atr / price


def effective_stage_threshold(stage: int, analysis: Dict[str, Any], price: float) -> float:
    """Taban TP + ATR hedefi karışımı; %12–%40 aralığına sıkıştırılır."""
    atr_p = _atr_pct(analysis, price)
    if stage == 1:
        base = float(STAGED_EXIT["take_profit_1"])
        atr_t = atr_p * float(STAGED_EXIT["tp_atr_mult_1"])
    elif stage == 2:
        base = float(STAGED_EXIT["take_profit_2"])
        atr_t = atr_p * float(STAGED_EXIT["tp_atr_mult_2"])
    else:
        base = float(STAGED_EXIT["take_profit_3"])
        atr_t = atr_p * float(STAGED_EXIT["tp_atr_mult_3"])
    blend = float(STAGED_EXIT["tp_atr_blend"])
    raw = blend * base + (1.0 - blend) * atr_t if atr_t > 0 else base
    return _clamp(
        raw,
        float(STAGED_EXIT["tp_min_pct"]),
        float(STAGED_EXIT["tp_max_pct"]),
    )


def _trailing_pct(analysis: Dict[str, Any]) -> float:
    oreg = str(analysis.get("omega_regime", "") or "").upper()
    adj = int(analysis.get("adj_signal_quality", 0) or 0)
    decay = analysis.get("alpha_decay_freshness") or {}
    decay_conf = float(decay.get("confidence", 1.0) or 1.0) if isinstance(decay, dict) else 1.0
    defer_min = int(STAGED_EXIT["stage_defer_min_adj_quality"])
    if (
        oreg == "TRENDING"
        and adj >= defer_min
        and (not STAGED_EXIT["stage_defer_decay_block"] or decay_conf >= 0.55)
    ):
        return float(RISK["trailing_stop_pct_strong"])
    if oreg in ("RANGING", "CRASH_RISK") or decay_conf < 0.55:
        return float(RISK["trailing_stop_pct_weak"])
    return float(RISK["trailing_stop_pct"])


def _should_defer_stage(pos: Dict[str, Any], analysis: Dict[str, Any]) -> bool:
    if not STAGED_EXIT["stage_defer_enabled"]:
        return False
    oreg = str(analysis.get("omega_regime", "") or "").upper()
    allowed = {
        r.strip().upper() for r in STAGED_EXIT["stage_defer_regimes"].split(",") if r.strip()
    }
    if oreg not in allowed:
        return False
    adj = int(analysis.get("adj_signal_quality", 0) or 0)
    if adj < int(STAGED_EXIT["stage_defer_min_adj_quality"]):
        return False
    decay = analysis.get("alpha_decay_freshness") or {}
    if STAGED_EXIT["stage_defer_decay_block"] and isinstance(decay, dict):
        if float(decay.get("confidence", 1.0) or 1.0) < 0.55:
            return False
    defer_bars = int(pos.get("stage_defer_bars", 0) or 0)
    return defer_bars < int(STAGED_EXIT["stage_defer_max_bars"])


def _partial_ratio_for_stage(stage: int) -> float:
    if stage == 1:
        return float(STAGED_EXIT["partial_exit_1"])
    if stage == 2:
        return float(STAGED_EXIT["partial_exit_2"])
    return float(STAGED_EXIT["partial_exit_3"])


def evaluate_exit(
    pos: Dict[str, Any],
    price: float,
    analysis: Dict[str, Any],
    *,
    signal: str = "HOLD",
) -> Optional[Tuple[str, float, int]]:
    """
    Dönüş: (reason, close_ratio_of_initial_qty, new_exit_stage) veya None.
    close_ratio: kalan qty üzerinden değil, açılış qty'sine göre pay.
    """
    entry = float(pos.get("entry", price) or price)
    if entry <= 0:
        return None

    pnl_pct = (price - entry) / entry
    stage = int(pos.get("exit_stage", 0) or 0)
    initial_qty = float(pos.get("initial_qty", pos.get("qty", 0.0)) or 0.0)
    current_qty = float(pos.get("qty", 0.0) or 0.0)
    if current_qty <= 0 or initial_qty <= 0:
        return None

    peak = float(pos.get("peak", entry) or entry)
    if price > peak:
        peak = price

    # Sert stop / breakeven
    hard_floor = entry * float(STAGED_EXIT["stop_hard_mult"])
    if stage >= int(STAGED_EXIT["breakeven_after_stage"]):
        hard_floor = max(hard_floor, entry * (1.0 + float(STAGED_EXIT["breakeven_buffer_pct"])))
    if price <= hard_floor or pnl_pct <= -float(RISK["stop_loss_pct"]):
        return ("STOP_LOSS", 1.0, 3)

    trail_pct = _trailing_pct(analysis)
    if peak > entry and price <= peak * (1.0 - trail_pct):
        return ("TRAILING_STOP", 1.0, 3)

    if signal in ("SELL", "CLOSE_ALL"):
        return ("SIGNAL_EXIT", 1.0, 3)

    if stage >= 3:
        return None

    next_stage = stage + 1
    threshold = effective_stage_threshold(next_stage, analysis, price)
    if pnl_pct < threshold:
        return None

    if _should_defer_stage(pos, analysis):
        pos["stage_defer_bars"] = int(pos.get("stage_defer_bars", 0) or 0) + 1
        return None

    pos["stage_defer_bars"] = 0
    ratio = _partial_ratio_for_stage(next_stage)
    if next_stage >= 3:
        ratio = max(0.0, min(1.0, current_qty / initial_qty))
    else:
        ratio = max(0.0, min(1.0, ratio))
    reason = f"STAGED_TP_{next_stage}"
    return (reason, ratio, next_stage)


async def apply_staged_exit(
    engine: Any,
    symbol: str,
    price: float,
    signal: str,
    out: Dict[str, Any],
    analysis: Dict[str, Any],
) -> None:
    """Açık pozisyon için kademeli çıkış değerlendirmesi."""
    pos = engine.open_positions.get(symbol)
    if not pos:
        return

    if price > float(pos.get("peak", pos.get("entry", price)) or 0.0):
        pos["peak"] = price
    pos["hold_bars"] = int(pos.get("hold_bars", 0) or 0) + 1

    decision = evaluate_exit(pos, price, analysis, signal=signal)
    if not decision:
        return

    reason, ratio, new_stage = decision
    if ratio >= 0.999 or reason in ("STOP_LOSS", "TRAILING_STOP", "SIGNAL_EXIT"):
        await engine._close(symbol, price, out, reason, analysis)
        return

    await engine._close_partial(symbol, price, ratio, out, reason, analysis, new_stage)
