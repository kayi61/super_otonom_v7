"""Backward-compatible shim — ``super_otonom.analysis.correlation_manager``."""
import importlib
import sys

_impl = importlib.import_module("super_otonom.analysis.correlation_manager")
sys.modules[__name__] = _impl
