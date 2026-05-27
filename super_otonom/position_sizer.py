"""Backward-compatible shim — ``super_otonom.trading.position_sizer``."""
import importlib
import sys

_impl = importlib.import_module("super_otonom.trading.position_sizer")
sys.modules[__name__] = _impl
