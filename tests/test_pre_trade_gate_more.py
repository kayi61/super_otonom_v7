"""pre_trade_gate — ek dal kapsamı."""
from __future__ import annotations

import pytest
from super_otonom.config import RISK
from super_otonom.position_sizer import PositionSizer
from super_otonom.pre_trade_gate import (
    _min_entry_confidence,
    gate_buy_signal_and_slots,
    gate_buy_size_and_exposure,
    gate_global_trade_disable,
    merge_entry_notional,
)


def test_gate_global_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GLOBAL_TRADE_DISABLE", "true")
    ok, code = gate_global_trade_disable()
    assert ok is False and code == "global_trade_disable"
    monkeypatch.delenv("GLOBAL_TRADE_DISABLE", raising=False)


def test_gate_global_allows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GLOBAL_TRADE_DISABLE", raising=False)
    ok, code = gate_global_trade_disable()
    assert ok is True and code == ""


def test_min_entry_env_invalid_uses_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENTRY_MIN_CONFIDENCE", "nope")
    assert _min_entry_confidence() == 0.55


def test_gate_buy_not_buy_signal() -> None:
    ok, _ = gate_buy_signal_and_slots("HOLD", 99, 0.1)
    assert ok is True


def test_gate_buy_max_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(RISK, "max_open_positions", 1)
    ok, b = gate_buy_signal_and_slots("BUY", 1, 0.99)
    assert ok is False and "max_open" in b


def test_gate_buy_low_confidence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(RISK, "max_open_positions", 5)
    monkeypatch.setenv("ENTRY_MIN_CONFIDENCE", "0.99")
    ok, b = gate_buy_signal_and_slots("BUY", 0, 0.1)
    assert ok is False and "confidence" in b
    monkeypatch.delenv("ENTRY_MIN_CONFIDENCE", raising=False)


def test_merge_entry_variants() -> None:
    assert merge_entry_notional(100.0, None)[0] == 100.0
    assert merge_entry_notional(100.0, "x")[0] == 100.0
    a, b, c = merge_entry_notional(100.0, 0.0)
    assert a == 0.0 and "ob_safe" in c
    a2, s, _ = merge_entry_notional(200.0, 50.0)
    assert a2 == 50.0 and s == "min_technical_ob_safe"


def test_gate_buy_size_paths() -> None:
    s = PositionSizer(0.1, 10.0)
    ok, _ = gate_buy_size_and_exposure(s, "X", 1000.0, 0.0, 100.0, 500.0, {})
    assert ok is False
    ok2, r2 = gate_buy_size_and_exposure(s, "X", 1000.0, 100.0, 0.0, 500.0, {})
    assert ok2 is False and "raw" in r2
    ok3, r3 = gate_buy_size_and_exposure(s, "X", 1000.0, 100.0, 100.0, 0.0, {})
    assert ok3 is False and "insufficient" in r3
    ok4, r4 = gate_buy_size_and_exposure(s, "X", 1000.0, 100.0, 100.0, 1_000_000.0, {})
    assert ok4 is True and r4 == ""
