"""Audit 5 — tek-host HA topolojisi ve iddia taraması."""

from __future__ import annotations

import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import pytest
from super_otonom.ha_audit import audit_ha_claims
from super_otonom.ha_audit import main as ha_audit_main
from super_otonom.ha_topology import (
    ha_disclosure,
    inspect_docker_compose,
    validate_compose_ha_contract,
)

pytestmark = pytest.mark.fastrun


def test_compose_single_bot_instance() -> None:
    topo = inspect_docker_compose()
    assert topo.bot_replicas == 1
    assert topo.single_bot_instance is True
    assert topo.institutional_ha_claim_allowed is False


def test_ha_disclosure_defaults() -> None:
    d = ha_disclosure()
    assert d["institutional_ha_claim_allowed"] is False
    assert d["ha_bias_controlled"] is True
    assert "no_multi_az" in d["limitations"]


def test_validate_compose_marker_present() -> None:
    assert validate_compose_ha_contract() == []


def test_validate_compose_rejects_multi_replica(tmp_path: Path) -> None:
    bad = tmp_path / "docker-compose.yml"
    bad.write_text(
        "  bot:\n    deploy:\n      replicas: 2\n",
        encoding="utf-8",
    )
    issues = validate_compose_ha_contract(bad)
    assert any("replicas=2" in i for i in issues)


def test_audit_repo_clean() -> None:
    assert audit_ha_claims() == []


def test_ha_audit_cli_json() -> None:
    buf = StringIO()
    with redirect_stdout(buf):
        assert ha_audit_main(["--json"]) == 0
    payload = json.loads(buf.getvalue())
    assert payload["ok"] is True
    assert payload["disclosure"]["institutional_ha_claim_allowed"] is False


def test_forbidden_ha_claim_detected(tmp_path: Path) -> None:
    (tmp_path / "bad.md").write_text("We offer high availability cluster.\n", encoding="utf-8")
    issues = audit_ha_claims(root=tmp_path)
    assert any("forbidden HA" in i for i in issues)
