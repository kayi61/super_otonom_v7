"""
PROMPT-A8 ÔÇö Tek normalize market snapshot (order book).

``prep_symbol_for_tick`` ham defteri bir kez burada i┼şler; ``analysis["order_book"]``
canonical seviyeler olur, tam ├Âzet ``analysis["market_snapshot"]`` alt─▒nda kal─▒r.
Fazlar tekrar tekrar ayn─▒ parse i┼şlemini yapmamal─▒; ├Ânce Faz 73 migrasyonu.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = "a8/v1"
SNAPSHOT_KEY = "market_snapshot"


def _coerce_side(rows: Any, max_levels: int) -> List[List[float]]:
    out: List[List[float]] = []
    if not isinstance(rows, list):
        return out
    for row in rows[:max_levels]:
        if not row or len(row) < 2:
            continue
        try:
            out.append([float(row[0]), float(row[1])])
        except (TypeError, ValueError):
            continue
    return out


def _best_prices(levels: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    bids = levels.get("bids") or []
    asks = levels.get("asks") or []
    try:
        bb = float(bids[0][0]) if bids else None
        ba = float(asks[0][0]) if asks else None
    except (IndexError, TypeError, ValueError):
        return None, None
    if bb is None or ba is None or bb <= 0 or ba <= 0:
        return None, None
    return bb, ba


def _spread_rel(best_bid: float, best_ask: float) -> float:
    mid = (best_bid + best_ask) / 2.0
    if mid <= 0:
        return 0.0
    return (best_ask - best_bid) / mid


def _ob_imbalance_top_n(levels: Dict[str, Any], n: int) -> Optional[float]:
    bids = levels.get("bids") or []
    asks = levels.get("asks") or []
    try:
        b = bids[:n]
        a = asks[:n]
        if not b or not a:
            return None
        bid_qty = sum(float(q) for _, q in b)
        ask_qty = sum(float(q) for _, q in a)
        den = bid_qty + ask_qty
        if den <= 0:
            return None
        return bid_qty / den
    except (TypeError, ValueError):
        return None


def _notional_sums(levels: Dict[str, Any], n: int) -> Tuple[float, float]:
    bid_n = 0.0
    ask_n = 0.0
    try:
        for p, q in (levels.get("bids") or [])[:n]:
            bid_n += float(p) * float(q)
        for p, q in (levels.get("asks") or [])[:n]:
            ask_n += float(p) * float(q)
    except (TypeError, ValueError):
        pass
    return bid_n, ask_n


def build_market_snapshot(
    symbol: str,
    raw_order_book: Dict[str, Any],
    *,
    captured_ts: Optional[float] = None,
    max_levels: int = 25,
) -> Dict[str, Any]:
    """
    Ham ccxt-benzeri ``{"bids":[], "asks":[]}`` ÔåÆ tek ┼şema.

    ``order_book.levels`` ÔÇö sonraki t├╝keticiler i├ğin canonical (float ├ğiftleri).
    """
    raw = raw_order_book if isinstance(raw_order_book, dict) else {}
    bids = _coerce_side(raw.get("bids"), max_levels)
    asks = _coerce_side(raw.get("asks"), max_levels)
    levels = {"bids": bids, "asks": asks}
    bb, ba = _best_prices(levels)
    mid: Optional[float] = None
    spread_rel: Optional[float] = None
    spread_bps: Optional[float] = None
    if bb is not None and ba is not None:
        mid = (bb + ba) / 2.0
        spread_rel = _spread_rel(bb, ba)
        spread_bps = spread_rel * 10_000.0 if spread_rel is not None else None

    imb10 = _ob_imbalance_top_n(levels, 10)
    bid_n10, ask_n10 = _notional_sums(levels, 10)
    empty = not bids or not asks

    ts = float(captured_ts if captured_ts is not None else time.time())
    return {
        "schema": SCHEMA_VERSION,
        "symbol": str(symbol),
        "captured_ts": ts,
        "order_book": {
            "empty": empty,
            "best_bid": bb,
            "best_ask": ba,
            "mid": mid,
            "spread_rel": spread_rel,
            "spread_bps": spread_bps,
            "ob_imbalance_top10": imb10,
            "bid_notional_top10": round(bid_n10, 6),
            "ask_notional_top10": round(ask_n10, 6),
            "levels": levels,
            "max_levels": int(max_levels),
        },
        "trades": None,
    }


def attach_market_snapshot(
    analysis: Dict[str, Any],
    symbol: str,
    raw_order_book: Dict[str, Any],
    *,
    captured_ts: Optional[float] = None,
    max_levels: int = 25,
) -> Dict[str, Any]:
    """
    ``analysis["market_snapshot"]`` yazar ve ``analysis["order_book"]`` alan─▒n─▒
    canonical seviyelerle g├╝nceller (tek parse noktas─▒).
    """
    snap = build_market_snapshot(
        symbol, raw_order_book, captured_ts=captured_ts, max_levels=max_levels
    )
    analysis[SNAPSHOT_KEY] = snap
    analysis["order_book"] = snap["order_book"]["levels"]
    return snap
