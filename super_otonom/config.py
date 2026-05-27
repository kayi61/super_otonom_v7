"""Backward-compatible shim — ``super_otonom.core.config``."""
import importlib
import sys

_impl = importlib.import_module("super_otonom.core.config")
sys.modules[__name__] = _impl
