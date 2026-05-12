"""
Faz 73 — Liquidity games / manipulation detector.

Amaç:
- Emir defteri ve (opsiyonel) analyzer çıktılarına bakarak manipülasyon / likidite oyunu
  riskini sezmek: spoofing, quote_stuffing, momentum_ignition, stop_hunt.

Standartlar:
- trade_permission = HALT/BLOCK/ALLOW
- alpha_score + risk_score
- confidence + data_health
- event_ts + half_life_ms

PROMPT-A8: ``analysis["market_snapshot"]`` (schema ``a8/v1``) varsa spread / imbalance
bu özetten okunur; aksi halde ``order_book`` üzerinde klasik parse.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, Literal, Optional

TradePermission = Literal["HALT", "BLOCK", "ALLOW"]
GameType = Literal[
    "spoofing",
    "quote_stuffing",
    "momentum_ignition",
    "stop_hunt",
    "unknown",
    "none",
]


@dataclass(frozen=True)
class LiquidityGameResult:
    # Faz 73 outputs (requested)
    manipulation_risk_score: int  # 0-100
    game_type: GameType
    do_not_trade_flag: bool
    cooldown_seconds: int

    # System standards (requested)
    trade_permission: TradePermission
    alpha_score: int  # 0-100
    risk_score: int  # 0-100
    confidence: float  # 0-1
    data_health: float  # 0-1
    event_ts: int  # ms
    half_life_ms: int

    # Optional debug
    spread_pct: Optional[float] = None
    ob_imbalance: Optional[float] = None
    vol_proxy: Optional[float] = None

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


def detect_liquidity_games(
    *,
    symbol: str,
    analysis: Optional[Dict[str, Any]] = None,
    order_book: Optional[Dict[str, Any]] = None,
    event_ts: Optional[int] = None,
    half_life_ms: int = 18_000,
) -> LiquidityGameResult:
    """
    Minimal, deterministic Faz-73 detector.

    Heuristics (proxy):
    - wide spread + high imbalance + high volatility proxy => stop_hunt / momentum ignition risk
    - extremely wide spread + missing depth => quote_stuffing/fragile book proxy
    - high imbalance with low spread but strong depth dominance => spoofing proxy (very rough)
    """
    a = analysis or {}
    ts = int(event_ts if event_ts is not None else a.get("event_ts") or _now_ms())
    hl = int(a.get("half_life_ms") or half_life_ms)
    hl = max(2_000, min(300_000, hl))

    spread_pct: Optional[float] = None
    ob_imb: Optional[float] = None
    ob_ok = False

    snap = a.get("market_snapshot")
    use_snap = isinstance(snap, dict) and snap.get("schema") == "a8/v1"
    ob_part: Dict[str, Any] = snap.get("order_book", {}) if use_snap else {}

    if use_snap and not ob_part.get("empty", True):
        if ob_part.get("spread_rel") is not None:
            spread_pct = float(ob_part["spread_rel"])
        if ob_part.get("ob_imbalance_top10") is not None:
            ob_imb = float(ob_part["ob_imbalance_top10"])
        lv = ob_part.get("levels") or {}
        if spread_pct is None or ob_imb is None:
            best_bid, best_ask = _extract_best_prices(lv)
            if spread_pct is None and best_bid is not None and best_ask is not None:
                spread_pct = _compute_spread_pct(best_bid, best_ask)
            if ob_imb is None:
                ob_imb = _compute_ob_imbalance(lv)
        ob_ok = bool(lv.get("bids")) and bool(lv.get("asks"))
    elif order_book and isinstance(order_book, dict):
        ob_ok = bool(order_book.get("bids")) and bool(order_book.get("asks"))

    data_health = 0.84 if ob_ok else 0.50

    if not use_snap and ob_ok:
        best_bid, best_ask = _extract_best_prices(order_book or {})
        if best_bid is not None and best_ask is not None:
            spread_pct = _compute_spread_pct(best_bid, best_ask)
        else:
            data_health = min(data_health, 0.60)
        ob_imb = _compute_ob_imbalance(order_book or {})
        if ob_imb is None:
            data_health = min(data_health, 0.65)
    elif use_snap and ob_ok:
        if spread_pct is None:
            data_health = min(data_health, 0.60)
        if ob_imb is None:
            data_health = min(data_health, 0.65)

    # volatility proxy: prefer analysis["volatility"] if available
    vol = a.get("volatility")
    try:
        vol_proxy = float(vol) if vol is not None else None
    except (TypeError, ValueError):
        vol_proxy = None
    if vol_proxy is None:
        vol_proxy = 0.02  # neutral default
        data_health = min(data_health, 0.70)
    vol_proxy = max(0.0, float(vol_proxy))

    spread_component = 0.0 if spread_pct is None else min(1.0, spread_pct / 0.010)  # 1.0% cap
    imb_component = 0.0 if ob_imb is None else abs(ob_imb - 0.5) * 2.0  # 0..1
    vol_component = min(1.0, vol_proxy / 0.06)  # 6% ~ high

    # base manipulation risk
    manipulation_risk_score = _clamp100(
        100.0 * (0.40 * spread_component + 0.35 * imb_component + 0.25 * vol_component)
    )

    # classify game type
    game_type: GameType = "unknown" if not ob_ok else "none"
    if ob_ok:
        if manipulation_risk_score >= 80 and spread_component >= 0.65 and vol_component >= 0.55:
            game_type = "stop_hunt"
        elif manipulation_risk_score >= 75 and vol_component >= 0.70 and imb_component >= 0.45:
            game_type = "momentum_ignition"
        elif spread_component >= 0.90 and data_health <= 0.65:
            game_type = "quote_stuffing"
        elif imb_component >= 0.70 and spread_component <= 0.25 and data_health >= 0.75:
            game_type = "spoofing"
        else:
            game_type = "none"

    # cooldown seconds
    cooldown_seconds = 0
    if manipulation_risk_score >= 90:
        cooldown_seconds = 300
    elif manipulation_risk_score >= 80:
        cooldown_seconds = 180
    elif manipulation_risk_score >= 70:
        cooldown_seconds = 90
    elif manipulation_risk_score >= 60:
        cooldown_seconds = 45

    do_not_trade_flag = bool(
        manipulation_risk_score >= 80 or game_type in ("stop_hunt", "quote_stuffing")
    )

    # Scores: this phase is mostly RISK/QUALITY; alpha is low.
    risk_score = _clamp100(max(manipulation_risk_score, 100.0 * (1.0 - _clamp01(data_health))))
    alpha_score = _clamp100(max(0.0, 45.0 - manipulation_risk_score * 0.30))

    # confidence
    confidence = _clamp01(
        0.20 + 0.65 * _clamp01(data_health) + 0.15 * (manipulation_risk_score / 100.0)
    )
    if not ob_ok:
        confidence = min(confidence, 0.55)

    # trade_permission: this phase can BLOCK (and participates in override chain).
    trade_permission: TradePermission = "ALLOW"
    if data_health < 0.35:
        trade_permission = "BLOCK"
    elif do_not_trade_flag and confidence >= 0.60:
        trade_permission = "BLOCK"
    elif risk_score >= 92 and confidence >= 0.65:
        trade_permission = "BLOCK"

    return LiquidityGameResult(
        manipulation_risk_score=int(manipulation_risk_score),
        game_type=game_type,
        do_not_trade_flag=do_not_trade_flag,
        cooldown_seconds=int(cooldown_seconds),
        trade_permission=trade_permission,
        alpha_score=int(alpha_score),
        risk_score=int(risk_score),
        confidence=float(confidence),
        data_health=float(_clamp01(data_health)),
        event_ts=ts,
        half_life_ms=hl,
        spread_pct=spread_pct,
        ob_imbalance=ob_imb,
        vol_proxy=float(vol_proxy),
    )
