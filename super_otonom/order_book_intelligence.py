"""
Faz 21 — Order Book Intelligence (Level-2 özet).

İçerik:
- Üst seviye bid/ask yoğunluğu ve klasik OBI (Order Book Imbalance)
- Duvar (tek seviyede anormal hacim), iceberg (üst satır vs derinlik), spoofing (flash likidite) heuristikleri

Çıktı `standard_phase_output` ile aynı anahtar isimlerini taşır; bu fazda alpha_score ve risk_score 0–1 ölçeklidir.
Ek alan: score_type ∈ {ALPHA, RISK, QUALITY}.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

from super_otonom.standard_phase_output import attach_phase_alias

ScoreType = Literal["ALPHA", "RISK", "QUALITY"]
TradePermission = Literal["ALLOW", "BLOCK", "HALT"]

_TOP_LEVELS = 15
_EPS = 1e-12


def _now_ms() -> int:
    return int(time.time() * 1000)


def _clamp01(x: float) -> float:
    if x != x:
        return 0.0
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else float(x)


def _parse_side(book: Dict[str, Any], key: str, max_levels: int) -> List[Tuple[float, float]]:
    raw = book.get(key) or []
    out: List[Tuple[float, float]] = []
    if not isinstance(raw, Sequence):
        return out
    for row in raw[:max_levels]:
        try:
            if not row or len(row) < 2:
                continue
            p, q = float(row[0]), float(row[1])
            if p > 0 and q >= 0:
                out.append((p, q))
        except (TypeError, ValueError):
            continue
    return out


def _total_qty(levels: List[Tuple[float, float]]) -> float:
    return float(sum(q for _, q in levels))


def compute_signed_obi(order_book: Dict[str, Any], *, depth: int = 10) -> Optional[float]:
    """
    Klasik işaretli OBI: (bid_qty - ask_qty) / (bid_qty + ask_qty) ∈ [-1, 1].
    Yoksa None.
    """
    bids = _parse_side(order_book, "bids", depth)
    asks = _parse_side(order_book, "asks", depth)
    if not bids or not asks:
        return None
    bq = _total_qty(bids)
    aq = _total_qty(asks)
    den = bq + aq
    if den <= _EPS:
        return None
    v = (bq - aq) / den
    return float(max(-1.0, min(1.0, v)))


def _wall_pressure(levels: List[Tuple[float, float]]) -> float:
    """Tek seviyede medyana göre abartılı hacim → [0,1] duvar şüphesi."""
    if len(levels) < 3:
        return 0.0
    qtys = sorted([q for _, q in levels], reverse=True)
    mx = qtys[0]
    rest = qtys[1:]
    med = float(rest[len(rest) // 2]) if rest else mx
    if med <= _EPS:
        return 1.0 if mx > _EPS else 0.0
    ratio = mx / (med + _EPS)
    return _clamp01((ratio - 2.2) / 7.0)


def _iceberg_pressure(levels: List[Tuple[float, float]]) -> float:
    """Üst satır hacmi, hemen alt derinliğe göre şişkin → iceberg proxy [0,1]."""
    if len(levels) < 2:
        return 0.0
    top = float(levels[0][1])
    tail = levels[1:6]
    if not tail:
        return 0.0
    avg_tail = sum(float(q) for _, q in tail) / len(tail)
    if avg_tail <= _EPS:
        return 1.0 if top > _EPS else 0.0
    ratio = top / (avg_tail + _EPS)
    return _clamp01((ratio - 1.6) / 5.0)


def _spoof_pressure(side_levels: List[Tuple[float, float]]) -> float:
    """
    En iyi fiyat kademesinin arkasındaki birikime göre 'flash' domination.
    Dar ARKA derinlik + şişkin BEST → spoof/layering şüphesi [0,1].
    """
    if len(side_levels) < 2:
        return 0.0
    best = float(side_levels[0][1])
    behind = _total_qty(side_levels[1:6])
    if behind <= _EPS:
        return _clamp01(best / (best + _EPS))
    ratio = best / (behind + _EPS)
    return _clamp01((ratio - 0.28) / 2.2)


def _spread_quality(book: Dict[str, Any]) -> Tuple[float, float]:
    """(spread_pct mid bazlı, mid). spread_pct yoksa (1.0, 0.0) kötü sayılır."""
    bids = _parse_side(book, "bids", 1)
    asks = _parse_side(book, "asks", 1)
    if not bids or not asks:
        return 1.0, 0.0
    bb, ba = bids[0][0], asks[0][0]
    mid = (bb + ba) / 2.0
    if mid <= 0:
        return 1.0, 0.0
    sp = (ba - bb) / mid
    return float(sp), float(mid)


def _directional_alpha_01(
    obi_signed: Optional[float],
    signal_hint: str,
) -> float:
    """Sinyal yönüne göre OBI'yi 0–1 alpha'ya çevir."""
    if obi_signed is None:
        return 0.5
    s = str(signal_hint or "HOLD").upper()
    x = obi_signed
    if s == "BUY":
        return _clamp01((x + 1.0) / 2.0)
    if s == "SELL":
        return _clamp01((1.0 - x) / 2.0)
    return _clamp01(abs(x))


def _pick_score_type(
    data_health: float,
    risk_01: float,
) -> ScoreType:
    if data_health < 0.42:
        return "QUALITY"
    if risk_01 >= 0.72:
        return "RISK"
    return "ALPHA"


def analyze_order_book_intelligence(
    symbol: str,
    order_book: Optional[Dict[str, Any]],
    analysis: Optional[Dict[str, Any]] = None,
    *,
    depth: int = _TOP_LEVELS,
    half_life_ms: int = 45_000,
    event_ts: Optional[int] = None,
    attach_to_analysis: bool = True,
) -> Dict[str, Any]:
    """
    Level-2 özet + OBI + duvar / iceberg / spoof heuristikleri.

    Dönüş: standard_phase_output anahtarları + score_type (alpha_score/risk_score bu fazda 0–1).
    """
    _ = symbol
    a = analysis if analysis is not None else {}
    ts = int(event_ts) if event_ts is not None else _try_ts_ms(a)
    book = order_book if isinstance(order_book, dict) else None

    if not book or not book.get("bids") or not book.get("asks"):
        payload = _empty_phase21(ts, half_life_ms, reason="missing_order_book")
        if attach_to_analysis:
            attach_phase_alias(a, "21", payload)
        return payload

    bids = _parse_side(book, "bids", depth)
    asks = _parse_side(book, "asks", depth)
    if not bids or not asks:
        payload = _empty_phase21(ts, half_life_ms, reason="empty_sides")
        if attach_to_analysis:
            attach_phase_alias(a, "21", payload)
        return payload

    obi = compute_signed_obi(book, depth=min(depth, 10))
    spread_pct, mid = _spread_quality(book)

    wall_b = _wall_pressure(bids)
    wall_a = _wall_pressure(asks)
    wall_max = max(wall_b, wall_a)

    ice_b = _iceberg_pressure(bids)
    ice_a = _iceberg_pressure(asks)
    ice_max = max(ice_b, ice_a)

    spo_b = _spoof_pressure(bids)
    spo_a = _spoof_pressure(asks)
    spo_max = max(spo_b, spo_a)

    signal_hint = str(a.get("signal", "HOLD"))
    alpha_01 = _directional_alpha_01(obi, signal_hint)

    risk_01 = _clamp01(
        0.34 * wall_max
        + 0.28 * ice_max
        + 0.38 * spo_max
        + (0.08 if spread_pct > 0.006 else 0.0)
    )

    levels_ok = min(len(bids), len(asks)) / max(1.0, float(depth))
    conf = _clamp01(0.35 + 0.45 * levels_ok + (0.15 if spread_pct < 0.004 else 0.0))
    dh = _clamp01(0.35 + 0.40 * levels_ok + (0.20 if mid > 0 else 0.0))

    perm: TradePermission = "ALLOW"
    if spo_max >= 0.92 and wall_max >= 0.75:
        perm = "HALT"
    elif risk_01 >= 0.88 or spo_max >= 0.85:
        perm = "BLOCK"
    elif risk_01 >= 0.72:
        perm = "BLOCK"

    st = _pick_score_type(dh, risk_01)

    payload: Dict[str, Any] = {
        "trade_permission": perm,
        "alpha_score": float(alpha_01),
        "risk_score": float(risk_01),
        "confidence": float(conf),
        "data_health": float(dh),
        "event_ts": float(ts),
        "half_life_ms": int(half_life_ms),
        "score_type": st,
        "phase": "21",
        "source": "order_book_intelligence",
        "obi_signed": obi,
        "spread_pct": spread_pct,
        "microstructure": {
            "wall_score": float(wall_max),
            "iceberg_score": float(ice_max),
            "spoof_score": float(spo_max),
            "bid_levels": len(bids),
            "ask_levels": len(asks),
        },
    }

    if attach_to_analysis:
        attach_phase_alias(a, "21", payload)

    return payload


def _try_ts_ms(analysis: Dict[str, Any]) -> int:
    v = analysis.get("event_ts") or analysis.get("candle_ts")
    try:
        if v is None:
            return _now_ms()
        fv = float(v)
        if fv < 1e11:
            return int(fv * 1000.0)
        return int(fv)
    except (TypeError, ValueError):
        return _now_ms()


def _empty_phase21(ts: int, half_life_ms: int, *, reason: str) -> Dict[str, Any]:
    return {
        "trade_permission": "BLOCK",
        "alpha_score": 0.0,
        "risk_score": 1.0,
        "confidence": 0.0,
        "data_health": 0.0,
        "event_ts": float(ts),
        "half_life_ms": int(half_life_ms),
        "score_type": "QUALITY",
        "phase": "21",
        "source": "order_book_intelligence",
        "empty_reason": reason,
        "obi_signed": None,
        "spread_pct": None,
        "microstructure": {},
    }
