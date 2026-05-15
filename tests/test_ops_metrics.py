"""ops_metrics ve yeni MetricsExporter yollari."""

from __future__ import annotations

import json
import logging

from super_otonom import ops_metrics
from super_otonom.metrics_exporter import MetricsExporter
from super_otonom.structured_logging import JsonFormatter, configure_logging


def test_ops_metrics_noop_without_bind() -> None:
    ops_metrics.bind_metrics(None)
    ops_metrics.inc_order_error("order")
    ops_metrics.inc_ws_reconnect()
    ops_metrics.set_dependency_up("vault", True)
    ops_metrics.refresh_dependencies()


def test_metrics_exporter_ops_methods_no_crash() -> None:
    m = MetricsExporter(port=0, namespace="test_ops_metrics")
    ops_metrics.bind_metrics(m)
    m.inc_order_error("order")
    m.inc_ws_reconnect()
    m.set_dependency_up("vault", True)
    m.set_dependency_up("timescale", False)
    ops_metrics.inc_order_error("order")
    ops_metrics.inc_ws_reconnect()
    ops_metrics.set_dependency_up("vault", False)


def test_structured_logging_json_format() -> None:
    configure_logging(level=logging.INFO, fmt="json")
    root = logging.getLogger()
    assert len(root.handlers) == 1
    fmt = root.handlers[0].formatter
    assert isinstance(fmt, JsonFormatter)
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="hello",
        args=(),
        exc_info=None,
    )
    line = fmt.format(record)
    payload = json.loads(line)
    assert payload["msg"] == "hello"
    assert payload["level"] == "INFO"
    configure_logging(level=logging.INFO, fmt="text")
