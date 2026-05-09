"""
Faz 38 — Çok fazlı karar katkı özeti; Telegram /explain metni.

Sadece NumPy.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Literal, Tuple

import numpy as np

_EPS = 1e-12
_HALF_LIFE_MS = 60_000

TradePermission = Literal["ALLOW", "BLOCK", "HALT"]
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


def weighted_mean(values: np.ndarray, weights: np.ndarray) -> float:
    """Ağırlıklı ortalama; tüm ağırlıklar 0 ise aritmetik ortalama."""
    v = np.asarray(values, dtype=float).ravel()
    w = np.maximum(np.asarray(weights, dtype=float).ravel(), 0.0)
    if v.size == 0:
        return 0.0
    sw = float(np.sum(w))
    if sw < _EPS:
        return float(np.mean(v))
    return float(np.sum(v * w) / sw)


def validate_market_data(data: Any) -> Tuple[bool, str]:
    if data is None or not isinstance(data, dict):
        return False, "market_data_missing_or_invalid"

    if "phase_outputs" not in data or "final_decision" not in data:
        return False, "missing_required_keys"

    po = data["phase_outputs"]
    if not isinstance(po, list) or len(po) == 0:
        return False, "phase_outputs_empty"

    fd = data["final_decision"]
    if str(fd).upper() not in ("ENTER", "WAIT", "EXIT", "HEDGE", "HALT"):
        return False, "final_decision_invalid"

    required = ("phase", "alpha_score", "risk_score", "trade_permission", "confidence", "score_type")
    for item in po:
        if not isinstance(item, dict):
            return False, "phase_output_not_dict"
        for k in required:
            if k not in item:
                return False, f"missing_field:{k}"

    return True, ""


def _normalize_permission(p: Any) -> str:
    s = str(p).strip().upper()
    if s in ("ALLOW", "BLOCK", "HALT"):
        return s
    return "ALLOW"


def compute_contributions(
    phase_outputs: List[Dict[str, Any]],
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """phase id, katkı (α×conf), risk×conf (blocker), alpha, risk ham, conf."""
    phases: List[int] = []
    kontrib: List[float] = []
    risk_weighted: List[float] = []
    alphas: List[float] = []
    risks_raw: List[float] = []
    confs: List[float] = []

    for item in phase_outputs:
        try:
            ph = int(item["phase"])
            a = float(item["alpha_score"])
            r = float(item["risk_score"])
            c = float(item["confidence"])
        except (KeyError, TypeError, ValueError):
            continue
        c = float(np.clip(c, 0.0, 1.0))
        a = float(np.clip(a, 0.0, 1.0))
        r = float(np.clip(r, 0.0, 1.0))
        phases.append(ph)
        kontrib.append(a * c)
        risk_weighted.append(r * c)
        alphas.append(a)
        risks_raw.append(r)
        confs.append(c)

    return (
        np.asarray(phases, dtype=int),
        np.asarray(kontrib, dtype=float),
        np.asarray(risk_weighted, dtype=float),
        np.asarray(alphas, dtype=float),
        np.asarray(risks_raw, dtype=float),
        np.asarray(confs, dtype=float),
    )


def build_top_contributors(phases: np.ndarray, kontrib: np.ndarray, k: int = 5) -> List[Dict[str, Any]]:
    if phases.size == 0:
        return []
    order = np.argsort(-kontrib)
    out: List[Dict[str, Any]] = []
    for idx in order[:k]:
        out.append({"phase": int(phases[idx]), "score": float(kontrib[idx])})
    return out


def build_top_blockers(phases: np.ndarray, risk_weighted: np.ndarray, k: int = 3) -> List[Dict[str, Any]]:
    if phases.size == 0:
        return []
    order = np.argsort(-risk_weighted)
    out: List[Dict[str, Any]] = []
    for idx in order[:k]:
        out.append({"phase": int(phases[idx]), "score": float(risk_weighted[idx])})
    return out


def build_explain_text(
    final_decision: str,
    allow_count: int,
    block_count: int,
    halt_count: int,
    top_contributors: List[Dict[str, Any]],
    top_blockers: List[Dict[str, Any]],
) -> str:
    tc = top_contributors[0] if top_contributors else {"phase": "—", "score": 0.0}
    tb = top_blockers[0] if top_blockers else {"phase": "—", "score": 0.0}
    ph_tc = tc["phase"]
    ph_tb = tb["phase"]
    sc_tc = float(tc["score"]) if isinstance(tc["score"], (int, float)) else 0.0
    sc_tb = float(tb["score"]) if isinstance(tb["score"], (int, float)) else 0.0
    return (
        f"Karar: {final_decision} | {allow_count}✅ {block_count}🚫 {halt_count}🛑 | "
        f"Top katkı: Faz {ph_tc}({sc_tc:.2f}) | "
        f"Top risk: Faz {ph_tb}({sc_tb:.2f})"
    )


def analyze(market_data: dict | None) -> dict:
    """Faz katkı özeti ve /explain metni — Faz 38 standart payload."""
    ts = _now_ms()
    empty: Dict[str, Any] = {}

    ok, err = validate_market_data(market_data)
    if not ok:
        return {
            "phase": 38,
            "module": "trade_explainability",
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
    po = d["phase_outputs"]
    final_decision = str(d["final_decision"]).strip().upper()

    allow_count = sum(1 for x in po if _normalize_permission(x.get("trade_permission")) == "ALLOW")
    block_count = sum(1 for x in po if _normalize_permission(x.get("trade_permission")) == "BLOCK")
    halt_count = sum(1 for x in po if _normalize_permission(x.get("trade_permission")) == "HALT")

    n = len(po)
    consensus_ratio = allow_count / max(n, 1)

    phases, kontrib, risk_w, alphas, risks_raw, confs = compute_contributions(po)

    if phases.size == 0:
        payload = {
            "phase": 38,
            "module": "trade_explainability",
            "trade_permission": "BLOCK",
            "alpha_score": 0.0,
            "risk_score": 1.0,
            "score_type": "QUALITY",
            "confidence": 0.0,
            "data_health": 0.0,
            "event_ts": ts,
            "half_life_ms": _HALF_LIFE_MS,
            "analysis": empty,
            "reason": "no_parseable_phase_outputs",
        }
        return payload

    avg_alpha = weighted_mean(alphas, confs)
    avg_risk = weighted_mean(risks_raw, confs)

    top_contributors = build_top_contributors(phases, kontrib, 5)
    top_blockers = build_top_blockers(phases, risk_w, 3)

    explain_text = build_explain_text(
        final_decision,
        allow_count,
        block_count,
        halt_count,
        top_contributors,
        top_blockers,
    )

    alpha_score = _clip01(avg_alpha)
    risk_score = _clip01(avg_risk)

    data_health = float(np.clip(n / 35.0, 0.1, 1.0))
    out_confidence = _clip01(data_health * consensus_ratio)

    score_type = _pick_score_type(data_health, risk_score)

    trade_permission: TradePermission = "ALLOW"
    reason = "consensus_allow"

    if halt_count > 0:
        trade_permission = "HALT"
        reason = "halt_phase_present"
    elif block_count > n * 0.3:
        trade_permission = "BLOCK"
        reason = "block_minority_exceeded"

    nested = {
        "top_contributors": top_contributors,
        "top_blockers": top_blockers,
        "allow_count": int(allow_count),
        "block_count": int(block_count),
        "halt_count": int(halt_count),
        "consensus_ratio": float(consensus_ratio),
        "explain_text": explain_text,
    }

    return {
        "phase": 38,
        "module": "trade_explainability",
        "trade_permission": trade_permission,
        "alpha_score": alpha_score,
        "risk_score": risk_score,
        "score_type": score_type,
        "confidence": out_confidence,
        "data_health": data_health,
        "event_ts": ts,
        "half_life_ms": _HALF_LIFE_MS,
        "analysis": nested,
        "reason": reason,
    }
