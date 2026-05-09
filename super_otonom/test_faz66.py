from __future__ import annotations


def _rich_analysis(now: int) -> dict:
    return {
        "regime": "TREND",
        "volatility": 0.02,
        "signal": "BUY",
        "liquidity_ratio": 0.7,
        "order_book": {"bids": [[100.0, 1.0]], "asks": [[100.1, 1.0]]},
        "event_ts": now,
        "half_life_ms": 30_000,
    }


def test_faz66_clean_high_quality_allow() -> None:
    from super_otonom.data_quality_governance import evaluate_data_quality_governance

    now = 1_700_000_000_000
    r = evaluate_data_quality_governance(
        symbol="BTC/USDT",
        analysis=_rich_analysis(now),
    )
    assert r.trade_permission == "ALLOW"
    assert r.data_quality_score >= 50
    assert r.source_trust_score >= 50
    assert r.quarantine_flag is False
    assert r.rollback_required is False
    assert 0 <= r.alpha_score <= 100
    assert 0 <= r.risk_score <= 100
    assert 0.0 <= r.confidence <= 1.0
    assert 0.0 <= r.data_health <= 1.0


def test_faz66_rollback_halts() -> None:
    from super_otonom.data_quality_governance import evaluate_data_quality_governance

    r = evaluate_data_quality_governance(
        symbol="BTC/USDT",
        analysis={**_rich_analysis(1_700_000_000_000), "rollback_required": True},
    )
    assert r.trade_permission == "HALT"
    assert r.rollback_required is True


def test_faz66_quarantine_blocks() -> None:
    from super_otonom.data_quality_governance import evaluate_data_quality_governance

    r = evaluate_data_quality_governance(
        symbol="ETH/USDT",
        analysis={"quarantine_flag": True, "event_ts": 1_700_000_000_000, "half_life_ms": 30_000},
    )
    assert r.trade_permission == "BLOCK"
    assert r.quarantine_flag is True


def test_faz66_explicit_low_scores_block() -> None:
    from super_otonom.data_quality_governance import evaluate_data_quality_governance

    r = evaluate_data_quality_governance(
        symbol="BTC/USDT",
        analysis={
            "data_quality_score": 30,
            "source_trust_score": 30,
            "event_ts": 1_700_000_000_000,
            "half_life_ms": 30_000,
        },
    )
    assert r.trade_permission == "BLOCK"
