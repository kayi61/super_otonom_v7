"""
Paket içi test modülü iddiası repo taraması (audit madde 9).
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import List, Optional, Sequence

from super_otonom.layout_topology import (
    layout_disclosure,
    validate_test_layout_contract,
)

_REPO = Path(__file__).resolve().parents[1]

_SKIP_PARTS = frozenset(
    {"build", ".venv", "node_modules", "__pycache__", ".git", "pytest-temproot"}
)

_FORBIDDEN_CLAIMS = (
    re.compile(r"\bproduction[- ]ready\s+test\s+layout\b", re.I),
    re.compile(r"\bno\s+test\s+files\s+in\s+package\b", re.I),
    re.compile(r"\bclean\s+package\s+without\s+tests\b", re.I),
    re.compile(r"kurumsal.*temiz\s+paket.*test", re.I),
)

_ALLOWLIST_FILES = (
    "layout_topology_audit.py",
    "layout_topology.py",
    "test_layout_manifest.json",
    "test_test_layout",
    "test_audit_modules_coverage",
    "_setup_build.py",
    "pyproject.toml",
)

_ALLOW_SUBSTR = (
    "audit 9",
    "institutional_production_test_layout_claim_allowed",
    "test_layout_controlled",
    "migration_debt",
    "canonical_test_dir",
    "wheel_must_exclude",
    "BuildPyExcludeInPackageTests",
    "testpaths",
    "disclaimer_tr",
    "geçiş dönemi",
    "gecis donemi",
)


def _allowlisted(rel: str, line: str) -> bool:
    low = rel.lower()
    if any(a.lower() in low for a in _ALLOWLIST_FILES):
        return True
    return any(s.lower() in line.lower() for s in _ALLOW_SUBSTR)


def audit_test_layout_claims(
    *,
    root: Optional[Path] = None,
    verify_wheel: bool = False,
) -> List[str]:
    base = root or _REPO
    issues: List[str] = list(
        validate_test_layout_contract(base, verify_wheel=verify_wheel)
    )

    tl = base / "super_otonom" / "layout_topology.py"
    if tl.is_file() and "institutional_production_test_layout_claim_allowed" not in tl.read_text(
        encoding="utf-8"
    ):
        issues.append(
            "layout_topology.py: must set institutional_production_test_layout_claim_allowed=False"
        )

    for path in sorted(base.rglob("*")):
        if any(part in _SKIP_PARTS for part in path.parts):
            continue
        try:
            if not path.is_file():
                continue
        except OSError:
            continue
        if path.suffix.lower() not in (".py", ".md", ".yml", ".yaml", ".rst", ".toml"):
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
                        f"{rel}:{i}: forbidden test layout claim {pat.pattern!r}"
                    )
                    break
    return issues


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="In-package test module layout audit.")
    p.add_argument("--json", action="store_true")
    p.add_argument(
        "--verify-wheel",
        action="store_true",
        help="Build wheel and assert super_otonom/test_*.py excluded",
    )
    args = p.parse_args(list(argv) if argv is not None else None)
    issues = audit_test_layout_claims(verify_wheel=args.verify_wheel)
    disc = layout_disclosure()
    payload = {"ok": not issues, "issues": issues, "disclosure": disc}
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print("=== test_layout_audit ===")
        print(f"OK: {payload['ok']}")
        t = disc["topology"]
        print(
            f"in_package={t['in_package_test_count']} "
            f"canonical={t['canonical_test_file_count']} "
            f"institutional_layout={disc['institutional_production_test_layout_claim_allowed']}"
        )
        for line in issues:
            print(f"  FAIL: {line}")
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
