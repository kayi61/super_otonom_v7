"""pre_trade_gate.merge_entry_notional — tek kaynak birleşimi."""
from __future__ import annotations

from super_otonom.pre_trade_gate import merge_entry_notional


def test_merge_none_ob_uses_technical_only() -> None:
    r, src, blk = merge_entry_notional(100.0, None)
    assert r == 100.0
    assert src == "technical_only"
    assert blk == ""


def test_merge_caps_by_order_book() -> None:
    r, src, blk = merge_entry_notional(100.0, 30.0)
    assert r == 30.0
    assert src == "min_technical_ob_safe"
    assert blk == ""


def test_merge_ob_zero_blocks() -> None:
    r, src, blk = merge_entry_notional(100.0, 0.0)
    assert r == 0.0
    assert blk == "ob_safe_size_zero"


def test_merge_invalid_ob_falls_back() -> None:
    r, src, blk = merge_entry_notional(50.0, "bad")
    assert r == 50.0
    assert src == "technical_only_invalid_ob"
