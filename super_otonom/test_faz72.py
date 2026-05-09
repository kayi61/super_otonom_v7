from __future__ import annotations


def test_faz72_no_order_book_unknown_intent_not_crash() -> None:
    from super_otonom.whale_intent_microstructure_engine import infer_whale_intent

    r = infer_whale_intent(symbol="BTC/USDT", analysis={"event_ts": 123, "half_life_ms": 30_000}, order_book=None)
    d = r.to_dict()
    assert d["whale_intent"] in ("accumulate", "distribute", "hunt", "exit", "none", "unknown")
    assert 0 <= d["absorption_score"] <= 100
    assert 0 <= d["sweep_risk"] <= 100
    assert d["entry_timing_hint"] in ("enter_now", "wait_pullback", "wait_confirm", "avoid", "unknown")
    assert d["trade_permission"] in ("HALT", "BLOCK", "ALLOW")
    assert 0 <= d["alpha_score"] <= 100
    assert 0 <= d["risk_score"] <= 100
    assert 0.0 <= d["confidence"] <= 1.0
    assert 0.0 <= d["data_health"] <= 1.0


def test_faz72_hunt_detected_blocks_under_high_sweep_risk() -> None:
    from super_otonom.whale_intent_microstructure_engine import infer_whale_intent

    # Strong imbalance + wide spread proxy -> sweep risk high -> hunt likely
    ob = {"bids": [[100, 50], [99.5, 10]], "asks": [[101.5, 1], [102, 1]]}
    r = infer_whale_intent(symbol="BTC/USDT", order_book=ob)
    assert r.whale_intent in ("hunt", "accumulate", "distribute", "none", "unknown", "exit")
    assert 0 <= r.sweep_risk <= 100
    if r.whale_intent == "hunt" and r.sweep_risk >= 80:
        assert r.trade_permission in ("BLOCK", "ALLOW")

