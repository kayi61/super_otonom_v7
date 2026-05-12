"""Kill-switch: global gate, sert sınır sayaçları (unit)."""

from __future__ import annotations

from unittest import mock

import pytest
from super_otonom.kill_switch import (
    HardLimitTracker,
    apply_storm_trip_to_risk,
    default_hard_limit_config,
    is_ratelimit_error,
)
from super_otonom.pre_trade_gate import gate_global_trade_disable
from super_otonom.risk_manager import RiskManager


def test_global_trade_disable_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GLOBAL_TRADE_DISABLE", "1")
    ok, code = gate_global_trade_disable()
    assert ok is False
    assert code == "global_trade_disable"


def test_global_trade_allows_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GLOBAL_TRADE_DISABLE", raising=False)
    ok, code = gate_global_trade_disable()
    assert ok is True
    assert code == ""


def test_hard_limit_order_burst() -> None:
    h = HardLimitTracker(max_orders=2, window_sec=1.0, max_price_jump_pct=0.5)
    assert h.can_submit_order() is None
    h.record_order()
    assert h.can_submit_order() is None
    h.record_order()
    assert h.can_submit_order() == "order_rate_exceeded"


def test_hard_limit_price_spike() -> None:
    h = HardLimitTracker(max_orders=5, window_sec=1.0, max_price_jump_pct=0.01)
    assert h.check_price_tick("X", 100.0) is None
    assert h.check_price_tick("X", 100.5) is None  # 0.5% move
    assert h.check_price_tick("X", 200.0) == "price_spike"


def test_risk_trigger_emergency_sets_reason() -> None:
    rm = RiskManager(10_000.0)
    rm.trigger_emergency("test")
    assert rm.emergency_stop is True
    assert rm.emergency_reason == "test"
    st = rm.status_dict()
    assert st.get("emergency_reason") == "test"


def test_rate_limit_storm_poll_after_streak() -> None:
    import super_otonom.kill_switch as ks

    t = ks.RateLimitStormTracker(max_consecutive=3)
    t.on_ratelimit()
    t.on_ratelimit()
    assert t.poll_trip() is None
    t.on_ratelimit()
    assert t.poll_trip() == "rate_limit_storm"

    ks._rl_storm = ks.RateLimitStormTracker(max_consecutive=2)
    ks._rl_storm.on_ratelimit()
    ks._rl_storm.on_ratelimit()
    rm = RiskManager(20_000.0)
    from super_otonom.kill_switch import apply_storm_trip_to_risk

    assert apply_storm_trip_to_risk(rm) is True
    assert rm.emergency_stop is True
    assert apply_storm_trip_to_risk(rm) is False
    ks._rl_storm = None


def test_default_hard_limit_invalid_env_uses_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """20-21, 27-28: _f / _i ValueError yolları."""
    monkeypatch.setenv("KILL_ORDER_WINDOW_SEC", "not_a_float")
    monkeypatch.setenv("KILL_MAX_ORDERS_PER_SEC", "not_an_int")
    d = default_hard_limit_config()
    assert d["window_sec"] == 1.0
    assert isinstance(d["max_orders"], int) and d["max_orders"] >= 1


def test_hard_limit_prune_removes_stale_timestamps() -> None:
    """75: popleft döngüsü."""
    h = HardLimitTracker(max_orders=10, window_sec=1.0, max_price_jump_pct=0.5)
    _t = iter([0.0, 0.0, 10.0])

    def _now() -> float:
        return next(_t)

    with mock.patch("super_otonom.kill_switch.time.time", side_effect=_now):
        h.record_order()
        assert len(h._order_times) == 1
        h._prune_orders()
        assert len(h._order_times) == 0


def test_hard_limit_nonpositive_price_skips_spike() -> None:
    """96: p <= 0."""
    h = HardLimitTracker(max_orders=5, window_sec=1.0, max_price_jump_pct=0.01)
    assert h.check_price_tick("Z", 0.0) is None
    assert h.check_price_tick("Z", -5.0) is None


def test_is_ratelimit_error_heuristic_branches() -> None:
    """127-134: isim / metin tabanlı eşleşmeler."""
    assert is_ratelimit_error(type("DDoSProtection", (Exception,), {})()) is True
    assert is_ratelimit_error(Exception("Too many requests")) is True
    assert is_ratelimit_error(Exception("http error 429 code")) is True
    assert is_ratelimit_error(Exception(" 429 timeout")) is True


def test_apply_storm_trip_false_when_already_emergency() -> None:
    """190-192: zaten emergency ise False."""
    import super_otonom.kill_switch as ks

    ks._rl_storm = ks.RateLimitStormTracker(max_consecutive=1)
    ks._rl_storm.on_ratelimit()
    rm = RiskManager(10_000.0)
    rm.emergency_stop = True
    assert apply_storm_trip_to_risk(rm) is False
    ks._rl_storm = None
