"""Backward-compatible shim — ``super_otonom.monitoring.deploy_env_check``."""
import importlib
import sys

_impl = importlib.import_module("super_otonom.monitoring.deploy_env_check")
sys.modules[__name__] = _impl
