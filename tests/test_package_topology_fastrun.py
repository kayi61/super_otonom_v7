"""Audit 7 — god package / düz super_otonom topolojisi."""

from __future__ import annotations

import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import pytest
from super_otonom.package_topology import (
    compare_topology_to_manifest,
    package_disclosure,
    scan_package_topology,
    validate_package_topology_contract,
    write_manifest,
)
from super_otonom.package_topology_audit import (
    audit_package_topology_claims,
)
from super_otonom.package_topology_audit import (
    main as pkg_audit_main,
)

pytestmark = pytest.mark.fastrun


def test_scan_god_package_flat() -> None:
    topo = scan_package_topology()
    assert topo.flat_production_count >= 80
    assert topo.god_package_flat is True
    assert topo.institutional_modular_boundary_claim_allowed is False
    assert topo.subpackages == [
        "analysis",
        "audit",
        "core",
        "execution",
        "ha",
        "infra",
        "monitoring",
        "pipelines",
        "risk",
        "signals",
        "trading",
    ]


def test_disclosure_no_institutional_modular() -> None:
    d = package_disclosure()
    assert d["institutional_modular_boundary_claim_allowed"] is False
    assert d["package_topology_controlled"] is True
    assert "god_package_flat" in d["topology"]


def test_validate_contract_on_repo() -> None:
    assert validate_package_topology_contract() == []


def test_audit_repo_clean() -> None:
    assert audit_package_topology_claims() == []


def test_manifest_write_and_match(tmp_path: Path) -> None:
    pkg = tmp_path / "super_otonom" / "pipelines"
    pkg.mkdir(parents=True)
    (tmp_path / "super_otonom" / "alpha.py").write_text("# m\n", encoding="utf-8")
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "risk_pipeline.py").write_text("# p\n", encoding="utf-8")
    man = tmp_path / "data" / "manifest.json"
    topo = scan_package_topology(tmp_path / "super_otonom")
    man.parent.mkdir(parents=True)
    man.write_text(
        json.dumps(
            {
                "flat_production_count": topo.flat_production_count,
                "flat_production_modules": topo.flat_production_modules,
                "flat_production_ceiling": 10,
                "allowed_subpackages": ["pipelines"],
                "institutional_modular_boundary_claim_allowed": False,
            }
        ),
        encoding="utf-8",
    )
    assert compare_topology_to_manifest(topo, json.loads(man.read_text(encoding="utf-8"))) == []


def test_ceiling_exceeded(tmp_path: Path) -> None:
    topo = scan_package_topology()
    manifest = {
        "flat_production_modules": topo.flat_production_modules,
        "flat_production_count": topo.flat_production_count,
        "flat_production_ceiling": 1,
        "allowed_subpackages": ["pipelines"],
    }
    issues = compare_topology_to_manifest(topo, manifest)
    assert any("ceiling" in i for i in issues)


def test_forbidden_modularity_claim(tmp_path: Path) -> None:
    (tmp_path / "bad.md").write_text("We have clean modular architecture.\n", encoding="utf-8")
    issues = audit_package_topology_claims(root=tmp_path)
    assert any("forbidden" in i for i in issues)


def test_pkg_audit_cli_json() -> None:
    buf = StringIO()
    with redirect_stdout(buf):
        assert pkg_audit_main(["--json"]) == 0
    assert json.loads(buf.getvalue())["ok"] is True


def test_write_manifest_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pkg = tmp_path / "super_otonom"
    pkg.mkdir()
    (pkg / "mod_a.py").write_text("", encoding="utf-8")
    out = tmp_path / "data" / "m.json"
    monkeypatch.setattr("super_otonom.audit.package_topology._PKG", pkg)
    monkeypatch.setattr("super_otonom.audit.package_topology._DEFAULT_MANIFEST", out)
    write_manifest(out, pkg_root=pkg)
    assert out.is_file()


def test_compare_missing_manifest_list() -> None:
    topo = scan_package_topology()
    issues = compare_topology_to_manifest(topo, {"allowed_subpackages": ["pipelines"]})
    assert any("flat_production_modules list missing" in i for i in issues)


def test_compare_unexpected_subpackage(tmp_path: Path) -> None:
    pkg = tmp_path / "super_otonom" / "extra_pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    topo = scan_package_topology(tmp_path / "super_otonom")
    issues = compare_topology_to_manifest(
        topo,
        {"allowed_subpackages": ["pipelines"], "flat_production_modules": topo.flat_production_modules},
    )
    assert any("unexpected subpackages" in i for i in issues)


