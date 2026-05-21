"""
VaR / CVaR kurumsal iddia repo taraması (audit madde 11).
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import List, Optional, Sequence

from super_otonom.var_topology import (
    validate_var_topology_contract,
    var_disclosure,
)

_REPO = Path(__file__).resolve().parents[1]

_SKIP_PARTS = frozenset(
    {"build", ".venv", "node_modules", "__pycache__", ".git", "pytest-temproot"}
)

_FORBIDDEN_CLAIMS = (
    re.compile(r"\binstitutional\s+VaR\b", re.I),
    re.compile(r"\benterprise\s+VaR\b", re.I),
    re.compile(r"\bregime[- ]adjusted\s+VaR\b", re.I),
    re.compile(r"\bliquidity[- ]adjusted\s+VaR\b", re.I),
    re.compile(r"\bfull\s+stress\s+grid\s+VaR\b", re.I),
    re.compile(r"\bhiç\s+VaR\s+yok\b", re.I),
    re.compile(r"\bno\s+VaR\s+at\s+all\b", re.I),
    re.compile(r"\bproduction[- ]ready\s+VaR\s+engine\b", re.I),
    re.compile(r"kurumsal.*VaR.*motor", re.I),
)

_ALLOWLIST_FILES = (
    "var_topology_audit.py",
    "var_topology.py",
    "var_topology_manifest.json",
    "portfolio_risk_engine.py",
    "risk_ontology.py",
    "risk_manager.py",
    "risk/",
    "metrics_exporter.py",
    "test_var_topology",
    "test_portfolio_risk_engine",
    "test_audit_modules_coverage",
    "test_lvar_vr08",
    "test_regime_var_vr10",
    "test_stressed_var_vr11",
    "test_stress_scenarios_vr12",
    "test_var_backtest_vr13",
    "test_christoffersen_vr14",
    "test_basel_traffic_light_vr15",
    "test_pnl_attribution_vr16",
    "test_pre_trade_var_gate_vr17",
    "test_position_sizer_var_vr18",
    "test_var_breach_kill_switch_vr19",
    "test_var_limits_hierarchy_vr20",
    "INSTITUTIONAL_CONTROL_CHECKLIST_TR.md",
    "RISK_METHODOLOGY.md",
    "CLAUDE.md",
)

_ALLOW_SUBSTR = (
    "audit 11",
    "institutional_var_claim_allowed",
    "var_topology_controlled",
    "yetersiz",
    "basit demek",
    "phase24",
    "faz 24",
    "portfolio_risk_engine",
    "var_parametric",
    "var_historical",
    "var_monte_carlo",
    "cvar_expected_shortfall",
    "disclaimer_tr",
    "implemente edilmemiş",
    "sinyal/analitik",
    "metadata",
    "heuristik",
    "risk_ontology_percentile",
    "stressed_var_engine",
    "stressed_var",
    "institutional_stress_grid",
    "stress_scenario",
    "stress_grid",
    "var_backtest_kupiec",
    "kupiec",
    "christoffersen_ind",
    "christoffersen_cc",
    "christoffersen",
    "conditional_coverage",
    "basel_traffic_light",
    "traffic_light",
    "pnl_attribution",
    "pnl_drift",
    "attribute_pnl",
    "pre_trade_var_gate",
    "pre_trade_var_check",
    "marginal_var_gate",
    "position_sizer_var_cap",
    "var_cap_result",
    "var_aware_position_sizer",
    "size_with_var_cap",
    "var_breach_kill_switch",
    "var_99_breach",
    "cvar_975_breach",
    "stressed_var_breach",
    "var_limit_hierarchy",
    "var_limits",
    "VaRLimits",
    "check_limits",
    "load_var_limits",
)


def _allowlisted(rel: str, line: str) -> bool:
    low = rel.lower()
    if any(a.lower() in low for a in _ALLOWLIST_FILES):
        return True
    return any(s.lower() in line.lower() for s in _ALLOW_SUBSTR)


def audit_var_topology_claims(*, root: Optional[Path] = None) -> List[str]:
    base = root or _REPO
    issues: List[str] = list(validate_var_topology_contract(base))

    vt = base / "super_otonom" / "var_topology.py"
    if vt.is_file() and "institutional_var_claim_allowed" not in vt.read_text(encoding="utf-8"):
        issues.append("var_topology.py: must set institutional_var_claim_allowed=False")

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
                    issues.append(f"{rel}:{i}: forbidden VaR claim {pat.pattern!r}")
                    break
    return issues


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="VaR topology audit.")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(list(argv) if argv is not None else None)
    issues = audit_var_topology_claims()
    disc = var_disclosure()
    payload = {"ok": not issues, "issues": issues, "disclosure": disc}
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print("=== var_topology_audit ===")
        print(f"OK: {payload['ok']}")
        t = disc["topology"]
        print(
            f"phase24={t.get('var_methods_present')} "
            f"live={t.get('live_var_modules')} "
            f"institutional={disc['institutional_var_claim_allowed']}"
        )
        for line in issues:
            print(f"  FAIL: {line}")
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
