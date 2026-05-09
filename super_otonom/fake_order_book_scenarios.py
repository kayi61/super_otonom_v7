from __future__ import annotations

"""
Sahte ama gerçekçi order book + senaryo analysis üreticisi.

Amaç:
- Faz 71-80 zinciri ve pipeline entegrasyon testleri için deterministik, repeatable veri.
- Flash crash / pump&dump / düşük likidite gibi uç senaryoları simüle etmek.

Çıktı şekli:
- order_book: {"bids":[[price,qty],...], "asks":[[price,qty],...]}  (price float, qty float)
- analysis: pipeline içinde kullanılan temel alanlar (regime, volatility, liquidity_ratio, mtf, venues, flash_crash flag)
"""

import math
import random
import time
from typing import Any, Dict, List, Literal, Tuple


OrderBook = Dict[str, List[List[float]]]
Scenario = Literal["normal", "flash_crash", "pump_dump", "low_liquidity"]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _round_px(x: float) -> float:
    return float(round(x, 4))


def _round_qty(x: float) -> float:
    return float(round(x, 6))


def _mk_ladder(
    *,
    mid: float,
    levels: int,
    tick: float,
    base_qty: float,
    side: Literal["bid", "ask"],
    qty_decay: float = 0.92,
    px_widen_mult: float = 1.0,
) -> List[List[float]]:
    out: List[List[float]] = []
    q = float(base_qty)
    for i in range(levels):
        step = (i + 1) * tick * px_widen_mult
        px = mid - step if side == "bid" else mid + step
        out.append([_round_px(px), _round_qty(max(0.000001, q))])
        q *= qty_decay
    return out


def _inject_wall(levels: List[List[float]], *, idx: int, mult: float) -> None:
    if 0 <= idx < len(levels):
        levels[idx][1] = _round_qty(levels[idx][1] * float(mult))


def _mtf_all_buy(score: int = 70) -> Dict[str, Dict[str, Any]]:
    return {
        "1m": {"signal": "BUY", "score": score},
        "5m": {"signal": "BUY", "score": score},
        "15m": {"signal": "BUY", "score": max(50, score - 10)},
        "1h": {"signal": "BUY", "score": min(85, score + 5)},
        "4h": {"signal": "BUY", "score": min(90, score + 10)},
    }


def _mtf_conflict() -> Dict[str, Dict[str, Any]]:
    return {
        "1m": {"signal": "BUY", "score": 65},
        "5m": {"signal": "SELL", "score": 60},
        "15m": {"signal": "BUY", "score": 55},
        "1h": {"signal": "SELL", "score": 70},
        "4h": {"signal": "HOLD", "score": 55},
    }


def _venues_base(mid: float) -> Dict[str, Dict[str, Any]]:
    return {
        "okx": {"price": mid, "ret_1s": 0.0006, "latency_ms": 40},
        "kucoin": {"price": mid * 1.0002, "ret_1s": 0.0002, "latency_ms": 60},
        "gate": {"price": mid * 1.0003, "ret_1s": 0.0001, "latency_ms": 70},
    }


