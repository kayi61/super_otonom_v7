"""Faz 36 — Sinyal birleştirme: çoklu kaynak skoru + signal_pipeline (AI/ML) zinciri."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Tuple

from super_otonom.pipelines import signal_pipeline
from super_otonom.standard_phase_output import attach_phase_alias, make_standard_phase_output

log = logging.getLogger("super_otonom.signal_fusion")

_W_TECH = float(os.getenv("FUSION_WEIGHT_TECHNICAL", "0.40") or 0.40)
_W_ML = float(os.getenv("FUSION_WEIGHT_ML", "0.30") or 0.30)
_W_SENT = float(os.getenv("FUSION_WEIGHT_SENTIMENT", "0.15") or 0.15)
_W_MTF = float(os.getenv("FUSION_WEIGHT_MTF", "0.15") or 0.15)
_SENT_VETO = float(os.getenv("FUSION_SENTIMENT_BUY_VETO", "-0.5") or -0.5)
_FUSION_CONFLICT = float(os.getenv("FUSION_CONFLICT_THRESHOLD", "0.12") or 0.12)


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


def _dir_from_signal(sig: str) -> float:
    s = (sig or "HOLD").upper()
    if s == "BUY":
        return 1.0
    if s == "SELL":
        return -1.0
    return 0.0


def _dir_from_mtf(trend: Any) -> float:
    t = str(trend or "").upper()
    if t == "UP":
        return 1.0
    if t == "DOWN":
        return -1.0
    return 0.0


def _dir_from_ml(analysis: Dict[str, Any]) -> float:
    raw = analysis.get("ml_score")
    if raw is None:
        raw = analysis.get("omega_ml_score")
    if raw is None:
        return 0.0
    try:
        ml = float(raw)
    except (TypeError, ValueError):
        return 0.0
    ml = max(0.0, min(1.0, ml))
    return (ml - 0.5) * 2.0


def _fusion_vector(analysis: Dict[str, Any]) -> Tuple[float, Dict[str, float]]:
    """-1..1 ağırlıklı konsensus skoru + kaynak bileşenleri."""
    tech = _dir_from_signal(str(analysis.get("signal", "HOLD")))
    ml_d = _dir_from_ml(analysis)
    sent = float(analysis.get("sentiment_score", 0.0) or 0.0)
    sent = max(-1.0, min(1.0, sent))
    mtf = _dir_from_mtf(analysis.get("high_tf_trend"))
    wsum = _W_TECH + _W_ML + _W_SENT + _W_MTF
    if wsum <= 0:
        return 0.0, {"tech": tech, "ml": ml_d, "sentiment": sent, "mtf": mtf}
    score = (_W_TECH * tech + _W_ML * ml_d + _W_SENT * sent + _W_MTF * mtf) / wsum
    return max(-1.0, min(1.0, score)), {
        "tech": tech,
        "ml": ml_d,
        "sentiment": sent,
        "mtf": mtf,
        "weights": {"tech": _W_TECH, "ml": _W_ML, "sent": _W_SENT, "mtf": _W_MTF},
    }


def _apply_fusion_to_out(analysis: Dict[str, Any], out: Dict[str, Any]) -> None:
    """AI çıktısından sonra çoklu kaynak uyumu: güven artır / çelişkide HOLD."""
    fscore, sources = _fusion_vector(analysis)
    out["fusion_score"] = round(fscore, 4)
    out["fusion_sources"] = sources
    base_conf = float(out.get("ai_confidence") or 0.0)
    out["fusion_confidence"] = round(base_conf, 4)

    sig_ai = str(out.get("final_signal", "HOLD")).upper()
    sent = float(analysis.get("sentiment_score", 0.0) or 0.0)

    if sig_ai == "BUY" and sent <= _SENT_VETO:
        out["final_signal"] = "HOLD"
        out["decision_reason"] = "FUSION_SENTIMENT_VETO"
        out["fusion_confidence"] = round(max(0.0, base_conf * 0.5), 4)
        log.warning("FUSION | BUY veto | sentiment=%.3f <= %.2f", sent, _SENT_VETO)
        return

    if sig_ai == "BUY" and fscore < _FUSION_CONFLICT:
        out["final_signal"] = "HOLD"
        out["decision_reason"] = "FUSION_CONFLICT"
        out["fusion_confidence"] = round(max(0.0, base_conf * 0.55), 4)
        log.info(
            "FUSION | BUY→HOLD | skor=%.3f < %.2f | kaynak=%s",
            fscore,
            _FUSION_CONFLICT,
            sources,
        )
        return

    if sig_ai in ("BUY", "SELL") and abs(fscore) >= 0.55:
        parts = [sources["tech"], sources["ml"], sources["sentiment"], sources["mtf"]]
        non_zero = [p for p in parts if abs(p) > 0.05]
        if non_zero and all(p * fscore > 0 for p in non_zero):
            boosted = min(0.95, base_conf + 0.06)
            out["ai_confidence"] = boosted
            out["fusion_confidence"] = round(boosted, 4)
            log.debug("FUSION | uyum boost | skor=%.3f conf=%.3f", fscore, boosted)


async def run_signal_fusion_phase(
    engine: Any,
    symbol: str,
    analysis: Dict[str, Any],
    candles: List[Dict[str, float]],
    dctx: Any,
    out: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Önce AI/ML ``process_signal_phase``, ardından teknik+ML+sentiment+MTF füzyon düzeltmesi.
    """
    await signal_pipeline.process_signal_phase(engine, symbol, analysis, candles, dctx, out)
    _apply_fusion_to_out(analysis, out)

    final = str(out.get("final_signal", "HOLD"))
    conf = float(out.get("fusion_confidence") or out.get("ai_confidence") or 0.0)
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
    snap["fusion_score"] = out.get("fusion_score")
    attach_phase_alias(analysis, "36", snap)
    return snap
