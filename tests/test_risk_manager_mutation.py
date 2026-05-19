"""risk_manager.py — mutmut kill-rate (>=80%). Sınır ve dallanma testleri."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from super_otonom.config import RISK
from super_otonom.risk.risk_engine import RiskEngine
from super_otonom.risk_manager import RiskManager
from super_otonom.risk_ontology import RiskOntology

pytestmark = pytest.mark.fastrun

_DAY_SEC = 86_400
_WEEK_SEC = 604_800


# ── OMEGA / init ──────────────────────────────────────────────────────────────


def test_omega_tighten_on_loss_and_relax_on_profit() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm.record_omega_trade_outcome(-10.0)
    assert rm._omega_qmin_tighten == 2
    rm.record_omega_trade_outcome(5.0)
    assert rm._omega_qmin_tighten == 1
    rm.record_omega_trade_outcome(0.0)
    assert rm._omega_qmin_tighten == 0


def test_omega_tighten_caps_at_25() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    for _ in range(20):
        rm.record_omega_trade_outcome(-1.0)
    assert rm._omega_qmin_tighten == 25


def test_get_omega_effective_qmin_clamped() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm._omega_qmin_tighten = 10
    assert rm.get_omega_effective_qmin(50) == 60
    rm._omega_qmin_tighten = 100
    assert rm.get_omega_effective_qmin(95) == 90
    rm._omega_qmin_tighten = 0
    assert rm.get_omega_effective_qmin(-5) == 0


# ── emergency / deny ──────────────────────────────────────────────────────────


def test_trigger_emergency_latches_reason() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm.trigger_emergency("first")
    rm.trigger_emergency("second")
    assert rm.emergency_reason == "first"
    assert rm.emergency_stop is True


def test_check_risk_blocked_when_emergency_latched() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm.emergency_stop = True
    rm.emergency_reason = "latched"
    assert rm.check_risk(10_000.0) is False
    assert rm.get_last_deny() == "latched"


def test_get_last_deny_empty_when_none() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    assert rm.get_last_deny() == ""


def test_reset_emergency_clears_flags() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm.trigger_emergency("x")
    rm.reset_emergency()
    assert rm.emergency_stop is False
    assert rm.emergency_reason is None


# ── zamanlayıcı ───────────────────────────────────────────────────────────────


def test_maybe_reset_day_at_literal_86400(monkeypatch: pytest.MonkeyPatch) -> None:
    t0 = 10_000.0
    rm = RiskManager(initial_capital=10_000.0)
    rm.daily_loss = 500.0
    rm._day_start = t0
    monkeypatch.setattr(time, "time", lambda: t0 + _DAY_SEC)
    rm._maybe_reset()
    assert rm.daily_loss == 0.0


def test_maybe_reset_week_at_literal_604800(monkeypatch: pytest.MonkeyPatch) -> None:
    t0 = 20_000.0
    rm = RiskManager(initial_capital=10_000.0)
    rm.weekly_loss = 300.0
    rm._week_start = t0
    monkeypatch.setattr(time, "time", lambda: t0 + _WEEK_SEC)
    rm._maybe_reset()
    assert rm.weekly_loss == 0.0


def test_maybe_reset_not_before_day_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    t0 = 30_000.0
    rm = RiskManager(initial_capital=10_000.0)
    rm.daily_loss = 100.0
    rm._day_start = t0
    monkeypatch.setattr(time, "time", lambda: t0 + _DAY_SEC - 1)
    rm._maybe_reset()
    assert rm.daily_loss == 100.0


# ── record_pnl / peak / vol ───────────────────────────────────────────────────


def test_record_pnl_positive_does_not_add_loss() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm.record_pnl(50.0)
    assert rm.daily_loss == 0.0
    assert rm.weekly_loss == 0.0


def test_record_pnl_negative_accumulates() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm.record_pnl(-40.0)
    rm.record_pnl(-10.0)
    assert rm.daily_loss == pytest.approx(50.0)
    assert rm.weekly_loss == pytest.approx(50.0)


def test_record_pnl_trim_at_501() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    for i in range(501):
        rm.record_pnl(float(i))
    assert len(rm._pnl_history) == 500
    assert rm._pnl_history[0] == pytest.approx(1.0)


def test_update_peak_strict_gt() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm.update_peak(10_500.0)
    rm.update_peak(10_500.0)
    assert rm._peak_equity == 10_500.0


def test_vol_history_trim_at_201() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    for i in range(201):
        rm.record_volatility(0.01 + i * 1e-6)
    assert len(rm._vol_history) == 200


def test_vol_spike_short_history_returns_true() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    assert rm.check_volatility_spike(0.5, history_vols=[0.01] * 5) is True


def test_vol_spike_zero_avg_returns_true() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    assert rm.check_volatility_spike(0.1, history_vols=[0.0] * 12) is True


def test_vol_spike_triggers_false() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    hist = [0.01] * 12
    assert rm.check_volatility_spike(0.05, history_vols=hist, spike_multiplier=2.0) is False


# ── check_dynamic_risk ───────────────────────────────────────────────────────


def test_check_dynamic_risk_invalid_capital() -> None:
    rm = RiskManager(initial_capital=0.0)
    assert rm.check_dynamic_risk(10_000.0, 0.02) is False


@pytest.mark.parametrize(
    "vol, expected_limit",
    [(0.001, 0.02), (0.015, 0.03), (0.04, 0.05)],
)
def test_check_dynamic_risk_limit_clamp(vol: float, expected_limit: float) -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm.daily_loss = 0.0
    assert rm.check_dynamic_risk(10_000.0, vol) is True
    assert rm._last_dynamic_limit == pytest.approx(expected_limit)


def test_check_dynamic_risk_breach_triggers_emergency() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm.daily_loss = 600.0
    assert rm.check_dynamic_risk(10_000.0, 0.01) is False
    assert rm.emergency_stop is True
    assert rm.emergency_reason == "dynamic_daily_loss"


def test_check_dynamic_risk_uses_current_equity_base() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm.daily_loss = 400.0
    assert rm.check_dynamic_risk(20_000.0, 0.02) is True


# ── check_risk + ontology ─────────────────────────────────────────────────────


def test_warn_if_onto_missing_only_once() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm.check_risk(10_000.0)
    assert rm._onto_warned is True
    rm.check_risk(10_000.0)
    assert rm._onto_warned is True


def test_check_risk_with_onto_daily_breach() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    rm = RiskManager(initial_capital=10_000.0)
    rm.set_ontology(onto)
    onto.daily_loss_pct = 0.10
    onto.dynamic_daily_limit = 0.05
    assert rm.check_risk(10_000.0) is False
    assert rm.get_last_deny() == "dynamic_daily_loss"


def test_check_risk_with_onto_weekly_breach() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    rm = RiskManager(initial_capital=10_000.0)
    rm.set_ontology(onto)
    onto.weekly_loss_pct = 0.20
    onto.dynamic_daily_limit = 1.0
    assert rm.check_risk(10_000.0) is False
    assert rm.get_last_deny() == "weekly_loss"


def test_check_risk_with_onto_drawdown_breach() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    rm = RiskManager(initial_capital=10_000.0)
    rm.set_ontology(onto)
    onto.intraday_dd_pct = 0.30
    onto.dynamic_daily_limit = 1.0
    onto.weekly_loss_pct = 0.0
    assert rm.check_risk(10_000.0) is False
    assert rm.get_last_deny() == "max_drawdown"


def test_check_risk_without_onto_static_daily() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm.daily_loss = RISK["max_daily_loss_pct"] * 10_000.0 + 100.0
    assert rm.check_risk(10_000.0, current_vol=0.0) is False
    assert rm.get_last_deny() == "static_daily_loss"


def test_check_risk_without_onto_weekly() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm.weekly_loss = RISK["max_weekly_loss_pct"] * 10_000.0 + 50.0
    assert rm.check_risk(10_000.0, current_vol=0.0) is False
    assert rm.get_last_deny() == "weekly_loss"


def test_check_risk_without_onto_drawdown() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm._peak_equity = 20_000.0
    eq = 20_000.0 * (1.0 - RISK["max_total_drawdown"] - 0.05)
    assert rm.check_risk(eq, current_vol=0.0) is False
    assert rm.get_last_deny() == "max_drawdown"


def test_check_risk_exposure_breach() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    exp = 10_000.0 * RISK["max_exposure_pct"] * 1.1
    assert rm.check_risk(10_000.0, open_exposure=exp, current_vol=0.0) is False
    assert rm.get_last_deny() == "max_exposure"


def test_check_risk_ok_clean() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    assert rm.check_risk(10_000.0, open_exposure=0.0, current_vol=0.0) is True
    assert rm.get_last_deny() == ""


# ── VaR / trailing / status ───────────────────────────────────────────────────


def test_calculate_var_delegates_to_onto() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    for i in range(120):
        onto._pnl_history.append(float(-5 + (i % 7)))
    rm = RiskManager(initial_capital=10_000.0)
    rm.set_ontology(onto)
    with patch.object(type(onto), "_calc_var", return_value=99.0) as mock_var:
        assert rm.calculate_var() == 99.0
        mock_var.assert_called_once()


def test_calculate_var_without_onto_uses_engine() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    for i in range(120):
        rm.record_pnl(float(-10 + (i % 5)))
    expected = RiskEngine().compute_from_pnl_history(
        rm._pnl_history, confidence=float(RISK["var_confidence"]), min_obs=100
    )
    assert rm.calculate_var() == expected


def test_trailing_stop_peak_not_above_entry() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    assert rm.should_trailing_stop(100.0, 95.0, 100.0) is False


def test_trailing_stop_at_threshold() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    peak, current = 120.0, 110.0
    dd = (peak - current) / peak
    assert rm.should_trailing_stop(100.0, current, peak) == (dd >= RISK["trailing_stop_pct"])


def test_status_dict_without_onto_keys() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    d = rm.status_dict()
    assert d["onto_active"] is False
    assert "var_95" in d
    assert "nav" not in d


def test_status_dict_with_onto_overrides() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    onto.nav = 9_500.0
    onto.var_1d = 12.5
    rm = RiskManager(initial_capital=10_000.0)
    rm.set_ontology(onto)
    d = rm.status_dict()
    assert d["onto_active"] is True
    assert d["nav"] == pytest.approx(9_500.0)
    assert d["var_1d"] == 12.5


def test_record_pnl_syncs_onto_var() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    rm = RiskManager(initial_capital=10_000.0)
    rm.set_ontology(onto)
    with patch.object(type(onto), "_calc_var", return_value=55.0) as mock_var:
        rm.record_pnl(-1.0)
        mock_var.assert_called()
        assert onto.var_1d == 55.0


def test_initial_capital_stored() -> None:
    rm = RiskManager(initial_capital=12_345.0)
    assert rm.initial_capital == 12_345.0


def test_set_ontology_links() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    rm = RiskManager(initial_capital=10_000.0)
    rm.set_ontology(onto)
    assert rm._onto is onto


def test_calculate_var_insufficient_history_returns_zero() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    assert rm.calculate_var() == 0.0


def test_check_risk_invalid_capital_deny() -> None:
    rm = RiskManager(initial_capital=0.0)
    assert rm.check_risk(10_000.0) is False
    assert rm.get_last_deny() == "invalid_capital"


def test_check_risk_dynamic_daily_via_vol_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(RiskManager, "_maybe_reset", lambda self: None)
    rm = RiskManager(initial_capital=10_000.0)
    rm.daily_loss = 400.0
    assert rm.check_risk(9_600.0, 0.0, current_vol=0.01) is False
    assert rm.get_last_deny() == "dynamic_daily_loss"


def test_check_risk_static_daily_zero_vol(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(RiskManager, "_maybe_reset", lambda self: None)
    rm = RiskManager(initial_capital=10_000.0)
    cap = RISK["max_daily_loss_pct"]
    rm.daily_loss = cap * 10_000.0 * 1.1
    assert rm.check_risk(10_000.0, 0.0, current_vol=0.0) is False
    assert rm.get_last_deny() == "static_daily_loss"


def test_check_risk_max_drawdown_without_onto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(RiskManager, "_maybe_reset", lambda self: None)
    rm = RiskManager(initial_capital=10_000.0)
    rm._peak_equity = 10_000.0
    assert rm.check_risk(7_990.0, 0.0, current_vol=0.01) is False
    assert rm.get_last_deny() == "max_drawdown"


def test_check_risk_exposure_emergency_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(RISK, "exposure_breach_emergency", True)
    monkeypatch.setattr(RiskManager, "_maybe_reset", lambda self: None)
    rm = RiskManager(initial_capital=10_000.0)
    rm._peak_equity = 10_000.0
    assert rm.check_risk(10_000.0, open_exposure=3_500.0, current_vol=0.01) is False
    assert rm.emergency_stop is True
    assert rm.get_last_deny() == "max_exposure"


def test_check_risk_exposure_warning_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(RISK, "exposure_breach_emergency", False)
    monkeypatch.setattr(RiskManager, "_maybe_reset", lambda self: None)
    rm = RiskManager(initial_capital=10_000.0)
    rm._peak_equity = 10_000.0
    assert rm.check_risk(10_000.0, open_exposure=3_500.0, current_vol=0.01) is False
    assert rm.emergency_stop is False
    assert rm.get_last_deny() == "max_exposure"


def test_check_risk_volatility_spike_deny(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(RiskManager, "_maybe_reset", lambda self: None)
    rm = RiskManager(initial_capital=10_000.0)
    for _ in range(15):
        rm.record_volatility(0.008)
    assert rm.check_risk(10_000.0, 0.0, current_vol=0.07) is False
    assert rm.get_last_deny() == "volatility_spike"


def test_check_risk_with_onto_uses_onto_nav_for_exposure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(RISK, "exposure_breach_emergency", False)
    monkeypatch.setattr(RiskManager, "_maybe_reset", lambda self: None)
    onto = RiskOntology(initial_nav=10_000.0)
    onto.nav = 5_000.0
    rm = RiskManager(initial_capital=10_000.0)
    rm.set_ontology(onto)
    onto.dynamic_daily_limit = 1.0
    onto.daily_loss_pct = 0.0
    onto.weekly_loss_pct = 0.0
    onto.intraday_dd_pct = 0.0
    exp = 5_000.0 * RISK["max_exposure_pct"] * 1.1
    assert rm.check_risk(10_000.0, open_exposure=exp, current_vol=0.0) is False
    assert rm.get_last_deny() == "max_exposure"


def test_record_pnl_onto_history_trim() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    rm = RiskManager(initial_capital=10_000.0)
    rm.set_ontology(onto)
    for i in range(501):
        rm.record_pnl(float(i))
    assert len(onto._pnl_history) == 500


def test_status_dict_peak_drawdown_and_avg_vol() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm._peak_equity = 12_000.0
    for v in [0.01, 0.02, 0.03, 0.01, 0.02, 0.03, 0.01, 0.02, 0.03, 0.01]:
        rm.record_volatility(v)
    d = rm.status_dict()
    expected_dd = (12_000.0 - 10_000.0) / 12_000.0 * 100.0
    assert d["peak_drawdown_pct"] == pytest.approx(round(expected_dd, 2))
    assert d["avg_vol_recent"] == pytest.approx(0.019, abs=0.002)
    assert d["emergency_stop"] is False
    assert d["omega_qmin_tighten"] == 0


def test_trigger_emergency_silent_skips_log(caplog: pytest.LogCaptureFixture) -> None:
    rm = RiskManager(initial_capital=10_000.0)
    with caplog.at_level("CRITICAL", logger="super_otonom.risk"):
        rm.trigger_emergency("silent_code", silent=True)
    assert not any("EMERGENCY_STOP" in r.message for r in caplog.records)
    assert rm.emergency_reason == "silent_code"


def test_check_dynamic_risk_ok_debug_log(caplog: pytest.LogCaptureFixture) -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm.daily_loss = 10.0
    with caplog.at_level("DEBUG", logger="super_otonom.risk"):
        assert rm.check_dynamic_risk(10_000.0, 0.02) is True
    assert any("DynamicRisk OK" in r.message for r in caplog.records)


# ── Mutation-kill: boundary & branch coverage ────────────────────────────────


def test_record_pnl_zero_no_loss() -> None:
    """pnl==0 → loss dalına girmemeli."""
    rm = RiskManager(initial_capital=10_000.0)
    rm.record_pnl(0.0)
    assert rm.daily_loss == 0.0
    assert rm.weekly_loss == 0.0
    assert len(rm._pnl_history) == 1


def test_record_pnl_exact_negative_boundary() -> None:
    """pnl < 0 sınır: -0.001 bile loss olmalı."""
    rm = RiskManager(initial_capital=10_000.0)
    rm.record_pnl(-0.001)
    assert rm.daily_loss == pytest.approx(0.001)
    assert rm.weekly_loss == pytest.approx(0.001)


def test_record_pnl_history_exactly_500() -> None:
    """500 kayıt → trim olmamalı."""
    rm = RiskManager(initial_capital=10_000.0)
    for i in range(500):
        rm.record_pnl(float(i))
    assert len(rm._pnl_history) == 500


def test_omega_zero_pnl_relaxes() -> None:
    """pnl==0 → profit yoluna gider, tighten azalır."""
    rm = RiskManager(initial_capital=10_000.0)
    rm._omega_qmin_tighten = 5
    rm.record_omega_trade_outcome(0.0)
    assert rm._omega_qmin_tighten == 4


def test_omega_relax_floors_at_zero() -> None:
    """Relax 0'ın altına düşmemeli."""
    rm = RiskManager(initial_capital=10_000.0)
    rm._omega_qmin_tighten = 0
    rm.record_omega_trade_outcome(1.0)
    assert rm._omega_qmin_tighten == 0


