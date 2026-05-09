from __future__ import annotations


def test_faz67_clean_allow() -> None:
    from super_otonom.exchange_connectivity_engine import evaluate_exchange_connectivity

    r = evaluate_exchange_connectivity(
        symbol="BTC/USDT",
        analysis={
            "exchange_latency_ms": 40.0,
            "rate_limit_pressure": 0.05,
            "circuit_breaker_state": "CLOSED",
            "event_ts": 1_700_000_000_000,
            "half_life_ms": 30_000,
        },
    )
    assert r.trade_permission == "ALLOW"
    assert r.failover_active is False
    assert r.connectivity_score >= 40
    assert 0 <= r.endpoint_health <= 100
    assert 0 <= r.rate_limit_risk <= 100
    assert 0 <= r.alpha_score <= 100
    assert 0 <= r.risk_score <= 100
    assert 0.0 <= r.confidence <= 1.0
    assert 0.0 <= r.data_health <= 1.0


def test_faz67_cb_open_and_dead_halts() -> None:
    from super_otonom.exchange_connectivity_engine import evaluate_exchange_connectivity

    r = evaluate_exchange_connectivity(
        symbol="BTC/USDT",
        analysis={
            "circuit_breaker_state": "OPEN",
            "connectivity_score": 15,
            "rate_limit_risk": 10,
            "event_ts": 1_700_000_000_000,
            "half_life_ms": 30_000,
        },
    )
    assert r.trade_permission == "HALT"


def test_faz67_rate_limit_blocks() -> None:
    from super_otonom.exchange_connectivity_engine import evaluate_exchange_connectivity

    r = evaluate_exchange_connectivity(
        symbol="ETH/USDT",
        analysis={
            "exchange_latency_ms": 30.0,
            "rate_limit_risk": 92,
            "circuit_breaker_state": "CLOSED",
            "event_ts": 1_700_000_000_000,
            "half_life_ms": 30_000,
        },
    )
    assert r.trade_permission == "BLOCK"
    assert r.rate_limit_risk >= 90


def test_faz67_failover_degraded_blocks() -> None:
    from super_otonom.exchange_connectivity_engine import evaluate_exchange_connectivity

    r = evaluate_exchange_connectivity(
        symbol="BTC/USDT",
        analysis={
            "failover_active": True,
            "exchange_latency_ms": 450.0,
            "rate_limit_pressure": 0.25,
            "circuit_breaker_state": "CLOSED",
            "event_ts": 1_700_000_000_000,
            "half_life_ms": 30_000,
        },
    )
    assert r.failover_active is True
    assert r.trade_permission == "BLOCK"
