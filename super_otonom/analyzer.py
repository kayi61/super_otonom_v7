"""Backward-compatible shim — ``super_otonom.analysis.analyzer``."""
import importlib
import sys

_impl = importlib.import_module("super_otonom.analysis.analyzer")
sys.modules[__name__] = _impl
