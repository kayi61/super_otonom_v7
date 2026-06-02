"""Backward-compatible shim — ``super_otonom.core.bot_patch_registry``."""
from __future__ import annotations

import importlib
from typing import Any

_mod = importlib.import_module("super_otonom.core.bot_patch_registry")


def __getattr__(name: str) -> Any:
    return getattr(_mod, name)


def __dir__() -> list[str]:
    return sorted(set(dir(_mod)))
