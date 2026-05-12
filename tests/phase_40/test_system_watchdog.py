"""Faz 40 — system_watchdog birim testleri."""

from __future__ import annotations

import numpy as np
import pytest
from phases.phase_40 import system_watchdog as wd_mod
from phases.phase_40.system_watchdog import (
    analyze,
    compute_exchange_metrics,
    compute_freshness_metrics,
    compute_service_metrics,
    validate_market_data,
)


def _schema() -> set:
    return {
        "phase",
        "module",
        "trade_permission",
        "alpha_score",
        "risk_score",
        "score_type",
        "confidence",
        "data_health",
        "event_ts",
        "half_life_ms",
        "analysis",
        "reason",
    }


def _svc(name: str, st: str, lat: float = 10.0, crit: bool = False) -> dict:
    return {"name": name, "status": st, "latency_ms": lat, "critical": crit}


def _feed(name: str, last_ms: float, max_age: float) -> dict:
    return {"name": name, "last_update_ms": last_ms, "max_age_ms": max_age}


def _ex(name: str, ok: bool, ping: float = 20.0) -> dict:
    return {"exchange": name, "connected": ok, "ping_ms": ping}


def _base(**kw: object) -> dict:
    now = float(kw.get("current_ts_ms", 1_000_000.0))
    return {
        "services": kw.get(
            "services",
            [
                _svc("redis", "up", 5.0),
                _svc("kafka", "up", 12.0),
            ],
        ),
        "data_feeds": kw.get(
            "data_feeds",
            [_feed("ticks", now - 100.0, 1000.0)],
        ),
        "exchange_connections": kw.get(
            "exchange_connections",
            [_ex("binance", True, 30.0), _ex("bybit", True, 40.0)],
        ),
        "current_ts_ms": now,
    }


def test_none_invalid_halt() -> None:
    r = analyze(None)
    assert r["trade_permission"] == "HALT"
    assert r["data_health"] == 0.0
    assert _schema() <= set(r.keys())


def test_empty_services_halt() -> None:
    d = _base(services=[])
    r = analyze(d)
    assert r["trade_permission"] == "HALT"
    assert r["reason"] == "services_empty"


def test_missing_keys_invalid() -> None:
    r = analyze({"services": [_svc("a", "up")]})
    assert r["trade_permission"] == "HALT"


def test_critical_service_down_halt() -> None:
    d = _base(
        services=[
            _svc("redis", "down", 0.0, crit=True),
            _svc("api", "up", 5.0),
        ]
    )
    r = analyze(d)
    assert r["trade_permission"] == "HALT"
    assert "critical_service_down" in r["reason"]
    assert "redis" in r["reason"]


def test_exchange_health_low_blocks() -> None:
    d = _base(
        exchange_connections=[
            _ex("a", False, 0.0),
            _ex("b", False, 0.0),
        ]
    )
    r = analyze(d)
    assert r["analysis"]["exchange_health"] == 0.0
    assert r["trade_permission"] == "BLOCK"
    assert r["reason"] == "exchange_health_low"


def test_stale_feed_blocks() -> None:
    now = 1_000_000.0
    d = _base(
        current_ts_ms=now,
        data_feeds=[_feed("old", now - 50_000.0, 1000.0)],
    )
    r = analyze(d)
    assert r["analysis"]["stale_feeds_count"] >= 1
    assert r["trade_permission"] == "BLOCK"
    assert r["reason"] == "stale_data_feeds"


def test_halt_before_exchange_block() -> None:
    now = 1_000_000.0
    d = _base(
        services=[_svc("db", "down", 0.0, crit=True)],
        exchange_connections=[_ex("x", False), _ex("y", False)],
        current_ts_ms=now,
    )
    r = analyze(d)
    assert r["trade_permission"] == "HALT"


def test_risk_formula() -> None:
    d = _base()
    r = analyze(d)
    a = r["analysis"]
    wh = 0.4 * a["service_health"] + 0.3 * a["freshness_score"] + 0.3 * a["exchange_health"]
    assert r["risk_score"] == pytest.approx(np.clip(1.0 - wh, 0, 1))


def test_alpha_equals_one_minus_risk() -> None:
    r = analyze(_base())
    assert r["alpha_score"] == pytest.approx(1.0 - r["risk_score"], abs=1e-9)


def test_data_health_formula() -> None:
    d = _base()
    r = analyze(d)
    n = len(d["services"]) + len(d["data_feeds"]) + len(d["exchange_connections"])
    assert r["data_health"] == pytest.approx(np.clip(n / 20.0, 0.1, 1.0))


def test_confidence_formula() -> None:
    r = analyze(_base())
    dh = r["data_health"]
    rs = r["risk_score"]
    assert r["confidence"] == pytest.approx(float(np.clip(dh * (1.0 - 0.4 * rs), 0, 1)))


def test_half_life_5000() -> None:
    assert analyze(_base())["half_life_ms"] == 5000


def test_analysis_keys() -> None:
    r = analyze(_base())
    a = r["analysis"]
    for k in (
        "service_health",
        "freshness_score",
        "exchange_health",
        "critical_down_services",
        "stale_feeds_count",
        "avg_latency",
        "avg_ping",
        "connected_exchanges",
    ):
        assert k in a


def test_validate_ok() -> None:
    ok, err = validate_market_data(_base())
    assert ok and err == ""


