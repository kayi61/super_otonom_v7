"""
Faz 55 — Meta piyasa zekası: faz 41–54 çıktılarını bileştirir.

Sadece NumPy.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np

_HALF_LIFE_MS = 10_000
_EPS = 1e-12
_WHALE_MM_PHASES = frozenset({41, 42, 51, 54})
_EXPECTED_PHASE_COUNT = 14


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


def weighted_mean(values: Sequence[float], weights: Sequence[float]) -> float:
    """Ağırlıklı ortalama; ağırlık toplamı ~0 ise aritmetik ortalama."""
    v = np.asarray(values, dtype=float).ravel()
    w = np.asarray(weights, dtype=float).ravel()
    if v.size == 0:
        return 0.0
    if v.size != w.size:
        raise ValueError("values and weights length mismatch")
    sw = float(np.sum(w))
    if sw <= _EPS:
        return float(np.mean(v))
    return float(np.sum(v * w) / sw)


def validate_market_data(data: Any) -> Tuple[bool, str]:
    if data is None or not isinstance(data, dict):
        return False, "market_data_missing_or_invalid"

    if "phase_outputs" not in data or not isinstance(data["phase_outputs"], list):
        return False, "phase_outputs_invalid"

    if len(data["phase_outputs"]) == 0:
        return False, "phase_outputs_empty"

    req = ("phase", "alpha_score", "risk_score", "trade_permission", "confidence", "score_type")
    for i, p in enumerate(data["phase_outputs"]):
        if not isinstance(p, dict):
            return False, f"phase_output_not_dict:{i}"
        for k in req:
            if k not in p:
                return False, f"missing_field:{k}:{i}"
        try:
            int(p["phase"])
            float(p["alpha_score"])
            float(p["risk_score"])
            float(p["confidence"])
        except (TypeError, ValueError):
            return False, f"numeric_parse_error:{i}"
        tp = p["trade_permission"]
        if tp not in ("ALLOW", "BLOCK", "HALT"):
            return False, f"trade_permission_invalid:{i}"
        if not isinstance(p["score_type"], str):
            return False, f"score_type_not_str:{i}"

    return True, ""


def analyze(market_data: dict | None) -> dict:
    """Meta piyasa analizi — Faz 55 standart payload."""
    ts = _now_ms()
    empty: Dict[str, Any] = {}

    ok, err = validate_market_data(market_data)
    if not ok:
        return {
            "phase": 55,
            "module": "meta_market_intelligence",
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
    outputs: List[dict] = list(market_data["phase_outputs"])
    n = len(outputs)

    whale_mm = [p for p in outputs if int(p["phase"]) in _WHALE_MM_PHASES]
    if whale_mm:
        wa = [float(x["alpha_score"]) for x in whale_mm]
        wr = [float(x["risk_score"]) for x in whale_mm]
        wc = [float(x["confidence"]) for x in whale_mm]
        whale_mm_alpha = weighted_mean(wa, wc)
        whale_mm_risk = weighted_mean(wr, wc)
    else:
        whale_mm_alpha = 0.5
        whale_mm_risk = 0.5

    whale_mm_composite = float(
        0.6 * whale_mm_alpha + 0.4 * (1.0 - whale_mm_risk)
    )

    allow_phases = [p for p in outputs if p["trade_permission"] == "ALLOW"]
    block_phases = [p for p in outputs if p["trade_permission"] == "BLOCK"]
    halt_phases = [p for p in outputs if p["trade_permission"] == "HALT"]

    allow_count = len(allow_phases)
    block_count = len(block_phases)
    halt_count = len(halt_phases)

    synergy_score = float(allow_count / max(n, 1))
    synergy_amplifier = _clip01(synergy_score * 1.2)

    confs = np.asarray([float(p["confidence"]) for p in outputs], dtype=float)
    avg_confidence = float(np.mean(confs))
    high_conf_count = int(np.sum(confs > 0.7))
    high_confidence_ratio = float(high_conf_count / max(n, 1))
    entry_timing_score = float(
        0.5 * avg_confidence + 0.5 * high_confidence_ratio
    )

    alpha_score = _clip01(
        0.40 * whale_mm_composite
        + 0.35 * synergy_amplifier
        + 0.25 * entry_timing_score
    )

    all_risks = [float(p["risk_score"]) for p in outputs]
    all_w = [float(p["confidence"]) for p in outputs]
    risk_score = _clip01(weighted_mean(all_risks, all_w))

    data_health = float(np.clip(n / float(_EXPECTED_PHASE_COUNT), 0.1, 1.0))
    top_confidence = float(data_health * entry_timing_score)

    score_type = _pick_score_type(data_health, risk_score)

    nested = {
        "whale_mm_composite": float(whale_mm_composite),
        "whale_mm_alpha": float(whale_mm_alpha),
        "whale_mm_risk": float(whale_mm_risk),
        "synergy_score": float(synergy_score),
        "synergy_amplifier": float(synergy_amplifier),
        "entry_timing_score": float(entry_timing_score),
        "avg_confidence": float(avg_confidence),
        "high_confidence_ratio": float(high_confidence_ratio),
        "allow_count": int(allow_count),
        "block_count": int(block_count),
        "halt_count": int(halt_count),
    }

    trade_permission: str = "ALLOW"
    reason = "meta_market_ok"

    if halt_count > 0:
        trade_permission = "HALT"
        reason = "phase_halt_override"
    elif block_count > n * 0.3:
        trade_permission = "BLOCK"
        reason = "block_majority"
    else:
        trade_permission = "ALLOW"
        reason = "meta_market_ok"

    return {
        "phase": 55,
        "module": "meta_market_intelligence",
        "trade_permission": trade_permission,
        "alpha_score": alpha_score,
        "risk_score": risk_score,
        "score_type": score_type,
        "confidence": top_confidence,
        "data_health": data_health,
        "event_ts": ts,
        "half_life_ms": _HALF_LIFE_MS,
        "analysis": nested,
        "reason": reason,
    }
