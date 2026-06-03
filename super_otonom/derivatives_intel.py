"""
Faz 18 — Türev / koordinat intel (funding, OI, L/S, basis, tasfiye haritası).

Girdi `derivatives_data` esnek dict:
- funding_rate: ondalık (ör. 0.0001 ≈ %0.01 / aralık)
- open_interest, open_interest_prev veya open_interest_change_pct
- long_short_ratio: long/short (>1 çoğunluk long)
- spot_price, mark_price | index_price | futures_price
- liquidation_levels: [{"price", "size", "side"?}, ...]

Çıktı Faz 21/25 ile uyumlu: alpha_score / risk_score 0–1, score_type, phase18/faz18.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Literal, Optional

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


def _get_num(d: Dict[str, Any], *keys: str, default: Optional[float] = None) -> Optional[float]:
    for k in keys:
        if k in d and d[k] is not None:
            try:
                return float(d[k])
            except (TypeError, ValueError):
                continue
    return default


def _normalize_derivatives_input(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return dict(raw)


def _funding_components(funding_rate: Optional[float]) -> tuple[float, float]:
    """
    Dönüş: (crowding_risk 0-1, directional_hint -1 long pay / +1 short pay uzantısı basit proxy)
    Pozitif funding → longlar shortlara öder → uzun kalabalık baskısı.
    """
    if funding_rate is None:
        return 0.25, 0.0
    fr = float(funding_rate)
    ax = min(1.0, abs(fr) / 0.0008)
    crowding = _clamp01(ax)
    hint = -math.copysign(1.0, fr) if fr != 0 else 0.0
    return crowding, float(max(-1.0, min(1.0, hint * ax)))


def _oi_trend_score(
    oi: Optional[float],
    oi_prev: Optional[float],
    oi_chg_pct: Optional[float],
) -> tuple[float, Optional[float]]:
    """(normalized trend -1..1 mapped to 0..1 momentum tag, raw change ratio or None)"""
    chg: Optional[float] = None
    if oi_chg_pct is not None:
        try:
            chg = float(oi_chg_pct)
        except (TypeError, ValueError):
            chg = None
    if chg is None and oi is not None and oi_prev is not None and oi_prev > _EPS:
        chg = (float(oi) - float(oi_prev)) / float(oi_prev)
    if chg is None:
        return 0.5, None
    chg = max(-0.25, min(0.25, float(chg)))
    tag = _clamp01((chg + 0.25) / 0.5)
    return tag, float(chg)


def _long_short_risk(ls_ratio: Optional[float]) -> float:
    if ls_ratio is None or ls_ratio <= _EPS:
        return 0.3
    r = float(ls_ratio)
    imbalance = abs(math.log(max(r, _EPS)))
    return _clamp01(imbalance / 1.5)


def _basis_pct(spot: Optional[float], mark: Optional[float]) -> Optional[float]:
    if spot is None or mark is None:
        return None
    if spot <= 0:
        return None
    return (float(mark) - float(spot)) / float(spot)


def _basis_risk(basis_pct: Optional[float]) -> float:
    if basis_pct is None:
        return 0.35
    return _clamp01(abs(float(basis_pct)) / 0.025)


def _liquidity_map_score(
    levels: Any,
    ref_price: float,
) -> float:
    """
    Fiyata yakın büyük tasfiye yoğunluğu → likidite/risk skoru [0,1].
    """
    if not isinstance(levels, list) or ref_price <= 0:
        return 0.2
    rows: List[tuple[float, float]] = []
    for row in levels:
        if not isinstance(row, dict):
            continue
        px = _get_num(row, "price", "px", "level")
        sz = _get_num(row, "size", "qty", "amount", "notional")
        if px is None or sz is None or px <= 0 or sz < 0:
            continue
        rows.append((float(px), float(sz)))
    if not rows:
        return 0.2
    tot = sum(s for _, s in rows) + _EPS
    stress = 0.0
    for px, sz in rows:
        dist = abs(px - ref_price) / ref_price
        w = sz / tot
        if dist < 0.015:
            stress += w * 1.0
        elif dist < 0.035:
            stress += w * 0.55
        else:
            stress += w * 0.15
    return _clamp01(stress * 1.15)


def _directional_alpha(
    signal_hint: str,
    funding_rate: Optional[float],
    oi_momentum_01: float,
    ls_ratio: Optional[float],
) -> float:
    """0–1 alpha: sinyal + türev çarpanları (heuristik)."""
    s = str(signal_hint or "HOLD").upper()
    base = 0.5
    if funding_rate is not None:
        fr = float(funding_rate)
        if s == "BUY":
            base = _clamp01(0.52 - 0.42 * math.tanh(fr / 0.00035))
        elif s == "SELL":
            base = _clamp01(0.48 + 0.42 * math.tanh(fr / 0.00035))
        else:
            base = _clamp01(0.5 - 0.15 * math.tanh(fr / 0.0004))

    adj_oi = 0.12 * (oi_momentum_01 - 0.5)
    base = _clamp01(base + adj_oi)

    if ls_ratio is not None and ls_ratio > _EPS:
        lr = float(ls_ratio)
        if s == "BUY":
            base = _clamp01(base - 0.08 * _clamp01(max(0.0, math.log(lr))))
        elif s == "SELL":
            base = _clamp01(base + 0.08 * _clamp01(max(0.0, math.log(lr))))

    return _clamp01(base)


def analyze_derivatives_intel(
    symbol: str,
    derivatives_data: Any,
    analysis: Optional[Dict[str, Any]] = None,
    *,
    attach_to_analysis: bool = True,
    half_life_ms: int = 55_000,
    event_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Türev metrikleri birleştirir; `analysis['phase18']` / `['faz18']` yazar.
    """
    _ = symbol
    a = analysis if analysis is not None else {}
    ts = int(event_ts) if event_ts is not None else _try_ts_ms(a)
    d = _normalize_derivatives_input(derivatives_data)

    if not d:
        payload = _empty_phase18(ts, half_life_ms, "no_derivatives_data")
        if attach_to_analysis:
            attach_phase_alias(a, "18", payload)
        return payload

    funding = _get_num(d, "funding_rate", "funding", "last_funding_rate")
    oi = _get_num(d, "open_interest", "oi")
    oi_prev = _get_num(d, "open_interest_prev", "oi_prev", "previous_open_interest")
    oi_chg = _get_num(d, "open_interest_change_pct", "oi_change_pct", "oi_pct_change")
    ls_ratio = _get_num(
        d,
        "long_short_ratio",
        "ls_ratio",
        "long_short",
        "top_trader_ls_ratio",
    )
    spot = _get_num(d, "spot_price", "spot", "index_spot")
    mark = _get_num(d, "mark_price", "futures_price", "index_price", "perp_price")

    crowd_fr, _ = _funding_components(funding)
    oi_tag, oi_raw = _oi_trend_score(oi, oi_prev, oi_chg)
    ls_risk = _long_short_risk(ls_ratio)
    basis_pct = _basis_pct(spot, mark)
    basis_r = _basis_risk(basis_pct)

    ref_px = float(spot or mark or 0.0)
    if ref_px <= 0:
        ref_px = 1.0
    liq_levels = d.get("liquidation_levels") or d.get("liq_levels") or d.get("liquidations")
    liq_score = _liquidity_map_score(liq_levels, ref_px)

    signal_hint = str(a.get("signal", "HOLD"))
    alpha_01 = _directional_alpha(signal_hint, funding, oi_tag, ls_ratio)

    risk_01 = _clamp01(0.24 * crowd_fr + 0.26 * ls_risk + 0.26 * basis_r + 0.24 * liq_score)

    # ── PROMPT-3.1: derinlemesine funding analizi ───────────────────────────
    funding_an = _deep_funding_analysis(d, funding)
    if funding_an is not None:
        # Aşırılık riski toplam riske eklenir; kontraryan alpha bias yansıtılır.
        risk_01 = _clamp01(max(risk_01, funding_an.risk_score))
        alpha_01 = _clamp01(alpha_01 + 0.10 * funding_an.alpha_bias)

    fields_ok = sum(
        1
        for v in (funding, oi, ls_ratio, spot, mark)
        if v is not None and (isinstance(v, (int, float)) and v == v)
    )
    liq_ok = 1 if isinstance(liq_levels, list) and len(liq_levels) > 0 else 0
    conf = _clamp01(0.22 + 0.14 * fields_ok + 0.18 * liq_ok)
    dh = _clamp01(0.28 + 0.11 * fields_ok + 0.15 * liq_ok)

    perm: TradePermission = "ALLOW"
    if crowd_fr >= 0.94 and ls_risk >= 0.82:
        perm = "HALT"
    elif risk_01 >= 0.88 or liq_score >= 0.88:
        perm = "BLOCK"
    elif risk_01 >= 0.72:
        perm = "BLOCK"
    # PROMPT-3.1: funding z-score aşırılığı (|z| > 2.5) → BLOCK
    if funding_an is not None and funding_an.block and perm == "ALLOW":
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
        "phase": "18",
        "source": "derivatives_intel",
        "derivatives": {
            "funding_rate": funding,
            "funding_crowding_score": float(crowd_fr),
            "open_interest": oi,
            "open_interest_change_pct": oi_raw,
            "oi_momentum_tag": float(oi_tag),
            "long_short_ratio": ls_ratio,
            "long_short_imbalance_risk": float(ls_risk),
            "basis_pct": basis_pct,
            "basis_risk": float(basis_r),
            "liquidity_cluster_score": float(liq_score),
            "reference_price": float(ref_px),
        },
    }

    if funding_an is not None:
        payload["derivatives"]["funding_analysis"] = funding_an.to_dict()

    if attach_to_analysis:
        attach_phase_alias(a, "18", payload)

    return payload


