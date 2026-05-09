from __future__ import annotations


def test_faz47_follows_leader_when_in_venues() -> None:
    from super_otonom.smart_order_router import compute_smart_order_route

    p74 = {"leader_venue": "okx", "route_preference": "leader"}
    p80 = {"final_action": "ENTER", "trade_permission": "ALLOW"}
    p76 = {"regime_execution_mode": "trend"}
    analysis = {"venues": {"okx": {"price": 100.0}, "kucoin": {"price": 100.01}}}
    r = compute_smart_order_route(
        symbol="BTC/USDT",
        analysis=analysis,
        phase74=p74,
        phase80=p80,
        phase76=p76,
    )
    assert r.preferred_venue == "okx"
    assert r.reason == "leader_present"
    assert r.execution_mode == "trend"


def test_faz47_empty_when_halt() -> None:
    from super_otonom.smart_order_router import compute_smart_order_route

    p74 = {"leader_venue": "okx", "route_preference": "leader"}
    p80 = {"final_action": "HALT", "trade_permission": "HALT"}
    r = compute_smart_order_route(
        symbol="BTC/USDT",
        analysis={"venues": {"okx": {}}},
        phase74=p74,
        phase80=p80,
        phase76={"regime_execution_mode": "volatile"},
    )
    assert r.preferred_venue == ""
    assert r.reason == "blocked_or_halt"
    assert r.execution_mode == "volatile"


def test_faz47_crisis_prefers_lowest_latency() -> None:
    from super_otonom.smart_order_router import compute_smart_order_route

    p74 = {"leader_venue": "okx", "route_preference": "leader"}
    p80 = {"final_action": "ENTER", "trade_permission": "ALLOW"}
    p76 = {"regime_execution_mode": "crisis"}
    analysis = {
        "venues": {
            "okx": {"price": 100.0, "latency_ms": 80.0},
            "kucoin": {"price": 100.01, "latency_ms": 20.0},
        }
    }
    r = compute_smart_order_route(
        symbol="BTC/USDT",
        analysis=analysis,
        phase74=p74,
        phase80=p80,
        phase76=p76,
    )
    assert r.preferred_venue == "kucoin"
    assert r.reason == "crisis_lowest_latency"
