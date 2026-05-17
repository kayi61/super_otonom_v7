"""sharpe_audit / survivorship_audit / ha_audit — hata yolları ve CLI (coverage)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from super_otonom.clock_skew_audit import audit_clock_skew_claims
from super_otonom.clock_skew_audit import main as clock_main
from super_otonom.ha_audit import audit_ha_claims
from super_otonom.ha_audit import main as ha_main
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
    (tmp_path / "evil.py").write_text("".join(("252", "*", "24", "*", "12", "\n")), encoding="utf-8")
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
    (tmp_path / "claim.py").write_text(
        "institutional universe backtest\n", encoding="utf-8"
    )
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


def test_package_topology_validate_missing_manifest(tmp_path: Path) -> None:
    from super_otonom.package_topology import validate_package_topology_contract

    (tmp_path / "docker-compose.yml").write_text("# audit 7\n", encoding="utf-8")
    issues = validate_package_topology_contract(tmp_path)
    assert any("package_topology_manifest.json" in i for i in issues)


def test_clock_skew_wiring_partial(tmp_path: Path) -> None:
    from super_otonom.clock_skew import validate_clock_skew_wiring

    (tmp_path / "docker-compose.yml").write_text("# audit 6\n", encoding="utf-8")
    prom = tmp_path / "docker" / "prometheus"
    prom.mkdir(parents=True)
    (prom / "alerts.yml").write_text(
        "bot_clock_skew_abs_ms\nBotClockSkewHigh\n", encoding="utf-8"
    )
    pkg = tmp_path / "super_otonom"
    pkg.mkdir()
    (pkg / "metrics_exporter.py").write_text(
        "clock_skew_abs_ms clock_skew_exchange_ms host_ntp_synchronized\n",
        encoding="utf-8",
    )
    (pkg / "config.py").write_text("CLOCK_SKEW = {}\n", encoding="utf-8")
    assert validate_clock_skew_wiring(tmp_path) == []
