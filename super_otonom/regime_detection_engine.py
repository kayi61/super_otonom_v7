"""Faz 26 — Piyasa rejimi: compute_omega_regime ince sarmalayıcı."""

from __future__ import annotations

from typing import Any, Dict, Tuple

from super_otonom.standard_phase_output import attach_phase_alias, make_standard_phase_output


def run_regime_detection_phase(
    analysis: Dict[str, Any],
    base_quality: int,
    *,
    event_ts: float | None = None,
) -> Tuple[Dict[str, Any], Tuple[str, float, float, int, str]]:
    """
    Omega rejim motorunu çalıştırır; phase26 / faz26 yazar.
    bot_engine.compute_omega_regime kullanılır (test patch uyumu).
    Dönüş: (standart çıktı, compute_omega_regime ham tuple)
    """
    import super_otonom.bot_engine as be_mod

    oreg, qm, sf, adj, omlog = be_mod.compute_omega_regime(analysis, int(base_quality))

    if str(oreg) == "CRASH_RISK":
        perm = "BLOCK"
    else:
        perm = "ALLOW"

    risk_from_reg = 75.0 if oreg == "CRASH_RISK" else (40.0 if oreg == "RANGING" else 25.0)
    snap = make_standard_phase_output(
        trade_permission=perm,
        alpha_score=float(adj),
        risk_score=risk_from_reg,
        confidence=min(1.0, float(qm)),
        data_health=0.7 if oreg == "CRASH_RISK" else 1.0,
        event_ts=event_ts,
        half_life_ms=120_000.0,
        phase="26",
        source="regime_detection_engine",
    )
    snap["omega_regime"] = str(oreg)
    snap["quality_mult"] = float(qm)
    snap["size_factor"] = float(sf)
    snap["log_line"] = str(omlog)

    attach_phase_alias(analysis, "26", snap)
    return snap, (oreg, qm, sf, adj, omlog)
