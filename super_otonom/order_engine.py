"""Backward-compatible shim — ``super_otonom.trading.order_engine``."""
import importlib
import sys

_impl = importlib.import_module("super_otonom.trading.order_engine")
sys.modules[__name__] = _impl
