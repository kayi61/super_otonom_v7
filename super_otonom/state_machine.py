"""Backward-compatible shim — ``super_otonom.core.state_machine``."""
import importlib
import sys

_impl = importlib.import_module("super_otonom.core.state_machine")
sys.modules[__name__] = _impl
