"""prometheus_client yokken bile ValueError → REGISTRY yolunu kapsar (shim)."""

from __future__ import annotations

import importlib
import sys
import types


def _build_shim_with_registry() -> types.ModuleType:
    m = types.ModuleType("prometheus_client")
    reg: dict[str, object] = {}

    class Gauge:
        def __init__(self, name: str, *a, **k) -> None:
            if name in reg:
                raise ValueError("duplicate")
            self._n = name
            reg[name] = self

        def set(self, *a, **k) -> None:
            return None

        def labels(self, **k) -> "Gauge":
            return self

    class Counter:
        def __init__(self, name: str, *a, **k) -> None:
            if name in reg:
                raise ValueError("duplicate")
            self._n = name
            reg[name] = self

        def labels(self, **k) -> "Counter":
            return self

        def inc(self, *a, **k) -> None:
            return None

    class Histogram:
        def __init__(self, name: str, *a, **k) -> None:
            if name in reg:
                raise ValueError("duplicate")
            self._n = name
            reg[name] = self

        def observe(self, *a, **k) -> None:
            return None

    class _R:
        _names_to_collectors = reg

    m.Gauge = Gauge
    m.Counter = Counter
    m.Histogram = Histogram
    m.REGISTRY = _R()
    m.start_http_server = lambda *a, **k: None
    return m


def test_metrics_exporter_second_init_uses_registry_get() -> None:
    saved = sys.modules.get("prometheus_client")
    saved_me = sys.modules.get("super_otonom.monitoring.metrics_exporter")
    try:
        sys.modules["prometheus_client"] = _build_shim_with_registry()
        if saved_me:
            del sys.modules["super_otonom.monitoring.metrics_exporter"]
        me = importlib.import_module("super_otonom.monitoring.metrics_exporter")
        ns = "mdup_shim"
        a = me.MetricsExporter(port=0, namespace=ns)
        b = me.MetricsExporter(port=0, namespace=ns)
        assert a._gauges.get("equity") is b._gauges.get("equity")
    finally:
        if saved is not None:
            sys.modules["prometheus_client"] = saved
        else:
            sys.modules.pop("prometheus_client", None)
        if saved_me is not None:
            sys.modules["super_otonom.monitoring.metrics_exporter"] = saved_me
        else:
            sys.modules.pop("super_otonom.monitoring.metrics_exporter", None)
            importlib.import_module("super_otonom.monitoring.metrics_exporter")


def test_metrics_exporter_update_and_record_paths_shim() -> None:
    saved = sys.modules.get("prometheus_client")
    saved_me = sys.modules.get("super_otonom.monitoring.metrics_exporter")
    try:
        sys.modules["prometheus_client"] = _build_shim_with_registry()
        if saved_me:
            del sys.modules["super_otonom.monitoring.metrics_exporter"]
        me = importlib.import_module("super_otonom.monitoring.metrics_exporter")
        ex = me.MetricsExporter(port=0, namespace="path_shim")
        ex.update({"equity": "x", "open_positions": object()})
        ex.update({"equity": 1.0})
        ex.record_analysis({"symbol": "S", "hurst": 0.5, "volatility": 0.1, "regime": "TRENDING"})
        ex.record_slippage("S", 0.0, 1.0)
        ex.update_circuit_breakers({"A": "OPEN (x)"})
        ex.record_trade(1.0, reason="t")
    finally:
        if saved is not None:
            sys.modules["prometheus_client"] = saved
        else:
            sys.modules.pop("prometheus_client", None)
        if saved_me is not None:
            sys.modules["super_otonom.monitoring.metrics_exporter"] = saved_me
        else:
            sys.modules.pop("super_otonom.monitoring.metrics_exporter", None)
            importlib.import_module("super_otonom.monitoring.metrics_exporter")


def test_metrics_start_http_succeeds_in_shim() -> None:
    saved = sys.modules.get("prometheus_client")
    saved_me = sys.modules.get("super_otonom.monitoring.metrics_exporter")
    try:
        sys.modules["prometheus_client"] = _build_shim_with_registry()
        if saved_me:
            del sys.modules["super_otonom.monitoring.metrics_exporter"]
        me = importlib.import_module("super_otonom.monitoring.metrics_exporter")
        me.MetricsExporter(port=1, namespace="http_ok_shim")
    finally:
        if saved is not None:
            sys.modules["prometheus_client"] = saved
        else:
            sys.modules.pop("prometheus_client", None)
        if saved_me is not None:
            sys.modules["super_otonom.monitoring.metrics_exporter"] = saved_me
        else:
            sys.modules.pop("super_otonom.monitoring.metrics_exporter", None)
            importlib.import_module("super_otonom.monitoring.metrics_exporter")


def test_metrics_start_http_oserror_in_shim(caplog) -> None:
    saved = sys.modules.get("prometheus_client")
    saved_me = sys.modules.get("super_otonom.monitoring.metrics_exporter")
    try:
        m = _build_shim_with_registry()

        def boom(*a, **k) -> None:
            raise OSError("bind")

        m.start_http_server = boom
        sys.modules["prometheus_client"] = m
        if saved_me:
            del sys.modules["super_otonom.monitoring.metrics_exporter"]
        me_mod = importlib.import_module("super_otonom.monitoring.metrics_exporter")
        with caplog.at_level("ERROR", logger="super_otonom.metrics"):
            me_mod.MetricsExporter(port=9999, namespace="oserr_shim")
    finally:
        if saved is not None:
            sys.modules["prometheus_client"] = saved
        else:
            sys.modules.pop("prometheus_client", None)
        if saved_me is not None:
            sys.modules["super_otonom.monitoring.metrics_exporter"] = saved_me
        else:
            sys.modules.pop("super_otonom.monitoring.metrics_exporter", None)
            importlib.import_module("super_otonom.monitoring.metrics_exporter")
