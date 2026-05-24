"""
Tek-host HA iddiası repo taraması (audit madde 5).
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import List, Optional, Sequence

from super_otonom.ha_topology import (
    ha_disclosure,
    inspect_docker_compose,
    validate_compose_ha_contract,
)

_REPO = Path(__file__).resolve().parents[1]

_SKIP_PARTS = frozenset(
    {"build", ".venv", "node_modules", "__pycache__", ".git", "pytest-temproot"}
)

_FORBIDDEN_CLAIMS = (
    re.compile(r"\bhigh[- ]availability\b", re.I),
    re.compile(r"\bHA\s+cluster\b", re.I),
    re.compile(r"\bactive[- ]passive\b", re.I),
    re.compile(r"\bmulti[- ]AZ\b", re.I),
    re.compile(r"\bzero[- ]downtime\b", re.I),
    re.compile(r"kurumsal.*yüksek\s+erişilebilirlik", re.I),
)

_ALLOWLIST = (
    "ha_audit.py",
    "ha_topology.py",
    "ha/__init__.py",
    "ha/leader_election.py",
    "ha/state_replicator.py",
    "ha/health_check.py",
    "ha/coordinator.py",
    "test_ha",
    "test_audit_modules_coverage",
    "SLO-Availability",
)

_SLO_ALLOW_SUBSTR = (
    "slo-availability",
    "slo_availability",
    "availability hedef",
    "availability zone yok",
    "no_multi_az",
    "institutional_ha_claim_allowed",
    "ha_bias_controlled",
    "disclaimer_tr",
    "audit 5",
    "tek host",
    "tek-host",
    "single.host",
    "single_host",
)


def _allowlisted(rel: str, line: str) -> bool:
    low = rel.lower()
    if any(a.lower() in low for a in _ALLOWLIST):
        return True
    ll = line.lower()
    return any(s in ll for s in _SLO_ALLOW_SUBSTR)


def audit_ha_claims(*, root: Optional[Path] = None) -> List[str]:
    base = root or _REPO
    issues: List[str] = list(validate_compose_ha_contract(base / "docker-compose.yml"))
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
        if any(a in rel for a in _ALLOWLIST):
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
                        f"{rel}:{i}: forbidden HA claim {pat.pattern!r}"
                    )
                    break
    ht = base / "super_otonom" / "ha_topology.py"
    if ht.is_file() and "institutional_ha_claim_allowed" not in ht.read_text(encoding="utf-8"):
        issues.append("ha_topology.py: must set institutional_ha_claim_allowed=False")
    return issues


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Single-host HA topology / claim audit.")
    p.add_argument("--json", action="store_true")
    p.add_argument("--compose", default=str(_REPO / "docker-compose.yml"))
    args = p.parse_args(list(argv) if argv is not None else None)
    issues = audit_ha_claims()
    topo = inspect_docker_compose(args.compose)
    disc = ha_disclosure(topology=topo)
    payload = {
        "ok": not issues,
        "issues": issues,
        "topology": disc["topology"],
        "disclosure": disc,
    }
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print("=== ha_audit ===")
        print(f"OK: {payload['ok']}")
        print(f"bot_replicas: {topo.bot_replicas} | institutional_ha: {disc['institutional_ha_claim_allowed']}")
        for line in issues:
            print(f"  FAIL: {line}")
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
