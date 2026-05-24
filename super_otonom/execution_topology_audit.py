"""
TWAP/VWAP yürütme iddiası repo taraması (audit madde 10).
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import List, Optional, Sequence

from super_otonom.execution_topology import (
    execution_disclosure,
    validate_execution_topology_contract,
)

_REPO = Path(__file__).resolve().parents[1]

_SKIP_PARTS = frozenset(
    {"build", ".venv", "node_modules", "__pycache__", ".git", "pytest-temproot"}
)

_FORBIDDEN_CLAIMS = (
    re.compile(r"\bfull\s+TWAP/VWAP\s+execution\b", re.I),
    re.compile(r"\binstitutional\s+algo\s+execution\b", re.I),
    re.compile(r"\bTWAP/VWAP\s+order\s+router\b", re.I),
    re.compile(r"\bhiç\s+VWAP\s+yok\b", re.I),
    re.compile(r"\bno\s+VWAP\s+at\s+all\b", re.I),
    re.compile(r"\bproduction[- ]ready\s+TWAP\b", re.I),
    re.compile(r"kurumsal.*TWAP.*yürüt", re.I),
    re.compile(r"kurumsal.*VWAP.*yürüt", re.I),
)

_ALLOWLIST_FILES = (
    "execution_topology_audit.py",
    "execution_topology.py",
    "execution_topology_manifest.json",
    "test_execution_topology",
    "test_audit_modules_coverage",
    "test_twap_vwap_execution",
    "hft_signal_engine.py",
    "regime_adaptive_execution_engine.py",
    "mm_whale_consensus_controller.py",
    "autonomous_decision_core.py",
    "execution_pipeline.py",
    "institutional_fingerprint_engine.py",
    "INSTITUTIONAL_CONTROL_CHECKLIST_TR.md",
    "execution/twap.py",
    "execution/vwap.py",
    "execution/base.py",
    "execution/__init__.py",
)

_ALLOW_SUBSTR = (
    "audit 10",
    "institutional_twap_vwap_execution_claim_allowed",
    "execution_topology_controlled",
    "vwap_signal_not_execution",
    "twap_metadata_not_algo_router",
    "metadata etiketi",
    "metadata etiket",
    "sinyal/analitik",
    "twap_fingerprint",
    "vwap_deviation",
    "disclaimer_tr",
    "hiç yok değil",
    "execution TWAP/VWAP yok",
    "implemente edilmemiş",
)


def _allowlisted(rel: str, line: str) -> bool:
    low = rel.lower()
    if any(a.lower() in low for a in _ALLOWLIST_FILES):
        return True
    return any(s.lower() in line.lower() for s in _ALLOW_SUBSTR)


def audit_execution_topology_claims(*, root: Optional[Path] = None) -> List[str]:
    base = root or _REPO
    issues: List[str] = list(validate_execution_topology_contract(base))

    et = base / "super_otonom" / "execution_topology.py"
    if et.is_file() and "institutional_twap_vwap_execution_claim_allowed" not in et.read_text(
        encoding="utf-8"
    ):
        issues.append(
            "execution_topology.py: must set institutional_twap_vwap_execution_claim_allowed=False"
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
                    issues.append(f"{rel}:{i}: forbidden execution claim {pat.pattern!r}")
                    break
    return issues


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="TWAP/VWAP execution topology audit.")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(list(argv) if argv is not None else None)
    issues = audit_execution_topology_claims()
    disc = execution_disclosure()
    payload = {"ok": not issues, "issues": issues, "disclosure": disc}
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print("=== execution_topology_audit ===")
        print(f"OK: {payload['ok']}")
        t = disc["topology"]
        print(
            f"vwap_signal={t['vwap_signal_present']} "
            f"twap_metadata={len(t.get('twap_metadata_modules', []))} "
            f"algo_hits={len(t.get('algo_implementation_hits', {}))} "
            f"institutional_execution={disc['institutional_twap_vwap_execution_claim_allowed']}"
        )
        for line in issues:
            print(f"  FAIL: {line}")
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
