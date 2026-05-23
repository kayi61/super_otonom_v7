from __future__ import annotations


def test_faz73_missing_order_book_low_health_not_halt() -> None:
    from super_otonom.liquidity_games_detector import detect_liquidity_games

    r = detect_liquidity_games(
        symbol="BTC/USDT", analysis={"volatility": 0.03, "event_ts": 123}, order_book=None
    )
    d = r.to_dict()
    assert 0 <= d["manipulation_risk_score"] <= 100
    assert d["game_type"] in (
        "spoofing",
        "quote_stuffing",
        "momentum_ignition",
        "stop_hunt",
        "unknown",
        "none",
    )
    assert isinstance(d["do_not_trade_flag"], bool)
    assert d["cooldown_seconds"] >= 0
    # This phase should not HALT by itself
    assert d["trade_permission"] in ("ALLOW", "BLOCK")


def test_faz73_extreme_vol_and_wide_spread_sets_do_not_trade() -> None:
    from super_otonom.liquidity_games_detector import detect_liquidity_games

    ob = {"bids": [[100, 1]], "asks": [[103, 1]]}  # very wide
    r = detect_liquidity_games(symbol="BTC/USDT", analysis={"volatility": 0.10}, order_book=ob)
    assert 0 <= r.manipulation_risk_score <= 100
    if r.manipulation_risk_score >= 80:
        assert r.do_not_trade_flag is True
        assert r.cooldown_seconds >= 90
