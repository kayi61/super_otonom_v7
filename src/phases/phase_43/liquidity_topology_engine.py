"""
Faz 43 — Likidite topoloji motoru: çok borsalı derinlik, black hole, spread/vacuum, OFI.

Sadece NumPy.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple

import numpy as np

_EPS = 1e-12
_BLACK_HOLE_BLOCK = 0.60
_HALF_LIFE_MS = 5_000
_DEFAULT_DEPTH = 10


def _clip01(x: float | np.floating) -> float:
    return float(np.clip(np.asarray(x, dtype=float), 0.0, 1.0))


def _now_ms() -> float:
    return float(time.time() * 1000.0)


def _pick_score_type(data_health: float, risk_score: float) -> str:
    if data_health < 0.42:
        return "QUALITY"
    if risk_score >= 0.72:
        return "RISK"
    return "ALPHA"


def _parse_levels(rows: Any, depth: int) -> Tuple[np.ndarray, np.ndarray]:
    """[[price, size], ...] → fiyat ve boyut vektörleri (ilk depth satır)."""
    if not isinstance(rows, list) or depth <= 0:
        return np.zeros(0, dtype=float), np.zeros(0, dtype=float)
    prices: List[float] = []
    sizes: List[float] = []
    for row in rows[:depth]:
        if isinstance(row, (list, tuple)) and len(row) >= 2:
            try:
                prices.append(float(row[0]))
                sizes.append(float(row[1]))
            except (TypeError, ValueError):
                continue
    return np.asarray(prices, dtype=float), np.asarray(sizes, dtype=float)


def compute_depth_totals(
    order_books: List[Dict[str, Any]],
    depth_levels: int,
) -> Tuple[float, float, int]:
    """total_bid_depth, total_ask_depth, exchange_count (işlem gören borsa sayısı)."""
    depth = max(1, int(depth_levels))
    tb = 0.0
    ta = 0.0
    used = 0
    for ob in order_books:
        if not isinstance(ob, dict):
            continue
        bids = ob.get("bids") or []
        asks = ob.get("asks") or []
        _, sz_b = _parse_levels(bids, depth)
        _, sz_a = _parse_levels(asks, depth)
        if sz_b.size == 0 and sz_a.size == 0:
            continue
        tb += float(np.sum(np.maximum(sz_b, 0.0)))
        ta += float(np.sum(np.maximum(sz_a, 0.0)))
        used += 1
    return tb, ta, used


def compute_ofi_score(total_bid_depth: float, total_ask_depth: float) -> Tuple[float, float]:
    """OFI [-1,1] ve ofi_score [0,1]."""
    b = float(total_bid_depth)
    a = float(total_ask_depth)
    den = b + a + _EPS
    ofi = (b - a) / den
    ofi = float(np.clip(ofi, -1.0, 1.0))
    ofi_score = _clip01((ofi + 1.0) / 2.0)
    return ofi, ofi_score


def compute_black_hole_score(
    order_books: List[Dict[str, Any]], depth_levels: int
) -> Tuple[float, float]:
    """
    Borsa başına max/mean oranı; global black_hole_ratio = max(oranlar).
    black_hole_score = clip((ratio - 5) / 15, 0, 1).
    """
    depth = max(1, int(depth_levels))
    ratios: List[float] = []
    for ob in order_books:
        if not isinstance(ob, dict):
            continue
        bids = ob.get("bids") or []
        asks = ob.get("asks") or []
        _, sz_b = _parse_levels(bids, depth)
        _, sz_a = _parse_levels(asks, depth)
        all_sz = (
            np.concatenate([sz_b, sz_a]) if sz_b.size + sz_a.size > 0 else np.zeros(0, dtype=float)
        )
        all_sz = np.maximum(all_sz, 0.0)
        if all_sz.size == 0:
            continue
        mx = float(np.max(all_sz))
        mn = float(np.mean(all_sz)) + _EPS
        ratios.append(mx / mn)

    if not ratios:
        return 0.0, 0.0

    black_hole_ratio = float(np.max(np.asarray(ratios, dtype=float)))
    bh_score = _clip01((black_hole_ratio - 5.0) / 15.0)
    return black_hole_ratio, bh_score


def compute_vacuum_score(
    order_books: List[Dict[str, Any]], current_price: float
) -> Tuple[float, float]:
    """Borsa başına göreli spread ortalaması → vacuum_score."""
    cp = float(current_price)
    if cp <= _EPS:
        return 1.0, 1.0

    spreads: List[float] = []
    for ob in order_books:
        if not isinstance(ob, dict):
            continue
        bids = ob.get("bids") or []
        asks = ob.get("asks") or []
        if not bids or not asks:
            continue
        try:
            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])
        except (IndexError, TypeError, ValueError):
            continue
        sp = (best_ask - best_bid) / cp
        spreads.append(max(sp, 0.0))

    if not spreads:
        return 1.0, 1.0

    avg_spread = float(np.mean(np.asarray(spreads, dtype=float)))
    vacuum_score = _clip01(avg_spread / 0.005)
    return avg_spread, vacuum_score


def validate_market_data(data: Any) -> Tuple[bool, str]:
    if data is None or not isinstance(data, dict):
        return False, "market_data_missing_or_invalid"

    if "order_books" not in data or "current_price" not in data:
        return False, "missing_required_keys"

    obs = data["order_books"]
    if not isinstance(obs, list) or len(obs) == 0:
        return False, "order_books_empty"

    try:
        cp = float(data["current_price"])
    except (TypeError, ValueError):
        return False, "current_price_invalid"
    if cp <= 0:
        return False, "current_price_non_positive"

    has_book = False
    for ob in obs:
        if not isinstance(ob, dict):
            return False, "order_book_not_dict"
        bids = ob.get("bids")
        asks = ob.get("asks")
        if not isinstance(bids, list) or not isinstance(asks, list):
            return False, "bids_or_asks_not_list"
        if len(bids) == 0 or len(asks) == 0:
            continue
        try:
            float(bids[0][0])
            float(asks[0][0])
        except (IndexError, TypeError, ValueError):
            return False, "invalid_top_of_book"
        has_book = True

    if not has_book:
        return False, "no_valid_order_book"

    return True, ""


def analyze(market_data: dict | None) -> dict:
    """Likidite topoloji analizi — Faz 43 standart payload."""
    ts = _now_ms()
    empty: Dict[str, Any] = {}

    ok, err = validate_market_data(market_data)
    if not ok:
        return {
            "phase": 43,
            "module": "liquidity_topology_engine",
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
    depth_levels = int(d.get("depth_levels") or _DEFAULT_DEPTH)

    obs = [x for x in d["order_books"] if isinstance(x, dict)]

    total_bid, total_ask, _ = compute_depth_totals(obs, depth_levels)
    _, ofi_score = compute_ofi_score(total_bid, total_ask)
    _, black_hole_score = compute_black_hole_score(obs, depth_levels)
    _, vacuum_score = compute_vacuum_score(obs, float(d["current_price"]))

    alpha_score = _clip01(
        0.5 * ofi_score + 0.3 * (1.0 - vacuum_score) + 0.2 * (1.0 - black_hole_score)
    )
    risk_score = _clip01(0.5 * black_hole_score + 0.3 * vacuum_score + 0.2 * (1.0 - ofi_score))

    data_health = float(np.clip(len(d["order_books"]) / 5.0, 0.2, 1.0))
    confidence = _clip01(data_health * (1.0 - 0.3 * risk_score))

    score_type = _pick_score_type(data_health, risk_score)

    trade_permission = "ALLOW"
    reason = "conditions_normal"

    if d.get("force_halt") is True:
        trade_permission = "HALT"
        reason = "force_halt"
    elif black_hole_score >= _BLACK_HOLE_BLOCK:
        trade_permission = "BLOCK"
        reason = "liquidity_black_hole"

    nested = {
        "ofi_score": ofi_score,
        "black_hole_score": black_hole_score,
        "vacuum_score": vacuum_score,
        "total_bid_depth": float(total_bid),
        "total_ask_depth": float(total_ask),
        "exchange_count": int(len(d["order_books"])),
    }

    return {
        "phase": 43,
        "module": "liquidity_topology_engine",
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
