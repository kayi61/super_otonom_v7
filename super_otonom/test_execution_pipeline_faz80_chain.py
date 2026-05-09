from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock


def test_execution_pipeline_runs_faz_71_to_79_then_47_80_chain() -> None:
    from super_otonom.decision_context import DecisionContext
    from super_otonom.pipelines.execution_pipeline import execute_trade_phase

    engine = MagicMock()
    engine.open_positions = {}
    engine._handle_exit = AsyncMock()
    engine._handle_entry = AsyncMock()

    symbol = "BTC/USDT"
    price = 100.0
    ts_now = int(time.time() * 1000)
    analysis = {
        "signal": "BUY",
        "regime": "TREND",
        "volatility": 0.02,
        "liquidity_ratio": 0.75,
        "atr": 1.0,
        # Provide OB for 71-73 / 76
        "order_book": {"bids": [[100.0, 10.0], [99.9, 5.0]], "asks": [[100.1, 10.0], [100.2, 5.0]]},
        # Provide venues for 74 / 47
        "venues": {
            "okx": {"price": 100.0, "ret_1s": 0.0006, "latency_ms": 40},
            "kucoin": {"price": 100.02, "ret_1s": 0.0002, "latency_ms": 60},
            "gate": {"price": 100.03, "ret_1s": 0.0001, "latency_ms": 70},
        },
        "mtf": {
            "1m": {"signal": "BUY", "score": 70},
            "5m": {"signal": "BUY", "score": 70},
            "15m": {"signal": "BUY", "score": 65},
            "1h": {"signal": "BUY", "score": 72},
        },
        "event_ts": ts_now,
        "half_life_ms": 30_000,
    }
    out = {"final_signal": "BUY", "ai_confidence": 0.8, "decision_reason": ""}
    dctx = DecisionContext.start(symbol=symbol, tick_id=1, analysis=analysis)

    asyncio.run(execute_trade_phase(engine, symbol, price, analysis, out, 1.0, dctx, candles=[]))

    assert set(dctx.phase_chain.keys()) == {
        "faz66",
        "faz67",
        "faz68",
        "faz69",
        "faz70",
        "faz71",
        "faz72",
        "faz73",
        "faz74",
        "faz75",
        "faz76",
        "faz77",
        "faz78",
        "faz79",
        "faz47",
        "faz80",
    }
    assert "trade_permission" in dctx.phase_chain["faz66"]
    assert "trade_permission" in dctx.phase_chain["faz68"]

    p80 = dctx.phase_chain["faz80"]
    assert "risk_gate" in p80
    assert 0 <= int(p80["risk_gate"]) <= 100
    assert out.get("final_action") == p80.get("final_action")
    assert out.get("final_action") in ("ENTER", "WAIT", "EXIT", "HEDGE", "HALT")
    assert out.get("trade_permission") == p80.get("trade_permission")
    assert out.get("trade_permission") in ("HALT", "BLOCK", "ALLOW")
    assert "phase80" in out and out["phase80"]["final_action"] == out["final_action"]
    assert out.get("faz47", {}).get("preferred_venue") == "okx"
    assert dctx.phase_chain["faz47"].get("execution_mode") == dctx.phase_chain["faz76"].get(
        "regime_execution_mode"
    )
    el = out.get("execution_layer") or {}
    assert el.get("final_action") == out["final_action"]
    assert el.get("preferred_venue") == "okx"
    assert el.get("route_preference") == out["phase80"].get("route_preference")
    assert el.get("risk_gate") == p80.get("risk_gate")
    assert el.get("execution_mode") == dctx.phase_chain["faz76"].get("regime_execution_mode")
    assert "dynamic_stop" in out and out["dynamic_stop"] == dctx.phase_chain["faz77"]["dynamic_stop_level"]

    engine._handle_entry.assert_awaited()


