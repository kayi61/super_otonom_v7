"""Backward-compatible shim — ``super_otonom.audit.package_topology_audit``."""
import importlib
import sys

_impl = importlib.import_module("super_otonom.audit.package_topology_audit")
sys.modules[__name__] = _impl