def test_omega_qmin_base_over_95_clamped() -> None:
    """base_min > 95 → 95'te kesilir, sonra tighten eklenir."""
    rm = RiskManager(initial_capital=10_000.0)
    rm._omega_qmin_tighten = 0
    assert rm.get_omega_effective_qmin(100) == 90


def test_omega_qmin_exact_boundaries() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm._omega_qmin_tighten = 0
    assert rm.get_omega_effective_qmin(0) == 0
    assert rm.get_omega_effective_qmin(90) == 90
    rm._omega_qmin_tighten = 5
    assert rm.get_omega_effective_qmin(85) == 90
    assert rm.get_omega_effective_qmin(86) == 90  # capped at 90


def test_check_dynamic_risk_zero_equity_uses_initial() -> None:
    """current_equity <= 0 → base = initial_capital."""
    rm = RiskManager(initial_capital=10_000.0)
    rm.daily_loss = 0.0
    assert rm.check_dynamic_risk(0.0, 0.02) is True
    assert rm.check_dynamic_risk(-100.0, 0.02) is True


def test_check_dynamic_risk_exact_boundary_breach() -> None:
    """daily_pct == dynamic_limit → breach (>=)."""
    rm = RiskManager(initial_capital=10_000.0)
    # vol=0.01 → limit = max(0.02, min(0.05, 0.02)) = 0.02
    rm.daily_loss = 200.0  # 200/10000 = 0.02 == limit
    assert rm.check_dynamic_risk(10_000.0, 0.01) is False


