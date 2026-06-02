"""
Explicit test patch registry — production kod buradan import eder (PROMPT-09).

Testler ``super_otonom.bot_patch_registry.<name>`` patch eder; ``bot_engine`` F401 re-export yok.
"""

from __future__ import annotations

from super_otonom.hard_safety_contract import (
    enforce_entry_leverage_cap,
    enforce_entry_prechecks,
    enforce_entry_size_safety,
    gate_global_trade_disable,
    merge_entry_notional,
)
from super_otonom.omega_regime import compute_omega_regime
from super_otonom.signals.signal_quality_scorer import compute_signal_quality

__all__ = [
    "compute_omega_regime",
    "compute_signal_quality",
    "enforce_entry_leverage_cap",
    "enforce_entry_prechecks",
    "enforce_entry_size_safety",
    "gate_global_trade_disable",
    "merge_entry_notional",
]
