"""Audit 11 — VaR / CVaR topolojisi (faz 24 vs canlı tick)."""

from __future__ import annotations

import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import pytest
from super_otonom.var_topology import (
    inspect_var_topology,
    scan_var_methods_in_portfolio_risk,
    validate_var_topology_contract,
    var_disclosure,
    write_manifest,
)
from super_otonom.var_topology_audit import audit_var_topology_claims
from super_otonom.var_topology_audit import main as var_audit_main

pytestmark = pytest.mark.fastrun


def test_phase24_var_methods_present() -> None:
    methods = scan_var_methods_in_portfolio_risk()
    assert methods == ["parametric", "historical", "monte_carlo", "cvar"]


def test_disclosure_not_institutional() -> None:
    d = var_disclosure()
    assert d["institutional_var_claim_allowed"] is False
    assert "no_regime_conditional_var" in d["limitations"]


def test_live_tick_does_not_use_phase24_engine() -> None:
    topo = inspect_var_topology()
    assert topo.live_tick_uses_portfolio_risk_engine is False
    assert "risk_ontology.py" in topo.live_var_modules


def test_validate_repo_contract() -> None:
    assert validate_var_topology_contract() == []


def test_audit_repo_clean() -> None:
    assert audit_var_topology_claims() == []


def test_forbidden_var_claim(tmp_path: Path) -> None:
    (tmp_path / "bad.md").write_text("We run institutional VaR for hedge funds.\n", encoding="utf-8")
    issues = audit_var_topology_claims(root=tmp_path)
    assert any("forbidden" in i for i in issues)


def test_audit_cli_json() -> None:
    buf = StringIO()
    with redirect_stdout(buf):
        assert var_audit_main(["--json"]) == 0
    assert json.loads(buf.getvalue())["ok"] is True


def test_write_manifest_roundtrip(tmp_path: Path) -> None:
    pkg = tmp_path / "super_otonom"
    pkg.mkdir()
    pre = pkg / "portfolio_risk_engine.py"
    pre.write_text(
        "\n".join(
            [
                "def var_parametric(r,c=0.95): return 0.1",
                "def var_historical(r,c=0.95): return 0.1",
                "def var_monte_carlo(r,c=0.95): return 0.1",
                "def cvar_expected_shortfall(r,c=0.95): return 0.1",
                "def _stress_max_loss_pct(w,h,d): return 0.2",
                "stress_scenarios = {}",
            ]
        ),
        encoding="utf-8",
    )
    (pkg / "risk_ontology.py").write_text("def _calc_var(): pass\nvar_1d=0\n", encoding="utf-8")
    (pkg / "risk_manager.py").write_text("def calculate_var(): pass\n", encoding="utf-8")
    (pkg / "var_topology.py").write_text("institutional_var_claim_allowed\n", encoding="utf-8")
    (tmp_path / "docker-compose.yml").write_text("# audit 11\n", encoding="utf-8")
    out = tmp_path / "data" / "m.json"
    write_manifest(out, pkg_root=pkg)
    assert out.is_file()
