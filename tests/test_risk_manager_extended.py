"""RiskManager: VaR, trailing, reset, statik path."""

from __future__ import annotations

import numpy as np
import pytest
from super_otonom.config import RISK
from super_otonom.risk_manager import RiskManager


def test_calculate_var_insufficient_history() -> None:
    rm = RiskManager(10_000.0)
    assert rm.calculate_var() == 0.0


def test_calculate_var_with_history() -> None:
    rm = RiskManager(10_000.0)
    rng = np.random.default_rng(0)
    for _ in range(120):
        rm.record_pnl(float(rng.normal(0, 10)))
    v = rm.calculate_var()
    assert isinstance(v, float)
    assert v != 0.0


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


def test_check_risk_dynamic_daily_denies_via_check_risk(monkeypatch: pytest.MonkeyPatch) -> None:
    """237-238: current_vol>0 ve check_dynamic_risk False → dynamic_daily_loss."""
    monkeypatch.setattr(RiskManager, "_maybe_reset", lambda self: None)
    rm = RiskManager(10_000.0)
    rm.daily_loss = 400.0
    assert rm.check_risk(9_600.0, 0.0, current_vol=0.01) is False
    assert rm.get_last_deny() == "dynamic_daily_loss"


def test_check_risk_max_drawdown_emergency(monkeypatch: pytest.MonkeyPatch) -> None:
    """267-276: peak–trough drawdown eşiği."""
    monkeypatch.setattr(RiskManager, "_maybe_reset", lambda self: None)
    rm = RiskManager(10_000.0)
    rm.daily_loss = 0.0
    rm.weekly_loss = 0.0
    rm._peak_equity = 10_000.0
    assert rm.check_risk(7_990.0, 0.0, current_vol=0.01) is False
    assert rm.get_last_deny() == "max_drawdown"


def test_check_risk_max_exposure_emergency(monkeypatch: pytest.MonkeyPatch) -> None:
    """283-285: exposure_breach_emergency=True iken aşım."""
    monkeypatch.setitem(RISK, "exposure_breach_emergency", True)
    monkeypatch.setattr(RiskManager, "_maybe_reset", lambda self: None)
    rm = RiskManager(10_000.0)
    rm.daily_loss = 0.0
    rm.weekly_loss = 0.0
    rm._peak_equity = 10_000.0
    assert rm.check_risk(10_000.0, open_exposure=3_500.0, current_vol=0.01) is False
    assert rm.get_last_deny() == "max_exposure"
    assert rm.emergency_stop is True


def test_check_risk_max_exposure_warning_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """290-296: exposure_breach_emergency=False."""
    monkeypatch.setitem(RISK, "exposure_breach_emergency", False)
    monkeypatch.setattr(RiskManager, "_maybe_reset", lambda self: None)
    rm = RiskManager(10_000.0)
    rm.daily_loss = 0.0
    rm.weekly_loss = 0.0
    rm._peak_equity = 10_000.0
    assert rm.check_risk(10_000.0, open_exposure=3_500.0, current_vol=0.01) is False
    assert rm.get_last_deny() == "max_exposure"
    assert rm.emergency_stop is False