def test_validate_missing_compose_marker(tmp_path: Path) -> None:
    (tmp_path / "docker-compose.yml").write_text("# no audit\n", encoding="utf-8")
    issues = validate_package_topology_contract(tmp_path)
    assert any("audit 7" in i for i in issues)


def _minimal_pkg_tree(root: Path) -> Path:
    pkg = root / "super_otonom" / "pipelines"
    pkg.mkdir(parents=True)
    (root / "super_otonom" / "mod.py").write_text("", encoding="utf-8")
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "risk_pipeline.py").write_text("", encoding="utf-8")
    return root / "super_otonom"


def test_validate_bad_manifest_json(tmp_path: Path) -> None:
    _minimal_pkg_tree(tmp_path)
    (tmp_path / "docker-compose.yml").write_text("# audit 7\n", encoding="utf-8")
    man = tmp_path / "data" / "package_topology_manifest.json"
    man.parent.mkdir(parents=True)
    man.write_text("{bad", encoding="utf-8")
    issues = validate_package_topology_contract(tmp_path)
    assert any("invalid JSON" in i for i in issues)


def test_validate_manifest_institutional_flag(tmp_path: Path) -> None:
    pkg_root = _minimal_pkg_tree(tmp_path)
    (tmp_path / "docker-compose.yml").write_text("# audit 7\n", encoding="utf-8")
    man = tmp_path / "data" / "package_topology_manifest.json"
    man.parent.mkdir(parents=True)
    topo = scan_package_topology(pkg_root)
    payload = {
        "flat_production_modules": topo.flat_production_modules,
        "flat_production_count": topo.flat_production_count,
        "flat_production_ceiling": 999,
        "allowed_subpackages": ["pipelines"],
        "institutional_modular_boundary_claim_allowed": True,
    }
    man.write_text(json.dumps(payload), encoding="utf-8")
    issues = validate_package_topology_contract(tmp_path)
    assert any("institutional_modular_boundary_claim_allowed" in i for i in issues)


def test_package_topology_cli_json(capsys: pytest.CaptureFixture[str]) -> None:
    from super_otonom.package_topology import main as topo_main

    assert topo_main(["--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True


def test_audit_missing_institutional_in_module(tmp_path: Path) -> None:
    pkg = tmp_path / "super_otonom"
    pkg.mkdir()
    (pkg / "package_topology.py").write_text("# stub\n", encoding="utf-8")
    issues = audit_package_topology_claims(root=tmp_path)
    assert any("institutional_modular_boundary_claim_allowed" in i for i in issues)


def test_pkg_audit_text_ok(capsys: pytest.CaptureFixture[str]) -> None:
    assert pkg_audit_main([]) == 0
    assert "OK: True" in capsys.readouterr().out


def test_compare_count_mismatch() -> None:
    topo = scan_package_topology()
    issues = compare_topology_to_manifest(
        topo,
        {
            "flat_production_modules": topo.flat_production_modules,
            "flat_production_count": topo.flat_production_count + 1,
            "allowed_subpackages": ["pipelines"],
        },
    )
    assert any("flat_production_count mismatch" in i for i in issues)


def test_compare_missing_subpackage(tmp_path: Path) -> None:
    pkg = tmp_path / "super_otonom"
    pkg.mkdir()
    (pkg / "a.py").write_text("", encoding="utf-8")
    topo = scan_package_topology(pkg)
    issues = compare_topology_to_manifest(
        topo,
        {
            "flat_production_modules": topo.flat_production_modules,
            "allowed_subpackages": ["pipelines"],
        },
    )
    assert any("missing expected subpackages" in i for i in issues)


def test_validate_missing_compose(tmp_path: Path) -> None:
    issues = validate_package_topology_contract(tmp_path)
    assert any("docker-compose.yml" in i for i in issues)


def test_disclosure_above_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    topo = scan_package_topology()
    monkeypatch.setattr("super_otonom.audit.package_topology.FLAT_PROD_CEILING", 1)
    d = package_disclosure(topo=topo)
    assert "flat_production_above_ceiling" in d["limitations"]


def test_topology_main_fail(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from super_otonom.audit.package_topology import main as topo_main

    monkeypatch.setattr(
        "super_otonom.audit.package_topology.validate_package_topology_contract",
        lambda repo_root=None: ["fake fail"],
    )
    assert topo_main([]) == 1
    assert "FAIL" in capsys.readouterr().out
