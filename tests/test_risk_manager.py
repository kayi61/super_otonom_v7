"""RiskManager critical paths (Faz 1)."""
from __future__ import annotations

from super_otonom.risk_manager import RiskManager


def test_risk_rejects_when_emergency_stop() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm.emergency_stop = True
    assert rm.check_risk(10_000.0, 0.0, 0.0) is False


def test_risk_rejects_zero_or_negative_capital() -> None:
    rm = RiskManager(initial_capital=0.0)
    assert rm.check_risk(0.0, 0.0, 0.0) is False

    rm2 = RiskManager(initial_capital=-1.0)
    assert rm2.check_risk(100.0, 0.0, 0.0) is False


def test_dynamic_risk_trip_sets_emergency() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    # High daily loss: e.g. 3% of capital with dynamic limit from vol
    rm.daily_loss = 400.0  # 4% of 10k
    ok = rm.check_dynamic_risk(9_600.0, market_volatility=0.01)
    # limit = clamp(0.02, 0.05, 0.01*2)=0.02 → 2% → daily 4% > 2% → False
    assert ok is False
    assert rm.emergency_stop is True
    assert rm.emergency_reason == "dynamic_daily_loss"


def test_check_risk_passes_healthy_path() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    assert rm.check_risk(10_000.0, open_exposure=0.0, current_vol=0.01) is True


def test_volatility_spike_blocks_when_huge_vs_history() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    for v in [0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01]:
        rm.record_volatility(v)
    # current 10x average → spike
    assert rm.check_volatility_spike(0.10, spike_multiplier=2.0, min_history=10) is False
