"""
God package / düz modül iddiası repo taraması (audit madde 7).
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import List, Optional, Sequence

from super_otonom.package_topology import (
    package_disclosure,
    validate_package_topology_contract,
)

_REPO = Path(__file__).resolve().parents[1]

_SKIP_PARTS = frozenset(
    {"build", ".venv", "node_modules", "__pycache__", ".git", "pytest-temproot"}
)

_FORBIDDEN_CLAIMS = (
    re.compile(r"\bclean\s+modular\s+architecture\b", re.I),
    re.compile(r"\bhedge[- ]fund.grade\s+modularity\b", re.I),
    re.compile(r"\bfully\s+modular\s+codebase\b", re.I),
    re.compile(r"\bzero\s+technical\s+debt\b", re.I),
    re.compile(r"kurumsal.*modüler\s+sınır", re.I),
)

_ALLOWLIST_FILES = (
    "package_topology_audit.py",
    "package_topology.py",
    "package_topology_manifest.json",
    "test_package_topology",
    "test_audit_modules_coverage",
)

_ALLOW_SUBSTR = (
    "audit 7",
    "institutional_modular_boundary_claim_allowed",
    "package_topology_controlled",
    "god_package_flat",
    "only_pipelines_subpackage",
    "high_maintenance_surface",
    "flat_super_otonom",
    "disclaimer_tr",
    "modüler sınır iddiası",
    "modular boundary",
)


def _allowlisted(rel: str, line: str) -> bool:
    low = rel.lower()
    if any(a.lower() in low for a in _ALLOWLIST_FILES):
        return True
    ll = line.lower()
    return any(s.lower() in ll for s in _ALLOW_SUBSTR)


def audit_package_topology_claims(*, root: Optional[Path] = None) -> List[str]:
    base = root or _REPO
    issues: List[str] = list(validate_package_topology_contract(base))

    pt = base / "super_otonom" / "package_topology.py"
    if pt.is_file() and "institutional_modular_boundary_claim_allowed" not in pt.read_text(
        encoding="utf-8"
    ):
        issues.append("package_topology.py: must set institutional_modular_boundary_claim_allowed=False")

    for path in sorted(base.rglob("*")):
        if any(part in _SKIP_PARTS for part in path.parts):
            continue
        try:
            if not path.is_file():
                continue
        except OSError:
            continue
        if path.suffix.lower() not in (".py", ".md", ".yml", ".yaml", ".rst"):
            continue
        rel = path.relative_to(base).as_posix()
        if any(a in rel for a in _ALLOWLIST_FILES):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            issues.append(f"{rel}: read error: {exc}")
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if _allowlisted(rel, line):
                continue
            for pat in _FORBIDDEN_CLAIMS:
                if pat.search(line):
                    issues.append(
                        f"{rel}:{i}: forbidden package modularity claim {pat.pattern!r}"
                    )
                    break
    return issues


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="God package / flat module topology audit.")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(list(argv) if argv is not None else None)
    issues = audit_package_topology_claims()
    disc = package_disclosure()
    payload = {"ok": not issues, "issues": issues, "disclosure": disc}
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print("=== package_topology_audit ===")
        print(f"OK: {payload['ok']}")
        t = disc["topology"]
        print(
            f"flat_prod={t['flat_production_count']} "
            f"ceiling={t['flat_production_ceiling']} "
            f"god_package_flat={t['god_package_flat']}"
        )
        for line in issues:
            print(f"  FAIL: {line}")
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
