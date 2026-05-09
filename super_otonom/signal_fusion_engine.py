"""Faz 36 — Sinyal birleştirme: analyzer çıktısı + signal_pipeline (AI/ML) zinciri."""
from __future__ import annotations

import time
from typing import Any, Dict, List

from super_otonom.pipelines import signal_pipeline
from super_otonom.standard_phase_output import attach_phase_alias, make_standard_phase_output


def record_analyzer_snapshot(symbol: str, analysis: Dict[str, Any]) -> Dict[str, Any]:
    """
    main_loop / prep sonrası ham analyzer özeti (tick öncesi isteğe bağlı).
    """
    sig = str(analysis.get("signal", "HOLD"))
    conf_hint = float(analysis.get("confidence", 0.55) or 0.55)
    snap = make_standard_phase_output(
        trade_permission="ALLOW",
        alpha_score=conf_hint * 60.0,
        risk_score=40.0,
        confidence=max(0.0, min(1.0, conf_hint)),
        data_health=0.95,
        event_ts=float(time.time() * 1000.0),
        half_life_ms=45_000.0,
        phase="36",
        source="signal_fusion_engine:analyzer_prep",
    )
    snap["prep_signal"] = sig
    snap["symbol"] = symbol
    analysis["phase36_prep"] = snap
    return snap


async def run_signal_fusion_phase(
    engine: Any,
    symbol: str,
    analysis: Dict[str, Any],
    candles: List[Dict[str, float]],
    dctx: Any,
    out: Dict[str, Any],
) -> Dict[str, Any]:
    """
    signal_pipeline.process_signal_phase sarmalayıcısı; phase36 standart çıktı üretir.
    """
    await signal_pipeline.process_signal_phase(
        engine, symbol, analysis, candles, dctx, out
    )
    final = str(out.get("final_signal", "HOLD"))
    conf = float(out.get("ai_confidence") or 0.0)
    perm = "ALLOW" if final in ("BUY", "SELL", "CLOSE_ALL") else "BLOCK"

    snap = make_standard_phase_output(
        trade_permission=perm,
        alpha_score=conf * 100.0,
        risk_score=max(0.0, 100.0 - conf * 100.0),
        confidence=max(0.0, min(1.0, conf)),
        data_health=1.0 if final != "HOLD" or conf > 0 else 0.7,
        event_ts=float(time.time() * 1000.0),
        half_life_ms=45_000.0,
        phase="36",
        source="signal_fusion_engine",
    )
    snap["final_signal"] = final
    attach_phase_alias(analysis, "36", snap)
    return snap
