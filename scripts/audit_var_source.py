#!/usr/bin/env python3
"""CI: dağınık VaR formülü — yalnızca super_otonom/risk/ altında olmalı (VR-01)."""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_PKG = _REPO / "super_otonom"

_SKIP_DIRS = frozenset(
    {"build", ".venv", "node_modules", "__pycache__", ".git", "pytest-temproot"}
)

_ALLOW_FILES = frozenset(
    {
        "audit_var_source.py",
        "var_topology.py",
        "var_topology_audit.py",
    }
)

_PATTERNS = (
    re.compile(r"np\.percentile\s*\([^)]*pnl", re.I),
    re.compile(r"np\.percentile\s*\([^)]*var", re.I),
    re.compile(r"def\s+var_parametric\s*\(", re.I),
    re.compile(r"def\s+var_historical\s*\(", re.I),
    re.compile(r"def\s+var_monte_carlo\s*\(", re.I),
    re.compile(r"def\s+cvar_expected_shortfall\s*\(", re.I),
)


def _allowed(path: Path) -> bool:
    rel = path.relative_to(_REPO).as_posix()
    if "super_otonom/risk/" in rel.replace("\\", "/"):
        return True
    if path.name in _ALLOW_FILES:
        return True
    if path.name.startswith("test_") or "/tests/" in rel:
        return True
    if rel.endswith("portfolio_risk_engine.py"):
        return True
    return False


def main() -> int:
    issues: list[str] = []
    for p in sorted(_PKG.rglob("*.py")):
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        if p.name.startswith("test_"):
            continue
        if _allowed(p):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = p.relative_to(_REPO).as_posix()
        for i, line in enumerate(text.splitlines(), start=1):
            for pat in _PATTERNS:
                if pat.search(line):
                    issues.append(f"{rel}:{i}: stray VaR logic {pat.pattern!r}")
                    break
    if issues:
        print("audit_var_source: FAIL")
        for line in issues[:50]:
            print(f"  {line}")
        if len(issues) > 50:
            print(f"  ... and {len(issues) - 50} more")
        return 1
    print("audit_var_source: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
