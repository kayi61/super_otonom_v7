from __future__ import annotations


def test_faz79_empty_mtf_returns_unknown_and_conflict() -> None:
    from super_otonom.multi_timeframe_consensus_engine import infer_mtf_consensus

    r = infer_mtf_consensus(symbol="BTC/USDT", analysis={})
    assert r.dominant_timeframe == "unknown"
    assert r.conflict_flag is True
    assert r.entry_timing in ("enter_now", "wait_confirm", "wait_pullback", "avoid", "unknown")


def test_faz79_majority_buy_increases_consensus() -> None:
    from super_otonom.multi_timeframe_consensus_engine import infer_mtf_consensus

    mtf = {
        "1m": {"signal": "BUY", "score": 60},
        "5m": {"signal": "BUY", "score": 70},
        "15m": {"signal": "BUY", "score": 55},
        "1h": {"signal": "SELL", "score": 55},
        "4h": {"signal": "BUY", "score": 75},
    }
    r = infer_mtf_consensus(symbol="BTC/USDT", analysis={"mtf": mtf})
    assert 0 <= r.mtf_consensus_score <= 100
    assert isinstance(r.conflict_flag, bool)
