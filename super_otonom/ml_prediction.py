"""Faz 19 — ML tahmin: ml_client.enrich_analysis ince sarmalayıcı."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Dict, Optional

from super_otonom.ml_client import get_ml_client
from super_otonom.standard_phase_output import attach_phase_alias, make_standard_phase_output

if TYPE_CHECKING:
    from super_otonom.decision_context import DecisionContext


async def run_ml_enrichment_phase(
    symbol: str,
    analysis: Dict[str, Any],
    dctx: Optional["DecisionContext"] = None,
    *,
    tick_id: int = 0,
) -> Dict[str, Any]:
    """
    Dış ML servisini çağırır; analysis güncellenir; standart faz 19 çıktısı döner.
    """
    t0 = time.perf_counter()
    await get_ml_client().enrich_analysis(symbol, analysis, dctx, tick_id=tick_id)
    lat_ms = (time.perf_counter() - t0) * 1000.0

    ml = analysis.get("ml_score")
    conf = float(ml) if ml is not None else 0.0
    conf = max(0.0, min(1.0, conf))
    dh = (
        1.0
        if ml is not None and analysis.get("external_ai_latency_ms") is not None
        else (0.85 if ml is not None else 0.75)
    )
    perm = "ALLOW"

    snap = make_standard_phase_output(
        trade_permission=perm,
        alpha_score=conf * 100.0,
        risk_score=max(0.0, 100.0 - conf * 100.0),
        confidence=conf,
        data_health=float(dh),
        half_life_ms=60_000.0,
        phase="19",
        source="ml_prediction",
    )
    snap["latency_ms"] = float(lat_ms)
    attach_phase_alias(analysis, "19", snap)
    return snap
