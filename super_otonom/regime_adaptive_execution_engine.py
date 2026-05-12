"""
Faz 76 — Regime-adaptive execution engine.

Amaç:
- Piyasa rejimine göre execution stratejisini dinamik seçmek:
  TREND / RANGE / VOLATILE / CRISIS gibi modlarda farklı emir tipi ve aciliyet.

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
OrderType = Literal["maker", "taker", "twap", "unknown"]
RegimeExecutionMode = Literal["trend", "range", "volatile", "crisis", "unknown"]


@dataclass(frozen=True)
class RegimeAdaptiveExecutionResult:
    # Faz 76 outputs (requested)
    regime_execution_mode: RegimeExecutionMode
    preferred_order_type: OrderType
    urgency_score: int  # 0-100
    slippage_risk: int  # 0-100

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
    volatility: Optional[float] = None
    liquidity_ratio: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _clamp01(x: float) -> float:
    if x != x:  # NaN
        return 0.0
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def _clamp100(x: float) -> int:
    if x != x:  # NaN
        return 0
    return int(max(0, min(100, round(x))))


def _try_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


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


def _map_regime(raw: str) -> RegimeExecutionMode:
    r = (raw or "").strip().upper()
    if r in ("TREND", "TRENDING", "UPTREND", "DOWNTREND"):
        return "trend"
    if r in ("RANGE", "MEAN_REVERTING", "SIDEWAYS"):
        return "range"
    if r in ("VOLATILE", "HIGH_VOL"):
        return "volatile"
    if r in ("CRISIS", "FLASH_CRASH", "PANIC"):
        return "crisis"
    return "unknown"


def infer_regime_adaptive_execution(
    *,
    symbol: str,
    analysis: Optional[Dict[str, Any]] = None,
    order_book: Optional[Dict[str, Any]] = None,
    event_ts: Optional[int] = None,
    half_life_ms: int = 20_000,
) -> RegimeAdaptiveExecutionResult:
    """
    Minimal, deterministic Faz-76 decision.

    Inputs:
    - analysis: should include "regime" (optional), "volatility" (optional), "liquidity_ratio" (optional)
    - order_book: used to estimate spread_pct (optional)
    """
    a = analysis or {}
    ts = int(event_ts if event_ts is not None else a.get("event_ts") or _now_ms())
    hl = int(a.get("half_life_ms") or half_life_ms)
    hl = max(2_000, min(300_000, hl))

    regime_execution_mode = _map_regime(str(a.get("regime", "")))

    vol = _try_float(a.get("volatility"))
    lr = _try_float(a.get("liquidity_ratio"))

    # data health: better with OB + valid regime signal
    ob_ok = bool(order_book and isinstance(order_book, dict))
    data_health = 0.86 if ob_ok else 0.62
    if regime_execution_mode == "unknown":
        data_health = min(data_health, 0.70)

    spread_pct: Optional[float] = None
    if ob_ok:
        bid, ask = _extract_best_prices(order_book or {})
        if bid is not None and ask is not None:
            spread_pct = _compute_spread_pct(bid, ask)
        else:
            data_health = min(data_health, 0.60)

    # Normalize helpers
    spread_component = 0.0 if spread_pct is None else min(1.0, spread_pct / 0.010)  # 1% cap
    vol_component = 0.35
    if vol is not None:
        vol_component = min(1.0, max(0.0, vol / 0.06))
    else:
        data_health = min(data_health, 0.70)
    liq_component = 0.60
    if lr is not None:
        liq_component = _clamp01(lr)
    else:
        data_health = min(data_health, 0.70)

    # Slippage risk increases with spread, volatility, and low liquidity.
    slippage_risk = _clamp100(
        100.0 * (0.45 * spread_component + 0.35 * vol_component + 0.20 * (1.0 - liq_component))
    )

    # Urgency: in trend/volatile/crisis we may need urgency; range usually low urgency.
    base_urg = 35.0
    if regime_execution_mode == "trend":
        base_urg = 55.0
    elif regime_execution_mode == "range":
        base_urg = 30.0
    elif regime_execution_mode == "volatile":
        base_urg = 65.0
    elif regime_execution_mode == "crisis":
        base_urg = 80.0
    # widen urgency with volatility and reduce with spread (if spread huge, prefer patience/twap)
    urgency_score = _clamp100(base_urg + 20.0 * vol_component - 15.0 * spread_component)

    # Preferred order type
    preferred_order_type: OrderType = "unknown"
    if regime_execution_mode == "range":
        preferred_order_type = "maker" if slippage_risk <= 70 else "twap"
    elif regime_execution_mode == "trend":
        preferred_order_type = "taker" if urgency_score >= 60 and slippage_risk <= 65 else "twap"
    elif regime_execution_mode == "volatile":
        preferred_order_type = "twap" if slippage_risk >= 55 else "taker"
    elif regime_execution_mode == "crisis":
        preferred_order_type = "twap"
    else:
        preferred_order_type = "twap" if slippage_risk >= 60 else "maker"

    # Scores: execution phase is mostly RISK/QUALITY; alpha is minimal.
    risk_score = _clamp100(max(slippage_risk, 100.0 * (1.0 - _clamp01(data_health))))
    alpha_score = _clamp100(
        max(0.0, 40.0 - slippage_risk * 0.25 + (5.0 if regime_execution_mode == "trend" else 0.0))
    )

    # Confidence: depends on data_health and regime clarity
    confidence = _clamp01(0.25 + 0.65 * _clamp01(data_health) + 0.10 * (1.0 - spread_component))
    if regime_execution_mode == "unknown":
        confidence = min(confidence, 0.65)

    # trade_permission: execution engine should BLOCK when slippage risk extreme or data missing
    trade_permission: TradePermission = "ALLOW"
    if data_health < 0.35:
        trade_permission = "BLOCK"
    elif slippage_risk >= 92 and confidence >= 0.60:
        trade_permission = "BLOCK"

    _ = symbol
    return RegimeAdaptiveExecutionResult(
        regime_execution_mode=regime_execution_mode,
        preferred_order_type=preferred_order_type,
        urgency_score=int(urgency_score),
        slippage_risk=int(slippage_risk),
        trade_permission=trade_permission,
        alpha_score=int(alpha_score),
        risk_score=int(risk_score),
        confidence=float(_clamp01(confidence)),
        data_health=float(_clamp01(data_health)),
        event_ts=ts,
        half_life_ms=hl,
        spread_pct=spread_pct,
        volatility=vol,
        liquidity_ratio=lr,
    )
