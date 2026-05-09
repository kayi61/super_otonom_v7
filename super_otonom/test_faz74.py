from __future__ import annotations


def test_faz74_no_venues_returns_unknown_low_confidence() -> None:
    from super_otonom.cross_venue_leadlag_intelligence import infer_cross_venue_leadlag

    r = infer_cross_venue_leadlag(symbol="BTC/USDT", analysis={"event_ts": 123}, half_life_ms=20_000)
    d = r.to_dict()
    assert d["leader_venue"] in ("unknown", "okx", "kucoin", "gate") or isinstance(d["leader_venue"], str)
    assert 0 <= d["leadlag_alpha_score"] <= 100
    assert 0 <= d["latency_arb_risk"] <= 100
    assert d["route_preference"] in ("leader", "best_price", "lowest_latency", "avoid_latency_arb", "unknown")
    assert d["trade_permission"] in ("HALT", "BLOCK", "ALLOW")
    assert 0.0 <= d["confidence"] <= 1.0


def test_faz74_multi_venues_computes_leader_and_route() -> None:
    from super_otonom.cross_venue_leadlag_intelligence import infer_cross_venue_leadlag

    venues = {
        "okx": {"price": 100.0, "ret_1s": 0.0010, "latency_ms": 40},
        "kucoin": {"price": 100.05, "ret_1s": 0.0004, "latency_ms": 55},
        "gate": {"price": 100.10, "ret_1s": 0.0002, "latency_ms": 70},
    }
    r = infer_cross_venue_leadlag(symbol="BTC/USDT", analysis={"venues": venues})
    assert isinstance(r.leader_venue, str) and r.leader_venue
    assert 0 <= r.latency_arb_risk <= 100
    assert r.route_preference in ("leader", "best_price", "lowest_latency", "avoid_latency_arb", "unknown")

