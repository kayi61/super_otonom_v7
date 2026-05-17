"""Audit 9 — paket içi test_*.py ve wheel exclude."""

from __future__ import annotations

import json
import shutil
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import pytest
from super_otonom.layout_topology import (
    count_wheel_test_modules,
    scan_in_package_test_modules,
    validate_test_layout_contract,
    write_manifest,
)
from super_otonom.layout_topology import (
    layout_disclosure as layout_disclosure_fn,
)
from super_otonom.layout_topology_audit import audit_test_layout_claims
from super_otonom.layout_topology_audit import main as layout_audit_main

pytestmark = pytest.mark.fastrun


def test_in_package_test_count() -> None:
    mods = scan_in_package_test_modules()
    assert len(mods) >= 29
    assert "test_5000.py" in mods


def test_disclosure_not_institutional() -> None:
    d = layout_disclosure_fn()
    assert d["institutional_production_test_layout_claim_allowed"] is False
    assert d["topology"]["canonical_test_dir"] == "tests"


def test_validate_repo_contract() -> None:
    assert validate_test_layout_contract() == []


def test_audit_repo_clean() -> None:
    assert audit_test_layout_claims() == []


def test_wheel_excludes_package_tests() -> None:
    from super_otonom.layout_topology import build_wheel_for_audit

    repo_build = Path("build") / "audit9_pytest_wheel"
    if repo_build.exists():
        shutil.rmtree(repo_build)
    whl = build_wheel_for_audit(out_dir=repo_build)
    assert count_wheel_test_modules(whl) == 0


def test_forbidden_layout_claim(tmp_path: Path) -> None:
    (tmp_path / "bad.md").write_text("We have a clean package without tests.\n", encoding="utf-8")
    issues = audit_test_layout_claims(root=tmp_path)
    assert any("forbidden" in i for i in issues)


def test_audit_cli_json() -> None:
    buf = StringIO()
    with redirect_stdout(buf):
        assert layout_audit_main(["--json"]) == 0
    assert json.loads(buf.getvalue())["ok"] is True


def test_write_manifest_roundtrip(tmp_path: Path) -> None:
    pkg = tmp_path / "super_otonom"
    pkg.mkdir()
    (pkg / "test_x.py").write_text("", encoding="utf-8")
    out = tmp_path / "data" / "m.json"
    write_manifest(out, pkg_root=pkg)
    assert out.is_file()