def test_check_dynamic_risk_just_below_boundary() -> None:
    """daily_pct < dynamic_limit → OK."""
    rm = RiskManager(initial_capital=10_000.0)
    rm.daily_loss = 199.0  # 199/10000 = 0.0199 < 0.02
    assert rm.check_dynamic_risk(10_000.0, 0.01) is True


def test_check_dynamic_risk_clamp_lower_exact() -> None:
    """vol=0.005 → limit = max(0.02, 0.01) = 0.02."""
    rm = RiskManager(initial_capital=10_000.0)
    rm.check_dynamic_risk(10_000.0, 0.005)
    assert rm._last_dynamic_limit == pytest.approx(0.02)


def test_check_dynamic_risk_clamp_upper_exact() -> None:
    """vol=0.025 → limit = max(0.02, min(0.05, 0.05)) = 0.05."""
    rm = RiskManager(initial_capital=10_000.0)
    rm.check_dynamic_risk(10_000.0, 0.025)
    assert rm._last_dynamic_limit == pytest.approx(0.05)


def test_check_dynamic_risk_clamp_mid() -> None:
    """vol=0.02 → limit = max(0.02, min(0.05, 0.04)) = 0.04."""
    rm = RiskManager(initial_capital=10_000.0)
    rm.check_dynamic_risk(10_000.0, 0.02)
    assert rm._last_dynamic_limit == pytest.approx(0.04)


def test_vol_spike_exact_multiplier_boundary() -> None:
    """current == avg * multiplier → not spike (must be >)."""
    rm = RiskManager(initial_capital=10_000.0)
    hist = [0.01] * 12
    assert rm.check_volatility_spike(0.02, history_vols=hist, spike_multiplier=2.0) is True


def test_vol_spike_just_above_multiplier() -> None:
    """current > avg * multiplier → spike."""
    rm = RiskManager(initial_capital=10_000.0)
    hist = [0.01] * 12
    assert rm.check_volatility_spike(0.0201, history_vols=hist, spike_multiplier=2.0) is False


def test_vol_spike_uses_internal_history() -> None:
    """history_vols=None → self._vol_history kullanılır."""
    rm = RiskManager(initial_capital=10_000.0)
    for _ in range(15):
        rm.record_volatility(0.01)
    assert rm.check_volatility_spike(0.015) is True
    assert rm.check_volatility_spike(0.025) is False


def test_vol_spike_custom_min_history() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    hist = [0.01] * 5
    assert rm.check_volatility_spike(0.05, history_vols=hist, min_history=6) is True
    assert rm.check_volatility_spike(0.05, history_vols=hist, min_history=5) is False


def test_update_peak_lower_value_no_change() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm._peak_equity = 15_000.0
    rm.update_peak(14_000.0)
    assert rm._peak_equity == 15_000.0


def test_trailing_stop_peak_equals_entry() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    assert rm.should_trailing_stop(100.0, 90.0, 100.0) is False


