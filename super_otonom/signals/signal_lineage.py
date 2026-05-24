"""
PROMPT-A7 — Signal lineage (minimum viable).

Her tick son kararı için zorunlu alanlar: ``phase``, ``reason``, ``scores``,
``event_ts``, ``source_summary`` (+ meta). Kritik yol: ``BotEngine.tick`` çıkışları.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

log = logging.getLogger("super_otonom.signals.signal_lineage")

SCHEMA_VERSION = "a7/v1"


def _f(d: Dict[str, Any], *keys: str) -> Optional[float]:
    for k in keys:
        if k not in d:
            continue
        try:
            return float(d[k])
        except (TypeError, ValueError):
            continue
    return None


def _scores_bundle(out: Dict[str, Any], analysis: Dict[str, Any], dctx: Any) -> Dict[str, Any]:
    """Ana skorlar — anahtarlar her zaman mevcut (değer yoksa ``None``)."""
    p50 = analysis.get("phase50") or analysis.get("faz50")
    if not isinstance(p50, dict):
        p50 = {}
    p80 = out.get("phase80")
    if not isinstance(p80, dict):
        p80 = analysis.get("phase80")
    if not isinstance(p80, dict):
        p80 = {}
    p45 = analysis.get("phase45") or analysis.get("faz45")
    if not isinstance(p45, dict):
        p45 = {}

    ac = out.get("ai_confidence")
    try:
        ai_c = float(ac) if ac is not None else None
    except (TypeError, ValueError):
        ai_c = None

    sq = getattr(dctx, "signal_quality", None) if dctx is not None else None
    adj = getattr(dctx, "adj_signal_quality", None) if dctx is not None else None

    return {
        "ai_confidence": ai_c,
        "phase50_alpha_score": _f(p50, "alpha_score"),
        "phase50_risk_score": _f(p50, "risk_score"),
        "phase50_confidence": _f(p50, "confidence"),
        "phase50_data_health": _f(p50, "data_health"),
        "phase80_alpha_score": _f(p80, "alpha_score"),
        "phase80_risk_score": _f(p80, "risk_score"),
        "phase80_confidence": _f(p80, "confidence"),
        "phase45_alpha_score": _f(p45, "alpha_score"),
        "phase45_risk_score": _f(p45, "risk_score"),
        "signal_quality": int(sq) if sq is not None else None,
        "adj_signal_quality": int(adj) if adj is not None else None,
    }


def _infer_primary_phase(
    completion: str,
    gate: Optional[str],
    out: Dict[str, Any],
    analysis: Dict[str, Any],
) -> int:
    if completion in ("kill", "risk") or gate in ("kill", "risk"):
        return 50
    dr = str(out.get("decision_reason") or "")
    if "LOW_QUALITY" in dr or "LOW_QUALITY_REJECT" in dr:
        return 45
    if out.get("phase80") is not None or out.get("execution_layer") is not None:
        return 80
    if "FAZ80" in dr or "faz80" in dr.lower():
        return 80
    return 0


def _source_summary(
    symbol: str,
    out: Dict[str, Any],
    dctx: Any,
    gate: Optional[str],
    completion: str,
    max_len: int = 300,
) -> str:
    parts = [symbol, f"c={completion}"]
    if gate:
        parts.append(f"g={gate}")
    parts.append(f"sig={out.get('final_signal', 'HOLD')}")
    tp = out.get("trade_permission")
    if tp:
        parts.append(f"tp={tp}")
    fa = out.get("final_action")
    if fa:
        parts.append(f"fa={fa}")
    dr = str(out.get("decision_reason") or "")
    if dr:
        parts.append(f"dr={dr[:100]}")
    if dctx is not None and getattr(dctx, "phase_chain", None):
        keys = [str(k) for k in list(dctx.phase_chain.keys())[:8]]
        if keys:
            parts.append("pc=" + ",".join(keys))
    s = "|".join(str(p) for p in parts)
    return s[:max_len]


def build_signal_lineage(
    *,
    symbol: str,
    tick_id: int,
    out: Dict[str, Any],
    dctx: Any,
    analysis: Dict[str, Any],
    event_ts: float,
    gate: Optional[str],
    completion: str,
) -> Dict[str, Any]:
    """
    ``completion``: ``no_candles`` | ``kill`` | ``risk`` | ``filters`` | ``full``
    """
    phase = _infer_primary_phase(completion, gate, out, analysis)
    reason = str(out.get("decision_reason") or "")
    if not reason and dctx is not None:
        reason = str(
            getattr(dctx, "emergency_code", "") or getattr(dctx, "entry_blocked", "") or ""
        )

    payload: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "symbol": symbol,
        "tick_id": int(tick_id),
        "phase": int(phase),
        "reason": reason,
        "scores": _scores_bundle(out, analysis, dctx),
        "event_ts": float(event_ts),
        "source_summary": _source_summary(symbol, out, dctx, gate, completion),
        "gate": gate,
        "completion": completion,
        "final_signal": str(out.get("final_signal", "HOLD")),
        "trade_permission": out.get("trade_permission"),
    }
    return payload


def log_signal_lineage(payload: Dict[str, Any]) -> None:
    """Tek satır yapılandırılmış log (JSON)."""
    try:
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        line = str(payload)
    log.info("SIGNAL_LINEAGE_JSON %s", line)
