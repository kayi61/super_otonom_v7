"""Audit 10 — TWAP/VWAP sinyal vs emir yürütme topolojisi."""

from __future__ import annotations

import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import pytest
from super_otonom.execution_topology import (
    execution_disclosure,
    inspect_execution_topology,
    scan_algo_implementation_hits,
    scan_vwap_signal_modules,
    validate_execution_topology_contract,
    write_manifest,
)
from super_otonom.execution_topology_audit import audit_execution_topology_claims
from super_otonom.execution_topology_audit import main as exec_audit_main

pytestmark = pytest.mark.fastrun


def test_vwap_signal_module_present() -> None:
    mods = scan_vwap_signal_modules()
    assert "hft_signal_engine.py" in mods


def test_disclosure_not_institutional() -> None:
    d = execution_disclosure()
    assert d["institutional_twap_vwap_execution_claim_allowed"] is False
    assert "vwap_signal_not_execution" in d["limitations"]


def test_no_algo_implementation_hits() -> None:
    assert scan_algo_implementation_hits() == {}


def test_validate_repo_contract() -> None:
    assert validate_execution_topology_contract() == []


def test_audit_repo_clean() -> None:
    assert audit_execution_topology_claims() == []


def test_forbidden_execution_claim(tmp_path: Path) -> None:
    (tmp_path / "bad.md").write_text(
        "We offer full TWAP/VWAP execution for institutions.\n", encoding="utf-8"
    )
    issues = audit_execution_topology_claims(root=tmp_path)
    assert any("forbidden" in i for i in issues)


def test_audit_cli_json() -> None:
    buf = StringIO()
    with redirect_stdout(buf):
        assert exec_audit_main(["--json"]) == 0
    assert json.loads(buf.getvalue())["ok"] is True


def test_write_manifest_roundtrip(tmp_path: Path) -> None:
    pkg = tmp_path / "super_otonom"
    pkg.mkdir()
    (pkg / "hft_signal_engine.py").write_text("vwap_deviation\nvwap\n", encoding="utf-8")
    (pkg / "engine_managers.py").write_text('order_type="limit"\n', encoding="utf-8")
    (pkg / "regime_adaptive_execution_engine.py").write_text("twap\n", encoding="utf-8")
    (pkg / "mm_whale_consensus_controller.py").write_text("execution_profile\n", encoding="utf-8")
    (pkg / "autonomous_decision_core.py").write_text("execution_profile twap\n", encoding="utf-8")
    pipe = pkg / "pipelines"
    pipe.mkdir()
    (pipe / "execution_pipeline.py").write_text("execution_profile\n", encoding="utf-8")
    (tmp_path / "docker-compose.yml").write_text("# audit 10\n", encoding="utf-8")
    et = pkg / "execution_topology.py"
    et.write_text("institutional_twap_vwap_execution_claim_allowed\n", encoding="utf-8")
    out = tmp_path / "data" / "m.json"
    write_manifest(out, pkg_root=pkg)
    assert out.is_file()
    topo = inspect_execution_topology(pkg_root=pkg, repo_root=tmp_path)
    assert topo.vwap_signal_present