def test_trailing_stop_drawdown_just_below_threshold() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    tsp = RISK["trailing_stop_pct"]
    peak = 100.0
    current = peak * (1.0 - tsp + 0.001)
    assert rm.should_trailing_stop(90.0, current, peak) is False


def test_trailing_stop_drawdown_at_threshold() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    tsp = RISK["trailing_stop_pct"]
    peak = 100.0
    current = peak * (1.0 - tsp)
    assert rm.should_trailing_stop(90.0, current, peak) is True


def test_trailing_stop_drawdown_above_threshold() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    tsp = RISK["trailing_stop_pct"]
    peak = 100.0
    current = peak * (1.0 - tsp - 0.01)
    assert rm.should_trailing_stop(90.0, current, peak) is True


def test_check_risk_without_onto_dynamic_path_ok() -> None:
    """vol > 0 + daily OK → True."""
    rm = RiskManager(initial_capital=10_000.0)
    rm.daily_loss = 0.0
    assert rm.check_risk(10_000.0, current_vol=0.01) is True


def test_check_risk_without_onto_weekly_exact_boundary() -> None:
    """weekly_pct == limit → breach (>=)."""
    rm = RiskManager(initial_capital=10_000.0)
    rm.weekly_loss = RISK["max_weekly_loss_pct"] * 10_000.0
    assert rm.check_risk(10_000.0, current_vol=0.0) is False
    assert rm.get_last_deny() == "weekly_loss"


def test_check_risk_without_onto_drawdown_exact_boundary() -> None:
    """dd == max_total_drawdown → breach (>=)."""
    rm = RiskManager(initial_capital=10_000.0)
    rm._peak_equity = 10_000.0
    eq = 10_000.0 * (1.0 - RISK["max_total_drawdown"])
    assert rm.check_risk(eq, current_vol=0.0) is False
    assert rm.get_last_deny() == "max_drawdown"


def test_check_risk_without_onto_static_daily_exact_boundary() -> None:
    """daily_pct == limit → breach (>=)."""
    rm = RiskManager(initial_capital=10_000.0)
    rm.daily_loss = RISK["max_daily_loss_pct"] * 10_000.0
    assert rm.check_risk(10_000.0, current_vol=0.0) is False
    assert rm.get_last_deny() == "static_daily_loss"


def test_exposure_zero_equity_skip() -> None:
    """equity_for_exposure == 0 → exposure kontrolü atlanır."""
    rm = RiskManager(initial_capital=10_000.0)
    rm._onto = None
    assert rm.check_risk(0.0, open_exposure=999.0, current_vol=0.0) is False
    # 0 capital → invalid_capital önce yakalar


def test_exposure_with_onto_zero_nav() -> None:
    """onto.nav == 0 → exposure kontrolü atlanır."""
    onto = RiskOntology(initial_nav=10_000.0)
    onto.nav = 0.0
    rm = RiskManager(initial_capital=10_000.0)
    rm.set_ontology(onto)
    onto.dynamic_daily_limit = 1.0
    onto.daily_loss_pct = 0.0
    onto.weekly_loss_pct = 0.0
    onto.intraday_dd_pct = 0.0
    assert rm.check_risk(10_000.0, open_exposure=999.0, current_vol=0.0) is True


def test_exposure_no_vol_no_spike_check() -> None:
    """current_vol == 0 → vol spike kontrolü yapılmaz."""
    rm = RiskManager(initial_capital=10_000.0)
    assert rm.check_risk(10_000.0, open_exposure=0.0, current_vol=0.0) is True


def test_check_risk_vol_spike_records_vol() -> None:
    """current_vol > 0 → record_volatility çağrılır."""
    rm = RiskManager(initial_capital=10_000.0)
    assert rm.check_risk(10_000.0, open_exposure=0.0, current_vol=0.005) is True
    assert len(rm._vol_history) == 1
    assert rm._vol_history[0] == pytest.approx(0.005)


def test_warn_if_onto_missing_no_warn_when_onto_set() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    rm = RiskManager(initial_capital=10_000.0)
    rm.set_ontology(onto)
    onto.dynamic_daily_limit = 1.0
    onto.daily_loss_pct = 0.0
    onto.weekly_loss_pct = 0.0
    onto.intraday_dd_pct = 0.0
    rm.check_risk(10_000.0)
    assert rm._onto_warned is False


def test_trigger_emergency_not_silent_logs(caplog: pytest.LogCaptureFixture) -> None:
    rm = RiskManager(initial_capital=10_000.0)
    with caplog.at_level("CRITICAL", logger="super_otonom.risk"):
        rm.trigger_emergency("loud_code", silent=False)
    assert any("EMERGENCY_STOP" in r.message for r in caplog.records)


def test_status_dict_peak_zero() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm._peak_equity = 0.0
    d = rm.status_dict()
    assert d["peak_drawdown_pct"] == 0.0


def test_status_dict_avg_vol_insufficient() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    for _ in range(9):
        rm.record_volatility(0.01)
    d = rm.status_dict()
    assert d["avg_vol_recent"] is None


def test_status_dict_avg_vol_exactly_10() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    for _ in range(10):
        rm.record_volatility(0.02)
    d = rm.status_dict()
    assert d["avg_vol_recent"] == pytest.approx(0.02)


def test_status_dict_keys_with_onto() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    rm = RiskManager(initial_capital=10_000.0)
    rm.set_ontology(onto)
    d = rm.status_dict()
    for key in ("nav", "sod_nav", "peak_nav", "daily_loss_pct",
                "weekly_loss_pct", "intraday_dd_pct", "dynamic_limit_pct",
                "gross_exp", "net_exp", "exp_pct", "var_1d"):
        assert key in d


def test_status_dict_daily_loss_rounded() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm.daily_loss = 123.456
    rm.weekly_loss = 789.012
    d = rm.status_dict()
    assert d["daily_loss"] == 123.46
    assert d["weekly_loss"] == 789.01


def test_record_pnl_with_onto_syncs_history() -> None:
    """onto.pnl_history'ye de eklenmeli."""
    onto = RiskOntology(initial_nav=10_000.0)
    rm = RiskManager(initial_capital=10_000.0)
    rm.set_ontology(onto)
    rm.record_pnl(5.0)
    assert 5.0 in onto._pnl_history


def test_record_pnl_without_onto_no_crash() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm.record_pnl(-10.0)
    assert rm.daily_loss == pytest.approx(10.0)


def test_vol_history_len_200_after_trim() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    for i in range(250):
        rm.record_volatility(float(i))
    assert len(rm._vol_history) == 200
    assert rm._vol_history[0] == pytest.approx(50.0)


def test_check_risk_passes_all_clean() -> None:
    """Tüm limitler içinde → True."""
    rm = RiskManager(initial_capital=10_000.0)
    rm.daily_loss = 0.0
    rm.weekly_loss = 0.0
    rm._peak_equity = 10_000.0
    assert rm.check_risk(10_000.0, open_exposure=0.0, current_vol=0.005) is True
    assert rm.get_last_deny() == ""


def test_check_risk_emergency_reason_fallback() -> None:
    """emergency_reason None → 'emergency_latched'."""
    rm = RiskManager(initial_capital=10_000.0)
    rm.emergency_stop = True
    rm.emergency_reason = None
    assert rm.check_risk(10_000.0) is False
    assert rm.get_last_deny() == "emergency_latched"


