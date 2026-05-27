"""Backward-compatible shim — ``super_otonom.trading.staged_exit``."""
import importlib
import sys

_impl = importlib.import_module("super_otonom.trading.staged_exit")
sys.modules[__name__] = _impl
