"""Backward-compatible shim — ``super_otonom.core.main_loop``."""
import importlib
import sys

_impl = importlib.import_module("super_otonom.core.main_loop")
sys.modules[__name__] = _impl
