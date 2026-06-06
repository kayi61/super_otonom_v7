"""hard_safety_contract gercek kapsama testleri — saf mantik + audit, ag yok.

Onceki %72; enforce wrapper'lari + audit zinciri + CLI kapsanir.
"""
from __future__ import annotations

import pytest
from super_otonom import hard_safety_contract as hsc


def test_risk_limit_returns_value():
    # max_position_pct RISK'te var (gate_leverage_notional kullanir)
    val = hsc.risk_limit("max_position_pct")
    assert val is not None


def test_risk_limit_missing_raises():
    with pytest.raises(KeyError):
        hsc.risk_limit("kesinlikle_olmayan_anahtar_xyz")


def test_risk_limit_default_when_missing():
    assert hsc.risk_limit("kesinlikle_olmayan_anahtar_xyz", default=42) == 42


def test_snapshot_active_limits_is_dict():
    snap = hsc.snapshot_active_limits()
    assert isinstance(snap, dict)
    # En az bir bilinen RISK anahtari donmeli
    assert any(k in snap for k in ("max_leverage", "max_position_pct", "max_exposure_pct"))


def test_snapshot_active_limits_custom_risk():
    snap = hsc.snapshot_active_limits(risk={"max_leverage": 3.0})
    assert snap == {"max_leverage": 3.0}


def test_audit_bot_engine_uses_contract_returns_list():
    issues = hsc.audit_bot_engine_uses_contract()
    assert isinstance(issues, list)


def test_audit_hard_safety_wiring_clean():
    # Kod tabani dogru bagliysa bos liste; degilse issue listesi (yine de list).
    issues = hsc.audit_hard_safety_wiring()
    assert isinstance(issues, list)
    # Wiring bozuk olmamali (canli kod tabani)
    assert issues == [], f"hard_safety wiring issues: {issues}"


def test_audit_wiring_detects_missing_risk_key():
    # Eksik RISK ile cagrilinca risk_keys ihlali yakalanmali
    issues = hsc.audit_hard_safety_wiring(risk={})
    assert isinstance(issues, list)
    assert any("RISK missing key" in s for s in issues)


def test_assert_hard_safety_wired_ok():
    # Canli kod tabaninda exception atmamali
    hsc.assert_hard_safety_wired()


def test_assert_hard_safety_wired_raises_on_broken():
    with pytest.raises(RuntimeError):
        hsc.assert_hard_safety_wired(risk={})


def test_enforce_global_trade_allowed_tuple():
    allowed, code = hsc.enforce_global_trade_allowed()
    assert isinstance(allowed, bool)
    assert isinstance(code, str)


def test_enforce_entry_signal_gates_tuple():
    ok, code = hsc.enforce_entry_signal_gates("BUY", open_position_count=0, confidence=0.9)
    assert isinstance(ok, bool) and isinstance(code, str)


def test_enforce_entry_cooldown_tuple():
    ok, code = hsc.enforce_entry_cooldown("BTCUSDT", {})
    assert isinstance(ok, bool) and isinstance(code, str)


def test_enforce_entry_leverage_cap_tuple():
    ok, code = hsc.enforce_entry_leverage_cap(equity=10_000.0, order_notional=100.0)
    assert isinstance(ok, bool) and isinstance(code, str)


def test_enforce_entry_prechecks_returns_triple():
    ok, bar_ts, code = hsc.enforce_entry_prechecks(
        symbol="BTCUSDT",
        signal="BUY",
        confidence=0.9,
        candles=[{"timestamp": 123.0}],
        last_order_bar_ts={},
        last_entry_wall_ts={},
        open_position_count=0,
    )
    assert isinstance(ok, bool)
    assert bar_ts == 123.0
    assert isinstance(code, str)


def test_enforce_entry_prechecks_same_bar_block():
    # Ayni bar daha once islendiyse same_bar_guard bloklamali
    last_bar = {"BTCUSDT": 500.0}
    ok, bar_ts, code = hsc.enforce_entry_prechecks(
        symbol="BTCUSDT",
        signal="BUY",
        confidence=0.9,
        candles=[{"timestamp": 500.0}],
        last_order_bar_ts=last_bar,
        last_entry_wall_ts={},
        open_position_count=0,
    )
    assert ok is False
    assert code  # bos olmayan block code


def test_main_json(capsys):
    rc = hsc.main(["--json"])
    assert rc == 0
    out = capsys.readouterr().out
    assert '"ok"' in out


def test_main_plain(capsys):
    rc = hsc.main([])
    assert rc == 0
    assert "hard_safety_contract audit" in capsys.readouterr().out
