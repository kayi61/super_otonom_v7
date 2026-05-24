"""v8 — Sinyal işleme: ML zenginleştirme + AI doğrulama + omega blend."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

from super_otonom.ai_confidence_bridge import blend_omega_confidence
from super_otonom.config import RISK
from super_otonom.decision_context import DecisionStage
from super_otonom.ml_prediction import run_ml_enrichment_phase

from .risk_pipeline import force_all_close_requested

log = logging.getLogger("super_otonom.pipelines.signal")


def _min_entry_confidence() -> float:
    try:
        v = float(
            os.getenv(
                "ENTRY_MIN_CONFIDENCE",
                str(RISK.get("entry_min_confidence", 0.55)),
            )
            or 0.55
        )
    except ValueError:
        v = 0.55
    return max(0.45, min(0.95, v))


async def process_signal_phase(
    engine: Any,
    symbol: str,
    analysis: Dict[str, Any],
    candles: List[Dict[str, float]],
    dctx: Any,
    out: Dict[str, Any],
) -> None:
    """
    AI buffer, dış ML, validate_signal, omega blend, ai.explain.
    out / dctx güncellenir.
    """
    engine.ai.update_buffer(symbol, candles[-1], analysis)
    await run_ml_enrichment_phase(symbol, analysis, dctx, tick_id=dctx.tick_id)
    base = analysis.get("signal", "HOLD")

    if analysis.get("execution_mode") == "TREND_FOLLOW":
        final = base
        conf = max(_min_entry_confidence(), 0.55)
        reason = "TREND_FOLLOW_OVERRIDE"
    else:
        result_tuple = engine.ai.validate_signal(symbol, base, analysis)
        if len(result_tuple) == 3:
            final, conf, reason = result_tuple
        else:
            final, conf = result_tuple
            reason = ""

    conf, _oml_b = blend_omega_confidence(float(conf or 0.0), analysis)
    analysis["omega_ml_bridge"] = _oml_b

    out["ai_confidence"] = conf
    out["final_signal"] = final
    out["decision_reason"] = reason
    dctx.after_ai_signal = str(final)
    dctx.ai_confidence = float(conf) if conf is not None else None
    dctx.add_trace(DecisionStage.AI.value, reason or "ok")

    why = engine.ai.explain(
        symbol, str(base), analysis, str(final), float(conf or 0.0), str(reason)
    )
    dctx.ai_explain = why
    out["ai_explain"] = why
    log.info("AI_EXPLAIN | %s | %s", symbol, why)

    if force_all_close_requested():
        if symbol in engine.open_positions:
            out["final_signal"] = "CLOSE_ALL"
            out["decision_reason"] = "FORCE_ALL_CLOSE"
            dctx.after_ai_signal = "CLOSE_ALL"
            dctx.add_trace("force_all_close", "open_position_flatten")
            log.warning("FORCE_ALL_CLOSE | %s | flatten", symbol)
        else:
            out["final_signal"] = "HOLD"
            out["decision_reason"] = "FORCE_ALL_CLOSE_NO_NEW"
            dctx.after_ai_signal = "HOLD"
            dctx.add_trace("force_all_close", "skip_new_entries")


async def apply_filters_phase(
    engine: Any,
    symbol: str,
    analysis: Dict[str, Any],
    price: float,
    dctx: Any,
    out: Dict[str, Any],
) -> bool:
    """
    Sentiment veto (+ erken çıkış) ve elite kalite filtresi.
    True: devam; False: tick sonlandı (out güncel).
    """
    final = out["final_signal"]

    if final in ("BUY", "SELL"):
        sentiment = engine.sentiment_layer.get_market_sentiment()
        out["sentiment_status"] = sentiment.get("status", "NEUTRAL")

        final, sent_reason = engine.sentiment_layer.validate_with_sentiment(final, sentiment)

        if final == "HOLD":
            dctx.after_sentiment_signal = "HOLD"
            dctx.add_trace(DecisionStage.SENTIMENT.value, sent_reason)
            out["final_signal"] = "HOLD"
            out["decision_reason"] = sent_reason
            dctx.final_signal = "HOLD"
            dctx.decision_reason = sent_reason
            out["decision_context"] = dctx.to_dict()
            log.info("SENTIMENT_VETO | symbol=%s | %s", symbol, sent_reason)
            if symbol in engine.open_positions:
                await engine._handle_exit(symbol, price, "HOLD", out, analysis)
            engine.metrics.update(engine.status())
            engine.metrics.record_analysis(analysis)
            return False
        out["final_signal"] = final
        dctx.after_sentiment_signal = str(final)
        dctx.add_trace(DecisionStage.SENTIMENT.value, "ok")
    else:
        out["sentiment_status"] = "N/A"
        dctx.after_sentiment_signal = str(out["final_signal"])

    from super_otonom.signals.unified_alpha_core import run_unified_alpha_phase

    run_unified_alpha_phase(engine, symbol, analysis, out, dctx)

    return True
