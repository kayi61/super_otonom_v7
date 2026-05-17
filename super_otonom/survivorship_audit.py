"""
Survivorship / evren iddiası repo taraması (audit madde 4).
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import List, Optional, Sequence

_REPO = Path(__file__).resolve().parents[1]

_FORBIDDEN_CLAIMS = (
    re.compile(r"kurumsal\s+evren\s+backtest", re.I),
    re.compile(r"institutional\s+universe\s+backtest", re.I),
    re.compile(r"survivorship[- ]bias[- ]free", re.I),
)

_REQUIRED_MARKERS = (
    "survivorship_disclosure",
    "backtest_universe",
)

_ALLOWLIST = (
    "survivorship_audit.py",
    "backtest_universe.py",
    "test_survivorship",
    "test_audit_modules_coverage.py",
)


def audit_survivorship_claims(*, root: Optional[Path] = None) -> List[str]:
    base = root or _REPO
    issues: List[str] = []
    for path in sorted(base.rglob("*.py")):
        if "build" in path.parts or ".venv" in path.parts:
            continue
        rel = path.relative_to(base).as_posix()
        if any(a in rel for a in _ALLOWLIST):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            issues.append(f"{rel}: read error: {exc}")
            continue
        for pat in _FORBIDDEN_CLAIMS:
            if pat.search(text):
                issues.append(f"{rel}: forbidden survivorship claim {pat.pattern!r}")
    edge = base / "super_otonom" / "edge_evidence.py"
    if edge.is_file():
        et = edge.read_text(encoding="utf-8")
        if "survivorship_disclosure" not in et:
            issues.append("edge_evidence.py: must include survivorship_disclosure in output")
    bt = base / "super_otonom" / "backtester.py"
    if bt.is_file():
        bt_text = bt.read_text(encoding="utf-8")
        if "survivorship" not in bt_text.lower() and "tek sembol" not in bt_text.lower():
            issues.append("backtester.py: must document single-symbol survivorship limit")
    return issues


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Survivorship claim / disclosure audit.")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(list(argv) if argv is not None else None)
    issues = audit_survivorship_claims()
    payload = {"ok": not issues, "issues": issues, "required_modules": list(_REQUIRED_MARKERS)}
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print("=== survivorship_audit ===")
        print(f"OK: {payload['ok']}")
        for line in issues:
            print(f"  FAIL: {line}")
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
