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
        # test_risk_mutation_targets.py capital_engine'i KAPSAMIYORDU -> "no mutants
        # tested" (coverage context bos) -> CI fail. Gercek capital_engine testlerine
        # yonlendirildi; mutmut --use-coverage artik dogru context bulur.
        "tests/test_capital_engine.py",
        "tests/test_capital_engine_journal_sink.py",
        "tests/test_capital_engine_v2_fixes.py",
        "tests/test_capital_engine_v3_fixes.py",
    ],
    "pre_trade_gate": [
        "tests/test_risk_mutation_targets.py",
    ],
    # ── risk/ package modules (VR-02+) ────────────────────────────────
    "var_models": [
        "tests/risk/test_var_models_vr02.py",
        "tests/risk/test_cornish_fisher_vr03.py",
        "tests/risk/test_risk_engine_unified.py",
    ],
    "cvar_models": [
        "tests/risk/test_cvar_vr04.py",
        "tests/risk/test_risk_engine_unified.py",
    ],
    "stressed_var": [
        "tests/risk/test_stressed_var_vr11.py",
        "tests/risk/test_risk_engine_unified.py",
    ],
    "var_backtest": [
        "tests/risk/test_var_backtest_vr13.py",
        "tests/risk/test_christoffersen_vr14.py",
        "tests/risk/test_basel_traffic_light_vr15.py",
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