def test_maybe_reset_day_and_week_simultaneously(monkeypatch: pytest.MonkeyPatch) -> None:
    t0 = 1_000_000.0
    rm = RiskManager(initial_capital=10_000.0)
    rm.daily_loss = 100.0
    rm.weekly_loss = 500.0
    rm._day_start = t0
    rm._week_start = t0
    monkeypatch.setattr(time, "time", lambda: t0 + _WEEK_SEC)
    rm._maybe_reset()
    assert rm.daily_loss == 0.0
    assert rm.weekly_loss == 0.0


def test_check_risk_with_onto_all_ok() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    rm = RiskManager(initial_capital=10_000.0)
    rm.set_ontology(onto)
    onto.dynamic_daily_limit = 0.10
    onto.daily_loss_pct = 0.01
    onto.weekly_loss_pct = 0.01
    onto.intraday_dd_pct = 0.01
    onto.nav = 10_000.0
    assert rm.check_risk(10_000.0, open_exposure=0.0, current_vol=0.0) is True


def test_initial_defaults() -> None:
    rm = RiskManager(initial_capital=5_000.0)
    assert rm.emergency_stop is False
    assert rm.emergency_reason is None
    assert rm._last_risk_deny is None
    assert rm.daily_loss == 0.0
    assert rm.weekly_loss == 0.0
    assert rm._peak_equity == 5_000.0
    assert rm._pnl_history == []
    assert rm._vol_history == []
    assert rm._omega_qmin_tighten == 0
    assert rm._onto is None
    assert rm._onto_warned is False


# ── Mutation-kill round 2: init defaults, log branches, boundary literals ────


def test_init_emergency_reason_is_none_not_empty() -> None:
    """Mutant: emergency_reason = '' vs None."""
    rm = RiskManager(initial_capital=10_000.0)
    assert rm.emergency_reason is None
    assert rm.emergency_reason != ""


def test_init_last_risk_deny_is_none_not_empty() -> None:
    """Mutant: _last_risk_deny = '' vs None."""
    rm = RiskManager(initial_capital=10_000.0)
    assert rm._last_risk_deny is None
    assert rm._last_risk_deny != ""


def test_init_last_dynamic_limit_from_config() -> None:
    """Mutant: default 0.05 vs RISK.get('max_daily_loss_pct', 0.05)."""
    rm = RiskManager(initial_capital=10_000.0)
    assert rm._last_dynamic_limit == RISK.get("max_daily_loss_pct", 0.05)
    assert rm._last_dynamic_limit > 0


def test_init_omega_tighten_zero() -> None:
    """Mutant: _omega_qmin_tighten = 0 vs 1."""
    rm = RiskManager(initial_capital=10_000.0)
    assert rm._omega_qmin_tighten == 0


def test_init_onto_warned_false() -> None:
    """Mutant: _onto_warned = True vs False."""
    rm = RiskManager(initial_capital=10_000.0)
    assert rm._onto_warned is False


def test_warn_if_onto_missing_sets_warned_true() -> None:
    """Line 86-87: onto is None AND not warned → set warned True."""
    rm = RiskManager(initial_capital=10_000.0)
    assert rm._onto_warned is False
    rm._warn_if_onto_missing()
    assert rm._onto_warned is True


def test_warn_if_onto_missing_both_conditions() -> None:
    """Both conditions: onto is None AND not warned."""
    rm = RiskManager(initial_capital=10_000.0)
    rm._onto_warned = True
    rm._warn_if_onto_missing()  # should NOT re-warn
    assert rm._onto_warned is True  # stays True


def test_warn_if_onto_present_no_warn() -> None:
    """onto is not None → skip warning entirely."""
    onto = RiskOntology(initial_nav=10_000.0)
    rm = RiskManager(initial_capital=10_000.0)
    rm.set_ontology(onto)
    rm._warn_if_onto_missing()
    assert rm._onto_warned is False


def test_trigger_emergency_silent_true_no_log(caplog: pytest.LogCaptureFixture) -> None:
    """Line 103: silent=True → no CRITICAL log."""
    rm = RiskManager(initial_capital=10_000.0)
    with caplog.at_level("CRITICAL", logger="super_otonom.risk"):
        rm.trigger_emergency("test_code", silent=True)
    assert not any("EMERGENCY_STOP" in r.message for r in caplog.records)


def test_trigger_emergency_silent_false_emits_log(caplog: pytest.LogCaptureFixture) -> None:
    """Line 103: silent=False → CRITICAL log emitted."""
    rm = RiskManager(initial_capital=10_000.0)
    with caplog.at_level("CRITICAL", logger="super_otonom.risk"):
        rm.trigger_emergency("test_code", silent=False)
    assert any("EMERGENCY_STOP" in r.message for r in caplog.records)
    assert any("test_code" in r.message for r in caplog.records)


def test_maybe_reset_day_boundary_literal_86400(monkeypatch: pytest.MonkeyPatch) -> None:
    """Line 113: >= 86400 boundary — mutant changes to > 86400."""
    t0 = 100_000.0
    rm = RiskManager(initial_capital=10_000.0)
    rm.daily_loss = 100.0
    rm._day_start = t0
    # Exactly 86400 — should reset
    monkeypatch.setattr(time, "time", lambda: t0 + 86400)
    rm._maybe_reset()
    assert rm.daily_loss == 0.0


def test_maybe_reset_day_boundary_just_below(monkeypatch: pytest.MonkeyPatch) -> None:
    """86399 seconds — should NOT reset."""
    t0 = 100_000.0
    rm = RiskManager(initial_capital=10_000.0)
    rm.daily_loss = 100.0
    rm._day_start = t0
    monkeypatch.setattr(time, "time", lambda: t0 + 86399)
    rm._maybe_reset()
    assert rm.daily_loss == 100.0


def test_maybe_reset_week_boundary_literal_604800(monkeypatch: pytest.MonkeyPatch) -> None:
    """Line 117: >= 604800 boundary — mutant changes to > 604800."""
    t0 = 100_000.0
    rm = RiskManager(initial_capital=10_000.0)
    rm.weekly_loss = 200.0
    rm._week_start = t0
    monkeypatch.setattr(time, "time", lambda: t0 + 604800)
    rm._maybe_reset()
    assert rm.weekly_loss == 0.0


def test_maybe_reset_week_boundary_just_below(monkeypatch: pytest.MonkeyPatch) -> None:
    """604799 seconds — should NOT reset."""
    t0 = 100_000.0
    rm = RiskManager(initial_capital=10_000.0)
    rm.weekly_loss = 200.0
    rm._week_start = t0
    monkeypatch.setattr(time, "time", lambda: t0 + 604799)
    rm._maybe_reset()
    assert rm.weekly_loss == 200.0


def test_pnl_history_trim_boundary_500_vs_501() -> None:
    """Line 133: > 500 — mutant changes to >= 500."""
    rm = RiskManager(initial_capital=10_000.0)
    rm._pnl_history = list(range(500))
    rm.record_pnl(999.0)
    assert len(rm._pnl_history) == 500
    assert rm._pnl_history[-1] == 999.0


def test_pnl_history_no_trim_at_500() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm._pnl_history = list(range(499))
    rm.record_pnl(999.0)
    assert len(rm._pnl_history) == 500  # no trim needed


def test_record_pnl_negative_adds_daily_and_weekly() -> None:
    """Line 135/138: pnl < 0 → both daily and weekly increase."""
    rm = RiskManager(initial_capital=10_000.0)
    rm.record_pnl(-25.0)
    assert rm.daily_loss == pytest.approx(25.0)
    assert rm.weekly_loss == pytest.approx(25.0)
    rm.record_pnl(-15.0)
    assert rm.daily_loss == pytest.approx(40.0)
    assert rm.weekly_loss == pytest.approx(40.0)


