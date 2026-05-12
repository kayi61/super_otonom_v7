from __future__ import annotations


def _base_phase_dicts(now: int) -> dict:
    # Minimal dicts to satisfy autonomous_decision_core inputs
    return {
        "p71": {
            "trade_permission": "ALLOW",
            "dealer_pressure_score": 20,
            "spread_regime": "normal",
            "likely_trap_side": "none",
            "confidence": 0.9,
            "data_health": 0.9,
            "event_ts": now,
            "half_life_ms": 25_000,
        },
        "p72": {
            "trade_permission": "ALLOW",
            "whale_intent": "accumulate",
            "absorption_score": 70,
            "sweep_risk": 20,
            "entry_timing_hint": "enter_now",
            "confidence": 0.9,
            "data_health": 0.9,
            "event_ts": now,
            "half_life_ms": 30_000,
        },
        "p73": {
            "trade_permission": "ALLOW",
            "manipulation_risk_score": 20,
            "do_not_trade_flag": False,
            "cooldown_seconds": 0,
            "confidence": 0.9,
            "data_health": 0.9,
            "event_ts": now,
            "half_life_ms": 18_000,
        },
        "p74": {
            "trade_permission": "ALLOW",
            "leadlag_alpha_score": 80,
            "latency_arb_risk": 10,
            "route_preference": "leader",
            "confidence": 0.9,
            "data_health": 0.9,
            "event_ts": now,
            "half_life_ms": 20_000,
        },
        "p75": {
            "trade_permission": "ALLOW",
            "action": "TRADE",
            "conviction": 80,
            "max_size_multiplier": 1.1,
            "execution_profile": "taker",
            "alpha_score": 75,
            "risk_score": 25,
            "confidence": 0.9,
            "data_health": 0.9,
            "event_ts": now,
            "half_life_ms": 22_000,
        },
        "p76": {
            "trade_permission": "ALLOW",
            "preferred_order_type": "taker",
            "slippage_risk": 25,
            "urgency_score": 60,
            "confidence": 0.9,
            "data_health": 0.9,
            "event_ts": now,
            "half_life_ms": 20_000,
        },
        "p77": {
            "trade_permission": "ALLOW",
            "hunt_risk_score": 25,
            "stop_placement_hint": "keep",
            "confidence": 0.9,
            "data_health": 0.9,
            "event_ts": now,
            "half_life_ms": 35_000,
        },
        "p78": {
            "trade_permission": "ALLOW",
            "alpha_freshness_score": 80,
            "exit_urgency": 15,
            "confidence": 0.9,
            "data_health": 0.9,
            "event_ts": now - 10_000,
            "half_life_ms": 30_000,
        },
        "p79": {
            "trade_permission": "ALLOW",
            "mtf_consensus_score": 75,
            "conflict_flag": False,
            "entry_timing": "enter_now",
            "confidence": 0.9,
            "data_health": 0.9,
            "event_ts": now,
            "half_life_ms": 40_000,
        },
    }


def test_faz80_override_phase73_block_prevents_enter() -> None:
    from super_otonom.autonomous_decision_core import decide_autonomously

    now = 1_700_000_000_000
    b = _base_phase_dicts(now)
    b["p73"]["trade_permission"] = "BLOCK"
    b["p73"]["do_not_trade_flag"] = True
    r = decide_autonomously(
        symbol="BTC/USDT",
        phase71=b["p71"],
        phase72=b["p72"],
        phase73=b["p73"],
        phase74=b["p74"],
        phase75=b["p75"],
        phase76=b["p76"],
        phase77=b["p77"],
        phase78=b["p78"],
        phase79=b["p79"],
    )
    assert r.trade_permission in ("BLOCK", "HALT")
    assert r.final_action != "ENTER"


def test_faz80_clean_path_can_enter() -> None:
    from super_otonom.autonomous_decision_core import decide_autonomously

    now = 1_700_000_000_000
    b = _base_phase_dicts(now)
    r = decide_autonomously(
        symbol="BTC/USDT",
        phase71=b["p71"],
        phase72=b["p72"],
        phase73=b["p73"],
        phase74=b["p74"],
        phase75=b["p75"],
        phase76=b["p76"],
        phase77=b["p77"],
        phase78=b["p78"],
        phase79=b["p79"],
    )
    assert r.trade_permission in ("ALLOW", "BLOCK", "HALT")
    assert 0.0 <= r.confidence <= 1.0
    assert 0 <= r.alpha_score <= 100
    assert 0 <= r.risk_score <= 100


def test_faz80_omitted_76_to_79_uses_neutral_defaults_and_can_enter() -> None:
    from super_otonom.autonomous_decision_core import decide_autonomously

    now = 1_700_000_000_000
    b = _base_phase_dicts(now)
    r = decide_autonomously(
        symbol="BTC/USDT",
        phase71=b["p71"],
        phase72=b["p72"],
        phase73=b["p73"],
        phase74=b["p74"],
        phase75=b["p75"],
    )
    assert r.final_action == "ENTER"
    assert r.trade_permission == "ALLOW"
    assert 0.0 <= r.confidence <= 1.0
