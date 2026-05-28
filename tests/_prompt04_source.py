"""PROMPT-04: kök shim yerine alt paketteki kaynak dosyayı oku (testler)."""

from __future__ import annotations

from pathlib import Path

# flat_name -> impl path under super_otonom/
_MOVED: dict[str, str] = {
    "risk_ontology": "analysis/risk_ontology.py",
    "order_engine": "trading/order_engine.py",
    "alert_manager": "monitoring/alert_manager.py",
    "main_loop": "core/main_loop.py",
    "bot_engine": "core/bot_engine.py",
    "config": "core/config.py",
    "metrics_exporter": "monitoring/metrics_exporter.py",
    "var_topology_audit": "audit/var_topology_audit.py",
}

# pytest patch targets (impl module, not root shim)
METRICS_EXPORTER_PATCH = "super_otonom.monitoring.metrics_exporter"


def module_source_path(pkg_root: Path, name: str) -> Path:
    rel = _MOVED.get(name, f"{name}.py")
    impl = pkg_root / rel
    if impl.is_file():
        return impl
    return pkg_root / f"{name}.py"


def read_module_source(pkg_root: Path, name: str) -> str:
    return module_source_path(pkg_root, name).read_text(encoding="utf-8")
