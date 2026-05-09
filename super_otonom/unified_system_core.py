"""Faz 50 — Sistem kapısı: risk_pipeline + kill_switch davranışını sarar."""
from __future__ import annotations

import time
from typing import Any, Dict, Literal

from super_otonom.pipelines import risk_pipeline
from super_otonom.standard_phase_output import attach_phase_alias, make_standard_phase_output

GateResult = Literal["ok", "kill", "risk"]


def _risk_permission_from_engine(engine: Any) -> str:
    if getattr(engine.risk, "emergency_stop", False):
        return "HALT"
    return "ALLOW"


def run_system_gate_phase(
    engine: Any,
    symbol: str,
    price: float,
    dctx: Any,
    out: Dict[str, Any],
    analysis: Dict[str, Any],
) -> GateResult:
    """
    ok: tick devam.
    kill: global kill / fiyat spike — BotEngine risk_block çağırmadan çıkar (eski semantik).
    risk: portföy risk red — caller _tick_handle_risk_block kullanır.
    analysis['phase50'] / faz50 güncellenir.
    """
    ts = float(time.time() * 1000.0)

    if risk_pipeline.tick_kill_switch_and_spike(engine, symbol, price, dctx, out):
        snap = make_standard_phase_output(
            trade_permission="HALT",
            alpha_score=0.0,
            risk_score=100.0,
            confidence=0.0,
            data_health=0.0,
            event_ts=ts,
            half_life_ms=25_000.0,
            phase="50",
            source="unified_system_core:kill_spike",
        )
        attach_phase_alias(analysis, "50", snap)
        return "kill"

    exposure = float(engine._open_exposure({symbol: price}))
    current_vol = float(analysis.get("volatility", 0.0))

    if not risk_pipeline.tick_portfolio_risk(
        engine, symbol, exposure, current_vol, dctx, out
    ):
        perm = _risk_permission_from_engine(engine)
        snap = make_standard_phase_output(
            trade_permission=perm,
            alpha_score=0.0,
            risk_score=95.0,
            confidence=0.1,
            data_health=0.4,
            event_ts=ts,
            half_life_ms=25_000.0,
            phase="50",
            source="unified_system_core:portfolio_risk",
        )
        attach_phase_alias(analysis, "50", snap)
        return "risk"

    snap_ok = make_standard_phase_output(
        trade_permission="ALLOW",
        alpha_score=50.0,
        risk_score=30.0,
        confidence=0.85,
        data_health=1.0,
        event_ts=ts,
        half_life_ms=25_000.0,
        phase="50",
        source="unified_system_core:ok",
    )
    attach_phase_alias(analysis, "50", snap_ok)
    return "ok"
