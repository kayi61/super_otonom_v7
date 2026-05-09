"""
Faz 25 — Market Microstructure (işlem akışı + likidite etkisi).

İçerik (heuristik, deterministik):
- OFI (Order Flow Imbalance): işaretli hacim dengesi
- Kyle lambda proxy: birim hacme göre ortalama |fiyat etkisi|
- Amihud illiquidity proxy: |getiri| / işlem tutarı
- Adverse selection skoru: alıcı baskısı vs kısa UF kayması uyumsuzluğu
- Momentum ignition: art arda tek yönlü işlem patlaması + OFI sıçraması

Çıktı Faz 21 ile uyumlu: alpha_score / risk_score 0–1, score_type, phase25/faz25.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

from super_otonom.order_book_intelligence import compute_signed_obi
from super_otonom.standard_phase_output import attach_phase_alias

ScoreType = Literal["ALPHA", "RISK", "QUALITY"]
TradePermission = Literal["ALLOW", "BLOCK", "HALT"]

_EPS = 1e-12


def _now_ms() -> int:
    return int(time.time() * 1000)


def _clamp01(x: float) -> float:
    if x != x:
        return 0.0
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else float(x)


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


def _pick_score_type(data_health: float, risk_01: float) -> ScoreType:
    if data_health < 0.42:
        return "QUALITY"
    if risk_01 >= 0.72:
        return "RISK"
    return "ALPHA"


def _parse_trade_row(row: Any) -> Optional[Tuple[int, float, float]]:
    """
    Dönüş: (side_sign +1 buy / -1 sell, price, qty)
    """
    if isinstance(row, dict):
        raw_side = str(
            row.get("side")
            or row.get("aggressor")
            or row.get("taker_side")
            or ""
        ).lower()
        qty = float(row.get("qty") or row.get("amount") or row.get("size") or 0.0)
        price = float(row.get("price") or row.get("px") or 0.0)
        if raw_side in ("b", "buy", "bid", "purchase"):
            sgn = 1
        elif raw_side in ("s", "sell", "ask", "sale"):
            sgn = -1
        else:
            return None
        if price <= 0 or qty <= 0:
            return None
        return sgn, price, qty

    if isinstance(row, (list, tuple)) and len(row) >= 3:
        a, b, c = row[0], row[1], row[2]
        if isinstance(a, str):
            sgn = 1 if str(a).lower() in ("b", "buy", "bid") else -1
            price, qty = float(b), float(c)
        else:
            price, qty, side = float(a), float(b), str(c).lower()
            sgn = 1 if side in ("b", "buy", "bid") else -1
        if price <= 0 or qty <= 0:
            return None
        return sgn, price, qty

    return None


def _normalize_trades(trades: Any) -> List[Tuple[int, float, float]]:
    out: List[Tuple[int, float, float]] = []
    if not trades:
        return out
    if isinstance(trades, (str, bytes)):
        return out
    if not isinstance(trades, Sequence):
        return out
    for row in trades:
        p = _parse_trade_row(row)
        if p is not None:
            out.append(p)
    return out


def compute_ofi_normalized(trades: List[Tuple[int, float, float]]) -> Optional[float]:
    """OFI: işaretli hacim / toplam hacim ∈ [-1, 1]."""
    if not trades:
        return None
    signed = 0.0
    vol = 0.0
    for sgn, _p, q in trades:
        signed += float(sgn) * q
        vol += q
    if vol <= _EPS:
        return None
    return float(max(-1.0, min(1.0, signed / vol)))


def _kyle_lambda_proxy(trades: List[Tuple[int, float, float]]) -> float:
    """
    Kyle lambda proxy: ortalama |Δp| / (qty) küçük işlemler üzerinden (0–1 ölçek).
    """
    if len(trades) < 2:
        return 0.0
    impacts: List[float] = []
    for i in range(1, len(trades)):
        s0, p0, q0 = trades[i - 1]
        s1, p1, q1 = trades[i]
        dp = abs(p1 - p0) / max(p0, _EPS)
        q = max(q1, _EPS)
        impacts.append(dp / q)
    if not impacts:
        return 0.0
    raw = sum(impacts) / len(impacts)
    return _clamp01(math.log1p(raw * 1e6) / 12.0)


def _amihud_proxy(trades: List[Tuple[int, float, float]]) -> float:
    """Amihud: |log ret| / (price*qty) ortalaması, normalize 0–1."""
    if len(trades) < 2:
        return 0.0
    terms: List[float] = []
    for i in range(1, len(trades)):
        _s0, p0, q0 = trades[i - 1]
        _s1, p1, q1 = trades[i]
        if p0 <= 0 or p1 <= 0:
            continue
        lr = abs(math.log(p1 / p0))
        dv = p1 * q1 + _EPS
        terms.append(lr / dv)
    if not terms:
        return 0.0
    raw = sum(terms) / len(terms)
    return _clamp01(math.log1p(raw * 1e8) / 14.0)


def _adverse_selection_score(trades: List[Tuple[int, float, float]]) -> float:
    """
    Alıcı hacmi baskınken net fiyat düşüşü (veya tersi) → bilgi asimetrisi proxy [0,1].
    """
    if len(trades) < 4:
        return 0.0
    buy_vol = sum(q for s, _p, q in trades if s > 0)
    sell_vol = sum(q for s, _p, q in trades if s < 0)
    tot = buy_vol + sell_vol
    if tot <= _EPS:
        return 0.0
    imb = (buy_vol - sell_vol) / tot
    p0 = trades[0][1]
    p1 = trades[-1][1]
    if p0 <= 0:
        return 0.0
    ret = (p1 - p0) / p0
    stress = -imb * ret
    return _clamp01((stress + 0.25) / 0.5)


def _momentum_ignition_score(trades: List[Tuple[int, float, float]]) -> float:
    """Art arda aynı yön + hacim yoğunluğu artışı → ignition [0,1]."""
    if len(trades) < 4:
        return 0.0
    streak = 1
    mx_streak = 1
    prev_s = trades[0][0]
    for i in range(1, len(trades)):
        s = trades[i][0]
        if s == prev_s:
            streak += 1
            mx_streak = max(mx_streak, streak)
        else:
            streak = 1
        prev_s = s
    vols = [q for _, _, q in trades]
    vm = max(vols) / (sum(vols) / len(vols) + _EPS)
    streak_n = _clamp01((mx_streak - 2.5) / 6.0)
    vm_n = _clamp01((vm - 1.4) / 4.0)
    return _clamp01(0.55 * streak_n + 0.45 * vm_n)


def _directional_alpha_ofi(ofi: Optional[float], signal_hint: str) -> float:
    if ofi is None:
        return 0.5
    s = str(signal_hint or "HOLD").upper()
    x = ofi
    if s == "BUY":
        return _clamp01((x + 1.0) / 2.0)
    if s == "SELL":
        return _clamp01((1.0 - x) / 2.0)
    return _clamp01(abs(x))


def analyze_market_microstructure(
    symbol: str,
    trades: Any,
    order_book: Optional[Dict[str, Any]],
    analysis: Optional[Dict[str, Any]] = None,
    *,
    attach_to_analysis: bool = True,
    half_life_ms: int = 50_000,
    event_ts: Optional[int] = None,
    depth_book: int = 10,
) -> Dict[str, Any]:
    """
    Mikro yapı metrikleri + standart faz çıktısı.
    `trades`: dict listesi veya [side, price, qty] satırları.
    """
    _ = symbol
    a = analysis if analysis is not None else {}
    ts = int(event_ts) if event_ts is not None else _try_ts_ms(a)
    parsed = _normalize_trades(trades)

    if not parsed:
        payload = _empty_phase25(ts, half_life_ms, "no_trades")
        if attach_to_analysis:
            attach_phase_alias(a, "25", payload)
        return payload

    ofi_n = compute_ofi_normalized(parsed)
    kyle = _kyle_lambda_proxy(parsed)
    amihud = _amihud_proxy(parsed)
    adverse = _adverse_selection_score(parsed)
    ignition = _momentum_ignition_score(parsed)

    obi_signed: Optional[float] = None
    if isinstance(order_book, dict) and order_book.get("bids") and order_book.get("asks"):
        obi_signed = compute_signed_obi(order_book, depth=depth_book)

    signal_hint = str(a.get("signal", "HOLD"))
    alpha_ofi = _directional_alpha_ofi(ofi_n, signal_hint)
    if obi_signed is not None:
        blend = 0.62 * alpha_ofi + 0.38 * _directional_alpha_ofi(obi_signed, signal_hint)
        alpha_01 = _clamp01(blend)
    else:
        alpha_01 = alpha_ofi

    risk_01 = _clamp01(
        0.22 * kyle
        + 0.28 * amihud
        + 0.28 * adverse
        + 0.22 * ignition
    )

    n = len(parsed)
    conf = _clamp01(0.28 + 0.55 * min(1.0, n / 25.0) + (0.12 if obi_signed is not None else 0.0))

    dh_trade = _clamp01(0.25 + 0.55 * min(1.0, n / 20.0))
    dh_ob = 0.12 if obi_signed is not None else 0.0
    dh = _clamp01(dh_trade + dh_ob)

    perm: TradePermission = "ALLOW"
    if ignition >= 0.92 and adverse >= 0.78:
        perm = "HALT"
    elif risk_01 >= 0.88 or ignition >= 0.88:
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
        "phase": "25",
        "source": "market_microstructure",
        "ofi_normalized": ofi_n,
        "obi_signed": obi_signed,
        "metrics": {
            "kyle_lambda_score": float(kyle),
            "amihud_score": float(amihud),
            "adverse_selection_score": float(adverse),
            "momentum_ignition_score": float(ignition),
            "trade_count": int(n),
        },
    }

    if attach_to_analysis:
        attach_phase_alias(a, "25", payload)

    return payload


def run_market_microstructure_phase(
    symbol: str,
    trades: Any,
    order_book: Optional[Dict[str, Any]],
    analysis: Optional[Dict[str, Any]] = None,
    *,
    attach_to_analysis: bool = True,
    half_life_ms: int = 50_000,
    event_ts: Optional[int] = None,
    depth_book: int = 10,
) -> Dict[str, Any]:
    """
    Pipeline giriş noktası — `analyze_market_microstructure` ile aynı işi yapar.
    """
    return analyze_market_microstructure(
        symbol,
        trades,
        order_book,
        analysis,
        attach_to_analysis=attach_to_analysis,
        half_life_ms=half_life_ms,
        event_ts=event_ts,
        depth_book=depth_book,
    )


def _empty_phase25(ts: int, half_life_ms: int, reason: str) -> Dict[str, Any]:
    return {
        "trade_permission": "BLOCK",
        "alpha_score": 0.0,
        "risk_score": 1.0,
        "confidence": 0.0,
        "data_health": 0.0,
        "event_ts": float(ts),
        "half_life_ms": int(half_life_ms),
        "score_type": "QUALITY",
        "phase": "25",
        "source": "market_microstructure",
        "empty_reason": reason,
        "ofi_normalized": None,
        "obi_signed": None,
        "metrics": {},
    }
