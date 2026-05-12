from __future__ import annotations


def test_faz77_invalid_price_does_not_crash() -> None:
    from super_otonom.smart_stop_engine import compute_smart_stop

    r = compute_smart_stop(
        symbol="BTC/USDT", side="LONG", last_price=0.0, analysis={"atr": 0.0, "volatility": 0.03}
    )
    assert r.dynamic_stop_level > 0
    assert 0 <= r.hunt_risk_score <= 100
    assert r.trade_permission in ("HALT", "BLOCK", "ALLOW")


def test_faz77_hunt_risk_widen_hint() -> None:
    from super_otonom.smart_stop_engine import compute_smart_stop

    r = compute_smart_stop(
        symbol="BTC/USDT",
        side="LONG",
        last_price=100.0,
        analysis={"atr": 1.0, "regime": "VOLATILE"},
        hunt_risk_score=90,
    )
    assert r.stop_placement_hint in ("widen", "tighten", "keep", "unknown")
    if r.hunt_risk_score >= 75:
        assert r.stop_placement_hint == "widen"
