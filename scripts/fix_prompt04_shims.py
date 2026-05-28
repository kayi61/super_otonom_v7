#!/usr/bin/env python3
"""Fix PROMPT-04 shims: PEP 562 __getattr__ alias (private names + python -m)."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PKG = REPO / "super_otonom"

SHIMS: dict[str, str] = {
    "bot_engine.py": "super_otonom.core.bot_engine",
    "config.py": "super_otonom.core.config",
    "main_loop.py": "super_otonom.core.main_loop",
    "state_machine.py": "super_otonom.core.state_machine",
    "order_engine.py": "super_otonom.trading.order_engine",
    "position_sizer.py": "super_otonom.trading.position_sizer",
    "staged_exit.py": "super_otonom.trading.staged_exit",
    "analyzer.py": "super_otonom.analysis.analyzer",
    "correlation_manager.py": "super_otonom.analysis.correlation_manager",
    "risk_ontology.py": "super_otonom.analysis.risk_ontology",
    "metrics_exporter.py": "super_otonom.monitoring.metrics_exporter",
    "ops_metrics.py": "super_otonom.monitoring.ops_metrics",
    "alert_manager.py": "super_otonom.monitoring.alert_manager",
    "deploy_env_check.py": "super_otonom.monitoring.deploy_env_check",
    "deploy_env_stamp.py": "super_otonom.monitoring.deploy_env_stamp",
    "var_topology.py": "super_otonom.audit.var_topology",
    "var_topology_audit.py": "super_otonom.audit.var_topology_audit",
    "bot_engine_audit.py": "super_otonom.audit.bot_engine_audit",
    "package_topology.py": "super_otonom.audit.package_topology",
    "package_topology_audit.py": "super_otonom.audit.package_topology_audit",
    "execution_topology.py": "super_otonom.audit.execution_topology",
    "kanon_drift_check.py": "super_otonom.audit.kanon_drift_check",
}

ALIAS_ON_IMPORT = {
    "main_loop.py",
}

TEMPLATE_ALIAS = '''\
"""Backward-compatible shim — ``{target}``."""
from __future__ import annotations

import importlib
import sys

_mod = importlib.import_module("{target}")

if __name__ != "__main__":
    # Import-time aliasing: monkeypatch/inspect doğrudan gerçek modüle gider.
    sys.modules[__name__] = _mod
else:
    _main = getattr(_mod, "main", None)
    if _main is not None:
        raise SystemExit(_main())
    import runpy

    runpy.run_module("{target}", alter_sys=True)
'''

TEMPLATE_GETATTR = '''\
"""Backward-compatible shim — ``{target}``."""
from __future__ import annotations

import importlib
from typing import Any

_mod = importlib.import_module("{target}")


def __getattr__(name: str) -> Any:
    return getattr(_mod, name)


def __dir__() -> list[str]:
    return sorted(set(dir(_mod)))


if __name__ == "__main__":
    _main = getattr(_mod, "main", None)
    if _main is not None:
        raise SystemExit(_main())
    import runpy

    runpy.run_module("{target}", alter_sys=True)
'''


def main() -> None:
    for flat, target in SHIMS.items():
        template = TEMPLATE_ALIAS if flat in ALIAS_ON_IMPORT else TEMPLATE_GETATTR
        (PKG / flat).write_text(template.format(target=target), encoding="utf-8")
        print(f"fixed {flat}")


if __name__ == "__main__":
    main()
