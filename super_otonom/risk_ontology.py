"""Backward-compatible shim — ``super_otonom.analysis.risk_ontology``."""
import importlib
import sys

_impl = importlib.import_module("super_otonom.analysis.risk_ontology")
sys.modules[__name__] = _impl
