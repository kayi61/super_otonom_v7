"""
Faz 17 — Akıllı para / balina & kurumsal akış takibi.

Girdi `smart_money_data` (esnek dict):
- whale_transfers: büyük transfer listesi
  [{"amount_usd","direction"|"flow"}, ...]
  direction / flow: inflow | outflow | to_exchange | from_exchange | accumulation | distribution | cold_storage
- exchange_netflow_usd: negatif ≈ borsadan çekim (birikim proxy)
- institutional_flow_usd | vc_net_flow_usd | etf_net_flow_usd
- institutional_accumulation_score | smart_money_index (0–1, opsiyonel önceden hesap)

Çıktı Faz 16/18 ile uyumlu: alpha/risk 0–1, score_type, phase17/faz17.
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


def _normalize_input(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return dict(raw)


def _parse_direction(row: Dict[str, Any]) -> str:
    v = row.get("direction") or row.get("flow") or row.get("type") or ""
    return str(v).lower().strip()


def _transfer_amount(row: Dict[str, Any]) -> float:
    return float(_get_num(row, "amount_usd", "usd", "value_usd", "notional_usd", "size_usd") or 0.0)


def _whale_transfer_scores(rows: Any) -> tuple[float, float, float]:
    """
    Dönüş: (whale_activity 0-1, accumulation_bias -1..1, dump_pressure 0-1)
    accumulation_bias pozitif: soğuk cüzdan / birikim yönü
    """
    if not isinstance(rows, list) or not rows:
        return 0.25, 0.0, 0.2

    amounts: List[float] = []
    signed_flow = 0.0
    total_abs = 0.0
    dump_to_ex = 0.0

    for row in rows:
        if not isinstance(row, dict):
            continue
        amt = _transfer_amount(row)
        if amt <= 0:
            continue
        amounts.append(amt)
        d = _parse_direction(row)
        total_abs += amt

        acc_sign = 1.0
        if d in ("outflow", "to_exchange", "distribution", "sell", "dump"):
            acc_sign = -1.0
            if d in ("to_exchange", "distribution", "dump"):
                dump_to_ex += amt
        elif d in ("inflow", "from_exchange", "accumulation", "cold_storage", "buy"):
            acc_sign = 1.0
        elif d in ("neutral", "internal", ""):
            acc_sign = 0.0

        signed_flow += acc_sign * amt

    if not amounts:
        return 0.25, 0.0, 0.2

    mx = max(amounts)
    med = sorted(amounts)[len(amounts) // 2]
    whale_sz = _clamp01(math.log1p(mx / max(med, _EPS)) / 4.0)

    bias = signed_flow / (total_abs + _EPS)
    bias = float(max(-1.0, min(1.0, bias)))

    dump_p = _clamp01(dump_to_ex / (total_abs + _EPS))

    act = _clamp01(min(1.0, math.log1p(sum(amounts) / 1e6) / 12.0) * 0.55 + whale_sz * 0.45)

    return act, bias, dump_p


def _institutional_vc_score(d: Dict[str, Any]) -> float:
    """VC / ETF / kurumsal net akış proxy [0,1]."""
    pre = _get_num(
        d,
        "institutional_accumulation_score",
        "smart_money_index",
        "institutional_score",
    )
    if pre is not None:
        x = float(pre)
        if 0.0 <= x <= 1.0:
            return _clamp01(x)
        return _clamp01(x / 100.0)

    etf = _get_num(d, "etf_net_flow_usd", "etf_flow_usd")
    vc = _get_num(d, "vc_net_flow_usd", "vc_accumulation_usd")
    inst = _get_num(d, "institutional_flow_usd", "institutional_net_usd")
    parts: List[float] = []
    for v in (etf, vc, inst):
        if v is None:
            continue
        parts.append(math.tanh(float(v) / max(5e6, _EPS)))
    if not parts:
        return 0.35
    return _clamp01(0.5 + 0.5 * (sum(parts) / len(parts)))


def _exchange_netflow_bias(net_usd: Optional[float]) -> float:
    """Negatif netflow (borsadan çıkış) → pozitif bias [-1,1] üzerinden 0–1 tag."""
    if net_usd is None:
        return 0.5
    x = float(net_usd)
    tag = -math.tanh(x / max(8e6, _EPS))
    return _clamp01(0.5 + 0.5 * tag)


def _alpha_smart_money(
    signal_hint: str,
    accum_bias: float,
    inst_vc_01: float,
    exch_tag_01: float,
    whale_activity: float,
) -> float:
    s = str(signal_hint or "HOLD").upper()
    flow_alpha = _clamp01(
        0.38 * ((accum_bias + 1.0) / 2.0) + 0.32 * inst_vc_01 + 0.30 * exch_tag_01
    )
    boost = 0.08 * whale_activity
    base = _clamp01(flow_alpha + boost)

    if s == "BUY":
        base = _clamp01(base + 0.06 * max(0.0, accum_bias))
    elif s == "SELL":
        base = _clamp01(base + 0.05 * max(0.0, -accum_bias))

    return _clamp01(base)


def _risk_smart_money(
    dump_pressure: float,
    whale_activity: float,
    accum_bias: float,
) -> float:
    return _clamp01(
        0.38 * dump_pressure
        + 0.28 * whale_activity
        + 0.22 * _clamp01(max(0.0, -accum_bias))
        + 0.12 * _clamp01(abs(accum_bias))
    )


def analyze_smart_money(
    symbol: str,
    smart_money_data: Any,
    analysis: Optional[Dict[str, Any]] = None,
    *,
    attach_to_analysis: bool = True,
    half_life_ms: int = 52_000,
    event_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Balina transferleri + kurumsal/VC akışını birleştirir; `phase17` / `faz17` yazar.
    """
    _ = symbol
    a = analysis if analysis is not None else {}
    ts = int(event_ts) if event_ts is not None else _try_ts_ms(a)
    d = _normalize_input(smart_money_data)

    if not d:
        payload = _empty_phase17(ts, half_life_ms, "no_smart_money_data")
        if attach_to_analysis:
            attach_phase_alias(a, "17", payload)
        return payload

    transfers = d.get("whale_transfers") or d.get("large_transfers") or d.get("transfers")
    whale_act, accum_bias, dump_p = _whale_transfer_scores(transfers)

    inst_vc = _institutional_vc_score(d)
    net_ex = _get_num(d, "exchange_netflow_usd", "exchange_net_flow", "net_exchange_flow_usd")
    exch_tag = _exchange_netflow_bias(net_ex)

    signal_hint = str(a.get("signal", "HOLD"))
    alpha_01 = _alpha_smart_money(signal_hint, accum_bias, inst_vc, exch_tag, whale_act)
    risk_01 = _risk_smart_money(dump_p, whale_act, accum_bias)

    wt_ok = 1 if isinstance(transfers, list) and len(transfers) > 0 else 0
    fld_ok = sum(
        1
        for v in (
            net_ex,
            _get_num(d, "etf_net_flow_usd"),
            _get_num(d, "vc_net_flow_usd"),
            _get_num(d, "institutional_flow_usd"),
        )
        if v is not None and v == v
    )
    conf = _clamp01(0.22 + 0.18 * wt_ok + 0.12 * fld_ok + 0.14 * inst_vc)
    dh = _clamp01(0.28 + 0.18 * wt_ok + 0.12 * fld_ok + 0.12 * (1.0 - dump_p))

    perm: TradePermission = "ALLOW"
    if dump_p >= 0.92 and risk_01 >= 0.88:
        perm = "HALT"
    elif risk_01 >= 0.88:
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
        "phase": "17",
        "source": "smart_money_tracker",
        "smart_money": {
            "whale_activity_score": float(whale_act),
            "accumulation_bias": float(accum_bias),
            "dump_to_exchange_pressure": float(dump_p),
            "institutional_vc_score": float(inst_vc),
            "exchange_netflow_usd": net_ex,
            "exchange_flow_bias_01": float(exch_tag),
            "whale_transfer_count": len(transfers) if isinstance(transfers, list) else 0,
        },
    }

    if attach_to_analysis:
        attach_phase_alias(a, "17", payload)

    return payload


def run_smart_money_phase(
    symbol: str,
    smart_money_data: Any,
    analysis: Optional[Dict[str, Any]] = None,
    *,
    attach_to_analysis: bool = True,
    half_life_ms: int = 52_000,
    event_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """Pipeline girişi — `analyze_smart_money` ile aynı."""
    return analyze_smart_money(
        symbol,
        smart_money_data,
        analysis,
        attach_to_analysis=attach_to_analysis,
        half_life_ms=half_life_ms,
        event_ts=event_ts,
    )


def _empty_phase17(ts: int, half_life_ms: int, reason: str) -> Dict[str, Any]:
    return {
        "trade_permission": "BLOCK",
        "alpha_score": 0.0,
        "risk_score": 1.0,
        "confidence": 0.0,
        "data_health": 0.0,
        "event_ts": float(ts),
        "half_life_ms": int(half_life_ms),
        "score_type": "QUALITY",
        "phase": "17",
        "source": "smart_money_tracker",
        "empty_reason": reason,
        "smart_money": {},
    }
