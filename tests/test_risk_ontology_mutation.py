"""risk_ontology.py — mutmut kill-rate hedefi (>=80%). Sınır ve dallanma testleri."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from super_otonom.risk.risk_engine import RiskEngine
from super_otonom.risk_ontology import RiskOntology

# Mutant sabitleri oldurur: testler modul importu degil literal kullanir.
_DAY_SEC = 86_400
_WEEK_SEC = 604_800

pytestmark = pytest.mark.fastrun


def _pnl_series(onto: RiskOntology, n: int, delta: float = -1.0) -> None:
    for _ in range(n):
        onto.update(nav=10_000.0, realized_pnl_delta=delta)


# ── __post_init__ / varsayılanlar ─────────────────────────────────────────────


def test_module_reset_constants_literals() -> None:
    from super_otonom import risk_ontology as ro

    assert ro._SOD_RESET_SECONDS == _DAY_SEC
    assert ro._SOW_RESET_SECONDS == _WEEK_SEC


def test_dataclass_field_defaults() -> None:
    onto = RiskOntology()
    assert onto.initial_nav == 10_000.0
    assert onto.dynamic_daily_limit == 0.03
    assert onto.var_1d == 0.0
    assert onto.gross_exp == 0.0
    assert onto.net_exp == 0.0
    assert onto.exp_pct == 0.0
    assert onto.intraday_dd_pct == 0.0
    assert onto.daily_loss_pct == 0.0
    assert onto.weekly_loss_pct == 0.0
    assert onto.nav == 10_000.0
    assert onto.sod_nav == 10_000.0
    assert onto.sow_nav == 10_000.0
    assert onto.peak_nav == 10_000.0


def test_post_init_zero_nav_uses_initial() -> None:
    onto = RiskOntology(initial_nav=7_500.0, nav=0.0, sod_nav=0.0, sow_nav=0.0, peak_nav=0.0)
    assert onto.nav == 7_500.0
    assert onto.sod_nav == 7_500.0
    assert onto.sow_nav == 7_500.0
    assert onto.peak_nav == 7_500.0


def test_post_init_preserves_explicit_nav() -> None:
    onto = RiskOntology(initial_nav=10_000.0, nav=12_345.0)
    assert onto.nav == 12_345.0
    assert onto.sod_nav == 10_000.0


def test_post_init_keeps_tiny_nonzero_nav() -> None:
    onto = RiskOntology(initial_nav=10_000.0, nav=1.5e-9)
    assert onto.nav == pytest.approx(1.5e-9)


def test_post_init_keeps_tiny_nonzero_sod_nav() -> None:
    onto = RiskOntology(initial_nav=10_000.0, sod_nav=1e-9)
    assert onto.sod_nav == pytest.approx(1e-9)


# ── update: peak / loss yüzdeleri ─────────────────────────────────────────────


def test_peak_not_raised_when_nav_equals_peak() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    onto.peak_nav = 10_500.0
    onto.update(nav=10_500.0)
    assert onto.peak_nav == 10_500.0


def test_peak_raises_only_when_nav_strictly_greater() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    onto.update(nav=10_001.0)
    assert onto.peak_nav == 10_001.0


def test_daily_loss_zero_when_nav_above_sod() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    onto.update(nav=10_500.0)
    assert onto.daily_loss_pct == 0.0


def test_weekly_loss_zero_when_nav_above_sow() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    onto.update(nav=10_500.0)
    assert onto.weekly_loss_pct == 0.0


def test_daily_loss_skipped_when_sod_nav_non_positive() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    onto.sod_nav = 0.0
    onto.daily_loss_pct = 0.42
    onto.update(nav=8_000.0)
    assert onto.daily_loss_pct == 0.42


def test_weekly_loss_skipped_when_sow_nav_non_positive() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    onto.sow_nav = 0.0
    onto.weekly_loss_pct = 0.33
    onto.update(nav=8_000.0)
    assert onto.weekly_loss_pct == 0.33


def test_drawdown_skipped_when_peak_nav_non_positive() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    onto.peak_nav = 0.0
    onto.nav = 0.0
    onto.intraday_dd_pct = 0.99
    onto.update(nav=0.0)
    assert onto.peak_nav == 0.0
    assert onto.intraday_dd_pct == 0.99


def test_drawdown_recomputed_when_peak_positive() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    onto.update(nav=12_000.0)
    onto.update(nav=10_800.0)
    assert onto.intraday_dd_pct == pytest.approx((12_000.0 - 10_800.0) / 12_000.0)


# ── exposure ──────────────────────────────────────────────────────────────────


def test_exposure_empty_positions_dict_is_falsy() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    onto.gross_exp = 999.0
    onto.update(nav=10_000.0, positions={})
    assert onto.gross_exp == 999.0


def test_exposure_missing_qty_entry_defaults() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    onto.update(nav=10_000.0, positions={"X": {}})
    assert onto.gross_exp == 0.0
    assert onto.net_exp == 0.0
    assert onto.exp_pct == 0.0


def test_exposure_pct_zero_when_nav_zero() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    onto.nav = 0.0
    onto._update_exposure({"A": {"qty": 2.0, "entry": 100.0}})
    assert onto.gross_exp == 200.0
    assert onto.exp_pct == 0.0


def test_exposure_pct_when_nav_fractional() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    onto.nav = 0.5
    onto._update_exposure({"A": {"qty": 1.0, "entry": 100.0}})
    assert onto.exp_pct == pytest.approx(200.0)


def test_exposure_short_path_values() -> None:
    onto = RiskOntology(initial_nav=20_000.0)
    onto.update(
        nav=20_000.0,
        positions={
            "A": {"qty": 1.0, "entry": 1_000.0},
            "B": {"qty": 0.5, "entry": 2_000.0},
        },
    )
    assert onto.gross_exp == 2_000.0
    assert onto.net_exp == 2_000.0
    assert onto.exp_pct == pytest.approx(0.1)


# ── vol / pnl geçmişi ─────────────────────────────────────────────────────────


def test_vol_not_recorded_when_zero_or_negative() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    onto.update(nav=10_000.0, current_vol=0.0)
    onto.update(nav=10_000.0, current_vol=-0.01)
    assert onto._vol_history == []


def test_vol_recorded_when_positive() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    onto.update(nav=10_000.0, current_vol=0.015)
    assert len(onto._vol_history) == 1
    assert onto._vol_history[0] == pytest.approx(0.015)


def test_vol_history_keeps_200_without_premature_trim() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    for i in range(200):
        onto.update(nav=10_000.0, current_vol=0.01 + i * 1e-6)
    assert len(onto._vol_history) == 200
    assert onto._vol_history[0] == pytest.approx(0.01)


def test_vol_history_trim_at_201st_entry() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    for i in range(201):
        onto.update(nav=10_000.0, current_vol=0.01 + i * 1e-6)
    assert len(onto._vol_history) == 200
    assert onto._vol_history[0] == pytest.approx(0.01 + 1e-6)


@pytest.mark.parametrize(
    "vol, expected_limit",
    [
        (0.001, 0.02),
        (0.015, 0.03),
        (0.025, 0.05),
        (0.10, 0.05),
    ],
)
def test_dynamic_daily_limit_clamp(vol: float, expected_limit: float) -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    onto.update(nav=10_000.0, current_vol=vol)
    assert onto.dynamic_daily_limit == pytest.approx(expected_limit)


def test_pnl_delta_below_threshold_not_appended() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    onto.update(nav=10_000.0, realized_pnl_delta=1e-10)
    assert onto._pnl_history == []
    assert onto.var_1d == 0.0


def test_pnl_delta_above_threshold_appends_and_recalc_var() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    with patch.object(RiskEngine, "compute_from_pnl_history", return_value=77.0) as mock_var:
        onto.update(nav=10_000.0, realized_pnl_delta=1e-8)
        assert len(onto._pnl_history) == 1
        assert onto.var_1d == 77.0
        mock_var.assert_called_once()


def test_pnl_history_trim_at_501st_entry() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    for i in range(501):
        onto.update(nav=10_000.0, realized_pnl_delta=float(i + 1))
    assert len(onto._pnl_history) == 500
    assert onto._pnl_history[0] == pytest.approx(2.0)


def test_calc_var_delegates_to_engine_with_args() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    onto._pnl_history = [float(x) for x in range(120)]
    with patch.object(RiskEngine, "compute_from_pnl_history", return_value=55.5) as mock_var:
        out = onto._calc_var(confidence=0.99)
        assert out == 55.5
        mock_var.assert_called_once_with(
            onto._pnl_history,
            confidence=0.99,
            min_obs=100,
        )


def test_var_recalc_only_after_meaningful_pnl_delta() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    _pnl_series(onto, 120)
    prev = onto.var_1d
    onto.update(nav=9_900.0, realized_pnl_delta=0.0)
    assert onto.var_1d == prev


# ── gün / hafta sıfırlama (sınır) ───────────────────────────────────────────


def test_day_reset_not_before_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    t0 = 50_000.0
    onto = RiskOntology(initial_nav=10_000.0)
    onto.sod_nav = 10_000.0
    onto._day_start = t0
    monkeypatch.setattr(time, "time", lambda: t0 + _DAY_SEC - 1.0)
    onto._maybe_reset_day()
    assert onto.sod_nav == 10_000.0


def test_day_reset_at_exact_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    t0 = 50_000.0
    onto = RiskOntology(initial_nav=10_000.0)
    onto.nav = 9_200.0
    onto.sod_nav = 10_000.0
    onto._day_start = t0
    monkeypatch.setattr(time, "time", lambda: t0 + _DAY_SEC)
    onto._maybe_reset_day()
    assert onto.sod_nav == pytest.approx(9_200.0)


def test_week_reset_at_exact_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    t0 = 60_000.0
    onto = RiskOntology(initial_nav=10_000.0)
    onto.nav = 9_700.0
    onto.sow_nav = 10_000.0
    onto._week_start = t0
    monkeypatch.setattr(time, "time", lambda: t0 + _WEEK_SEC)
    onto._maybe_reset_week()
    assert onto.sow_nav == pytest.approx(9_700.0)


def test_update_applies_nav_before_day_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    """FIX-5: sod_nav sifirlamada guncel nav kullanilir (bir onceki tick degil)."""
    t_now = 200_000.0
    onto = RiskOntology(initial_nav=10_000.0)
    onto.nav = 9_000.0
    onto._day_start = t_now - _DAY_SEC - 1.0
    monkeypatch.setattr(time, "time", lambda: t_now)
    onto.update(nav=10_800.0)
    assert onto.sod_nav == pytest.approx(10_800.0)


def test_update_resets_day_start_timestamp(monkeypatch: pytest.MonkeyPatch) -> None:
    t_now = 100_000.0
    onto = RiskOntology(initial_nav=10_000.0)
    onto._day_start = t_now - _DAY_SEC - 1.0
    monkeypatch.setattr(time, "time", lambda: t_now)
    onto.update(nav=10_200.0)
    assert onto._day_start == pytest.approx(t_now)


# ── breach sorguları (eşik) ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "daily_loss, limit, breached",
    [
        (0.05, 0.05, True),
        (0.049999, 0.05, False),
        (0.06, 0.05, True),
    ],
)
def test_is_daily_limit_boundary(daily_loss: float, limit: float, breached: bool) -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    onto.daily_loss_pct = daily_loss
    onto.dynamic_daily_limit = limit
    assert onto.is_daily_limit_breached() is breached


@pytest.mark.parametrize(
    "weekly_loss, max_pct, breached",
    [
        (0.10, 0.10, True),
        (0.09999, 0.10, False),
    ],
)
def test_is_weekly_limit_boundary(weekly_loss: float, max_pct: float, breached: bool) -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    onto.weekly_loss_pct = weekly_loss
    assert onto.is_weekly_limit_breached(max_weekly_pct=max_pct) is breached


@pytest.mark.parametrize(
    "dd, max_dd, breached",
    [
        (0.15, 0.15, True),
        (0.14999, 0.15, False),
    ],
)
def test_is_drawdown_boundary(dd: float, max_dd: float, breached: bool) -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    onto.intraday_dd_pct = dd
    assert onto.is_drawdown_breached(max_dd=max_dd) is breached


@pytest.mark.parametrize(
    "exp_pct, max_exp, breached",
    [
        (0.95, 0.95, False),
        (0.950001, 0.95, True),
        (0.50, 0.95, False),
    ],
)
def test_is_exposure_strict_gt(exp_pct: float, max_exp: float, breached: bool) -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    onto.exp_pct = exp_pct
    assert onto.is_exposure_breached(max_exp_pct=max_exp) is breached


# ── snapshot / serileştirme ───────────────────────────────────────────────────


def test_snapshot_exact_rounding() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    onto.nav = 10_123.456
    onto.sod_nav = 10_000.0
    onto.sow_nav = 10_000.0
    onto.peak_nav = 11_000.0
    onto.intraday_dd_pct = 0.081234
    onto.daily_loss_pct = 0.012345
    onto.weekly_loss_pct = 0.023456
    onto.dynamic_daily_limit = 0.034567
    onto.gross_exp = 1234.567
    onto.net_exp = 1234.567
    onto.exp_pct = 0.121234
    onto.var_1d = 88.88
    snap = onto.snapshot()
    assert snap == {
        "nav": 10123.46,
        "sod_nav": 10000.0,
        "sow_nav": 10000.0,
        "peak_nav": 11000.0,
        "intraday_dd_pct": 8.12,
        "daily_loss_pct": 1.23,
        "weekly_loss_pct": 2.35,
        "dynamic_daily_limit": 3.46,
        "gross_exp": 1234.57,
        "net_exp": 1234.57,
        "exp_pct": 12.12,
        "var_1d": 88.88,
    }


def test_to_dict_includes_internal_timestamps_and_trims() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    onto._day_start = 111.0
    onto._week_start = 222.0
    onto._pnl_history = [float(i) for i in range(510)]
    onto._vol_history = [0.01] * 210
    d = onto.to_dict()
    assert d["day_start"] == 111.0
    assert d["week_start"] == 222.0
    assert len(d["pnl_history"]) == 500
    assert len(d["vol_history"]) == 200
    assert d["initial_nav"] == 10_000.0


def test_from_dict_defaults_and_lists() -> None:
    onto = RiskOntology.from_dict({})
    assert onto.initial_nav == 10_000.0
    assert onto.nav == 10_000.0
    assert onto.dynamic_daily_limit == 0.03
    assert onto._pnl_history == []
    assert onto._vol_history == []


def test_update_debug_log_metric_scaling(caplog: pytest.LogCaptureFixture) -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    onto.update(nav=11_000.0)
    with caplog.at_level("DEBUG", logger="super_otonom.risk_ontology"):
        onto.update(
            nav=9_900.0,
            positions={"A": {"qty": 1.0, "entry": 500.0}},
            current_vol=0.02,
            realized_pnl_delta=-1.0,
        )
    lines = [r.message for r in caplog.records if "RiskOntology |" in r.message]
    assert lines
    msg = lines[-1]
    assert "dd=10.00%" in msg
    assert "daily_loss=1.00%" in msg
    assert "exp=5.1%" in msg


def test_from_dict_restores_all_fields() -> None:
    data = {
        "initial_nav": 5_000.0,
        "nav": 5_100.0,
        "sod_nav": 5_050.0,
        "sow_nav": 5_040.0,
        "peak_nav": 5_200.0,
        "dynamic_daily_limit": 0.04,
        "day_start": 333.0,
        "week_start": 444.0,
        "pnl_history": [1.0, -2.0],
        "vol_history": [0.02],
    }
    onto = RiskOntology.from_dict(data)
    assert onto.nav == pytest.approx(5_100.0)
    assert onto.sod_nav == pytest.approx(5_050.0)
    assert onto._day_start == 333.0
    assert onto._pnl_history == [1.0, -2.0]
    assert onto._vol_history == [0.02]


def test_from_dict_missing_keys_use_defaults() -> None:
    onto = RiskOntology.from_dict({"initial_nav": 8_000.0, "nav": 8_100.0})
    assert onto.sod_nav == pytest.approx(8_000.0)
    assert onto.sow_nav == pytest.approx(8_000.0)
    assert onto.peak_nav == pytest.approx(8_000.0)
    assert isinstance(onto.sow_nav, float)


def test_from_dict_logs_info(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("INFO", logger="super_otonom.risk_ontology"):
        RiskOntology.from_dict({"nav": 1_234.0, "initial_nav": 1_000.0})
    assert any("RiskOntology yüklendi" in r.message for r in caplog.records)


def test_update_nav_coerced_to_float() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    onto.update(nav=10_001)  # int
    assert isinstance(onto.nav, float)
    assert onto.nav == 10_001.0


def test_daily_weekly_loss_formulas_via_update() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    onto.update(nav=9_000.0)
    assert onto.daily_loss_pct == pytest.approx(0.1)
    assert onto.weekly_loss_pct == pytest.approx(0.1)


def test_calc_var_integration_matches_engine() -> None:
    onto = RiskOntology(initial_nav=10_000.0)
    _pnl_series(onto, 120, delta=-12.5)
    expected = RiskEngine().compute_from_pnl_history(
        onto._pnl_history, confidence=0.95, min_obs=100
    )
    assert onto.var_1d == expected
    assert onto._calc_var() == expected
