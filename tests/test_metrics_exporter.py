"""MetricsExporter: no-op veya prom ile çökmeme."""
from __future__ import annotations

import pytest
from super_otonom.metrics_exporter import _PROMETHEUS_AVAILABLE, MetricsExporter


def test_init_port_zero_no_server_bind() -> None:
    m = MetricsExporter(port=0, namespace="test_bot_metrics")
    assert isinstance(m.is_active, bool)
    r = repr(m)
    assert "MetricsExporter" in r


def test_update_and_record_safe_with_disabled() -> None:
    m = MetricsExporter(port=0)
    m.update(
        {
            "equity": 10_000.0,
            "emergency_stop": False,
            "dynamic_daily_limit": 3.0,
        }
    )
    m.record_analysis(
        {
            "symbol": "BTC/USDT",
            "regime": "TRENDING",
            "hurst": 0.6,
            "volatility": 0.02,
        }
    )
    m.update_circuit_breakers({"ETH/USDT": "CLOSED"})
    m.update_circuit_breakers({"ETH/USDT": "OPEN (recovery=1s kaldı)"})
    m.record_slippage("BTC/USDT", 100.0, 100.1)
    m.record_slippage("BTC/USDT", 0.0, 100.0)
    m.record_trade(5.0, reason="test")


def test_update_ignores_non_coercible_status_numbers() -> None:
    m = MetricsExporter(port=0, namespace="test_metrics_coerce")
    m.update({"equity": "not_a_float", "open_positions": object()})
    m.update({"equity": 100.0})


@pytest.mark.skipif(not _PROMETHEUS_AVAILABLE, reason="prometheus_client yok")
def test_second_exporter_reuses_prometheus_registry() -> None:
    ns = "test_metrics_dup_ns"
    a = MetricsExporter(port=0, namespace=ns)
    b = MetricsExporter(port=0, namespace=ns)
    assert a._gauges["equity"] is b._gauges["equity"]
    assert a._counters["trades"] is b._counters["trades"]
    b.update({"equity": 1.0})
    b.record_trade(0.0, reason="dup")
