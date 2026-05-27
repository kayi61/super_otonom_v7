"""Backward-compatible shim — ``super_otonom.core.bot_engine``."""
import importlib
import sys

_impl = importlib.import_module("super_otonom.core.bot_engine")
sys.modules[__name__] = _impl
