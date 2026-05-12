"""
Faz 71 — Dealer / Market Maker intent inference.

Amaç:
- Emir defteri (best bid/ask), spread rejimi ve basit imbalance sinyallerinden
  dealer inventory baskısı / olası trap tarafını sezmek.

Bu modül Phase I/O Contract + tek bayrak standardına uyumludur:
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
TrapSide = Literal["long", "short", "none", "unknown"]
SpreadRegime = Literal["tight", "normal", "wide", "unknown"]
RiskOffHint = Literal["risk_off", "neutral", "risk_on", "unknown"]


@dataclass(frozen=True)
class DealerIntentResult:
    # Faz 71 outputs (requested)
    dealer_pressure_score: int  # 0-100
    likely_trap_side: TrapSide
    spread_regime: SpreadRegime
    risk_off_hint: RiskOffHint

    # System standards (requested)
    trade_permission: TradePermission
    alpha_score: int  # 0-100
    risk_score: int  # 0-100
    confidence: float  # 0-1
    data_health: float  # 0-1
    event_ts: int  # ms
    half_life_ms: int

    # Optional: helps downstream debugging (kept minimal)
    spread_pct: Optional[float] = None
    ob_imbalance: Optional[float] = None

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


def _spread_regime(spread_pct: Optional[float]) -> SpreadRegime:
    if spread_pct is None:
        return "unknown"
    # Heuristics — aligns with pre_trade_gate default max_spread_pct=0.5% (0.005)
    if spread_pct <= 0.0012:
        return "tight"
    if spread_pct <= 0.0045:
        return "normal"
    return "wide"


def _compute_ob_imbalance(order_book: Dict[str, Any]) -> Optional[float]:
    """
    0..1: bid dominance (1.0) vs ask dominance (0.0). 0.5 neutral.
    Uses top-of-book depths (first N levels) if possible.
    """
    try:
        bids = order_book.get("bids", [])[:10]
        asks = order_book.get("asks", [])[:10]
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


def infer_dealer_intent(
    *,
    symbol: str,
    analysis: Optional[Dict[str, Any]] = None,
    order_book: Optional[Dict[str, Any]] = None,
    event_ts: Optional[int] = None,
    half_life_ms: int = 25_000,
) -> DealerIntentResult:
    """
    Minimal, deterministic Faz-71 inference.

    Inputs:
    - analysis: analyzer çıktı dict'i (opsiyonel)
    - order_book: {"bids": [[p,q],...], "asks": [[p,q],...]} (opsiyonel)

    Output fields match user request + system standards.
    """
    a = analysis or {}
    ts = int(event_ts if event_ts is not None else a.get("event_ts") or _now_ms())
    hl = int(a.get("half_life_ms") or half_life_ms)
    hl = max(2_000, min(300_000, hl))

    # Data health: if no order book, we still return something but mark uncertainty.
    ob_ok = bool(order_book and isinstance(order_book, dict))
    data_health = 0.85 if ob_ok else 0.55

    spread_pct: Optional[float] = None
    spread_regime: SpreadRegime = "unknown"
    ob_imb: Optional[float] = None

    if ob_ok:
        best_bid, best_ask = _extract_best_prices(order_book or {})
        if best_bid is not None and best_ask is not None:
            spread_pct = _compute_spread_pct(best_bid, best_ask)
            spread_regime = _spread_regime(spread_pct)
        else:
            data_health = min(data_health, 0.60)
        ob_imb = _compute_ob_imbalance(order_book or {})
        if ob_imb is None:
            data_health = min(data_health, 0.65)

    # Dealer pressure: wide spread + strong imbalance implies "dealer cautious / inventory pressure"
    spread_component = 0.0 if spread_pct is None else min(1.0, spread_pct / 0.008)  # 0.8% ~ max
    imb_component = 0.0 if ob_imb is None else abs(ob_imb - 0.5) * 2.0  # 0..1
    dealer_pressure_score = _clamp100(100.0 * (0.65 * spread_component + 0.35 * imb_component))

    # Trap side: crude heuristic from imbalance + wide spread
    likely_trap_side: TrapSide = "unknown" if not ob_ok else "none"
    if ob_ok and ob_imb is not None:
        if spread_regime == "wide" and ob_imb >= 0.62:
            likely_trap_side = "long"
        elif spread_regime == "wide" and ob_imb <= 0.38:
            likely_trap_side = "short"
        else:
            likely_trap_side = "none"

    # Risk-off hint: map pressure → hint
    if not ob_ok:
        risk_off_hint = "unknown"
    elif dealer_pressure_score >= 75:
        risk_off_hint = "risk_off"
    elif dealer_pressure_score <= 30:
        risk_off_hint = "risk_on"
    else:
        risk_off_hint = "neutral"

    # Scores: Faz 71 is mostly RISK/QUALITY, alpha is usually low here.
    risk_score = _clamp100(dealer_pressure_score * 0.90 + (0 if spread_regime != "wide" else 10))
    alpha_score = _clamp100(max(0.0, 55.0 - dealer_pressure_score * 0.35))

    # Confidence derived from data health + strength of signal
    strength = dealer_pressure_score / 100.0
    confidence = _clamp01(0.25 + 0.55 * _clamp01(data_health) + 0.20 * strength)

    # trade_permission: this phase should NOT HALT by itself; it can BLOCK when risk is high.
    trade_permission: TradePermission = "ALLOW"
    if data_health < 0.35:
        trade_permission = "BLOCK"
    elif risk_score >= 85 and confidence >= 0.60:
        trade_permission = "BLOCK"

    return DealerIntentResult(
        dealer_pressure_score=int(dealer_pressure_score),
        likely_trap_side=likely_trap_side,
        spread_regime=spread_regime,
        risk_off_hint=risk_off_hint,
        trade_permission=trade_permission,
        alpha_score=int(alpha_score),
        risk_score=int(risk_score),
        confidence=float(confidence),
        data_health=float(_clamp01(data_health)),
        event_ts=ts,
        half_life_ms=hl,
        spread_pct=spread_pct,
        ob_imbalance=ob_imb,
    )
