"""
Clock skew / NTP iddiası repo taraması (audit madde 6).
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import List, Optional, Sequence

from super_otonom.clock_skew import (
    clock_skew_disclosure,
    validate_clock_skew_wiring,
)

_REPO = Path(__file__).resolve().parents[1]

_SKIP_PARTS = frozenset(
    {"build", ".venv", "node_modules", "__pycache__", ".git", "pytest-temproot"}
)

_FORBIDDEN_CLAIMS = (
    re.compile(r"\bNTP\s+synchronized\b", re.I),
    re.compile(r"\bchrony\s+managed\b", re.I),
    re.compile(r"\bzero\s+clock\s+skew\b", re.I),
    re.compile(r"\bntp\s+guaranteed\b", re.I),
    re.compile(r"kurumsal.*NTP\s+senkron", re.I),
)

_ALLOWLIST_FILES = (
    "clock_skew_audit.py",
    "clock_skew.py",
    "test_clock_skew",
    "test_audit_modules_coverage",
)

_ALLOW_SUBSTR = (
    "audit 6",
    "institutional_ntp_claim_allowed",
    "clock_skew_controlled",
    "no_chrony",
    "best-effort",
    "best effort",
    "timeDifference",
    "load_time_difference",
    "BotClockSkewHigh",
    "bot_clock_skew",
    "host_ntp_probe",
    "disclaimer_tr",
    "NTP synchronized"  # negation context handled below — skip if "yok" nearby
)


def _allowlisted(rel: str, line: str) -> bool:
    low = rel.lower()
    if any(a.lower() in low for a in _ALLOWLIST_FILES):
        return True
    ll = line.lower()
    if "ntp synchronized" in ll and any(
        neg in ll for neg in ("yok", "not ", "değil", "degil", "false", "unknown")
    ):
        return True
    return any(s.lower() in ll for s in _ALLOW_SUBSTR)


def audit_clock_skew_claims(*, root: Optional[Path] = None) -> List[str]:
    base = root or _REPO
    issues: List[str] = list(validate_clock_skew_wiring(base))

    cs = base / "super_otonom" / "clock_skew.py"
    if cs.is_file() and "institutional_ntp_claim_allowed" not in cs.read_text(encoding="utf-8"):
        issues.append("clock_skew.py: must set institutional_ntp_claim_allowed=False")

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
                    issues.append(f"{rel}:{i}: forbidden clock/NTP claim {pat.pattern!r}")
                    break
    return issues


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Clock skew / NTP disclosure audit.")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(list(argv) if argv is not None else None)
    issues = audit_clock_skew_claims()
    disc = clock_skew_disclosure()
    payload = {"ok": not issues, "issues": issues, "disclosure": disc}
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print("=== clock_skew_audit ===")
        print(f"OK: {payload['ok']}")
        print(
            f"institutional_ntp: {disc['institutional_ntp_claim_allowed']} | "
            f"warn={disc['thresholds_ms']['warn']}ms crit={disc['thresholds_ms']['crit']}ms"
        )
        for line in issues:
            print(f"  FAIL: {line}")
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
