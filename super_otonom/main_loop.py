"""Backward-compatible shim — ``super_otonom.core.main_loop``."""
from __future__ import annotations

import importlib
import sys

_PARENT = "super_otonom.core"
_TARGET = "super_otonom.core.main_loop"

# Parent paket zinciri reload/xdist için sys.modules'ta kalmalı (test_ai_layer_paths vb.).
importlib.import_module("super_otonom")
importlib.import_module(_PARENT)
_mod = importlib.import_module(_TARGET)

if __name__ != "__main__":
    # Import-time aliasing: monkeypatch/inspect doğrudan gerçek modüle gider.
    sys.modules[_PARENT] = importlib.import_module(_PARENT)
    sys.modules[_TARGET] = _mod
    sys.modules[__name__] = _mod
else:
    import asyncio

    _main = getattr(_mod, "main", None)
    if _main is None:
        import runpy

        runpy.run_module("super_otonom.core.main_loop", run_name="__main__", alter_sys=True)
    elif asyncio.iscoroutinefunction(_main):
        # main() async coroutine — asyncio.run ile calistirilmali.
        # Dogrudan _main() cagirmak coroutine'i await ETMEZ -> bot HIC baslamaz.
        try:
            raise SystemExit(asyncio.run(_main()))
        except KeyboardInterrupt:
            raise SystemExit(0) from None
    else:
        raise SystemExit(_main())