def make_scenario(
    *,
    scenario: Scenario,
    symbol: str = "BTC/USDT",
    mid_price: float = 100.0,
    seed: int = 42,
    event_ts: int | None = None,
) -> Tuple[OrderBook, Dict[str, Any]]:
    """
    Returns (order_book, analysis).
    Deterministic for a given seed.
    """
    rnd = random.Random(seed)
    ts = int(event_ts if event_ts is not None else _now_ms())

    # Baseline parameters
    mid = float(mid_price)
    tick = max(0.01, mid * 0.0002)  # 2 bps tick-ish
    levels = 20
    base_qty = 8.0

    bids = _mk_ladder(mid=mid, levels=levels, tick=tick, base_qty=base_qty, side="bid")
    asks = _mk_ladder(mid=mid, levels=levels, tick=tick, base_qty=base_qty, side="ask")

    analysis: Dict[str, Any] = {
        "symbol": symbol,
        "signal": "HOLD",
        "regime": "NOISY",
        "volatility": 0.02,
        "liquidity_ratio": 0.75,
        "mtf": _mtf_all_buy(70),
        "venues": _venues_base(mid),
        "event_ts": ts,
        "half_life_ms": 30_000,
        "flash_crash": False,
    }

    if scenario == "normal":
        # Slight asymmetry, realistic wall
        _inject_wall(bids, idx=2, mult=2.2)
        _inject_wall(asks, idx=4, mult=1.6)
        analysis["signal"] = "BUY"
        analysis["regime"] = "TREND"
        analysis["volatility"] = 0.018
        analysis["liquidity_ratio"] = 0.80

    elif scenario == "flash_crash":
        # Huge spread, thin asks, deep bids far away (liquidity vacuum + jump risk)
        # Move best ask far and reduce near-book depth
        for i in range(min(5, len(asks))):
            asks[i][0] = _round_px(asks[i][0] * (1.02 + 0.01 * i))
            asks[i][1] = _round_qty(asks[i][1] * 0.25)
        for i in range(min(5, len(bids))):
            bids[i][0] = _round_px(bids[i][0] * (0.98 - 0.005 * i))
            bids[i][1] = _round_qty(bids[i][1] * 0.45)
        # Add a "catch bid" wall deeper
        _inject_wall(bids, idx=10, mult=6.0)
        analysis["signal"] = "HOLD"
        analysis["regime"] = "CRISIS"
        analysis["volatility"] = 0.12
        analysis["liquidity_ratio"] = 0.20
        analysis["mtf"] = _mtf_conflict()
        analysis["flash_crash"] = True
        # Venues diverge
        v = _venues_base(mid)
        v["okx"]["price"] = mid * 0.985
        v["kucoin"]["price"] = mid * 0.992
        v["gate"]["price"] = mid * 0.978
        analysis["venues"] = v

    elif scenario == "pump_dump":
        # Tight-ish spread but strong imbalance + spoof-like wall then thin depth (trap risk)
        # Big bid wall near top (accumulation), but asks also have a far wall (distribution)
        _inject_wall(bids, idx=0, mult=8.0)
        _inject_wall(bids, idx=1, mult=4.0)
        _inject_wall(asks, idx=6, mult=7.0)
        # Slightly widen tick ladder to look jumpy
        asks = _mk_ladder(mid=mid * 1.002, levels=levels, tick=tick * 1.3, base_qty=base_qty * 0.9, side="ask", px_widen_mult=1.2)
        bids = _mk_ladder(mid=mid, levels=levels, tick=tick * 1.3, base_qty=base_qty * 1.3, side="bid", px_widen_mult=1.2)
        _inject_wall(bids, idx=0, mult=8.0)
        analysis["signal"] = "BUY"
        analysis["regime"] = "VOLATILE"
        analysis["volatility"] = 0.07
        analysis["liquidity_ratio"] = 0.55
        analysis["mtf"] = _mtf_conflict()
        # Venues show lead-lag (one venue moves first)
        v = _venues_base(mid)
        v["okx"]["ret_1s"] = 0.0025
        v["okx"]["price"] = mid * 1.006
        v["kucoin"]["price"] = mid * 1.002
        v["gate"]["price"] = mid * 1.003
        analysis["venues"] = v

    elif scenario == "low_liquidity":
        # Very thin book: small quantities and wider ticks
        base_qty_thin = 0.45
        bids = _mk_ladder(mid=mid, levels=levels, tick=tick * 2.5, base_qty=base_qty_thin, side="bid", qty_decay=0.88, px_widen_mult=1.25)
        asks = _mk_ladder(mid=mid, levels=levels, tick=tick * 2.5, base_qty=base_qty_thin, side="ask", qty_decay=0.88, px_widen_mult=1.25)
        analysis["signal"] = "HOLD"
        analysis["regime"] = "NOISY"
        analysis["volatility"] = 0.035
        analysis["liquidity_ratio"] = 0.12
        analysis["mtf"] = _mtf_conflict()
        # Venues sparse
        analysis["venues"] = {"okx": {"price": mid, "ret_1s": 0.0002, "latency_ms": 45}}

    else:
        raise ValueError(f"unknown scenario: {scenario}")

    # Add microstructure-ish fields that other parts may look at
    # Use approximate spread computed from best levels
    try:
        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
        mid2 = (best_bid + best_ask) / 2.0 if best_bid > 0 and best_ask > 0 else mid
        spread_pct = (best_ask - best_bid) / mid2 if mid2 > 0 else 0.0
    except Exception:
        spread_pct = 0.0

    # liquidity_ratio sanity (keep in 0..1)
    analysis["liquidity_ratio"] = max(0.0, min(1.0, float(analysis.get("liquidity_ratio", 0.5))))
    analysis["spread_pct"] = float(round(max(0.0, spread_pct), 6))

    order_book: OrderBook = {"bids": bids, "asks": asks}
    return order_book, analysis

