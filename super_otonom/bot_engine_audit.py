"""
BotEngine god-class iddiası repo taraması (audit madde 8).
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import List, Optional, Sequence

from super_otonom.bot_engine_topology import (
    bot_engine_disclosure,
    validate_bot_engine_topology_contract,
)

_REPO = Path(__file__).resolve().parents[1]

_SKIP_PARTS = frozenset(
    {"build", ".venv", "node_modules", "__pycache__", ".git", "pytest-temproot"}
)

_FORBIDDEN_CLAIMS = (
    re.compile(r"\bBotEngine\b.*\bsingle\s+responsibility\b", re.I),
    re.compile(r"\bclean\s+architecture\b.*\bBotEngine\b", re.I),
    re.compile(r"\bhedge[- ]fund.grade\b.*\bBotEngine\b", re.I),
    re.compile(r"\bmodular\s+monolith\b.*\bcomplete\b", re.I),
    re.compile(r"kurumsal.*tek\s+sorumluluk.*BotEngine", re.I),
)

_ALLOWLIST_FILES = (
    "bot_engine_audit.py",
    "bot_engine_topology.py",
    "bot_engine_topology_manifest.json",
    "test_bot_engine_topology",
    "test_audit_modules_coverage",
    "bot_engine.py",
)

_ALLOW_SUBSTR = (
    "audit 8",
    "institutional_single_responsibility_claim_allowed",
    "bot_engine_topology_controlled",
    "god_class",
    "god_class_bot_engine",
    "multi_domain_single_class",
    "partial_delegation",
    "disclaimer_tr",
    "mimari borcu",
    "mimari genişletme",
    "pipelines + BotEngine",
)


def _allowlisted(rel: str, line: str) -> bool:
    low = rel.lower()
    if any(a.lower() in low for a in _ALLOWLIST_FILES):
        return True
    return any(s.lower() in line.lower() for s in _ALLOW_SUBSTR)


def audit_bot_engine_claims(*, root: Optional[Path] = None) -> List[str]:
    base = root or _REPO
    issues: List[str] = list(validate_bot_engine_topology_contract(base))

    bt = base / "super_otonom" / "bot_engine_topology.py"
    if bt.is_file() and "institutional_single_responsibility_claim_allowed" not in bt.read_text(
        encoding="utf-8"
    ):
        issues.append(
            "bot_engine_topology.py: must set institutional_single_responsibility_claim_allowed=False"
        )

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
                        f"{rel}:{i}: forbidden BotEngine architecture claim {pat.pattern!r}"
                    )
                    break
    return issues


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="BotEngine god-class disclosure audit.")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(list(argv) if argv is not None else None)
    issues = audit_bot_engine_claims()
    disc = bot_engine_disclosure()
    payload = {"ok": not issues, "issues": issues, "disclosure": disc}
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print("=== bot_engine_audit ===")
        print(f"OK: {payload['ok']}")
        t = disc["topology"]
        print(
            f"class_lines={t['bot_engine_class_line_count']} "
            f"file_lines={t['file_line_count']} god_class={t['god_class']}"
        )
        for line in issues:
            print(f"  FAIL: {line}")
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
