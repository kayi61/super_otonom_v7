from __future__ import annotations


def test_faz75_block_propagates_to_wait_or_halt() -> None:
    from super_otonom.mm_whale_consensus_controller import compute_mm_whale_consensus

    p71 = {"dealer_pressure_score": 10, "spread_regime": "normal", "likely_trap_side": "none", "trade_permission": "ALLOW", "confidence": 0.9, "data_health": 0.9}
    p72 = {"whale_intent": "accumulate", "absorption_score": 70, "sweep_risk": 20, "entry_timing_hint": "enter_now", "trade_permission": "ALLOW", "confidence": 0.9, "data_health": 0.9}
    p73 = {"manipulation_risk_score": 95, "game_type": "stop_hunt", "do_not_trade_flag": True, "cooldown_seconds": 300, "trade_permission": "BLOCK", "confidence": 0.9, "data_health": 0.9}
    p74 = {"leader_venue": "okx", "leadlag_alpha_score": 80, "latency_arb_risk": 10, "route_preference": "leader", "trade_permission": "ALLOW", "confidence": 0.9, "data_health": 0.9}

    r = compute_mm_whale_consensus(symbol="BTC/USDT", phase71=p71, phase72=p72, phase73=p73, phase74=p74)
    assert r.trade_permission in ("BLOCK", "HALT")
    assert r.action in ("WAIT", "HALT", "HEDGE", "REDUCE")  # should not TRADE with do_not_trade


def test_faz75_trade_possible_when_clean() -> None:
    from super_otonom.mm_whale_consensus_controller import compute_mm_whale_consensus

    p71 = {"dealer_pressure_score": 15, "spread_regime": "tight", "likely_trap_side": "none", "trade_permission": "ALLOW", "confidence": 0.9, "data_health": 0.9}
    p72 = {"whale_intent": "accumulate", "absorption_score": 75, "sweep_risk": 20, "entry_timing_hint": "enter_now", "trade_permission": "ALLOW", "confidence": 0.9, "data_health": 0.9}
    p73 = {"manipulation_risk_score": 20, "game_type": "none", "do_not_trade_flag": False, "cooldown_seconds": 0, "trade_permission": "ALLOW", "confidence": 0.9, "data_health": 0.9}
    p74 = {"leader_venue": "okx", "leadlag_alpha_score": 85, "latency_arb_risk": 10, "route_preference": "leader", "trade_permission": "ALLOW", "confidence": 0.9, "data_health": 0.9}

    r = compute_mm_whale_consensus(symbol="BTC/USDT", phase71=p71, phase72=p72, phase73=p73, phase74=p74)
    assert r.trade_permission == "ALLOW"
    assert r.action in ("TRADE", "WAIT")  # depending on heuristics
    assert 0 <= r.conviction <= 100

