"""
OMEGA: dinamik rejim (TRENDING, RANGING, CRASH_RISK) + kalite çarpanı + boyut faktörü.
Analyzer rejimi (Hurst) ile ayrı — burada sadece çarpan ve etiket.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Tuple

# Kalite = ham_skor * quality_mult, clamp 0-100
_CRASH_V = float(os.getenv("OMEGA_CRASH_VOL", "0.075") or 0.075)


def compute_omega_regime(
    analysis: Dict[str, Any], base_quality: int
) -> Tuple[str, float, float, int, str]:
    """
    Dönüş: (omega_regime, quality_mult, size_factor, adj_quality, log_line)
    """
    a     = analysis or {}
    reg   = str(a.get("regime", "NOISY") or "NOISY")
    h     = float(a.get("hurst", 0.5) or 0.5)
    vol   = float(a.get("volatility", 0.02) or 0.02)
    flash = bool(a.get("flash_crash"))

    if flash or vol > _CRASH_V:
        oreg = "CRASH_RISK"
        qm   = 0.75
        sf   = 0.35
    elif h > 0.56 and reg == "TRENDING" and vol < 0.05:
        oreg = "TRENDING"
        qm   = 1.05
        sf   = 1.0 if base_quality < 90 else 1.1
    elif reg in ("MEAN_REVERTING", "NOISY") or 0.44 <= h <= 0.58:
        oreg = "RANGING"
        qm   = 0.90
        sf   = 0.70
    else:
        oreg = "TRENDING" if reg == "TRENDING" else "RANGING"
        qm   = 0.95
        sf   = 0.9

    if 40 <= base_quality <= 52 and oreg != "CRASH_RISK":
        sf = min(sf, 0.45)
    if base_quality >= 90 and oreg == "TRENDING" and not flash:
        sf = min(1.15, max(sf, 1.0))

    sf  = max(0.2, min(1.2, float(sf)))
    qm  = max(0.4, min(1.2, float(qm)))
    bq  = int(max(0, min(100, base_quality)))
    adj = int(max(0, min(100, round(bq * qm))))
    log = f"[OMEGA-AI] {oreg} | mult={qm:.2f} adjQ={adj} sizeF={sf:.2f} baseQ={bq}"
    return oreg, qm, sf, adj, log