def test_faz79_conflict_lowers_risk_gate_vs_aligned_mtf() -> None:
    from super_otonom.autonomous_decision_core import decide_autonomously

    now = int(time.time() * 1000)
    base = {
        "p71": {"trade_permission": "ALLOW", "dealer_pressure_score": 20, "spread_regime": "normal", "likely_trap_side": "none", "confidence": 0.9, "data_health": 0.9, "event_ts": now, "half_life_ms": 25_000},
        "p72": {"trade_permission": "ALLOW", "whale_intent": "accumulate", "absorption_score": 70, "sweep_risk": 20, "entry_timing_hint": "enter_now", "confidence": 0.9, "data_health": 0.9, "event_ts": now, "half_life_ms": 30_000},
        "p73": {"trade_permission": "ALLOW", "manipulation_risk_score": 20, "do_not_trade_flag": False, "cooldown_seconds": 0, "confidence": 0.9, "data_health": 0.9, "event_ts": now, "half_life_ms": 18_000},
        "p74": {"trade_permission": "ALLOW", "leadlag_alpha_score": 60, "latency_arb_risk": 15, "route_preference": "leader", "confidence": 0.9, "data_health": 0.9, "event_ts": now, "half_life_ms": 20_000},
        "p75": {"trade_permission": "ALLOW", "action": "TRADE", "conviction": 70, "max_size_multiplier": 1.0, "execution_profile": "taker", "alpha_score": 65, "risk_score": 30, "confidence": 0.9, "data_health": 0.9, "event_ts": now, "half_life_ms": 22_000},
        "p76": {"trade_permission": "ALLOW", "preferred_order_type": "taker", "slippage_risk": 20, "urgency_score": 40, "confidence": 0.9, "data_health": 0.9, "event_ts": now, "half_life_ms": 20_000},
        "p77": {"trade_permission": "ALLOW", "hunt_risk_score": 20, "stop_placement_hint": "keep", "confidence": 0.9, "data_health": 0.9, "event_ts": now, "half_life_ms": 35_000},
        "p78": {"trade_permission": "ALLOW", "alpha_freshness_score": 75, "exit_urgency": 10, "confidence": 0.9, "data_health": 0.9, "event_ts": now, "half_life_ms": 30_000},
    }
    ok79 = {
        "trade_permission": "ALLOW",
        "mtf_consensus_score": 70,
        "conflict_flag": False,
        "entry_timing": "enter_now",
        "confidence": 0.9,
        "data_health": 0.9,
        "event_ts": now,
        "half_life_ms": 40_000,
    }
    bad79 = {**ok79, "conflict_flag": True}

    r_ok = decide_autonomously(
        symbol="BTC/USDT",
        phase71=base["p71"],
        phase72=base["p72"],
        phase73=base["p73"],
        phase74=base["p74"],
        phase75=base["p75"],
        phase76=base["p76"],
        phase77=base["p77"],
        phase78=base["p78"],
        phase79=ok79,
    )
    r_cf = decide_autonomously(
        symbol="BTC/USDT",
        phase71=base["p71"],
        phase72=base["p72"],
        phase73=base["p73"],
        phase74=base["p74"],
        phase75=base["p75"],
        phase76=base["p76"],
        phase77=base["p77"],
        phase78=base["p78"],
        phase79=bad79,
    )
    assert r_cf.risk_gate < r_ok.risk_gate