def _deep_funding_analysis(d: Dict[str, Any], funding: Optional[float]) -> Any:
    """PROMPT-3.1 — funding history varsa derinlemesine analiz; yoksa None.

    Girdi alanları (hepsi opsiyonel): ``funding_history`` (8h ondalık liste),
    ``cross_exchange_funding`` ({borsa: rate}), ``order_book_imbalance`` (-1..1),
    ``funding_premium_pct``, ``position_notional``, ``prev_funding_cross_spread``.
    """
    history = d.get("funding_history") or d.get("funding_rate_history")
    per_exchange = d.get("cross_exchange_funding") or d.get("funding_by_exchange")
    if not isinstance(history, (list, tuple)):
        history = []
    if not (history or isinstance(per_exchange, dict)):
        return None
    from super_otonom.signals.funding_rate_alpha import analyze_funding

    ob_imb = _get_num(d, "order_book_imbalance", "ob_imbalance")
    premium = _get_num(d, "funding_premium_pct", "premium_pct")
    notional = _get_num(d, "position_notional", "notional", default=0.0) or 0.0
    prev_spread = _get_num(d, "prev_funding_cross_spread")
    try:
        return analyze_funding(
            list(history),
            current=funding,
            per_exchange=per_exchange if isinstance(per_exchange, dict) else None,
            order_book_imbalance=ob_imb,
            premium_pct=premium,
            notional=float(notional),
            prev_cross_spread=prev_spread,
        )
    except Exception:  # funding analizi asla Faz 18'i bozmamalı
        return None


def run_derivatives_phase(
    symbol: str,
    derivatives_data: Any,
    analysis: Optional[Dict[str, Any]] = None,
    *,
    attach_to_analysis: bool = True,
    half_life_ms: int = 55_000,
    event_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """Pipeline girişi — `analyze_derivatives_intel` ile aynı."""
    return analyze_derivatives_intel(
        symbol,
        derivatives_data,
        analysis,
        attach_to_analysis=attach_to_analysis,
        half_life_ms=half_life_ms,
        event_ts=event_ts,
    )


def _empty_phase18(ts: int, half_life_ms: int, reason: str) -> Dict[str, Any]:
    return {
        "trade_permission": "BLOCK",
        "alpha_score": 0.0,
        "risk_score": 1.0,
        "confidence": 0.0,
        "data_health": 0.0,
        "event_ts": float(ts),
        "half_life_ms": int(half_life_ms),
        "score_type": "QUALITY",
        "phase": "18",
        "source": "derivatives_intel",
        "empty_reason": reason,
        "derivatives": {},
    }
