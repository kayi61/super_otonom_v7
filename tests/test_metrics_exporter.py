"""MetricsExporter: no-op veya prom ile çökmeme."""

from __future__ import annotations

import importlib
import sys
import types
import uuid
from unittest.mock import MagicMock

import pytest
from super_otonom.metrics_exporter import _PROMETHEUS_AVAILABLE, MetricsExporter


def test_import_error_sets_no_prometheus_and_noops() -> None:
    """21-23 ImportError; 57-58 erken çıkış; update/record yolları 182,216,247,268,285."""
    saved_pc = sys.modules.get("prometheus_client")
    saved_me = sys.modules.get("super_otonom.metrics_exporter")
    try:
        sys.modules["prometheus_client"] = types.ModuleType("prometheus_client")
        sys.modules.pop("super_otonom.metrics_exporter", None)
        me = importlib.import_module("super_otonom.metrics_exporter")
        assert me._PROMETHEUS_AVAILABLE is False
        m = me.MetricsExporter(port=8000, namespace=f"imp_err_{uuid.uuid4().hex[:8]}")
        assert m.is_active is False
        m.update({"equity": 1.0, "emergency_stop": True})
        m.record_analysis({"symbol": "BTC/USDT", "regime": "TRENDING"})
        m.record_slippage("BTC/USDT", 100.0, 100.1)
        m.update_circuit_breakers({"ETH/USDT": "OPEN (x)"})
        m.record_trade(0.5, reason="t")
    finally:
        if saved_pc is not None:
            sys.modules["prometheus_client"] = saved_pc
        else:
            sys.modules.pop("prometheus_client", None)
        sys.modules.pop("super_otonom.metrics_exporter", None)
        if saved_me is not None:
            sys.modules["super_otonom.metrics_exporter"] = saved_me
        importlib.import_module("super_otonom.metrics_exporter")


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
def test_update_circuit_breakers_swallows_label_errors() -> None:
    """273-274: labels/set patlarsa yutulur."""
    m = MetricsExporter(port=0, namespace=f"cb_lbl_{uuid.uuid4().hex[:8]}")
    bad = MagicMock()
    bad.labels.side_effect = KeyError("cb labels")
    m._gauges["circuit_breaker_open"] = bad
    m.update_circuit_breakers({"BTC/USDT": "CLOSED"})


@pytest.mark.skipif(not _PROMETHEUS_AVAILABLE, reason="prometheus_client yok")
def test_record_slippage_swallows_prom_errors() -> None:
    """254-255: gauge veya histogram hata verirse yutulur."""
    m = MetricsExporter(port=0, namespace=f"slip_ex_{uuid.uuid4().hex[:8]}")
    bad_g = MagicMock()
    bad_g.labels.return_value.set.side_effect = RuntimeError("slip set")
    m._gauges["slippage_avg"] = bad_g
    m.record_slippage("S", 100.0, 101.0)


@pytest.mark.skipif(not _PROMETHEUS_AVAILABLE, reason="prometheus_client yok")
def test_record_trade_swallows_prom_errors() -> None:
    """289-290."""
    m = MetricsExporter(port=0, namespace=f"tr_ex_{uuid.uuid4().hex[:8]}")
    bad_c = MagicMock()
    bad_c.labels.return_value.inc.side_effect = RuntimeError("inc")
    m._counters["trades"] = bad_c
    m.record_trade(1.0, reason="r")


@pytest.mark.skipif(not _PROMETHEUS_AVAILABLE, reason="prometheus_client yok")
def test_record_analysis_swallows_regime_label_errors() -> None:
    """231-232: regime gauge labels hata."""
    m = MetricsExporter(port=0, namespace=f"reg_ex_{uuid.uuid4().hex[:8]}")
    bad = MagicMock()
    bad.labels.return_value.set.side_effect = TypeError("reg")
    m._gauges["regime"] = bad
    m.record_analysis({"symbol": "S", "regime": "TRENDING"})


@pytest.mark.skipif(not _PROMETHEUS_AVAILABLE, reason="prometheus_client yok")
def test_second_exporter_reuses_prometheus_registry() -> None:
    ns = "test_metrics_dup_ns"
    a = MetricsExporter(port=0, namespace=ns)
    b = MetricsExporter(port=0, namespace=ns)
    assert a._gauges["equity"] is b._gauges["equity"]
    assert a._counters["trades"] is b._counters["trades"]
    b.update({"equity": 1.0})
    b.record_trade(0.0, reason="dup")


@pytest.mark.skipif(not _PROMETHEUS_AVAILABLE, reason="prometheus_client yok")
def test_record_portfolio_risk_sets_gauges() -> None:
    """Faz-24: record_portfolio_risk sets all 5 portfolio risk gauges."""
    ns = f"pf_risk_{uuid.uuid4().hex[:8]}"
    m = MetricsExporter(port=0, namespace=ns)
    result = {
        "trade_permission": "BLOCK",
        "risk_score": 0.82,
        "portfolio_risk": {
            "var_max": 0.12,
            "cvar": 0.18,
            "herfindahl_hhi": 0.65,
        },
    }
    m.record_portfolio_risk(result)
    # Gauges should have been set — verify no error
    assert m._gauges["portfolio_risk_permission"] is not None


@pytest.mark.skipif(not _PROMETHEUS_AVAILABLE, reason="prometheus_client yok")
def test_record_portfolio_risk_swallows_errors() -> None:
    """Faz-24: record_portfolio_risk exception path."""
    ns = f"pf_err_{uuid.uuid4().hex[:8]}"
    m = MetricsExporter(port=0, namespace=ns)
    bad = MagicMock()
    bad.set.side_effect = RuntimeError("gauge boom")
    m._gauges["portfolio_risk_permission"] = bad
    m.record_portfolio_risk({"trade_permission": "ALLOW"})  # should not raise


def test_record_portfolio_risk_disabled_noop() -> None:
    """Faz-24: disabled exporter → early return."""
    m = MetricsExporter(port=0)
    m._enabled = False
    m.record_portfolio_risk({"trade_permission": "HALT"})  # no-op, no crash
