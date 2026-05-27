"""Backward-compatible shim — ``super_otonom.audit.kanon_drift_check``."""
import importlib
import sys

_impl = importlib.import_module("super_otonom.audit.kanon_drift_check")
sys.modules[__name__] = _impl
