"""Audit 8 — BotEngine god-class LOC ve sorumluluk alanları."""

from __future__ import annotations

import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import pytest
from super_otonom.bot_engine_audit import audit_bot_engine_claims
from super_otonom.bot_engine_audit import main as be_audit_main
from super_otonom.bot_engine_topology import (
    bot_engine_disclosure,
    compare_topology_to_manifest,
    inspect_bot_engine,
    validate_bot_engine_topology_contract,
    write_manifest,
)

pytestmark = pytest.mark.fastrun


def test_inspect_god_class_on_repo() -> None:
    topo = inspect_bot_engine()
    assert topo.file_line_count >= 1200
    assert topo.bot_engine_class_line_count >= 800
    assert topo.god_class is True
    assert topo.institutional_single_responsibility_claim_allowed is False
    assert {"tick", "entry", "exit", "risk", "state"}.issubset(set(topo.responsibility_domains))


def test_disclosure() -> None:
    d = bot_engine_disclosure()
    assert d["institutional_single_responsibility_claim_allowed"] is False
    assert d["topology"]["god_class"] is True


def test_validate_contract_repo() -> None:
    assert validate_bot_engine_topology_contract() == []


def test_audit_repo_clean() -> None:
    assert audit_bot_engine_claims() == []


def test_audit_cli_json() -> None:
    buf = StringIO()
    with redirect_stdout(buf):
        assert be_audit_main(["--json"]) == 0
    assert json.loads(buf.getvalue())["ok"] is True


def test_forbidden_claim(tmp_path: Path) -> None:
    (tmp_path / "bad.md").write_text(
        "Our BotEngine follows single responsibility principle.\n", encoding="utf-8"
    )
    issues = audit_bot_engine_claims(root=tmp_path)
    assert any("forbidden" in i for i in issues)


def test_compare_ceiling_exceeded() -> None:
    topo = inspect_bot_engine()
    issues = compare_topology_to_manifest(
        topo,
        {
            "institutional_single_responsibility_claim_allowed": False,
            "file_line_count": topo.file_line_count,
            "bot_engine_class_line_count": topo.bot_engine_class_line_count,
            "bot_engine_method_count": topo.bot_engine_method_count,
            "bot_engine_methods": topo.methods,
            "file_line_ceiling": 1,
            "class_line_ceiling": 1,
        },
    )
    assert any("ceiling" in i for i in issues)


def test_write_manifest_minimal(tmp_path: Path) -> None:
    eng = tmp_path / "super_otonom" / "bot_engine.py"
    eng.parent.mkdir(parents=True)
    eng.write_text(
        "class BotEngine:\n"
        "    def tick(self): pass\n"
        "    def process_signal(self): pass\n"
        "    def apply_filters(self): pass\n"
        "    def calculate_position(self): pass\n"
        "    def execute_trade(self): pass\n"
        "    async def _handle_entry(self): pass\n"
        "    async def _handle_exit(self): pass\n"
        "    def _entry_check_gates(self): pass\n"
        "    def _save_state(self): pass\n"
        "    def _load_state(self): pass\n"
        "    def status(self): pass\n"
        "    def shutdown(self): pass\n",
        encoding="utf-8",
    )
    out = tmp_path / "data" / "m.json"
    write_manifest(out, engine_path=eng)
    assert out.is_file()


def test_validate_missing_manifest(tmp_path: Path) -> None:
    _minimal_audit8_tree(tmp_path)
    issues = validate_bot_engine_topology_contract(tmp_path)
    assert any("bot_engine_topology_manifest" in i for i in issues)


def test_be_audit_text_ok(capsys: pytest.CaptureFixture[str]) -> None:
    assert be_audit_main([]) == 0
    assert "OK: True" in capsys.readouterr().out


def test_topology_main_json(capsys: pytest.CaptureFixture[str]) -> None:
    from super_otonom.bot_engine_topology import main as topo_main

    assert topo_main(["--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_topology_main_fail(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from super_otonom.bot_engine_topology import main as topo_main

    monkeypatch.setattr(
        "super_otonom.bot_engine_topology.validate_bot_engine_topology_contract",
        lambda repo_root=None: ["fail"],
    )
    assert topo_main([]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_validate_bad_json(tmp_path: Path) -> None:
    _minimal_audit8_tree(tmp_path)
    man = tmp_path / "data" / "bot_engine_topology_manifest.json"
    man.parent.mkdir(parents=True, exist_ok=True)
    man.write_text("{", encoding="utf-8")
    issues = validate_bot_engine_topology_contract(tmp_path)
    assert any("invalid JSON" in i for i in issues)


def test_validate_compose_marker(tmp_path: Path) -> None:
    (tmp_path / "docker-compose.yml").write_text("# no marker\n", encoding="utf-8")
    issues = validate_bot_engine_topology_contract(tmp_path)
    assert any("audit 8" in i for i in issues)


def test_compare_method_list_mismatch() -> None:
    topo = inspect_bot_engine()
    issues = compare_topology_to_manifest(
        topo,
        {
            "institutional_single_responsibility_claim_allowed": False,
            "file_line_count": topo.file_line_count,
            "bot_engine_class_line_count": topo.bot_engine_class_line_count,
            "bot_engine_method_count": topo.bot_engine_method_count,
            "bot_engine_methods": [],
            "file_line_ceiling": 9999,
            "class_line_ceiling": 9999,
        },
    )
    assert any("new BotEngine methods" in i for i in issues)


def test_audit_missing_institutional_flag(tmp_path: Path) -> None:
    pkg = tmp_path / "super_otonom"
    pkg.mkdir()
    (pkg / "bot_engine_topology.py").write_text("# stub\n", encoding="utf-8")
    issues = audit_bot_engine_claims(root=tmp_path)
    assert any("institutional_single_responsibility_claim_allowed" in i for i in issues)


def _minimal_audit8_tree(root: Path) -> None:
    (root / "docker-compose.yml").write_text("# audit 8\n", encoding="utf-8")
    eng = root / "super_otonom" / "bot_engine.py"
    eng.parent.mkdir(parents=True)
    eng.write_text(
        "class BotEngine:\n"
        "    def tick(self): pass\n"
        "    def process_signal(self): pass\n"
        "    def apply_filters(self): pass\n"
        "    def calculate_position(self): pass\n"
        "    def execute_trade(self): pass\n"
        "    async def _handle_entry(self): pass\n"
        "    async def _handle_exit(self): pass\n"
        "    def _entry_check_gates(self): pass\n"
        "    def _save_state(self): pass\n"
        "    def _load_state(self): pass\n"
        "    def status(self): pass\n"
        "    def shutdown(self): pass\n",
        encoding="utf-8",
    )
