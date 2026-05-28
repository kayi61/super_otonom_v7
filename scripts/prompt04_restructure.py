#!/usr/bin/env python3
"""PROMPT-04: move flat modules into subpackages + root compatibility shims."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PKG = REPO / "super_otonom"

MOVES: dict[str, list[str]] = {
    "core": [
        "bot_engine.py",
        "config.py",
        "main_loop.py",
        "state_machine.py",
    ],
    "trading": [
        "order_engine.py",
        "position_sizer.py",
        "staged_exit.py",
    ],
    "analysis": [
        "analyzer.py",
        "correlation_manager.py",
        "risk_ontology.py",
    ],
    "monitoring": [
        "metrics_exporter.py",
        "ops_metrics.py",
        "alert_manager.py",
        "deploy_env_check.py",
        "deploy_env_stamp.py",
    ],
    "audit": [
        "var_topology.py",
        "var_topology_audit.py",
        "bot_engine_audit.py",
        "package_topology.py",
        "package_topology_audit.py",
        "execution_topology.py",
        "kanon_drift_check.py",
    ],
}

SHIM_TEMPLATE = '''\
"""Backward-compatible shim — use ``super_otonom.{subpkg}.{mod}``."""
from super_otonom.{subpkg}.{mod} import *  # noqa: F403
'''

INIT_TEMPLATE = '''\
"""PROMPT-04: ``super_otonom.{subpkg}`` subpackage."""
'''

# Files moved one level deeper: repo root was parents[1], now parents[2].
REPO_ROOT_FIX_FILES = {
    "audit/package_topology.py",
    "audit/var_topology.py",
    "audit/var_topology_audit.py",
    "audit/bot_engine_audit.py",
    "audit/execution_topology.py",
    "audit/kanon_drift_check.py",
    "monitoring/deploy_env_check.py",
}


def _fix_repo_paths(text: str) -> str:
    return text.replace("parents[1]", "parents[2]")


def main() -> None:
    for subpkg, modules in MOVES.items():
        dest_dir = PKG / subpkg
        dest_dir.mkdir(parents=True, exist_ok=True)
        init_py = dest_dir / "__init__.py"
        if not init_py.exists():
            init_py.write_text(INIT_TEMPLATE.format(subpkg=subpkg), encoding="utf-8")

        for mod_file in modules:
            src = PKG / mod_file
            if not src.is_file():
                print(f"SKIP missing: {mod_file}")
                continue
            dst = dest_dir / mod_file
            if dst.exists():
                print(f"SKIP already moved: {subpkg}/{mod_file}")
                continue
            shutil.move(str(src), str(dst))
            rel = f"{subpkg}/{mod_file}"
            if rel in REPO_ROOT_FIX_FILES:
                dst.write_text(_fix_repo_paths(dst.read_text(encoding="utf-8")), encoding="utf-8")
            mod = mod_file[:-3]
            shim = PKG / mod_file
            shim.write_text(SHIM_TEMPLATE.format(subpkg=subpkg, mod=mod), encoding="utf-8")
            print(f"OK {mod_file} -> {subpkg}/ + shim")

    subprocess.run(["git", "add", "-A", "super_otonom"], cwd=REPO, check=False)
    print("Done. Run: ruff check super_otonom tests && pytest")


if __name__ == "__main__":
    main()
