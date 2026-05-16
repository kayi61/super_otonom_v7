"""Audit 2: hard_safety_contract — doc-only sabitler + gerçek enforcement wiring."""

from __future__ import annotations

import json
from io import StringIO

import pytest

from super_otonom import hard_safety_contract as hsc
from super_otonom.hard_safety_contract import (
    HARD_SAFETY_ENFORCEMENT,
    audit_bot_engine_uses_contract,
    audit_hard_safety_wiring,
    assert_hard_safety_wired,
    enforce_entry_leverage_cap,
    enforce_global_trade_allowed,
    main,
    risk_limit,
    snapshot_active_limits,
)
from super_otonom.pre_trade_gate import fat_finger_check, gate_global_trade_disable

pytestmark = pytest.mark.fastrun


def test_enforcement_map_not_empty() -> None:
    assert len(HARD_SAFETY_ENFORCEMENT) >= 7


def test_audit_wiring_passes() -> None:
    assert audit_hard_safety_wiring() == []


def test_assert_hard_safety_wired() -> None:
    assert_hard_safety_wired()


def test_snapshot_reads_risk_keys() -> None:
    snap = snapshot_active_limits()
    assert "max_leverage" in snap
    assert "max_notional_per_order" in snap


def test_global_trade_disable_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GLOBAL_TRADE_DISABLE", "1")
    ok, reason = gate_global_trade_disable()
    assert ok is False
    assert reason == "global_trade_disable"


def test_fat_finger_blocks_oversized_order() -> None:
    ok, reason = fat_finger_check(100_000.0, max_notional=50_000.0)
    assert ok is False
    assert "fat_finger" in reason


def test_main_json_ok() -> None:
    buf = StringIO()
    import sys

    old = sys.stdout
    sys.stdout = buf
    try:
        code = main(["--json"])
    finally:
        sys.stdout = old
    assert code == 0
    payload = json.loads(buf.getvalue())
    assert payload["ok"] is True
    assert hsc.HARD_SAFETY_CONFIG_NAMESPACE in ("RISK", payload["config_namespace"])


def test_broken_wiring_detected() -> None:
    fake_risk = {"max_leverage": 1.0}
    issues = audit_hard_safety_wiring(risk=fake_risk)
    assert any("RISK missing" in x for x in issues)


def test_bot_engine_imports_contract() -> None:
    assert audit_bot_engine_uses_contract() == []


def test_enforce_leverage_cap_from_risk() -> None:
    ok, _ = enforce_entry_leverage_cap(10_000.0, float(risk_limit("max_notional_per_order")) + 1.0)
    assert ok is False


def test_enforce_global_trade() -> None:
    ok, _ = enforce_global_trade_allowed()
    assert isinstance(ok, bool)
