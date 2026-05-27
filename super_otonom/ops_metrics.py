"""Backward-compatible shim — ``super_otonom.monitoring.ops_metrics``."""
import importlib
import sys

_impl = importlib.import_module("super_otonom.monitoring.ops_metrics")
sys.modules[__name__] = _impl
