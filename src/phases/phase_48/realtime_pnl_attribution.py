"""
Faz 48 — Gerçek zamanlı P&L attribution: faz katkısı, ablation, benchmark karşılaştırması.

Sadece NumPy.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple

import numpy as np

_HALF_LIFE_MS = 30_000
_DEFAULT_ROLLING = 20


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


def _weighted_pnl(rec: Dict[str, Any]) -> float:
    return float(rec["pnl"]) * float(rec["weight"])


def validate_market_data(data: Any) -> Tuple[bool, str]:
    if data is None or not isinstance(data, dict):
        return False, "market_data_missing_or_invalid"

    if "phase_pnl_records" not in data or not isinstance(data["phase_pnl_records"], list):
        return False, "phase_pnl_records_invalid"

    recs: List[Any] = data["phase_pnl_records"]
    if len(recs) == 0:
        return False, "phase_pnl_records_empty"

    for i, r in enumerate(recs):
        if not isinstance(r, dict):
            return False, f"record_not_dict:{i}"
        for k in ("phase", "pnl", "enabled", "weight"):
            if k not in r:
                return False, f"missing_field:{k}:{i}"
        try:
            int(r["phase"])
            float(r["pnl"])
            float(r["weight"])
        except (TypeError, ValueError):
            return False, f"numeric_parse_error:{i}"
        if not isinstance(r["enabled"], bool):
            return False, f"enabled_not_bool:{i}"
        w = float(r["weight"])
        if w < 0.0 or w > 1.0:
            return False, f"weight_out_of_range:{i}"

    if "total_pnl" not in data or "benchmark_pnl" not in data:
        return False, "missing_pnl_fields"
    try:
        float(data["total_pnl"])
        float(data["benchmark_pnl"])
    except (TypeError, ValueError):
        return False, "pnl_numeric_parse_error"

    rw = data.get("rolling_window", _DEFAULT_ROLLING)
    try:
        ri = int(rw)
    except (TypeError, ValueError):
        return False, "rolling_window_invalid"
    if ri < 1:
        return False, "rolling_window_too_small"

    return True, ""


def _apply_rolling(records: List[dict], rolling_window: int) -> List[dict]:
    if len(records) <= rolling_window:
        return list(records)
    return list(records[-rolling_window:])


def analyze(market_data: dict | None) -> dict:
    """Gerçek zamanlı P&L attribution — Faz 48 standart payload."""
    ts = _now_ms()
    empty: Dict[str, Any] = {}

    ok, err = validate_market_data(market_data)
    if not ok:
        return {
            "phase": 48,
            "module": "realtime_pnl_attribution",
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

    rolling_window = int(d.get("rolling_window", _DEFAULT_ROLLING))
    raw_records = [dict(x) for x in d["phase_pnl_records"]]
    raw_len = len(raw_records)
    records = _apply_rolling(raw_records, rolling_window)

    total_pnl = float(d["total_pnl"])
    benchmark_pnl = float(d["benchmark_pnl"])

    enabled_records = [r for r in records if bool(r["enabled"])]
    enabled_count = sum(1 for r in records if bool(r["enabled"]))
    disabled_count = len(records) - enabled_count

    attributed_pnl = float(
        sum(_weighted_pnl(r) for r in enabled_records)
    )
    denom_total = max(abs(total_pnl), 1e-9)
    attribution_ratio = attributed_pnl / denom_total

    # Rank enabled phases by weighted PnL
    contrib_rows: List[Tuple[int, float]] = []
    for r in enabled_records:
        wpnl = _weighted_pnl(r)
        contrib_rows.append((int(r["phase"]), wpnl))

    contrib_rows.sort(key=lambda x: x[1], reverse=True)
    top_contributors = [
        {"phase": ph, "contribution": float(c)} for ph, c in contrib_rows[:5]
    ]

    # En düşük weighted PnL (en kötü katkı); negatifler doğal olarak önce gelir
    contrib_rows.sort(key=lambda x: x[1])
    top_detractors = [
        {"phase": ph, "contribution": float(c)} for ph, c in contrib_rows[:3]
    ]

    ablation_coverage = enabled_count / max(len(records), 1)

    excess_return = total_pnl - benchmark_pnl
    bench_denom = max(abs(benchmark_pnl), 1e-9)
    raw_alpha_vs = (excess_return / bench_denom + 1.0) / 2.0
    alpha_vs_bench = _clip01(raw_alpha_vs)

    attribution_ratio_clipped = _clip01((attribution_ratio + 1.0) / 2.0)

    alpha_score = _clip01(
        0.5 * float(alpha_vs_bench)
        + 0.3 * float(attribution_ratio_clipped)
        + 0.2 * float(ablation_coverage)
    )
    risk_score = _clip01(1.0 - alpha_score)

    if excess_return < 0.0:
        risk_score = _clip01(risk_score + 0.10)
        alpha_score = _clip01(1.0 - risk_score)

    data_health = float(np.clip(raw_len / 45.0, 0.1, 1.0))
    confidence = float(data_health * ablation_coverage)

    score_type = _pick_score_type(data_health, risk_score)

    metrics = {
        "super_otonom_total_pnl": float(total_pnl),
        "super_otonom_attributed_pnl": float(attributed_pnl),
        "super_otonom_alpha_vs_bench": float(alpha_vs_bench),
        "super_otonom_enabled_phases": int(enabled_count),
    }

    nested = {
        "attributed_pnl": float(attributed_pnl),
        "attribution_ratio": float(attribution_ratio),
        "top_contributors": top_contributors,
        "top_detractors": top_detractors,
        "ablation_coverage": float(ablation_coverage),
        "enabled_count": int(enabled_count),
        "disabled_count": int(disabled_count),
        "alpha_vs_bench": float(alpha_vs_bench),
        "excess_return": float(excess_return),
        "metrics": metrics,
    }

    return {
        "phase": 48,
        "module": "realtime_pnl_attribution",
        "trade_permission": "ALLOW",
        "alpha_score": alpha_score,
        "risk_score": risk_score,
        "score_type": score_type,
        "confidence": confidence,
        "data_health": data_health,
        "event_ts": ts,
        "half_life_ms": _HALF_LIFE_MS,
        "analysis": nested,
        "reason": "pnl_attribution_ok",
    }
