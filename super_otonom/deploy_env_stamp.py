"""Backward-compatible shim — ``super_otonom.monitoring.deploy_env_stamp``."""
from __future__ import annotations

import importlib
import sys

_mod = importlib.import_module("super_otonom.monitoring.deploy_env_stamp")

if __name__ != "__main__":
    # Import-time aliasing: monkeypatch/inspect doğrudan gerçek modüle gider.
    sys.modules[__name__] = _mod
else:
    _main = getattr(_mod, "main", None)
    if _main is not None:
        raise SystemExit(_main())
    import runpy

    runpy.run_module("super_otonom.monitoring.deploy_env_stamp", alter_sys=True)
