"""prometheus_client shim + metrics_exporter yeniden yükleme — tam init kapsamı."""
from __future__ import annotations

import importlib
import sys
import types


def _fake_prometheus_module():
    m = types.ModuleType("prometheus_client")

    class _B:
        def __init__(self, *a, **k) -> None:
            pass

        def set(self, *a, **k) -> None:
            pass

        def labels(self, **k):
            return self

        def inc(self, *a, **k) -> None:
            pass

        def observe(self, *a, **k) -> None:
            pass

    m.Gauge = _B
    m.Counter = _B
    m.Histogram = _B

    def _start_http_server(_port: int) -> None:
        return None

    m.start_http_server = _start_http_server
    return m


def test_metrics_exporter_full_path_with_shim() -> None:
    saved_pc = sys.modules.get("prometheus_client")
    saved_me = sys.modules.get("super_otonom.metrics_exporter")
    try:
        sys.modules["prometheus_client"] = _fake_prometheus_module()
        if saved_me:
            del sys.modules["super_otonom.metrics_exporter"]
        me = importlib.import_module("super_otonom.metrics_exporter")
        m = me.MetricsExporter(port=0, namespace="shim_test")
        assert m.is_active
        m.update(
            {
                "equity": 100.0,
                "free_capital": 50.0,
                "total_pnl": 1.0,
                "pnl_pct": 0.1,
                "open_positions": 0,
                "trades_today": 0,
                "total_trades": 1,
                "win_rate": 55.0,
                "rr_ratio": 1.2,
                "var_95": 0.01,
                "daily_loss": 0.0,
                "peak_drawdown_pct": 1.0,
                "emergency_stop": False,
                "dynamic_daily_limit": 3.0,
            }
        )
        m.record_analysis(
            {
                "symbol": "BTC/USDT",
                "hurst": 0.6,
                "volatility": 0.02,
                "regime": "TRENDING",
            }
        )
        m.record_slippage("BTC/USDT", 100.0, 100.05)
        m.update_circuit_breakers({"BTC/USDT": "OPEN (x)"})
        m.record_trade(1.5, reason="tp")
        assert "shim_test" in repr(m)
    finally:
        if saved_pc is not None:
            sys.modules["prometheus_client"] = saved_pc
        else:
            sys.modules.pop("prometheus_client", None)
        if saved_me is not None:
            sys.modules["super_otonom.metrics_exporter"] = saved_me
        else:
            sys.modules.pop("super_otonom.metrics_exporter", None)
            importlib.import_module("super_otonom.metrics_exporter")
