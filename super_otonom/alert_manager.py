"""Backward-compatible shim — ``super_otonom.monitoring.alert_manager``."""
import importlib
import sys

_impl = importlib.import_module("super_otonom.monitoring.alert_manager")
sys.modules[__name__] = _impl
