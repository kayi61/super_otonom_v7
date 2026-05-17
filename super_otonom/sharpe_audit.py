"""
Sharpe annualize repo taraması — yalnızca equity/backtest hattı (Faz 9 / backtester).

``portfolio_optimizer_pro.portfolio_sharpe`` yıllıklandırılmış değil (dönem içi mu/sig);
bu modül allowlist'te.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import List, Optional, Sequence, Set, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Bilinçli istisnalar: legacy sabit tanımı veya testte açık override
_ALLOWLIST_SUBSTR: Tuple[str, ...] = (
    "data_freshness.py",
    "sharpe_audit.py",
    "test_sharpe_annualize_fastrun.py",
    "test_audit_quick_fastrun.py",
    "test_audit_modules_coverage.py",
)

_FORBIDDEN_PATTERNS: Tuple[re.Pattern[str], ...] = (
    re.compile(r"252\.0\s*\*\s*24\.0\s*\*\s*12\.0"),
    re.compile(r"252\s*\*\s*24\s*\*\s*12"),
    re.compile(r"periods_per_year\s*=\s*252\.0\s*\*\s*24"),
)

# portfolio_sharpe = cross-sectional, not annualized equity Sharpe
_NON_EQUITY_SHARPE_MODULES: Set[str] = {
    "portfolio_optimizer_pro.py",
}


def _scan_file(path: Path) -> List[str]:
    rel = path.relative_to(_REPO_ROOT).as_posix()
    if any(sub in rel for sub in _ALLOWLIST_SUBSTR):
        return []
    if path.suffix != ".py":
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{rel}: read error: {exc}"]
    issues: List[str] = []
    for pat in _FORBIDDEN_PATTERNS:
        if pat.search(text):
            issues.append(f"{rel}: forbidden Sharpe annualize pattern {pat.pattern!r}")
    if (
        "_compute_sharpe" in text
        and "periods_per_year_from_timeframe" not in text
        and "resolve_periods_per_year" not in text
        and path.name == "backtester.py"
    ):
        issues.append(f"{rel}: backtester must use resolve_periods_per_year")
    return issues


def audit_sharpe_annualization(*, root: Optional[Path] = None) -> List[str]:
    base = root or _REPO_ROOT
    issues: List[str] = []
    for path in sorted(base.rglob("*.py")):
        if "build" in path.parts or ".venv" in path.parts or "node_modules" in path.parts:
            continue
        issues.extend(_scan_file(path))
    return issues


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Sharpe annualize repo audit (backtest path).")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(list(argv) if argv is not None else None)
    issues = audit_sharpe_annualization()
    payload = {
        "ok": not issues,
        "issues": issues,
        "allowlist_note": list(_ALLOWLIST_SUBSTR),
        "non_equity_sharpe_modules": sorted(_NON_EQUITY_SHARPE_MODULES),
    }
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print("=== sharpe_audit ===")
        print(f"OK: {payload['ok']}")
        for line in issues:
            print(f"  FAIL: {line}")
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
