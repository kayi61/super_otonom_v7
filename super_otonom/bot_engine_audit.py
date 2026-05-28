"""Backward-compatible shim — ``super_otonom.audit.bot_engine_audit``."""
from __future__ import annotations

import importlib
from typing import Any

_mod = importlib.import_module("super_otonom.audit.bot_engine_audit")


def __getattr__(name: str) -> Any:
    return getattr(_mod, name)


def __dir__() -> list[str]:
    return sorted(set(dir(_mod)))


if __name__ == "__main__":
    _main = getattr(_mod, "main", None)
    if _main is not None:
        raise SystemExit(_main())
    import runpy

    runpy.run_module("super_otonom.audit.bot_engine_audit", alter_sys=True)