def test_faz78_freshness_scales_confidence() -> None:
    from super_otonom.autonomous_decision_core import decide_autonomously

    now = int(time.time() * 1000)
    low_f = {
        "trade_permission": "ALLOW",
        "alpha_freshness_score": 15,
        "exit_urgency": 5,
        "confidence": 0.9,
        "data_health": 0.9,
        "event_ts": now,
        "half_life_ms": 30_000,
    }
    high_f = {**low_f, "alpha_freshness_score": 95}
    common = {
        "p71": {"trade_permission": "ALLOW", "dealer_pressure_score": 25, "spread_regime": "normal", "likely_trap_side": "none", "confidence": 0.85, "data_health": 0.9, "event_ts": now, "half_life_ms": 25_000},
        "p72": {"trade_permission": "ALLOW", "whale_intent": "accumulate", "absorption_score": 65, "sweep_risk": 25, "entry_timing_hint": "enter_now", "confidence": 0.85, "data_health": 0.9, "event_ts": now, "half_life_ms": 30_000},
        "p73": {"trade_permission": "ALLOW", "manipulation_risk_score": 18, "do_not_trade_flag": False, "cooldown_seconds": 0, "confidence": 0.85, "data_health": 0.9, "event_ts": now, "half_life_ms": 18_000},
        "p74": {"trade_permission": "ALLOW", "leadlag_alpha_score": 55, "latency_arb_risk": 12, "route_preference": "leader", "confidence": 0.85, "data_health": 0.9, "event_ts": now, "half_life_ms": 20_000},
        "p75": {"trade_permission": "ALLOW", "action": "TRADE", "conviction": 72, "max_size_multiplier": 1.0, "execution_profile": "taker", "alpha_score": 62, "risk_score": 28, "confidence": 0.85, "data_health": 0.9, "event_ts": now, "half_life_ms": 22_000},
        "p76": {"trade_permission": "ALLOW", "preferred_order_type": "taker", "slippage_risk": 22, "urgency_score": 35, "confidence": 0.85, "data_health": 0.9, "event_ts": now, "half_life_ms": 20_000},
        "p77": {"trade_permission": "ALLOW", "hunt_risk_score": 22, "stop_placement_hint": "keep", "confidence": 0.85, "data_health": 0.9, "event_ts": now, "half_life_ms": 35_000},
        "p79": {"trade_permission": "ALLOW", "mtf_consensus_score": 68, "conflict_flag": False, "entry_timing": "enter_now", "confidence": 0.85, "data_health": 0.9, "event_ts": now, "half_life_ms": 40_000},
    }
    r_lo = decide_autonomously(
        symbol="BTC/USDT",
        phase71=common["p71"],
        phase72=common["p72"],
        phase73=common["p73"],
        phase74=common["p74"],
        phase75=common["p75"],
        phase76=common["p76"],
        phase77=common["p77"],
        phase78=low_f,
        phase79=common["p79"],
    )
    r_hi = decide_autonomously(
        symbol="BTC/USDT",
        phase71=common["p71"],
        phase72=common["p72"],
        phase73=common["p73"],
        phase74=common["p74"],
        phase75=common["p75"],
        phase76=common["p76"],
        phase77=common["p77"],
        phase78=high_f,
        phase79=common["p79"],
    )
    assert r_lo.confidence < r_hi.confidence
    assert 0.0 <= r_lo.confidence <= 1.0


def test_execution_pipeline_passes_override_phases_from_analysis() -> None:
    from super_otonom.decision_context import DecisionContext
    from super_otonom.pipelines.execution_pipeline import execute_trade_phase

    engine = MagicMock()
    engine.open_positions = {}
    engine._handle_exit = AsyncMock()
    engine._handle_entry = AsyncMock()

    ts_now = int(time.time() * 1000)
    analysis = {
        "signal": "BUY",
        "regime": "TREND",
        "volatility": 0.02,
        "liquidity_ratio": 0.75,
        "atr": 1.0,
        "order_book": {"bids": [[100.0, 10.0]], "asks": [[100.2, 10.0]]},
        "venues": {"okx": {"price": 100.0, "ret_1s": 0.0005, "latency_ms": 40}},
        "mtf": {
            "1m": {"signal": "BUY", "score": 70},
            "5m": {"signal": "BUY", "score": 70},
            "15m": {"signal": "BUY", "score": 65},
            "1h": {"signal": "BUY", "score": 72},
        },
        "event_ts": ts_now,
        "half_life_ms": 30_000,
        "phase50": {"trade_permission": "BLOCK", "event_ts": ts_now, "half_life_ms": 25_000},
    }
    out = {"final_signal": "BUY", "ai_confidence": 0.8, "decision_reason": ""}
    dctx = DecisionContext.start(symbol="BTC/USDT", tick_id=1, analysis=analysis)

    asyncio.run(execute_trade_phase(engine, "BTC/USDT", 100.0, analysis, out, 1.0, dctx, candles=[]))

    assert dctx.phase_chain["faz80"]["block_reason"] == "override:phase50"
    assert dctx.phase_chain["faz80"]["final_action"] != "ENTER"

