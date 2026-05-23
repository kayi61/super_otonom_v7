from __future__ import annotations


def test_scenarios_shapes_and_ranges() -> None:
    from super_otonom.fake_order_book_scenarios import make_scenario

    for sc in ("normal", "flash_crash", "pump_dump", "low_liquidity"):
        ob, analysis = make_scenario(scenario=sc, mid_price=100.0, seed=123)
        assert "bids" in ob and "asks" in ob
        assert len(ob["bids"]) >= 5 and len(ob["asks"]) >= 5
        assert all(len(x) == 2 for x in ob["bids"][:5])
        assert all(len(x) == 2 for x in ob["asks"][:5])
        assert 0 <= float(analysis["liquidity_ratio"]) <= 1
        assert float(analysis["volatility"]) >= 0
        assert isinstance(analysis.get("mtf"), dict)
        assert isinstance(analysis.get("venues"), dict)


def test_flash_crash_has_high_vol_and_flag() -> None:
    from super_otonom.fake_order_book_scenarios import make_scenario

    _ob, a = make_scenario(scenario="flash_crash", mid_price=100.0, seed=1)
    assert a.get("flash_crash") is True
    assert float(a.get("volatility", 0.0)) >= 0.08
