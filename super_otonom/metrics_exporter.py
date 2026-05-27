"""Backward-compatible shim — ``super_otonom.monitoring.metrics_exporter``."""
import importlib
import sys

_impl = importlib.import_module("super_otonom.monitoring.metrics_exporter")
sys.modules[__name__] = _impl
