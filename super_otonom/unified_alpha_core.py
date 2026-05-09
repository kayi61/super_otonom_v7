"""Faz 45 — Alpha / decay / omega yığını: kalite skoru + omega + decay izi."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional, Tuple

from super_otonom.alpha_decay_realtime_monitor import monitor_alpha_decay
from super_otonom.config import RISK
from super_otonom.regime_detection_engine import run_regime_detection_phase
from super_otonom.standard_phase_output import attach_phase_alias, make_standard_phase_output

log = logging.getLogger("super_otonom.unified_alpha_core")


def run_unified_alpha_phase(
    engine: Any,
    symbol: str,
    analysis: Dict[str, Any],
    out: Dict[str, Any],
    dctx: Any,
    *,
    event_ts: float | None = None,
) -> Tuple[int, Tuple[str, float, float, int, str]]:
    """
    Ham kalite + rejim (faz 26) + decay monitör; dctx/analysis alanlarını doldurur (apply_filters ile uyumlu).
    Dönüş: (adj_quality, omega_tuple)
    """
    import super_otonom.bot_engine as be_mod

    fs = str(out.get("final_signal", "HOLD"))
    _eff = dict(analysis, signal=fs)

    _qs, _pr, _qc, _qmp = be_mod.compute_signal_quality(_eff)

    phase26, omega_t = run_regime_detection_phase(analysis, int(_qs), event_ts=event_ts)
    _oreg, _qmult, _sfi, _adj, _omlog = omega_t

    decay_snap: Optional[Dict[str, Any]] = None
    try:
        decay_res = monitor_alpha_decay(
            symbol=symbol,
            analysis=analysis,
            event_ts=int(event_ts) if event_ts is not None else None,
        )
        decay_snap = decay_res.to_dict()
        analysis["alpha_decay_freshness"] = decay_snap
    except Exception:
        decay_snap = None

    _effq = int(engine.risk.get_omega_effective_qmin(int(RISK.get("signal_quality_min", 40))))

    dctx.signal_quality = int(_qs)
    dctx.adj_signal_quality = int(_adj)
    dctx.penalty_reasons = list(_pr)
    dctx.quality_main_penalty = str(_qmp)
    dctx.omega_regime = str(_oreg)
    dctx.omega_quality_mult = float(_qmult)
    dctx.omega_size_factor = float(_sfi)
    dctx.effective_quality_min = int(_effq)
    analysis["quality_score"] = int(_qs)
    analysis["penalty_reasons"] = list(_pr)
    analysis["quality_components"] = _qc
    analysis["adj_signal_quality"] = int(_adj)
    analysis["omega_regime"] = str(_oreg)
    analysis["omega_size_factor"] = float(_sfi)
    omlb = str(analysis.get("omega_ml_bridge", "no_external_ml"))
    ext = dctx.external_ai_log or "—"
    dctx.omega_ai_log = f"ml={omlb} | ext={ext} | {_omlog}"

    decay_conf = 1.0
    if decay_snap:
        decay_conf = float(decay_snap.get("confidence", 0.8))

    phase45 = make_standard_phase_output(
        trade_permission="ALLOW" if int(_adj) >= _effq or fs != "BUY" else "BLOCK",
        alpha_score=float(_adj),
        risk_score=float(max(0.0, 100.0 - int(_adj))),
        confidence=min(1.0, float(_qmult) * decay_conf),
        data_health=float(phase26.get("data_health", 1.0)),
        event_ts=float(time.time() * 1000.0) if event_ts is None else float(event_ts),
        half_life_ms=90_000.0,
        phase="45",
        source="unified_alpha_core",
    )
    phase45["raw_quality"] = int(_qs)
    phase45["effective_quality_min"] = int(_effq)
    phase45["omega_regime"] = str(_oreg)
    phase45["phase26_ref"] = phase26
    if decay_snap:
        phase45["decay"] = decay_snap

    attach_phase_alias(analysis, "45", phase45)

    if fs == "BUY" and int(_adj) < int(_effq):
        out["final_signal"] = "HOLD"
        out["decision_reason"] = (
            f"LOW_QUALITY_REJECT(adj={_adj}<{_effq} raw={_qs} regime={_oreg})"
        )
        dctx.decision_reason = out["decision_reason"]
        dctx.entry_blocked = "low_quality"
        dctx.add_trace("quality", f"reject adj={_adj} effmin={_effq} main={_qmp}")
        log.info(
            "ELITE-OMEGA | %s | LOW_QUALITY | adj=%d < eff=%d (raw=%d) | %s | %s",
            symbol,
            int(_adj),
            int(_effq),
            int(_qs),
            _oreg,
            _pr[:5],
        )
    else:
        dctx.add_trace("quality", f"raw={_qs} adj={_adj} regime={_oreg} effmin={_effq}")

    return int(_adj), omega_t
