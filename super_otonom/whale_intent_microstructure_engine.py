"""
Faz 72 — Whale intent microstructure inference.

Amaç:
- Emir defteri derinliği/imbalance, spread, ve (opsiyonel) tape/flow proxy'lerinden
  balina niyetini sezmek: accumulation / distribution / hunt / exit.

Standartlar:
- trade_permission = HALT/BLOCK/ALLOW
- alpha_score + risk_score
- confidence + data_health
- event_ts + half_life_ms
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, Literal, Optional

TradePermission = Literal["HALT", "BLOCK", "ALLOW"]
WhaleIntent = Literal["accumulate", "distribute", "hunt", "exit", "none", "unknown"]
EntryTimingHint = Literal["enter_now", "wait_pullback", "wait_confirm", "avoid", "unknown"]


@dataclass(frozen=True)
class WhaleIntentResult:
    # Faz 72 outputs (requested)
    whale_intent: WhaleIntent
    absorption_score: int  # 0-100
    sweep_risk: int  # 0-100
    entry_timing_hint: EntryTimingHint

    # System standards (requested)
    trade_permission: TradePermission
    alpha_score: int  # 0-100
    risk_score: int  # 0-100
    confidence: float  # 0-1
    data_health: float  # 0-1
    event_ts: int  # ms
    half_life_ms: int

    # Optional debug
    ob_imbalance: Optional[float] = None
    spread_pct: Optional[float] = None
    absorption_proxy: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _clamp01(x: float) -> float:
    if x != x:  # NaN
        return 0.0
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def _clamp100(x: float) -> int:
    if x != x:  # NaN
        return 0
    return int(max(0, min(100, round(x))))


def _now_ms() -> int:
    return int(time.time() * 1000)


def _extract_best_prices(order_book: Dict[str, Any]) -> tuple[Optional[float], Optional[float]]:
    try:
        best_bid = float(order_book["bids"][0][0])
        best_ask = float(order_book["asks"][0][0])
        if best_bid <= 0 or best_ask <= 0:
            return None, None
        return best_bid, best_ask
    except (KeyError, IndexError, TypeError, ValueError):
        return None, None


def _compute_spread_pct(best_bid: float, best_ask: float) -> float:
    mid = (best_bid + best_ask) / 2.0
    if mid <= 0:
        return 0.0
    return (best_ask - best_bid) / mid


def _compute_ob_imbalance(order_book: Dict[str, Any]) -> Optional[float]:
    """
    0..1: bid dominance (1.0) vs ask dominance (0.0). 0.5 neutral.
    """
    try:
        bids = order_book.get("bids", [])[:15]
        asks = order_book.get("asks", [])[:15]
        if not bids or not asks:
            return None
        bid_qty = sum(float(q) for _, q in bids)
        ask_qty = sum(float(q) for _, q in asks)
        den = bid_qty + ask_qty
        if den <= 0:
            return None
        return bid_qty / den
    except (TypeError, ValueError):
        return None


def _absorption_proxy_from_ob(order_book: Dict[str, Any]) -> Optional[float]:
    """
    Very rough proxy:
    - If top levels show heavy resting liquidity on one side, interpret as absorption potential.
    Returns 0..1 where 1 means "strong absorption/defense present".
    """
    try:
        bids = order_book.get("bids", [])[:5]
        asks = order_book.get("asks", [])[:5]
        if not bids or not asks:
            return None
        bid_notional = sum(float(p) * float(q) for p, q in bids)
        ask_notional = sum(float(p) * float(q) for p, q in asks)
        den = bid_notional + ask_notional
        if den <= 0:
            return None
        dom = max(bid_notional, ask_notional) / den  # 0.5..1
        return _clamp01((dom - 0.5) / 0.5)
    except (TypeError, ValueError):
        return None


def infer_whale_intent(
    *,
    symbol: str,
    analysis: Optional[Dict[str, Any]] = None,
    order_book: Optional[Dict[str, Any]] = None,
    event_ts: Optional[int] = None,
    half_life_ms: int = 30_000,
) -> WhaleIntentResult:
    """
    Minimal, deterministic Faz-72 inference.

    Notes:
    - Gerçek "whale intent" için tape/prints/flow gerekir; burada OB tabanlı proxy kullanılır.
    - Veri yoksa score=0 yerine unknown intent + düşük confidence/data_health.
    """
    a = analysis or {}
    ts = int(event_ts if event_ts is not None else a.get("event_ts") or _now_ms())
    hl = int(a.get("half_life_ms") or half_life_ms)
    hl = max(2_000, min(300_000, hl))

    ob_ok = bool(order_book and isinstance(order_book, dict))
    data_health = 0.86 if ob_ok else 0.52

    ob_imb: Optional[float] = None
    spread_pct: Optional[float] = None
    absorption_p: Optional[float] = None

    if ob_ok:
        best_bid, best_ask = _extract_best_prices(order_book or {})
        if best_bid is not None and best_ask is not None:
            spread_pct = _compute_spread_pct(best_bid, best_ask)
        else:
            data_health = min(data_health, 0.60)

        ob_imb = _compute_ob_imbalance(order_book or {})
        if ob_imb is None:
            data_health = min(data_health, 0.65)

        absorption_p = _absorption_proxy_from_ob(order_book or {})
        if absorption_p is None:
            data_health = min(data_health, 0.68)

    # Absorption score: depends on absorption proxy + how "one-sided" the book looks.
    imb_strength = 0.0 if ob_imb is None else abs(ob_imb - 0.5) * 2.0  # 0..1
    absorption_strength = 0.0 if absorption_p is None else absorption_p
    absorption_score = _clamp100(100.0 * (0.60 * absorption_strength + 0.40 * (1.0 - imb_strength)))

    # Sweep risk: wide spread + strong imbalance ⇒ sweep/stop-run risk higher
    spread_component = 0.0 if spread_pct is None else min(1.0, spread_pct / 0.010)  # 1.0% cap
    sweep_risk = _clamp100(100.0 * (0.55 * spread_component + 0.45 * imb_strength))

    # Infer intent:
    whale_intent: WhaleIntent = "unknown"
    entry_timing_hint: EntryTimingHint = "unknown"
    if not ob_ok:
        whale_intent = "unknown"
        entry_timing_hint = "unknown"
    else:
        # If sweep risk very high -> likely hunt behavior
        if sweep_risk >= 80 and imb_strength >= 0.55:
            whale_intent = "hunt"
            entry_timing_hint = "avoid"
        else:
            # Determine side dominance
            if ob_imb is None:
                whale_intent = "unknown"
                entry_timing_hint = "unknown"
            else:
                if ob_imb >= 0.60 and absorption_score >= 55:
                    whale_intent = "accumulate"
                    entry_timing_hint = "wait_confirm" if sweep_risk >= 55 else "enter_now"
                elif ob_imb <= 0.40 and absorption_score >= 55:
                    whale_intent = "distribute"
                    entry_timing_hint = "avoid" if sweep_risk >= 55 else "wait_pullback"
                else:
                    whale_intent = "none"
                    entry_timing_hint = "wait_confirm"

    # Scores:
    # - alpha_score: higher when accumulation/distribution is clear and sweep risk is not extreme.
    intent_strength = 0.0
    if whale_intent in ("accumulate", "distribute"):
        intent_strength = 0.65 + 0.35 * _clamp01(absorption_score / 100.0)
    elif whale_intent == "hunt":
        intent_strength = 0.40
    elif whale_intent == "none":
        intent_strength = 0.25
    else:
        intent_strength = 0.10

    alpha_score = _clamp100(
        100.0 * (intent_strength * _clamp01(data_health) * (1.0 - sweep_risk / 120.0))
    )
    risk_score = _clamp100(max(sweep_risk, 100.0 * (1.0 - _clamp01(data_health))))

    # Confidence:
    confidence = _clamp01(0.20 + 0.60 * _clamp01(data_health) + 0.20 * (absorption_score / 100.0))
    if whale_intent in ("unknown",):
        confidence = min(confidence, 0.55)

    # trade_permission:
    trade_permission: TradePermission = "ALLOW"
    if data_health < 0.35:
        trade_permission = "BLOCK"
    elif whale_intent == "hunt" and sweep_risk >= 80 and confidence >= 0.60:
        trade_permission = "BLOCK"
    elif risk_score >= 90 and confidence >= 0.65:
        trade_permission = "BLOCK"

    return WhaleIntentResult(
        whale_intent=whale_intent,
        absorption_score=int(absorption_score),
        sweep_risk=int(sweep_risk),
        entry_timing_hint=entry_timing_hint,
        trade_permission=trade_permission,
        alpha_score=int(alpha_score),
        risk_score=int(risk_score),
        confidence=float(confidence),
        data_health=float(_clamp01(data_health)),
        event_ts=ts,
        half_life_ms=hl,
        ob_imbalance=ob_imb,
        spread_pct=spread_pct,
        absorption_proxy=absorption_p,
    )
