#!/usr/bin/env python3
"""pip-audit + CycloneDX SBOM + CVE SLA gate (CI / fastrun)."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / "artifacts"
CONFIG_PATH = ROOT / "config" / "dependency_security.json"
DEFAULT_REQ = ROOT / "requirements.txt"


def _load_config() -> Dict[str, Any]:
    if CONFIG_PATH.is_file():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {
        "remediation_sla_days": {"critical": 7, "high": 30, "medium": 90, "low": 180},
        "ci_fail_severities": ["critical", "high"],
        "scan_targets": ["requirements.txt"],
    }


def _run(cmd: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd))
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=check)


def _pip_audit_json(req: Path) -> List[Dict[str, Any]]:
    proc = _run(
        [
            sys.executable,
            "-m",
            "pip_audit",
            "--requirement",
            str(req),
            "--format",
            "json",
            "--progress-spinner",
            "off",
        ],
        check=False,
    )
    if proc.returncode not in (0, 1):
        print(proc.stderr or proc.stdout, file=sys.stderr)
        raise SystemExit(f"pip-audit failed (exit {proc.returncode})")
    if not proc.stdout.strip():
        return []
    data = json.loads(proc.stdout)
    if isinstance(data, dict) and "dependencies" in data:
        return list(data["dependencies"])
    if isinstance(data, list):
        return data
    return []


def _flatten_vulns(deps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for dep in deps:
        name = dep.get("name") or dep.get("package") or "?"
        version = dep.get("version", "?")
        for v in dep.get("vulns") or dep.get("vulnerabilities") or []:
            sev = str(v.get("severity") or v.get("cvss_severity") or "unknown").lower()
            out.append(
                {
                    "package": name,
                    "version": version,
                    "id": v.get("id") or v.get("vuln_id") or "?",
                    "severity": sev,
                    "fix_versions": v.get("fix_versions") or [],
                }
            )
    return out


def _write_sbom(req: Path, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = _run(
        [
            sys.executable,
            "-m",
            "pip_audit",
            "--requirement",
            str(req),
            "--format",
            "cyclonedx-json",
            "--output",
            str(out),
            "--progress-spinner",
            "off",
        ],
        check=False,
    )
    if proc.returncode not in (0, 1) or not out.is_file():
        print(proc.stderr or proc.stdout, file=sys.stderr)
        raise SystemExit("SBOM (cyclonedx-json) uretilemedi")
    print(f"SBOM: {out}")


def _check_sla(vulns: List[Dict[str, Any]], fail_on: Sequence[str]) -> int:
    cfg = _load_config()
    sla = cfg.get("remediation_sla_days") or {}
    fail_set = {s.lower() for s in fail_on}
    blocked: List[Dict[str, Any]] = []
    for v in vulns:
        sev = v["severity"]
        if sev in fail_set:
            blocked.append(v)
    report = ARTIFACTS / "cve-report.json"
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps({"vulnerabilities": vulns, "blocked": blocked, "sla_days": sla}, indent=2),
        encoding="utf-8",
    )
    print(f"CVE raporu: {report} ({len(vulns)} bulgu, {len(blocked)} blok)")
    for v in blocked[:20]:
        fix = ", ".join(v["fix_versions"]) or "yok"
        days = sla.get(v["severity"], "?")
        print(
            f"  [{v['severity'].upper()}] {v['package']}=={v['version']} "
            f"{v['id']} | fix: {fix} | SLA: {days} gun"
        )
    if len(blocked) > 20:
        print(f"  ... +{len(blocked) - 20} daha")
    return 1 if blocked else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Bagimlilik guvenligi: pip-audit + SBOM + SLA")
    parser.add_argument("--requirements", type=Path, default=DEFAULT_REQ)
    parser.add_argument("--sbom", action="store_true", help="CycloneDX SBOM yaz")
    parser.add_argument("--no-audit", action="store_true", help="Yalnizca SBOM")
    parser.add_argument(
        "--fail-on",
        default="",
        help="Virgulle: critical,high (bos = config ci_fail_severities)",
    )
    args = parser.parse_args()
    cfg = _load_config()
    fail_on = [s.strip() for s in args.fail_on.split(",") if s.strip()] or list(
        cfg.get("ci_fail_severities") or ["critical", "high"]
    )

    req = args.requirements.resolve()
    if not req.is_file():
        print(f"requirements yok: {req}", file=sys.stderr)
        return 2

    if args.sbom:
        _write_sbom(req, ARTIFACTS / "sbom.cyclonedx.json")

    if args.no_audit:
        return 0

    deps = _pip_audit_json(req)
    vulns = _flatten_vulns(deps)
    if not vulns:
        print("pip-audit: bilinen CVE yok (requirements.txt)")
        return 0
    return _check_sla(vulns, fail_on)


if __name__ == "__main__":
    raise SystemExit(main())
