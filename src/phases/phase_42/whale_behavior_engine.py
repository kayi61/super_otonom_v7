"""
Faz 42 — Balina davranış motoru: whale cluster, wash trade filtresi, Wyckoff A/D imzası.

Sadece NumPy.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Literal, Optional, Tuple

import numpy as np

_EPS = 1e-12
_WASH_BLOCK = 0.70
_WASH_RATIO_CAP = 0.3
_HALF_LIFE_MS = 15_000

WyckoffSignal = Literal["ACCUMULATION", "DISTRIBUTION", "NEUTRAL"]


def _clip01(x: float | np.floating) -> float:
    return float(np.clip(np.asarray(x, dtype=float), 0.0, 1.0))


def _now_ms() -> float:
    return float(time.time() * 1000.0)


def _normalize_side(side: Any) -> str:
    s = str(side).strip().lower()
    if s in ("buy", "b", "1"):
        return "buy"
    if s in ("sell", "s", "-1"):
        return "sell"
    return ""


def compute_whale_metrics(
    trades: List[Dict[str, Any]],
    whale_threshold: float,
) -> Tuple[float, float, float, float, float]:
    """
    whale_ratio, whale_direction [-1,1], whale_cluster_score [0,1],
    buy_whale_vol, sell_whale_vol.
    """
    wt = float(whale_threshold)
    if not trades or wt <= 0:
        return 0.0, 0.0, 0.5, 0.0, 0.0

    whale_trades: List[Dict[str, Any]] = []
    for t in trades:
        if not isinstance(t, dict):
            continue
        try:
            sz = float(t.get("size", 0))
        except (TypeError, ValueError):
            continue
        if sz >= wt:
            whale_trades.append(t)

    n = len(trades)
    whale_ratio = len(whale_trades) / max(n, 1)

    buy_w = 0.0
    sell_w = 0.0
    for t in whale_trades:
        try:
            sz = float(t.get("size", 0))
        except (TypeError, ValueError):
            continue
        side = _normalize_side(t.get("side", ""))
        if side == "buy":
            buy_w += sz
        elif side == "sell":
            sell_w += sz

    denom = max(buy_w + sell_w, 1.0)
    whale_direction = (buy_w - sell_w) / denom
    whale_direction = float(np.clip(whale_direction, -1.0, 1.0))
    whale_cluster_score = _clip01((whale_direction + 1.0) / 2.0)

    return whale_ratio, whale_direction, whale_cluster_score, buy_w, sell_w


def compute_wash_trade_score(trades: List[Dict[str, Any]]) -> Tuple[float, float]:
    """wash_ratio ve wash_trade_score [0,1]; şüpheli = aynı fiyat hem alım hem satım."""
    if not trades:
        return 0.0, 0.0

    buys_at: Dict[float, int] = {}
    sells_at: Dict[float, int] = {}
    for t in trades:
        if not isinstance(t, dict):
            continue
        try:
            px = float(t["price"])
        except (KeyError, TypeError, ValueError):
            continue
        key = float(np.round(px, 8))
        side = _normalize_side(t.get("side", ""))
        if side == "buy":
            buys_at[key] = buys_at.get(key, 0) + 1
        elif side == "sell":
            sells_at[key] = sells_at.get(key, 0) + 1

    suspicious_prices = {p for p in buys_at if p in sells_at and sells_at[p] > 0}
    suspicious = 0
    for t in trades:
        if not isinstance(t, dict):
            continue
        try:
            px = float(t["price"])
        except (KeyError, TypeError, ValueError):
            continue
        key = float(np.round(px, 8))
        if key in suspicious_prices:
            suspicious += 1

    wash_ratio = suspicious / max(len(trades), 1)
    wash_trade_score = _clip01(wash_ratio / max(_WASH_RATIO_CAP, _EPS))
    return wash_ratio, wash_trade_score


def compute_wyckoff(
    price_history: List[float],
    volume_history: List[float],
    whale_direction: float,
    whale_cluster_score: float,
) -> Tuple[WyckoffSignal, float]:
    """
    Wyckoff imzası ve accumulation_score [0,1] (birikim senaryosu gücü).

    Accumulation: fiyat düşüşü, hacim artışı, whale alım baskısı.
    Distribution: fiyat yükselişi, hacim artışı, whale satım baskısı.
    """
    ph = np.asarray(price_history, dtype=float).ravel()
    vh = np.asarray(volume_history, dtype=float).ravel()
    if ph.size < 2 or vh.size < 2:
        return "NEUTRAL", 0.0

    p0 = float(ph[0])
    v0 = float(vh[0])
    price_trend = (float(ph[-1]) - p0) / max(abs(p0), 1.0)
    vol_trend = (float(vh[-1]) - v0) / max(v0, _EPS)

    wd = float(np.clip(whale_direction, -1.0, 1.0))

    pt_neg = max(0.0, -price_trend)
    vt_pos = max(0.0, vol_trend)

    whale_buy_bias = _clip01(max(0.0, wd))
    accumulation_score = _clip01(
        0.38 * _clip01(pt_neg / (abs(price_trend) + 0.35))
        + 0.37 * _clip01(vt_pos / (abs(vol_trend) + 0.35))
        + 0.25 * whale_cluster_score * (0.55 + 0.45 * whale_buy_bias)
    )

    eps = 1e-9
    sig: WyckoffSignal = "NEUTRAL"
    if price_trend < -eps and vol_trend > eps and wd > eps:
        sig = "ACCUMULATION"
    elif price_trend > eps and vol_trend > eps and wd < -eps:
        sig = "DISTRIBUTION"

    if sig == "DISTRIBUTION":
        accumulation_score = _clip01(accumulation_score * 0.35)

    return sig, accumulation_score


def validate_market_data(data: Any) -> Tuple[bool, str]:
    if data is None or not isinstance(data, dict):
        return False, "market_data_missing_or_invalid"

    if "trades" not in data or "whale_threshold" not in data:
        return False, "missing_required_keys"

    tr = data["trades"]
    if not isinstance(tr, list) or len(tr) == 0:
        return False, "trades_empty"

    try:
        wt = float(data["whale_threshold"])
    except (TypeError, ValueError):
        return False, "whale_threshold_invalid"
    if wt <= 0:
        return False, "whale_threshold_non_positive"

    if "price_history" not in data or "volume_history" not in data:
        return False, "missing_history"

    ph = data["price_history"]
    vh = data["volume_history"]
    if not isinstance(ph, (list, tuple)) or not isinstance(vh, (list, tuple)):
        return False, "history_not_list"
    if len(ph) < 2 or len(vh) < 2:
        return False, "history_too_short"
    if len(ph) != len(vh):
        return False, "history_length_mismatch"

    for t in tr:
        if not isinstance(t, dict):
            return False, "trade_not_dict"
        for k in ("size", "price", "side"):
            if k not in t:
                return False, f"trade_missing_{k}"

    return True, ""


def _pick_score_type(data_health: float, risk_score: float) -> str:
    if data_health < 0.42:
        return "QUALITY"
    if risk_score >= 0.72:
        return "RISK"
    return "ALPHA"


def analyze(market_data: dict | None) -> dict:
    """Balina davranış analizi — Faz 42 standart payload."""
    ts = _now_ms()
    empty: Dict[str, Any] = {}

    ok, err = validate_market_data(market_data)
    if not ok:
        return {
            "phase": 42,
            "module": "whale_behavior_engine",
            "trade_permission": "BLOCK",
            "alpha_score": 0.0,
            "risk_score": 1.0,
            "score_type": "QUALITY",
            "confidence": 0.0,
            "data_health": 0.0,
            "event_ts": ts,
            "half_life_ms": _HALF_LIFE_MS,
            "analysis": empty,
            "reason": err,
        }

    assert market_data is not None
    d = market_data
    trades = [x for x in d["trades"] if isinstance(x, dict)]

    whale_ratio, whale_direction, whale_cluster_score, _, _ = compute_whale_metrics(
        trades, float(d["whale_threshold"])
    )
    wash_ratio, wash_trade_score = compute_wash_trade_score(trades)

    ph = [float(x) for x in d["price_history"]]
    vh = [float(x) for x in d["volume_history"]]
    wyckoff_signal, accumulation_score = compute_wyckoff(ph, vh, whale_direction, whale_cluster_score)

    alpha_score = _clip01(
        0.5 * whale_cluster_score
        + 0.3 * accumulation_score
        + 0.2 * (1.0 - wash_trade_score)
    )
    risk_score = _clip01(
        0.6 * wash_trade_score + 0.4 * (1.0 - whale_cluster_score)
    )

    n_tr = len(trades)
    data_health = float(np.clip(n_tr / 50.0, 0.1, 1.0))
    confidence = _clip01(data_health * (1.0 - 0.3 * risk_score))

    score_type = _pick_score_type(data_health, risk_score)

    trade_permission = "ALLOW"
    reason = "conditions_normal"

    if d.get("force_halt") is True:
        trade_permission = "HALT"
        reason = "force_halt"
    elif wash_trade_score >= _WASH_BLOCK:
        trade_permission = "BLOCK"
        reason = "wash_trade_manipulation"

    nested = {
        "whale_cluster_score": whale_cluster_score,
        "wash_trade_score": wash_trade_score,
        "wyckoff_signal": wyckoff_signal,
        "accumulation_score": accumulation_score,
        "whale_direction": float(np.clip(whale_direction, -1.0, 1.0)),
        "whale_ratio": _clip01(whale_ratio),
        "wash_ratio": _clip01(wash_ratio),
    }

    return {
        "phase": 42,
        "module": "whale_behavior_engine",
        "trade_permission": trade_permission,
        "alpha_score": alpha_score,
        "risk_score": risk_score,
        "score_type": score_type,
        "confidence": confidence,
        "data_health": data_health,
        "event_ts": ts,
        "half_life_ms": _HALF_LIFE_MS,
        "analysis": nested,
        "reason": reason,
    }
