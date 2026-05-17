"""sharpe_audit / survivorship_audit / ha_audit — hata yolları ve CLI (coverage)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from super_otonom.bot_engine_audit import audit_bot_engine_claims
from super_otonom.bot_engine_audit import main as be_topo_main
from super_otonom.clock_skew_audit import audit_clock_skew_claims
from super_otonom.clock_skew_audit import main as clock_main
from super_otonom.execution_topology import (
    ExecutionTopology as ExecutionTopologySnapshot,
)
from super_otonom.execution_topology import (
    compare_topology_to_manifest,
    execution_disclosure,
    validate_execution_topology_contract,
)
from super_otonom.execution_topology import main as exec_topo_main
from super_otonom.execution_topology_audit import main as exec_topo_audit_main
from super_otonom.ha_audit import audit_ha_claims
from super_otonom.ha_audit import main as ha_main
from super_otonom.layout_topology import (
    TestLayoutTopology as LayoutTopologySnapshot,
)
from super_otonom.layout_topology import (
    compare_layout_to_manifest,
    count_canonical_tests,
    count_wheel_test_modules,
    inspect_test_layout,
    layout_disclosure,
    validate_pyproject_packaging,
    validate_test_layout_contract,
)
from super_otonom.layout_topology import main as layout_topo_main
from super_otonom.layout_topology_audit import audit_test_layout_claims
from super_otonom.layout_topology_audit import main as tl_audit_main
from super_otonom.package_topology_audit import audit_package_topology_claims
from super_otonom.package_topology_audit import main as pkg_topo_main
from super_otonom.sharpe_audit import (
    _REPO_ROOT,
    _scan_file,
)
from super_otonom.sharpe_audit import (
    main as sharpe_main,
)
from super_otonom.survivorship_audit import audit_survivorship_claims
from super_otonom.survivorship_audit import main as surv_main

pytestmark = pytest.mark.fastrun


def test_sharpe_scan_non_py_skipped() -> None:
    readme = _REPO_ROOT / "README.md"
    if readme.is_file():
        assert _scan_file(readme) == []


def test_sharpe_scan_read_error() -> None:
    target = _REPO_ROOT / "super_otonom" / "backtester.py"
    with patch.object(Path, "read_text", side_effect=OSError("denied")):
        issues = _scan_file(target)
    assert issues and "read error" in issues[0]


def test_sharpe_audit_json_fail(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "super_otonom.sharpe_audit.audit_sharpe_annualization",
        lambda root=None: ["evil.py: forbidden pattern"],
    )
    assert sharpe_main(["--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False


def test_sharpe_audit_text_fail(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "evil.py").write_text(
        "".join(("252", "*", "24", "*", "12", "\n")), encoding="utf-8"
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        "super_otonom.sharpe_audit.audit_sharpe_annualization",
        lambda root=None: [f"{tmp_path}/evil.py: forbidden"],
    )
    try:
        assert sharpe_main([]) == 1
        text = capsys.readouterr().out
        assert "FAIL" in text
    finally:
        monkeypatch.undo()


def test_survivorship_forbidden_claim(tmp_path: Path) -> None:
    (tmp_path / "claim.py").write_text("institutional universe backtest\n", encoding="utf-8")
    issues = audit_survivorship_claims(root=tmp_path)
    assert any("forbidden" in i for i in issues)


def test_survivorship_edge_and_backtester_checks(tmp_path: Path) -> None:
    pkg = tmp_path / "super_otonom"
    pkg.mkdir()
    (pkg / "edge_evidence.py").write_text("# no disclosure\n", encoding="utf-8")
    (pkg / "backtester.py").write_text('"""plain"""\n', encoding="utf-8")
    issues = audit_survivorship_claims(root=tmp_path)
    assert any("edge_evidence" in i for i in issues)
    assert any("backtester" in i for i in issues)


def test_survivorship_cli_json_fail(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "super_otonom.survivorship_audit.audit_survivorship_claims",
        lambda root=None: ["fake: forbidden claim"],
    )
    assert surv_main(["--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False


def test_survivorship_cli_text_fail(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "super_otonom.survivorship_audit.audit_survivorship_claims",
        lambda root=None: ["fake: fail"],
    )
    assert surv_main([]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_ha_audit_read_error(tmp_path: Path) -> None:
    bad = tmp_path / "x.md"
    bad.write_text("ok\n", encoding="utf-8")
    with patch.object(Path, "read_text", side_effect=OSError("denied")):
        issues = audit_ha_claims(root=tmp_path)
    assert any("read error" in i for i in issues)


def test_ha_audit_cli_json_fail(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "super_otonom.ha_audit.audit_ha_claims",
        lambda root=None: ["fake: forbidden HA claim"],
    )
    assert ha_main(["--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False


def test_ha_audit_cli_text_fail(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "super_otonom.ha_audit.audit_ha_claims",
        lambda root=None: ["fake: fail"],
    )
    assert ha_main([]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_clock_skew_audit_read_error(tmp_path: Path) -> None:
    bad = tmp_path / "x.md"
    bad.write_text("ok\n", encoding="utf-8")
    with patch.object(Path, "read_text", side_effect=OSError("denied")):
        issues = audit_clock_skew_claims(root=tmp_path)
    assert any("read error" in i for i in issues)


def test_clock_skew_audit_cli_json_fail(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "super_otonom.clock_skew_audit.audit_clock_skew_claims",
        lambda root=None: ["fake: forbidden"],
    )
    assert clock_main(["--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False


def test_clock_skew_audit_cli_text_fail(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "super_otonom.clock_skew_audit.audit_clock_skew_claims",
        lambda root=None: ["fake: fail"],
    )
    assert clock_main([]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_clock_skew_wiring_missing_alert(tmp_path: Path) -> None:
    from super_otonom.clock_skew import validate_clock_skew_wiring

    (tmp_path / "docker-compose.yml").write_text("# audit 6\n", encoding="utf-8")
    prom = tmp_path / "docker" / "prometheus"
    prom.mkdir(parents=True)
    (prom / "alerts.yml").write_text("bot_clock_skew_abs_ms\n", encoding="utf-8")
    issues = validate_clock_skew_wiring(tmp_path)
    assert any("BotClockSkewHigh" in i for i in issues)


def test_package_topology_audit_read_error(tmp_path: Path) -> None:
    bad = tmp_path / "x.md"
    bad.write_text("ok\n", encoding="utf-8")
    with patch.object(Path, "read_text", side_effect=OSError("denied")):
        issues = audit_package_topology_claims(root=tmp_path)
    assert any("read error" in i for i in issues)


def test_package_topology_audit_cli_json_fail(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "super_otonom.package_topology_audit.audit_package_topology_claims",
        lambda root=None: ["fake: forbidden"],
    )
    assert pkg_topo_main(["--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False


def test_package_topology_audit_cli_text_fail(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "super_otonom.package_topology_audit.audit_package_topology_claims",
        lambda root=None: ["fake: fail"],
    )
    assert pkg_topo_main([]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_bot_engine_audit_read_error(tmp_path: Path) -> None:
    bad = tmp_path / "x.md"
    bad.write_text("ok\n", encoding="utf-8")
    with patch.object(Path, "read_text", side_effect=OSError("denied")):
        issues = audit_bot_engine_claims(root=tmp_path)
    assert any("read error" in i for i in issues)


def test_bot_engine_audit_cli_json_fail(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "super_otonom.bot_engine_audit.audit_bot_engine_claims",
        lambda root=None: ["fake: forbidden"],
    )
    assert be_topo_main(["--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False


def test_bot_engine_audit_cli_text_fail(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "super_otonom.bot_engine_audit.audit_bot_engine_claims",
        lambda root=None: ["fake: fail"],
    )
    assert be_topo_main([]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_bot_engine_topology_cli_write_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from super_otonom.bot_engine_topology import main as be_top_main

    eng = tmp_path / "super_otonom" / "bot_engine.py"
    eng.parent.mkdir(parents=True)
    eng.write_text("class BotEngine:\n    def tick(self): pass\n", encoding="utf-8")
    out = tmp_path / "data" / "m.json"
    monkeypatch.setattr("super_otonom.bot_engine_topology._BOT_ENGINE", eng)
    monkeypatch.setattr("super_otonom.bot_engine_topology._DEFAULT_MANIFEST", out)
    assert be_top_main(["--write-manifest"]) == 0
    assert out.is_file()


def test_test_layout_audit_read_error(tmp_path: Path) -> None:
    bad = tmp_path / "x.md"
    bad.write_text("ok\n", encoding="utf-8")
    with patch.object(Path, "read_text", side_effect=OSError("denied")):
        issues = audit_test_layout_claims(root=tmp_path)
    assert any("read error" in i for i in issues)


def test_test_layout_audit_cli_json_fail(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "super_otonom.layout_topology_audit.audit_test_layout_claims",
        lambda root=None, verify_wheel=False: ["fake: fail"],
    )
    assert tl_audit_main(["--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False


def test_test_layout_audit_cli_text_fail(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "super_otonom.layout_topology_audit.audit_test_layout_claims",
        lambda root=None, verify_wheel=False: ["fake: fail"],
    )
    assert tl_audit_main([]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_test_layout_audit_cli_text_ok(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "super_otonom.layout_topology_audit.audit_test_layout_claims",
        lambda root=None, verify_wheel=False: [],
    )
    assert tl_audit_main([]) == 0
    assert "test_layout_audit" in capsys.readouterr().out


def test_test_layout_audit_missing_institutional_flag(tmp_path: Path) -> None:
    pkg = tmp_path / "super_otonom"
    pkg.mkdir(parents=True)
    (pkg / "layout_topology.py").write_text("x = 1\n", encoding="utf-8")
    issues = audit_test_layout_claims(root=tmp_path)
    assert any("institutional_production_test_layout_claim_allowed=False" in i for i in issues)


def test_test_layout_topology_helpers(tmp_path: Path) -> None:
    topo = LayoutTopologySnapshot(in_package_test_modules=["test_a.py"])
    assert topo.in_package_test_count == 1
    assert topo.institutional_production_test_layout_claim_allowed is False
    assert count_canonical_tests(tmp_path / "missing_tests") == 0
    assert count_wheel_test_modules(tmp_path / "nope.whl") == -1
    disc = layout_disclosure(topo=topo)
    assert "migration_debt_super_otonom_test_files" in disc["limitations"]


def test_test_layout_compare_manifest_branches() -> None:
    topo = LayoutTopologySnapshot(in_package_test_modules=["test_a.py"])
    assert compare_layout_to_manifest(
        topo, {"institutional_production_test_layout_claim_allowed": True}
    )
    assert compare_layout_to_manifest(
        topo,
        {
            "institutional_production_test_layout_claim_allowed": False,
            "in_package_test_modules": ["test_b.py"],
            "in_package_test_count": 1,
            "in_package_test_ceiling": 35,
        },
    )
    assert compare_layout_to_manifest(
        topo,
        {
            "institutional_production_test_layout_claim_allowed": False,
            "in_package_test_modules": [],
            "in_package_test_count": 1,
            "in_package_test_ceiling": 35,
        },
    )
    assert compare_layout_to_manifest(
        topo, {"institutional_production_test_layout_claim_allowed": False}
    )
    many = [f"test_{i}.py" for i in range(40)]
    big = LayoutTopologySnapshot(in_package_test_modules=many)
    assert compare_layout_to_manifest(
        big,
        {
            "institutional_production_test_layout_claim_allowed": False,
            "in_package_test_modules": many,
            "in_package_test_count": len(many),
            "in_package_test_ceiling": 5,
        },
    )


def test_test_layout_validate_pyproject_branches(tmp_path: Path) -> None:
    assert validate_pyproject_packaging(tmp_path)
    pp = tmp_path / "pyproject.toml"
    pp.write_text("[project]\nname='x'\n", encoding="utf-8")
    issues = validate_pyproject_packaging(tmp_path)
    assert any("BuildPyExcludeInPackageTests" in i for i in issues)
    pp.write_text(
        'testpaths = ["tests"]\nsuper_otonom/test_*.py\nBuildPyExcludeInPackageTests\n',
        encoding="utf-8",
    )
    assert validate_pyproject_packaging(tmp_path) == []


def test_test_layout_validate_contract_branches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issues = validate_test_layout_contract(tmp_path)
    assert any("docker-compose.yml" in i for i in issues)
    (tmp_path / "docker-compose.yml").write_text("# audit 9\n", encoding="utf-8")
    issues = validate_test_layout_contract(tmp_path)
    assert any("test_layout_manifest.json" in i for i in issues)
    manifest = tmp_path / "data" / "test_layout_manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{not json", encoding="utf-8")
    issues = validate_test_layout_contract(tmp_path)
    assert any("invalid JSON" in i for i in issues)
    manifest.write_text(
        json.dumps(
            {
                "institutional_production_test_layout_claim_allowed": False,
                "in_package_test_modules": [],
                "in_package_test_count": 0,
                "in_package_test_ceiling": 35,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        'testpaths = ["tests"]\nsuper_otonom/test_*.py\nBuildPyExcludeInPackageTests\n',
        encoding="utf-8",
    )
    topo = LayoutTopologySnapshot(
        in_package_test_modules=[],
        wheel_test_module_count=3,
    )
    monkeypatch.setattr(
        "super_otonom.layout_topology.inspect_test_layout",
        lambda **kw: topo,
    )
    issues = validate_test_layout_contract(tmp_path, verify_wheel=True)
    assert any("wheel contains" in i for i in issues)


def test_test_layout_inspect_wheel_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "super_otonom.layout_topology.build_wheel_for_audit",
        lambda **kw: (_ for _ in ()).throw(OSError("wheel fail")),
    )
    topo = inspect_test_layout(build_wheel=True)
    assert topo.wheel_test_module_count == -1


def test_test_layout_inspect_wheel_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    whl = tmp_path / "pkg-1.whl"
    whl.write_bytes(b"PK\x05\x06")
    monkeypatch.setattr(
        "super_otonom.layout_topology.build_wheel_for_audit",
        lambda **kw: whl,
    )
    monkeypatch.setattr(
        "super_otonom.layout_topology.count_wheel_test_modules",
        lambda _p: 0,
    )
    topo = inspect_test_layout(build_wheel=True)
    assert topo.wheel_test_module_count == 0


def test_test_layout_build_wheel_no_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    out = tmp_path / "wheels"
    out.mkdir()
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(
        "super_otonom.layout_topology._REPO",
        tmp_path,
    )
    from super_otonom.layout_topology import build_wheel_for_audit

    with pytest.raises(FileNotFoundError):
        build_wheel_for_audit(out_dir=out)


def test_test_layout_compose_marker_required(tmp_path: Path) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        'testpaths = ["tests"]\nsuper_otonom/test_*.py\nBuildPyExcludeInPackageTests\n',
        encoding="utf-8",
    )
    manifest = tmp_path / "data" / "test_layout_manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "institutional_production_test_layout_claim_allowed": False,
                "in_package_test_modules": [],
                "in_package_test_count": 0,
                "in_package_test_ceiling": 35,
            }
        ),
        encoding="utf-8",
    )
    issues = validate_test_layout_contract(tmp_path)
    assert any("audit 9 marker" in i for i in issues)


def test_test_layout_pyproject_testpaths_branch(tmp_path: Path) -> None:
    pp = tmp_path / "pyproject.toml"
    pp.write_text(
        "BuildPyExcludeInPackageTests\nsuper_otonom/test_*.py\n",
        encoding="utf-8",
    )
    issues = validate_pyproject_packaging(tmp_path)
    assert any("testpaths" in i for i in issues)


def test_test_layout_disclosure_no_migration_debt() -> None:
    topo = LayoutTopologySnapshot(in_package_test_modules=[])
    disc = layout_disclosure(topo=topo)
    assert "migration_debt_super_otonom_test_files" not in disc["limitations"]


def test_test_layout_manifest_count_mismatch() -> None:
    topo = LayoutTopologySnapshot(in_package_test_modules=["test_a.py"])
    issues = compare_layout_to_manifest(
        topo,
        {
            "institutional_production_test_layout_claim_allowed": False,
            "in_package_test_modules": ["test_a.py"],
            "in_package_test_count": 99,
            "in_package_test_ceiling": 35,
        },
    )
    assert any("in_package_test_count mismatch" in i for i in issues)


def test_test_layout_topology_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "data" / "m.json"
    monkeypatch.setattr("super_otonom.layout_topology._DEFAULT_MANIFEST", out)
    pkg = tmp_path / "super_otonom"
    pkg.mkdir()
    (pkg / "test_x.py").write_text("", encoding="utf-8")
    monkeypatch.setattr("super_otonom.layout_topology._PKG", pkg)
    assert layout_topo_main(["--write-manifest"]) == 0
    assert out.is_file()
    monkeypatch.setattr(
        "super_otonom.layout_topology.validate_test_layout_contract",
        lambda *a, **k: ["fake"],
    )
    assert layout_topo_main([]) == 1
    assert "FAIL" in capsys.readouterr().out
    monkeypatch.setattr(
        "super_otonom.layout_topology.validate_test_layout_contract",
        lambda *a, **k: [],
    )
    assert layout_topo_main(["--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_package_topology_validate_missing_manifest(tmp_path: Path) -> None:
    from super_otonom.package_topology import validate_package_topology_contract

    (tmp_path / "docker-compose.yml").write_text("# audit 7\n", encoding="utf-8")
    issues = validate_package_topology_contract(tmp_path)
    assert any("package_topology_manifest.json" in i for i in issues)


def test_execution_topology_audit_cli_json_fail(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "super_otonom.execution_topology_audit.audit_execution_topology_claims",
        lambda root=None: ["fake: fail"],
    )
    assert exec_topo_audit_main(["--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False


def test_execution_topology_compare_manifest() -> None:
    topo = ExecutionTopologySnapshot(
        vwap_signal_modules=["hft_signal_engine.py"],
        algo_implementation_hits={"bad.py": ["twap_slice"]},
    )
    assert compare_topology_to_manifest(
        topo,
        {"institutional_twap_vwap_execution_claim_allowed": True},
    )
    assert compare_topology_to_manifest(
        topo,
        {
            "institutional_twap_vwap_execution_claim_allowed": False,
            "algo_implementation_hits_expected_empty": True,
        },
    )


def test_execution_topology_validate_contract(tmp_path: Path) -> None:
    issues = validate_execution_topology_contract(tmp_path)
    assert any("docker-compose.yml" in i for i in issues)
    assert any("execution_topology_manifest.json" in i for i in issues)


def test_execution_topology_disclosure_limitations() -> None:
    d = execution_disclosure()
    assert d["institutional_twap_vwap_execution_claim_allowed"] is False
    assert "twap_metadata_not_algo_router" in d["limitations"]


def test_execution_topology_cli_json(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "super_otonom.execution_topology.validate_execution_topology_contract",
        lambda *a, **k: [],
    )
    assert exec_topo_main(["--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_clock_skew_wiring_partial(tmp_path: Path) -> None:
    from super_otonom.clock_skew import validate_clock_skew_wiring

    (tmp_path / "docker-compose.yml").write_text("# audit 6\n", encoding="utf-8")
    prom = tmp_path / "docker" / "prometheus"
    prom.mkdir(parents=True)
    (prom / "alerts.yml").write_text("bot_clock_skew_abs_ms\nBotClockSkewHigh\n", encoding="utf-8")
    pkg = tmp_path / "super_otonom"
    pkg.mkdir()
    (pkg / "metrics_exporter.py").write_text(
        "clock_skew_abs_ms clock_skew_exchange_ms host_ntp_synchronized\n",
        encoding="utf-8",
    )
    (pkg / "config.py").write_text("CLOCK_SKEW = {}\n", encoding="utf-8")
    assert validate_clock_skew_wiring(tmp_path) == []
