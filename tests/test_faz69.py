from __future__ import annotations


def test_faz69_clean_allow() -> None:
    from super_otonom.backtest_leakage_guard import evaluate_backtest_leakage_guard

    r = evaluate_backtest_leakage_guard(
        symbol="BTC/USDT",
        analysis={
            "event_ts": 1_700_000_000_000,
            "half_life_ms": 60_000,
        },
    )
    assert r.trade_permission == "ALLOW"
    assert r.lookahead_detected is False
    assert r.data_snooping_warning is False
    assert r.purged_cv_required is False
    assert r.leakage_risk_score < 30
    assert 0 <= r.alpha_score <= 100
    assert 0 <= r.risk_score <= 100
    assert 0.0 <= r.confidence <= 1.0
    assert 0.0 <= r.data_health <= 1.0


def test_faz69_integrity_breach_halts() -> None:
    from super_otonom.backtest_leakage_guard import evaluate_backtest_leakage_guard

    r = evaluate_backtest_leakage_guard(
        symbol="BTC/USDT",
        analysis={"backtest_integrity_breach": True, "event_ts": 1_700_000_000_000},
    )
    assert r.trade_permission == "HALT"
    assert r.leakage_risk_score >= 90


def test_faz69_lookahead_blocks() -> None:
    from super_otonom.backtest_leakage_guard import evaluate_backtest_leakage_guard

    r = evaluate_backtest_leakage_guard(
        symbol="ETH/USDT",
        analysis={"lookahead_detected": True, "event_ts": 1_700_000_000_000},
    )
    assert r.trade_permission in ("BLOCK", "HALT")
    assert r.lookahead_detected is True


def test_faz69_high_explicit_score_blocks() -> None:
    from super_otonom.backtest_leakage_guard import evaluate_backtest_leakage_guard

    r = evaluate_backtest_leakage_guard(
        symbol="BTC/USDT",
        analysis={"leakage_risk_score": 70, "event_ts": 1_700_000_000_000},
    )
    assert r.trade_permission == "BLOCK"
