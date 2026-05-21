"""VR-25: Risk Appetite ↔ RiskConfig / VaRLimits consistency checker.

Compares the risk appetite statement (RISK_APPETITE.md) against
the actual VaRLimits defaults and RiskConfig to ensure no drift.

Exit codes:
  0  — all appetite thresholds are consistent with code limits
  1  — mismatch detected between appetite and implementation
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

risk_appetite_check_active = True

_ROOT = Path(__file__).resolve().parents[1]
_APPETITE_DOC = _ROOT / "docs" / "RISK_APPETITE.md"

sys.path.insert(0, str(_ROOT))


# ── Appetite thresholds parsed from doc ─────────────────────────────────────

_LIMIT_TABLE_ROW = re.compile(
    r"^\|\s*(?P<label>[^|]+)\s*\|"
    r"\s*`(?P<field>[^`]+)`\s*\|"
    r"\s*(?P<default>[^|]+)\s*\|"
    r"\s*(?P<zones>[^|]+)\s*\|",
)


@dataclass(frozen=True)
class AppetiteEntry:
    label: str
    field: str
    doc_default: str
    zones: str


@dataclass(frozen=True)
class ConsistencyIssue:
    field: str
    expected: str
    actual: str
    severity: str  # "error" | "warning"


def parse_appetite_limits(path: Optional[Path] = None) -> List[AppetiteEntry]:
    """Parse the cross-reference table from RISK_APPETITE.md."""
    p = path or _APPETITE_DOC
    if not p.is_file():
        return []
    text = p.read_text(encoding="utf-8")
    entries: List[AppetiteEntry] = []
    in_section = False
    for line in text.splitlines():
        if "Specific Limits" in line and "Cross-Reference" in line:
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if not in_section:
            continue
        m = _LIMIT_TABLE_ROW.match(line)
        if m:
            entries.append(
                AppetiteEntry(
                    label=m.group("label").strip(),
                    field=m.group("field").strip(),
                    doc_default=m.group("default").strip(),
                    zones=m.group("zones").strip(),
                )
            )
    return entries


def _parse_pct(s: str) -> Optional[float]:
    """Parse '6%' → 0.06, '0.5%' → 0.005, '0.06' → 0.06."""
    raw = s.strip()
    has_pct = raw.endswith("%")
    raw = raw.rstrip("%").strip()
    try:
        v = float(raw)
    except ValueError:
        return None
    if has_pct:
        return v / 100.0
    if v > 1:
        return v / 100.0
    return v


def load_var_limits_defaults() -> Dict[str, float]:
    """Load VaRLimits default values without instantiating the full risk stack."""
    try:
        from super_otonom.risk.var_limits import VaRLimits

        lim = VaRLimits()
        return {f.name: getattr(lim, f.name) for f in lim.__dataclass_fields__.values()}
    except ImportError:
        return {}


def check_appetite_vs_limits(
    entries: List[AppetiteEntry],
    limits: Dict[str, float],
) -> List[ConsistencyIssue]:
    """Compare documented appetite defaults against code defaults."""
    issues: List[ConsistencyIssue] = []
    for e in entries:
        if e.field not in limits:
            issues.append(
                ConsistencyIssue(
                    field=e.field,
                    expected=e.doc_default,
                    actual="NOT FOUND in VaRLimits",
                    severity="error",
                )
            )
            continue
        doc_val = _parse_pct(e.doc_default)
        code_val = limits[e.field]
        if doc_val is not None and abs(doc_val - code_val) > 1e-6:
            issues.append(
                ConsistencyIssue(
                    field=e.field,
                    expected=f"{e.doc_default} ({doc_val:.4f})",
                    actual=f"{code_val:.4f}",
                    severity="error",
                )
            )
    return issues


def check_escalation_matrix(path: Optional[Path] = None) -> List[ConsistencyIssue]:
    """Verify escalation matrix section exists with required levels."""
    p = path or _APPETITE_DOC
    if not p.is_file():
        return [ConsistencyIssue("RISK_APPETITE.md", "exists", "missing", "error")]
    text = p.read_text(encoding="utf-8")
    issues: List[ConsistencyIssue] = []
    required = ["AMBER", "RED", "CRITICAL", "emergency_stop"]
    for keyword in required:
        if keyword not in text:
            issues.append(
                ConsistencyIssue(
                    field="escalation_matrix",
                    expected=f"contains '{keyword}'",
                    actual="missing",
                    severity="error",
                )
            )
    return issues


def check_approval_levels(path: Optional[Path] = None) -> List[ConsistencyIssue]:
    """Verify approval levels are documented."""
    p = path or _APPETITE_DOC
    if not p.is_file():
        return []
    text = p.read_text(encoding="utf-8")
    issues: List[ConsistencyIssue] = []
    if "< 2%" not in text and "<2%" not in text:
        issues.append(
            ConsistencyIssue("approval_levels", "desk approval < 2%", "missing", "warning")
        )
    if "2–5%" not in text and "2-5%" not in text:
        issues.append(
            ConsistencyIssue("approval_levels", "risk manager 2-5%", "missing", "warning")
        )
    if "> 5%" not in text and ">5%" not in text:
        issues.append(
            ConsistencyIssue("approval_levels", "committee > 5%", "missing", "warning")
        )
    return issues


def check_quarterly_review(path: Optional[Path] = None) -> List[ConsistencyIssue]:
    """Verify quarterly review section exists."""
    p = path or _APPETITE_DOC
    if not p.is_file():
        return []
    text = p.read_text(encoding="utf-8")
    if "Quarterly" not in text and "quarterly" not in text:
        return [
            ConsistencyIssue("review_cycle", "quarterly review defined", "missing", "warning")
        ]
    return []


def run_all_checks(
    appetite_path: Optional[Path] = None,
) -> Tuple[List[ConsistencyIssue], Dict[str, any]]:
    """Run all consistency checks, return issues and summary."""
    entries = parse_appetite_limits(appetite_path)
    limits = load_var_limits_defaults()

    all_issues: List[ConsistencyIssue] = []
    all_issues.extend(check_appetite_vs_limits(entries, limits))
    all_issues.extend(check_escalation_matrix(appetite_path))
    all_issues.extend(check_approval_levels(appetite_path))
    all_issues.extend(check_quarterly_review(appetite_path))

    summary = {
        "ok": len(all_issues) == 0,
        "appetite_entries": len(entries),
        "var_limits_fields": len(limits),
        "errors": len([i for i in all_issues if i.severity == "error"]),
        "warnings": len([i for i in all_issues if i.severity == "warning"]),
    }
    return all_issues, summary


def format_report(
    issues: List[ConsistencyIssue], summary: Dict[str, any]
) -> str:
    """Format human-readable report."""
    lines = [
        "Risk Appetite Consistency Check",
        "=" * 40,
        f"Appetite entries: {summary['appetite_entries']}",
        f"VaRLimits fields: {summary['var_limits_fields']}",
        "",
    ]
    if not issues:
        lines.append("All checks PASSED. No inconsistencies detected.")
    else:
        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]
        if errors:
            lines.append(f"ERRORS ({len(errors)}):")
            for e in errors:
                lines.append(f"  [{e.severity.upper()}] {e.field}: expected={e.expected}, actual={e.actual}")
        if warnings:
            lines.append(f"WARNINGS ({len(warnings)}):")
            for w in warnings:
                lines.append(f"  [{w.severity.upper()}] {w.field}: expected={w.expected}, actual={w.actual}")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Risk appetite consistency check (VR-25).")
    p.add_argument("--json", action="store_true", help="JSON output")
    args = p.parse_args(list(argv) if argv is not None else None)

    if not _APPETITE_DOC.is_file():
        print("ERROR: RISK_APPETITE.md not found")
        return 1

    issues, summary = run_all_checks()

    if args.json:
        payload = {
            **summary,
            "issues": [
                {
                    "field": i.field,
                    "expected": i.expected,
                    "actual": i.actual,
                    "severity": i.severity,
                }
                for i in issues
            ],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(format_report(issues, summary))

    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
