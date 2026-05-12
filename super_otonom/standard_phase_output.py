"""Ortak faz çıktı şeması — tüm faz modülleri aynı anahtarları üretir."""

from __future__ import annotations

import time
from typing import Any, Dict

STANDARD_PHASE_KEYS = (
    "trade_permission",
    "alpha_score",
    "risk_score",
    "confidence",
    "data_health",
    "event_ts",
    "half_life_ms",
)


def make_standard_phase_output(
    *,
    trade_permission: str = "ALLOW",
    alpha_score: float = 0.0,
    risk_score: float = 0.0,
    confidence: float = 0.0,
    data_health: float = 1.0,
    event_ts: float | None = None,
    half_life_ms: float = 60_000.0,
    phase: str = "",
    source: str = "",
) -> Dict[str, Any]:
    """
    trade_permission: ALLOW | BLOCK | HALT
    alpha_score / risk_score: 0–100 ölçeği (float)
    confidence / data_health: 0–1
    event_ts: unix ms (varsayılan: şimdi)
    """
    ts = float(time.time() * 1000.0) if event_ts is None else float(event_ts)
    out: Dict[str, Any] = {
        "trade_permission": str(trade_permission).upper(),
        "alpha_score": float(alpha_score),
        "risk_score": float(risk_score),
        "confidence": float(confidence),
        "data_health": float(data_health),
        "event_ts": ts,
        "half_life_ms": float(half_life_ms),
    }
    if phase:
        out["phase"] = phase
    if source:
        out["source"] = source
    return out


def attach_phase_alias(analysis: Dict[str, Any], phase_id: str, payload: Dict[str, Any]) -> None:
    """analysis['phaseNN'] ve analysis['fazNN'] (phase_id='NN')."""
    analysis[f"phase{phase_id}"] = payload
    analysis[f"faz{phase_id}"] = payload