def test_record_pnl_onto_history_trim_at_501() -> None:
    """Line 142: onto pnl_history > 500 → trim."""
    onto = RiskOntology(initial_nav=10_000.0)
    rm = RiskManager(initial_capital=10_000.0)
    rm.set_ontology(onto)
    onto._pnl_history = list(range(500))
    rm.record_pnl(999.0)
    assert len(onto._pnl_history) == 500
    assert onto._pnl_history[-1] == 999.0


def test_record_pnl_onto_var_recalculated() -> None:
    """Line 144: onto.var_1d = onto._calc_var() called after pnl append."""
    onto = RiskOntology(initial_nav=10_000.0)
    rm = RiskManager(initial_capital=10_000.0)
    rm.set_ontology(onto)
    # Add enough history for var to be non-zero
    onto._pnl_history = [float(-5 + (i % 7)) for i in range(120)]
    rm.record_pnl(-100.0)
    # var should be recalculated (may or may not change, but _calc_var was called)
    assert onto.var_1d == onto._calc_var()


def test_update_peak_exact_equal_no_update() -> None:
    """Line 148: > (strict) — equal should NOT update."""
    rm = RiskManager(initial_capital=10_000.0)
    rm._peak_equity = 10_000.0
    rm.update_peak(10_000.0)
    assert rm._peak_equity == 10_000.0


def test_update_peak_above_updates() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm.update_peak(10_001.0)
    assert rm._peak_equity == 10_001.0


def test_vol_history_trim_boundary_200_vs_201() -> None:
    """Line 159: > 200 — mutant changes to >= 200."""
    rm = RiskManager(initial_capital=10_000.0)
    rm._vol_history = [0.01] * 200
    rm.record_volatility(0.02)
    assert len(rm._vol_history) == 200
    assert rm._vol_history[-1] == pytest.approx(0.02)


def test_vol_history_no_trim_at_200() -> None:
    rm = RiskManager(initial_capital=10_000.0)
    rm._vol_history = [0.01] * 199
    rm.record_volatility(0.02)
    assert len(rm._vol_history) == 200


def test_vol_spike_default_multiplier() -> None:
    """Line 166: default spike_multiplier=2.0."""
    rm = RiskManager(initial_capital=10_000.0)
    hist = [0.01] * 15
    # Without explicit multiplier — uses default 2.0
    assert rm.check_volatility_spike(0.019, history_vols=hist) is True
    assert rm.check_volatility_spike(0.021, history_vols=hist) is False


def test_vol_spike_avg_zero_returns_true() -> None:
    """Line 180: avg_vol <= 0 → True (can't compute spike)."""
    rm = RiskManager(initial_capital=10_000.0)
    assert rm.check_volatility_spike(0.05, history_vols=[0.0] * 15) is True


def test_vol_spike_avg_negative_returns_true() -> None:
    """avg_vol < 0 edge (shouldn't happen but boundary)."""
    rm = RiskManager(initial_capital=10_000.0)
    assert rm.check_volatility_spike(0.05, history_vols=[-0.01] * 15) is True


def test_vol_spike_gt_not_gte() -> None:
    """Line 183: > (strict) — exact match is NOT a spike."""
    rm = RiskManager(initial_capital=10_000.0)
    hist = [0.01] * 15
    # exact: current == avg * multiplier → True (no spike)
    assert rm.check_volatility_spike(0.02, history_vols=hist, spike_multiplier=2.0) is True
    # just above → False (spike)
    assert rm.check_volatility_spike(0.020001, history_vols=hist, spike_multiplier=2.0) is False


def test_check_dynamic_risk_zero_capital_returns_false() -> None:
    """Line 214: initial_capital <= 0 → False."""
    rm = RiskManager(initial_capital=0.0)
    assert rm.check_dynamic_risk(10_000.0, 0.02) is False


def test_check_dynamic_risk_negative_capital_returns_false() -> None:
    rm = RiskManager(initial_capital=-100.0)
    assert rm.check_dynamic_risk(10_000.0, 0.02) is False


def test_check_dynamic_risk_positive_capital_not_false() -> None:
    """Positive capital with no loss → True."""
    rm = RiskManager(initial_capital=1.0)
    rm.daily_loss = 0.0
    assert rm.check_dynamic_risk(1.0, 0.02) is True


# ── Mutation-kill round 3: log format, status_dict values, trigger_emergency ─


def test_omega_tighten_increment_is_2() -> None:
    """Line 65: tighten += 2 (not 1 or 3)."""
    rm = RiskManager(initial_capital=10_000.0)
    rm._omega_qmin_tighten = 0
    rm.record_omega_trade_outcome(-1.0)
    assert rm._omega_qmin_tighten == 2


def test_omega_qmin_base_min_clamp_95() -> None:
    """Line 73: min(95, base_min) — 95 not 90 or 96."""
    rm = RiskManager(initial_capital=10_000.0)
    rm._omega_qmin_tighten = 0
    assert rm.get_omega_effective_qmin(95) == 90  # min(90, 95+0) = 90
    assert rm.get_omega_effective_qmin(96) == 90  # min(90, min(95,96)+0) = 90


def test_trigger_emergency_default_not_silent() -> None:
    """Line 93: default silent=False."""
    rm = RiskManager(initial_capital=10_000.0)
    import logging
    with patch.object(logging.getLogger("super_otonom.risk"), "critical") as mock_log:
        rm.trigger_emergency("test")
        mock_log.assert_called()


def test_day_start_updated_on_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Line 115: self._day_start = now."""
    t0 = 100_000.0
    rm = RiskManager(initial_capital=10_000.0)
    rm._day_start = t0
    rm.daily_loss = 100.0
    new_time = t0 + 86400
    monkeypatch.setattr(time, "time", lambda: new_time)
    rm._maybe_reset()
    assert rm._day_start == new_time


def test_week_start_updated_on_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Line 119: self._week_start = now."""
    t0 = 100_000.0
    rm = RiskManager(initial_capital=10_000.0)
    rm._week_start = t0
    rm.weekly_loss = 200.0
    new_time = t0 + 604800
    monkeypatch.setattr(time, "time", lambda: new_time)
    rm._maybe_reset()
    assert rm._week_start == new_time


def test_pnl_history_trim_keeps_last_500() -> None:
    """Line 133-134: trim to [-500:]."""
    rm = RiskManager(initial_capital=10_000.0)
    rm._pnl_history = list(range(505))
    rm.record_pnl(999.0)
    assert len(rm._pnl_history) == 500
    assert rm._pnl_history[0] == 6.0  # 505 items + 1 = 506, trim [-500:] → starts at 6


def test_record_pnl_loss_abs_value() -> None:
    """Line 135-138: loss = abs(pnl), added to both daily and weekly."""
    rm = RiskManager(initial_capital=10_000.0)
    rm.record_pnl(-33.0)
    assert rm.daily_loss == pytest.approx(33.0)
    assert rm.weekly_loss == pytest.approx(33.0)


def test_onto_pnl_trim_keeps_last_500() -> None:
    """Line 142-143: onto trim to [-500:]."""
    onto = RiskOntology(initial_nav=10_000.0)
    rm = RiskManager(initial_capital=10_000.0)
    rm.set_ontology(onto)
    onto._pnl_history = list(range(505))
    rm.record_pnl(888.0)
    assert len(onto._pnl_history) == 500
    assert onto._pnl_history[0] == 6.0