def test_service_health_all_up() -> None:
    sv = [_svc("a", "up"), _svc("b", "up")]
    sh, _, cd, _ = compute_service_metrics(sv)
    assert sh == 1.0
    assert cd == []


def test_service_health_partial_up() -> None:
    sv = [_svc("a", "up"), _svc("b", "down")]
    sh, _, _, _ = compute_service_metrics(sv)
    assert sh == pytest.approx(0.5)


def test_freshness_all_fresh() -> None:
    now = 5000.0
    fs, sc = compute_freshness_metrics([_feed("x", now - 10.0, 100.0)], now)
    assert fs == 1.0
    assert sc == 0


def test_freshness_stale_count() -> None:
    now = 10_000.0
    fs, sc = compute_freshness_metrics([_feed("x", 1000.0, 500.0)], now)
    assert sc == 1
    assert fs < 1.0


def test_exchange_metrics_all_connected() -> None:
    eh, ap, ps, cc = compute_exchange_metrics([_ex("a", True, 100.0), _ex("b", True, 100.0)])
    assert eh == 1.0
    assert cc == 2
    assert ap == pytest.approx(100.0)


def test_exchange_metrics_none_connected() -> None:
    eh, ap, ps, cc = compute_exchange_metrics([_ex("a", False), _ex("b", False)])
    assert eh == 0.0
    assert cc == 0


def test_allow_healthy_system() -> None:
    d = _base(
        services=[_svc("r", "up", 10.0), _svc("k", "up", 15.0)],
        exchange_connections=[_ex("b", True, 25.0), _ex("c", True, 35.0)],
    )
    r = analyze(d)
    assert r["trade_permission"] == "ALLOW"
    assert r["reason"] == "system_healthy"


def test_phase_module() -> None:
    r = analyze(_base())
    assert r["phase"] == 40
    assert r["module"] == "system_watchdog"


def test_constants() -> None:
    assert wd_mod._HALF_LIFE_MS == 5000


def test_services_not_list() -> None:
    r = analyze({**_base(), "services": "bad"})
    assert r["trade_permission"] == "HALT"


def test_current_ts_invalid() -> None:
    d = _base()
    d["current_ts_ms"] = "not-a-ts"
    r = analyze(d)
    assert r["trade_permission"] == "HALT"


def test_critical_multiple_names_in_reason() -> None:
    d = _base(
        services=[
            _svc("a", "down", 0.0, crit=True),
            _svc("b", "down", 0.0, crit=True),
        ]
    )
    r = analyze(d)
    assert r["trade_permission"] == "HALT"
    assert "a" in r["reason"] and "b" in r["reason"]


def test_exchange_exactly_half_borderline() -> None:
    d = _base(exchange_connections=[_ex("a", True), _ex("b", False)])
    r = analyze(d)
    assert r["analysis"]["exchange_health"] == pytest.approx(0.5)
    assert r["trade_permission"] == "ALLOW"


def test_exchange_below_half_blocks() -> None:
    d = _base(
        exchange_connections=[
            _ex("a", True),
            _ex("b", False),
            _ex("c", False),
        ]
    )
    r = analyze(d)
    assert r["analysis"]["exchange_health"] < 0.5
    assert r["trade_permission"] == "BLOCK"


def test_empty_data_feeds_freshness_one() -> None:
    d = _base(data_feeds=[])
    r = analyze(d)
    assert r["analysis"]["freshness_score"] == 1.0


def test_empty_exchange_list_blocks_low_health() -> None:
    d = _base(exchange_connections=[])
    r = analyze(d)
    assert r["trade_permission"] == "BLOCK"


def test_avg_latency_computed() -> None:
    sh, lat, _, _ = compute_service_metrics([_svc("a", "up", 100.0), _svc("b", "up", 200.0)])
    assert lat == pytest.approx(150.0)
    assert sh == 1.0


def test_status_case_insensitive() -> None:
    sh, _, _, _ = compute_service_metrics([{"name": "x", "status": "UP", "latency_ms": 1.0}])
    assert sh == pytest.approx(1.0)


def test_all_scores_clipped() -> None:
    r = analyze(_base())
    for k in ("alpha_score", "risk_score", "confidence", "data_health"):
        assert 0.0 <= r[k] <= 1.0


def test_event_ts_float() -> None:
    assert isinstance(analyze(_base())["event_ts"], float)


def test_degraded_not_counted_as_up() -> None:
    sh, _, _, _ = compute_service_metrics([_svc("a", "degraded", 5.0)])
    assert sh == pytest.approx(0.0)


def test_connected_exchanges_count() -> None:
    r = analyze(_base())
    assert r["analysis"]["connected_exchanges"] == 2


def test_stale_priority_after_exchange_resolved() -> None:
    """exchange ok, stale → BLOCK stale."""
    now = 1e6
    d = _base(
        current_ts_ms=now,
        exchange_connections=[_ex("b", True, 10.0), _ex("c", True, 10.0)],
        data_feeds=[_feed("q", now - 99999.0, 1000.0)],
    )
    r = analyze(d)
    assert r["trade_permission"] == "BLOCK"
    assert r["reason"] == "stale_data_feeds"


def test_score_type_quality_low_dh() -> None:
    d = _base(services=[_svc("only", "up")], data_feeds=[], exchange_connections=[])
    r = analyze(d)
    assert r["data_health"] < 0.42


def test_validate_missing_current_ts() -> None:
    d = _base()
    del d["current_ts_ms"]
    assert analyze(d)["trade_permission"] == "HALT"
