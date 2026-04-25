"""
AI-Ready Gateway: dış ML tahminini (inference) mevcut güven skoru ile birleştirir.

analysis içinde (isteğe bağlı)::
  - ml_score, omega_ml_score: 0.0-1.0 sınıf veya kazanma olasılığı
  - ml_confidence, omega_ml_confidence: 0-1 açık güven
Env: OMEGA_ML_BLEND (varsayılan 0.35) — harici model ağırlığı.
Mevcut AILayer.model_path akışı değişmez; bu köprü ek bir besleme kanalıdır.

Öncelik: `ml_client.MLClient.enrich_analysis` tick içinde `analysis['ml_score']` doldurur;
yoksa burada no_external_ml kalır.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Tuple

from super_otonom.ml_client import format_ml_inference_payload

_BLEND = float(os.getenv("OMEGA_ML_BLEND", "0.35") or 0.35)
_BLEND = max(0.0, min(0.8, _BLEND))

__all__ = ("blend_omega_confidence", "format_ml_inference_payload", "_BLEND")


def blend_omega_confidence(base_confidence: float, analysis: Dict[str, Any]) -> Tuple[float, str]:
    """
    Dış ML skoru yoksa base aynen döner.
    Dönüş: (birleşik 0-1, kısa not: bridge_ok|no_ml|...)
    """
    a = analysis or {}
    raw = a.get("ml_score")
    if raw is None:
        raw = a.get("omega_ml_score")
    if raw is None:
        raw = a.get("ml_confidence")
    if raw is None:
        raw = a.get("omega_ml_confidence")

    if raw is None:
        return max(0.0, min(1.0, float(base_confidence))), "no_external_ml"

    try:
        ml = float(raw)
    except (TypeError, ValueError):
        return max(0.0, min(1.0, float(base_confidence))), "ml_score_invalid"

    ml = max(0.0, min(1.0, ml))
    b  = max(0.0, min(1.0, float(base_confidence)))
    merged = (1.0 - _BLEND) * b + _BLEND * ml
    return round(merged, 4), f"ml_fusion w={_BLEND:.2f}"
