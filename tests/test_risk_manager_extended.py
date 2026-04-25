"""RiskManager: VaR, trailing, reset, statik path."""
from __future__ import annotations

import numpy as np
from super_otonom.config import RISK
from super_otonom.risk_manager import RiskManager


def test_calculate_var_insufficient_history() -> None:
    rm = RiskManager(10_000.0)
    assert rm.calculate_var() == 0.0


def test_calculate_var_with_history() -> None:
    rm = RiskManager(10_000.0)
    rng = np.random.default_rng(0)
    for _ in range(25):
        rm.record_pnl(float(rng.normal(0, 10)))
    v = rm.calculate_var()
    assert isinstance(v, float)


def test_trailing_stop_triggers() -> None:
    rm = RiskManager(1.0)
    assert rm.should_trailing_stop(entry=100.0, current=100.0, peak=120.0) is True


def test_trailing_stop_no_peak_gain() -> None:
    rm = RiskManager(1.0)
    assert rm.should_trailing_stop(entry=100.0, current=99.0, peak=99.0) is False


def test_reset_emergency() -> None:
    rm = RiskManager(1000.0)
    rm.emergency_stop = True
    rm.reset_emergency()
    assert rm.emergency_stop is False


def test_check_risk_with_zero_vol_uses_static_daily_cap() -> None:
    rm = RiskManager(10_000.0)
    cap = RISK["max_daily_loss_pct"]
    rm.daily_loss = cap * 10_000.0 * 1.1
    assert rm.check_risk(10_000.0, 0.0, current_vol=0.0) is False
