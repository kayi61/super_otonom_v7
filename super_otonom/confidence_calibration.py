"""
PROMPT-A6 — Aynı tick kök verisinden beslenen faz çıktıları için minimal güven kalibrasyonu.

Aşırı iddia yok: aynı ``family`` içinde birden fazla ``yüksek`` confidence varsa
basit ceza çarpanı; isteğe bağlı medyan üst sınır (MVP).

Env (opsiyonel)::
  CALIB_HIGH_THRESHOLD — varsayılan 0.72
  CALIB_PENALTY_PER_REDUNDANT — varsayılan 0.065
  CALIB_FLOOR_MULT — varsayılan 0.82 (minimum çarpan)
  CALIB_MEDIAN_CAP_MARGIN — varsayılan 0.08 (faz medyanı + margin tavan)
"""

from __future__ import annotations

import os
import re
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

__all__ = (
    "phase_key_to_int",
    "family_for_phase_num",
    "calibrate_confidence_mvp",
)

_HIGH = float(os.getenv("CALIB_HIGH_THRESHOLD", "0.72") or 0.72)
_PEN = float(os.getenv("CALIB_PENALTY_PER_REDUNDANT", "0.065") or 0.065)
_FLOOR = float(os.getenv("CALIB_FLOOR_MULT", "0.82") or 0.82)
_MED_M = float(os.getenv("CALIB_MEDIAN_CAP_MARGIN", "0.08") or 0.08)

_HIGH = max(0.5, min(0.95, _HIGH))
_PEN = max(0.0, min(0.2, _PEN))
_FLOOR = max(0.5, min(1.0, _FLOOR))
_MED_M = max(0.0, min(0.25, _MED_M))


def phase_key_to_int(key: str) -> Optional[int]:
    k = str(key).strip().lower()
    for prefix in ("faz", "phase"):
        if k.startswith(prefix):
            tail = k[len(prefix) :]
            if tail.isdigit():
                return int(tail)
    m = re.search(r"(\d{2,3})$", k)
    if m:
        return int(m.group(1))
    return None


def family_for_phase_num(phase_num: int) -> str:
    """Aynı OHLC / tick bağlamından türeyen modüller için kaba aile."""
    if 66 <= phase_num <= 70:
        return "gov"
    if 71 <= phase_num <= 75:
        return "micro"
    if phase_num == 47 or 76 <= phase_num <= 80:
        return "exec"
    return "other"


def _confidence_from_blob(blob: Any) -> Optional[float]:
    if not isinstance(blob, dict):
        return None
    for k in ("confidence", "data_confidence"):
        if k not in blob:
            continue
        try:
            return float(blob[k])
        except (TypeError, ValueError):
            return None
    return None


def _gather_rows(phase_chain: Dict[str, Any]) -> List[Tuple[str, int, str, float]]:
    rows: List[Tuple[str, int, str, float]] = []
    if not isinstance(phase_chain, dict):
        return rows
    for key, blob in phase_chain.items():
        c = _confidence_from_blob(blob)
        if c is None:
            continue
        c = max(0.0, min(1.0, c))
        pid = phase_key_to_int(str(key))
        if pid is None:
            fam = "other"
        else:
            fam = family_for_phase_num(pid)
        rows.append((str(key), pid if pid is not None else -1, fam, c))
    return rows


def calibrate_confidence_mvp(
    base_confidence: float,
    phase_chain: Dict[str, Any],
) -> Tuple[float, Dict[str, Any]]:
    """
    Dönüş: (kalibre güven 0..1, meta — log / analysis için).
    """
    base = max(0.0, min(1.0, float(base_confidence)))
    rows = _gather_rows(phase_chain)
    if not rows:
        return base, {
            "schema": "a6/v1",
            "applied": False,
            "reason": "no_phase_confidence",
            "base": round(base, 4),
            "calibrated": round(base, 4),
        }

    confs = [r[3] for r in rows]
    highs = [r for r in rows if r[3] >= _HIGH]
    per_fam: Dict[str, int] = {}
    for _k, _pid, fam, c in highs:
        if c >= _HIGH:
            per_fam[fam] = per_fam.get(fam, 0) + 1

    redundant = sum(max(0, n - 1) for n in per_fam.values())
    mult = max(_FLOOR, 1.0 - _PEN * float(redundant))
    calibrated = base * mult

    med = median(confs)
    soft_cap = min(0.95, med + _MED_M)
    if redundant > 0:
        calibrated = min(calibrated, soft_cap)

    out = max(0.0, min(1.0, float(calibrated)))
    meta = {
        "schema": "a6/v1",
        "applied": redundant > 0 or (out < base - 1e-6),
        "base": round(base, 4),
        "calibrated": round(out, 4),
        "high_threshold": _HIGH,
        "penalty_per_redundant": _PEN,
        "floor_mult": _FLOOR,
        "redundant_high_by_family": {k: int(v) for k, v in sorted(per_fam.items())},
        "redundant_count": int(redundant),
        "mult": round(mult, 4),
        "phase_median": round(med, 4),
        "soft_cap": round(soft_cap, 4) if redundant > 0 else None,
        "n_phase_scores": len(rows),
        "summary": f"redundant={redundant} mult={mult:.3f}",
    }
    return out, meta