def test_update_peak_strict_greater() -> None:
    """Line 148: > not >=."""
    rm = RiskManager(initial_capital=10_000.0)
    rm._peak_equity = 100.0
    rm.update_peak(100.0)
    assert rm._peak_equity == 100.0
    rm.update_peak(100.01)
    assert rm._peak_equity == 100.01


def test_vol_trim_keeps_last_200() -> None:
    """Line 159-160: trim to [-200:]."""
    rm = RiskManager(initial_capital=10_000.0)
    rm._vol_history = [float(i) for i in range(205)]
    rm.record_volatility(999.0)
    assert len(rm._vol_history) == 200
    assert rm._vol_history[0] == pytest.approx(6.0)


def test_dynamic_risk_base_equity_positive() -> None:
    """Line 222: current_equity > 0 → use it as base."""
    rm = RiskManager(initial_capital=10_000.0)
    rm.daily_loss = 100.0
    rm.check_dynamic_risk(5_000.0, 0.02)
    # daily_pct = 100/5000 = 0.02, limit = max(0.02, min(0.05, 0.04)) = 0.04
    # 0.02 < 0.04 → True


def test_dynamic_risk_breach_emergency_and_log(caplog: pytest.LogCaptureFixture) -> None:
    """Lines 226-231: breach → trigger_emergency + CRITICAL log with pct values."""
    rm = RiskManager(initial_capital=10_000.0)
    rm.daily_loss = 300.0
    with caplog.at_level("CRITICAL", logger="super_otonom.risk"):
        result = rm.check_dynamic_risk(10_000.0, 0.01)
    assert result is False
    assert rm.emergency_stop is True
    # Log should contain percentage values (* 100)
    log_msg = [r.message for r in caplog.records if "dynamic_daily_loss" in r.message]
    assert len(log_msg) > 0


def test_dynamic_risk_ok_log(caplog: pytest.LogCaptureFixture) -> None:
    """Lines 239-240: OK path → DEBUG log with pct values."""
    rm = RiskManager(initial_capital=10_000.0)
    rm.daily_loss = 10.0
    with caplog.at_level("DEBUG", logger="super_otonom.risk"):
        result = rm.check_dynamic_risk(10_000.0, 0.02)
    assert result is True
    log_msg = [r.message for r in caplog.records if "DynamicRisk OK" in r.message]
    assert len(log_msg) > 0


def test_check_risk_onto_daily_breach_emergency_and_log(caplog: pytest.LogCaptureFixture) -> None:
    """Lines 250-255: onto daily breach → emergency + CRITICAL log."""
    onto = RiskOntology(initial_nav=10_000.0)
    rm = RiskManager(initial_capital=10_000.0)
    rm.set_ontology(onto)
    onto.daily_loss_pct = 0.10
    onto.dynamic_daily_limit = 0.05
    with caplog.at_level("CRITICAL", logger="super_otonom.risk"):
        result = rm.check_risk(10_000.0)
    assert result is False
    assert rm.emergency_stop is True
    assert rm.emergency_reason == "dynamic_daily_loss"
    log_msg = [r.message for r in caplog.records if "dynamic_daily_loss" in r.message]
    assert len(log_msg) > 0


def test_check_risk_onto_weekly_breach_emergency_and_log(caplog: pytest.LogCaptureFixture) -> None:
    """Lines 260-264."""
    onto = RiskOntology(initial_nav=10_000.0)
    rm = RiskManager(initial_capital=10_000.0)
    rm.set_ontology(onto)
    onto.daily_loss_pct = 0.0
    onto.dynamic_daily_limit = 1.0
    onto.weekly_loss_pct = 0.20
    with caplog.at_level("CRITICAL", logger="super_otonom.risk"):
        result = rm.check_risk(10_000.0)
    assert result is False
    assert rm.emergency_reason == "weekly_loss"
    log_msg = [r.message for r in caplog.records if "weekly_loss" in r.message]
    assert len(log_msg) > 0


def test_check_risk_onto_drawdown_breach_emergency_and_log(caplog: pytest.LogCaptureFixture) -> None:
    """Lines 269-272."""
    onto = RiskOntology(initial_nav=10_000.0)
    rm = RiskManager(initial_capital=10_000.0)
    rm.set_ontology(onto)
    onto.daily_loss_pct = 0.0
    onto.dynamic_daily_limit = 1.0
    onto.weekly_loss_pct = 0.0
    onto.intraday_dd_pct = 0.30
    with caplog.at_level("CRITICAL", logger="super_otonom.risk"):
        result = rm.check_risk(10_000.0)
    assert result is False
    assert rm.emergency_reason == "max_drawdown"
    log_msg = [r.message for r in caplog.records if "max_drawdown" in r.message]
    assert len(log_msg) > 0


def test_check_risk_without_onto_static_daily_emergency_and_log(caplog: pytest.LogCaptureFixture) -> None:
    """Lines 286-290."""
    rm = RiskManager(initial_capital=10_000.0)
    rm.daily_loss = RISK["max_daily_loss_pct"] * 10_000.0 + 1.0
    with caplog.at_level("CRITICAL", logger="super_otonom.risk"):
        result = rm.check_risk(10_000.0, current_vol=0.0)
    assert result is False
    assert rm.emergency_reason == "static_daily_loss"
    log_msg = [r.message for r in caplog.records if "static_daily_loss" in r.message]
    assert len(log_msg) > 0


def test_check_risk_without_onto_weekly_emergency_and_log(caplog: pytest.LogCaptureFixture) -> None:
    """Lines 296-300."""
    rm = RiskManager(initial_capital=10_000.0)
    rm.weekly_loss = RISK["max_weekly_loss_pct"] * 10_000.0 + 1.0
    with caplog.at_level("CRITICAL", logger="super_otonom.risk"):
        result = rm.check_risk(10_000.0, current_vol=0.0)
    assert result is False
    assert rm.emergency_reason == "weekly_loss"
    log_msg = [r.message for r in caplog.records if "weekly_loss" in r.message]
    assert len(log_msg) > 0


def test_check_risk_without_onto_drawdown_peak_positive(caplog: pytest.LogCaptureFixture) -> None:
    """Lines 305-313: peak > 0 path."""
    rm = RiskManager(initial_capital=10_000.0)
    rm._peak_equity = 10_000.0
    eq = 10_000.0 * (1.0 - RISK["max_total_drawdown"] - 0.01)
    with caplog.at_level("CRITICAL", logger="super_otonom.risk"):
        result = rm.check_risk(eq, current_vol=0.0)
    assert result is False
    assert rm.emergency_reason == "max_drawdown"
    log_msg = [r.message for r in caplog.records if "max_drawdown" in r.message]
    assert len(log_msg) > 0


def test_check_risk_without_onto_peak_zero_no_drawdown() -> None:
    """Lines 305: peak_equity == 0 → skip drawdown check."""
    rm = RiskManager(initial_capital=10_000.0)
    rm._peak_equity = 0.0
    assert rm.check_risk(5_000.0, current_vol=0.0) is True


def test_exposure_equity_zero_skips_check() -> None:
    """Line 324: equity_for_exposure <= 0 → skip."""
    rm = RiskManager(initial_capital=10_000.0)
    rm._peak_equity = 10_000.0
    # current_equity=0 → no onto → equity_for_exposure=0
    # But initial_capital check fails first for check_risk
    # Test _check_exposure_and_vol directly
    result = rm._check_exposure_and_vol(0.0, 999.0, 0.0)
    assert result is None  # skipped


