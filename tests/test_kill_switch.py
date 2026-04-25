"""Kill-switch: global gate, sert sınır sayaçları (unit)."""
from __future__ import annotations

import pytest
from super_otonom.kill_switch import HardLimitTracker
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
