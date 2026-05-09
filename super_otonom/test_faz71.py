from __future__ import annotations


def test_faz71_no_order_book_returns_unknownish_but_valid_ranges() -> None:
    from super_otonom.dealer_intent_inference_engine import infer_dealer_intent

    r = infer_dealer_intent(symbol="BTC/USDT", analysis={"event_ts": 123, "half_life_ms": 25_000}, order_book=None)
    d = r.to_dict()

    assert 0 <= d["dealer_pressure_score"] <= 100
    assert d["likely_trap_side"] in ("long", "short", "none", "unknown")
    assert d["spread_regime"] in ("tight", "normal", "wide", "unknown")
    assert d["risk_off_hint"] in ("risk_off", "neutral", "risk_on", "unknown")

    assert d["trade_permission"] in ("HALT", "BLOCK", "ALLOW")
    assert 0 <= d["alpha_score"] <= 100
    assert 0 <= d["risk_score"] <= 100
    assert 0.0 <= d["confidence"] <= 1.0
    assert 0.0 <= d["data_health"] <= 1.0
    assert d["event_ts"] == 123
    assert 2_000 <= d["half_life_ms"] <= 300_000


def test_faz71_wide_spread_flags_pressure_and_may_block() -> None:
    from super_otonom.dealer_intent_inference_engine import infer_dealer_intent

    # Very wide spread + imbalance
    ob = {"bids": [[100, 10], [99.5, 1]], "asks": [[103, 1], [104, 1]]}
    r = infer_dealer_intent(symbol="BTC/USDT", order_book=ob)
    assert 0 <= r.dealer_pressure_score <= 100
    assert r.spread_regime in ("wide", "normal", "tight", "unknown")
    # Under extreme conditions, should not return HALT by itself
    assert r.trade_permission in ("ALLOW", "BLOCK")