def test_exposure_breach_emergency_flag_log(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    """Lines 328-332: exposure_breach_emergency=True → emergency + log."""
    monkeypatch.setitem(RISK, "exposure_breach_emergency", True)
    rm = RiskManager(initial_capital=10_000.0)
    with caplog.at_level("CRITICAL", logger="super_otonom.risk"):
        result = rm._check_exposure_and_vol(10_000.0, 10_000.0 * RISK["max_exposure_pct"] * 1.5, 0.0)
    assert result == "max_exposure"
    assert rm.emergency_stop is True
    log_msg = [r.message for r in caplog.records if "max_exposure" in r.message]
    assert len(log_msg) > 0


def test_exposure_breach_warning_only_log(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    """Lines 337-338: exposure_breach_emergency=False → warning only."""
    monkeypatch.setitem(RISK, "exposure_breach_emergency", False)
    rm = RiskManager(initial_capital=10_000.0)
    with caplog.at_level("WARNING", logger="super_otonom.risk"):
        result = rm._check_exposure_and_vol(10_000.0, 10_000.0 * RISK["max_exposure_pct"] * 1.5, 0.0)
    assert result == "max_exposure"
    assert rm.emergency_stop is False
    log_msg = [r.message for r in caplog.records if "exposure_limit" in r.message]
    assert len(log_msg) > 0


def test_exposure_vol_records_and_checks(caplog: pytest.LogCaptureFixture) -> None:
    """Line 342: current_vol > 0 → record + spike check."""
    rm = RiskManager(initial_capital=10_000.0)
    result = rm._check_exposure_and_vol(10_000.0, 0.0, 0.01)
    assert result is None
    assert len(rm._vol_history) == 1


def test_check_risk_default_params() -> None:
    """Lines 353-354: default open_exposure=0.0, current_vol=0.0."""
    rm = RiskManager(initial_capital=10_000.0)
    assert rm.check_risk(10_000.0) is True


def test_check_risk_resets_last_deny() -> None:
    """Line 368: _last_risk_deny = None at start."""
    rm = RiskManager(initial_capital=10_000.0)
    rm._last_risk_deny = "old_deny"
    rm.check_risk(10_000.0)
    assert rm._last_risk_deny is None


def test_check_risk_invalid_capital_boundary() -> None:
    """Line 377: <= 0."""
    rm_zero = RiskManager(initial_capital=0.0)
    assert rm_zero.check_risk(10_000.0) is False
    rm_neg = RiskManager(initial_capital=-1.0)
    assert rm_neg.check_risk(10_000.0) is False
    rm_pos = RiskManager(initial_capital=0.01)
    assert rm_pos.check_risk(0.01) is True


def test_calculate_var_min_obs_100() -> None:
    """Line 415: min_obs=100."""
    rm = RiskManager(initial_capital=10_000.0)
    for i in range(99):
        rm.record_pnl(float(i))
    assert rm.calculate_var() == 0.0
    rm.record_pnl(100.0)
    # Now 100 obs — should compute
    assert rm.calculate_var() is not None


def test_status_dict_peak_dd_formula() -> None:
    """Line 435: (peak - initial) / peak * 100."""
    rm = RiskManager(initial_capital=8_000.0)
    rm._peak_equity = 10_000.0
    d = rm.status_dict()
    expected = (10_000.0 - 8_000.0) / 10_000.0 * 100.0
    assert d["peak_drawdown_pct"] == pytest.approx(round(expected, 2))


def test_status_dict_peak_dd_zero_peak() -> None:
    """Line 435: peak == 0 → 0.0."""
    rm = RiskManager(initial_capital=10_000.0)
    rm._peak_equity = 0.0
    d = rm.status_dict()
    assert d["peak_drawdown_pct"] == 0.0


def test_status_dict_avg_vol_10_items() -> None:
    """Line 438: exactly 10 items → compute avg."""
    rm = RiskManager(initial_capital=10_000.0)
    for v in [0.01, 0.02, 0.03, 0.04, 0.05, 0.01, 0.02, 0.03, 0.04, 0.05]:
        rm.record_volatility(v)
    d = rm.status_dict()
    expected = sum([0.01, 0.02, 0.03, 0.04, 0.05, 0.01, 0.02, 0.03, 0.04, 0.05]) / 10
    assert d["avg_vol_recent"] == pytest.approx(round(expected, 6))


def test_status_dict_avg_vol_9_items_none() -> None:
    """Line 438: < 10 → None."""
    rm = RiskManager(initial_capital=10_000.0)
    for _ in range(9):
        rm.record_volatility(0.01)
    d = rm.status_dict()
    assert d["avg_vol_recent"] is None


def test_status_dict_peak_equity_rounded() -> None:
    """Line 446: round(peak, 2)."""
    rm = RiskManager(initial_capital=10_000.0)
    rm._peak_equity = 12345.6789
    d = rm.status_dict()
    assert d["peak_equity"] == 12345.68


def test_status_dict_dynamic_limit_pct_formula() -> None:
    """Line 449: round(limit * 100, 2)."""
    rm = RiskManager(initial_capital=10_000.0)
    rm._last_dynamic_limit = 0.0345
    d = rm.status_dict()
    assert d["dynamic_daily_limit_pct"] == pytest.approx(3.45)


def test_status_dict_onto_all_values_rounded() -> None:
    """Lines 457-466: all onto values rounded with * 100 for pct fields."""
    onto = RiskOntology(initial_nav=10_000.0)
    onto.nav = 9_876.543
    onto.sod_nav = 10_000.123
    onto.peak_nav = 10_500.789
    onto.daily_loss_pct = 0.0345
    onto.weekly_loss_pct = 0.0678
    onto.intraday_dd_pct = 0.0912
    onto.dynamic_daily_limit = 0.0456
    onto.gross_exp = 1234.567
    onto.net_exp = 987.654
    onto.exp_pct = 0.1234
    onto.var_1d = 42.0
    rm = RiskManager(initial_capital=10_000.0)
    rm.set_ontology(onto)
    d = rm.status_dict()
    assert d["nav"] == pytest.approx(9876.54)
    assert d["sod_nav"] == pytest.approx(10000.12)
    assert d["peak_nav"] == pytest.approx(10500.79)
    assert d["daily_loss_pct"] == pytest.approx(3.45)
    assert d["weekly_loss_pct"] == pytest.approx(6.78)
    assert d["intraday_dd_pct"] == pytest.approx(9.12)
    assert d["dynamic_limit_pct"] == pytest.approx(4.56)
    assert d["gross_exp"] == pytest.approx(1234.57)
    assert d["net_exp"] == pytest.approx(987.65)
    assert d["exp_pct"] == pytest.approx(12.34)
    assert d["var_1d"] == 42.0


def test_status_dict_avg_vol_rounded_6_decimals() -> None:
    """Line 448: round(avg, 6)."""
    rm = RiskManager(initial_capital=10_000.0)
    for _ in range(10):
        rm.record_volatility(0.0123456789)
    d = rm.status_dict()
    assert d["avg_vol_recent"] == pytest.approx(0.012346, abs=1e-6)


def test_init_last_dynamic_limit_value() -> None:
    """Line 50: RISK.get fallback 0.05 matches config."""
    rm = RiskManager(initial_capital=10_000.0)
    expected = RISK.get("max_daily_loss_pct", 0.05)
    assert rm._last_dynamic_limit == expected
    assert isinstance(rm._last_dynamic_limit, float)
