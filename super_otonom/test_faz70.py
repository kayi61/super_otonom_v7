from __future__ import annotations


def test_faz70_no_incident_allow() -> None:
    from super_otonom.incident_response_engine import evaluate_incident_response

    r = evaluate_incident_response(
        symbol="BTC/USDT",
        analysis={
            "incident_severity": "none",
            "event_ts": 1_700_000_000_000,
            "half_life_ms": 60_000,
        },
    )
    assert r.trade_permission == "ALLOW"
    assert r.incident_severity == "none"
    assert r.slo_breach is False
    assert 0 <= r.alpha_score <= 100
    assert 0 <= r.risk_score <= 100
    assert 0.0 <= r.confidence <= 1.0
    assert 0.0 <= r.data_health <= 1.0
    assert isinstance(r.root_cause_template, str)


def test_faz70_slo_critical_halts() -> None:
    from super_otonom.incident_response_engine import evaluate_incident_response

    r = evaluate_incident_response(
        symbol="BTC/USDT",
        analysis={
            "incident_severity": "critical",
            "slo_breach": True,
            "incident_active": True,
            "event_ts": 1_700_000_000_000,
        },
    )
    assert r.trade_permission == "HALT"
    assert r.slo_breach is True


def test_faz70_medium_incident_blocks() -> None:
    from super_otonom.incident_response_engine import evaluate_incident_response

    r = evaluate_incident_response(
        symbol="ETH/USDT",
        analysis={
            "incident_active": True,
            "incident_severity": "medium",
            "event_ts": 1_700_000_000_000,
        },
    )
    assert r.trade_permission == "BLOCK"
    assert r.incident_severity == "medium"


def test_faz70_numeric_severity_maps() -> None:
    from super_otonom.incident_response_engine import evaluate_incident_response

    r = evaluate_incident_response(
        symbol="BTC/USDT",
        analysis={"incident_severity": 95, "event_ts": 1_700_000_000_000},
    )
    assert r.incident_severity == "critical"


def test_faz70_custom_root_cause_preserved() -> None:
    from super_otonom.incident_response_engine import evaluate_incident_response

    r = evaluate_incident_response(
        symbol="BTC/USDT",
        analysis={
            "root_cause_template": "DB_FAILOVER_PARTIAL",
            "incident_severity": "high",
            "event_ts": 1_700_000_000_000,
        },
    )
    assert r.root_cause_template == "DB_FAILOVER_PARTIAL"
