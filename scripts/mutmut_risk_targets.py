#!/usr/bin/env python3
"""mutmut CI: modul basina hedef pytest dosyalari (tum tests/ degil — saatler surmesin)."""

from __future__ import annotations

import sys

# Her mutant icin yalnizca bu dosyalar kosulur; coverage adimi da ayni seti kullanir.
TARGETS: dict[str, list[str]] = {
    "risk_ontology": [
        "tests/test_risk_ontology_mutation.py",
        "tests/test_risk_mutation_targets.py",
        "tests/risk/test_risk_engine_unified.py",
    ],
    "risk_manager": [
        "tests/test_risk_manager_mutation.py",
        "tests/test_risk_mutation_targets.py",
        "tests/branch/test_risk_manager_branch_matrix.py",
        "tests/risk/test_risk_engine_unified.py",
        "tests/test_risk_manager.py",
        "tests/test_risk_manager_extended.py",
        "tests/test_kill_switch.py",
    ],
    "capital_engine": [
        "tests/test_risk_mutation_targets.py",
    ],
    "pre_trade_gate": [
        "tests/test_risk_mutation_targets.py",
    ],
}


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in TARGETS:
        print(f"Usage: {sys.argv[0]} <{'|'.join(TARGETS)}>", file=sys.stderr)
        return 2
    print(" ".join(TARGETS[sys.argv[1]]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
