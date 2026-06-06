"""metrics_exporter record_* metotlari gercek kapsama testleri.

Onceki %82; kapsanmayan record_* govdeleri (719-1033) + except + disabled guard'lari.
Gauge/Counter/Histogram mock'lanir (gercek Prometheus REGISTRY cakismasi yok).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import super_otonom.monitoring.metrics_exporter as me

_MOD = "super_otonom.monitoring.metrics_exporter"


def _metrics():
    attrs = [
        "var_historical_95", "var_parametric_95", "var_monte_carlo_95",
        "var_cornish_fisher_95", "var_for_limits_95", "var_historical_99",
        "var_parametric_99", "var_monte_carlo_99", "var_cornish_fisher_99",
        "var_for_limits_99", "var_evt_99", "var_fhs_95", "var_fhs_99",
        "var_regime_conditional_95", "var_regime_conditional_99",
        "cvar_historical_95", "cvar_parametric_95", "cvar_monte_carlo_95",
        "cvar_historical_99", "cvar_parametric_99", "cvar_monte_carlo_99",
        "cvar_975_1d", "cvar_95_1d", "cvar_99_1d", "cvar_evt_99",
        "cvar_fhs_95", "cvar_fhs_99", "stressed_var", "var_10d_99",
        "cvar_10d_975", "model_dispersion_pct", "var_99_1d", "lvar",
    ]
    ns = SimpleNamespace(**{a: 0.01 for a in attrs})
    ns.component_var_per_position = {}
    return ns


def _limits():
    return SimpleNamespace(
        max_var_total_pct=0.05,
        max_cvar_total_pct=0.10,
        max_stressed_var_total_pct=0.15,
        max_lvar_to_nav=0.20,
    )


def _call_all(exp):
    m, lim = _metrics(), _limits()
    exp.record_trade(1.0, "tp")
    exp.inc_order_error("order")
    exp.inc_ws_reconnect()
    exp.set_dependency_up("vault", True)
    exp.set_dependency_up("db", False)
    exp.record_clock_skew("binance", 50)
    exp.record_kupiec(0.5, 3)
    exp.record_pnl_attribution(0.9, 0.1, False)
    exp.record_pnl_attribution(0.5, 0.5, True)
    exp.record_traffic_light("GREEN", 2, 0.0)
    exp.record_traffic_light("RED", 11, 1.0)
    exp.record_christoffersen(0.5, 0.4)
    exp.record_pre_trade_var_gate(True, 0.03, 0.01)
    exp.record_pre_trade_var_gate(False, 0.07, 0.05)
    exp.record_stress_grid(-0.1, 0.05)
    exp.record_lvar("BTCUSDT", 0.04)
    exp.record_var_breach("var_99_breach", 0.06, 0.10, 0.5)
    exp.record_var_breach(None, 0.0, 0.0, 0.0)
    exp.record_var_cap(True, 100.0)
    exp.record_var_cap(False, 0.0)
    exp.record_portfolio_risk(
        {
            "trade_permission": "BLOCK",
            "risk_score": 5,
            "portfolio_risk": {"var_max": 0.1, "cvar": 0.12, "herfindahl_hhi": 0.3},
        }
    )
    exp.record_host_ntp(True)
    exp.record_host_ntp(False)
    exp.record_host_ntp(None)
    exp.record_performance(1e6, 5.0)
    exp.record_var_suite(m, limits=lim, component_var={"BTCUSDT": 0.02})
    exp.record_var_suite(m)  # limits/component dalsiz


@pytest.fixture()
def exporter():
    """Mock'lanmis Gauge/Counter/Histogram ile MetricsExporter (enabled, server yok)."""
    with patch.object(me, "_PROMETHEUS_AVAILABLE", True), \
         patch.object(me, "Gauge", lambda *a, **k: MagicMock()), \
         patch.object(me, "Counter", lambda *a, **k: MagicMock()), \
         patch.object(me, "Histogram", lambda *a, **k: MagicMock()), \
         patch.object(me, "start_http_server", lambda *a, **k: None):
        exp = me.MetricsExporter(port=0)
        yield exp


def test_record_all_enabled(exporter):
    assert exporter.is_active is True
    _call_all(exporter)  # tum govdeler kosar, exception yok


def test_record_all_except_paths(exporter):
    # _gauges/_counters/_histos erisimi patlasin -> her metodun except blogu kapsanir
    class _Boom(dict):
        def __getitem__(self, k):
            # KeyError: hem genis 'except Exception' hem de record_var_suite'in
            # 'except (KeyError, TypeError, ValueError)' bloklarinca yakalanir.
            raise KeyError(k)

    exporter._gauges = _Boom()
    exporter._counters = _Boom()
    exporter._histos = _Boom()
    _call_all(exporter)  # tum except'ler yutulur, test patlamaz


def test_record_all_disabled():
    # prometheus yokmus gibi -> _enabled False -> tum metotlar erken return
    with patch.object(me, "_PROMETHEUS_AVAILABLE", False):
        exp = me.MetricsExporter(port=0)
        assert exp.is_active is False
        _call_all(exp)  # hepsi no-op


def test_repr_contains_enabled(exporter):
    assert "enabled=" in repr(exporter)
