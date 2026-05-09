"""
RiskManager check_risk — 4×4×4×4 parametrik matris + exposure katmanı (≥200 senaryo).

Her eksen 0..3: artan baskı katsayısı (dal kapsamı).
"""
from __future__ import annotations

import pytest
from super_otonom.config import RISK
from super_otonom.risk_manager import RiskManager

LEVELS = (0, 1, 2, 3)
IC = 200_000.0

# Günlük / haftalık: limit oranının bu kesirleri (son dilim limit üstü)
_FR = [0.0, 0.45, 0.97, 1.04]

# Drawdown: peak sabit; equity bu orana göre düşer (son dilim limit üstü)
_EQR = [1.0, 0.94, 0.86, 0.78]

# Exposure: equity'ye oranlı notional (son dilim limit üstü)
_EXF = [0.0, 0.12, 0.28, 0.38]


def _fill_rm(rm: RiskManager, di: int, wi: int, ddi: int, ei: int) -> tuple[float, float]:
    """Günlük/haftalık kayıp, tepe, maruziyet; (equity, open_exposure) döner."""
    rm.daily_loss = _FR[di] * RISK["max_daily_loss_pct"] * IC
    rm.weekly_loss = _FR[wi] * RISK["max_weekly_loss_pct"] * IC
    peak = IC * 1.08
    rm._peak_equity = peak
    eq = peak * _EQR[ddi]
    ox = _EXF[ei] * eq
    rm._last_risk_deny = None
    rm.emergency_stop = False
    rm.emergency_reason = None
    return float(eq), float(ox)


@pytest.mark.parametrize("di", LEVELS)
@pytest.mark.parametrize("wi", LEVELS)
@pytest.mark.parametrize("ddi", LEVELS)
@pytest.mark.parametrize("ei", LEVELS)
def test_check_risk_matrix_static_daily_branch(
    di: int, wi: int, ddi: int, ei: int
) -> None:
    """current_vol=0 → statik günlük limit."""
    rm = RiskManager(IC)
    eq, ox = _fill_rm(rm, di, wi, ddi, ei)
    ok = rm.check_risk(eq, ox, current_vol=0.0)
    daily_pct = rm.daily_loss / IC
    weekly_pct = rm.weekly_loss / IC
    dd = (rm._peak_equity - eq) / rm._peak_equity if rm._peak_equity > 0 else 0.0
    ex_pct = ox / eq if eq > 0 else 1.0

    if daily_pct >= RISK["max_daily_loss_pct"]:
        assert ok is False
        assert rm.get_last_deny() == "static_daily_loss"
    elif weekly_pct >= RISK["max_weekly_loss_pct"]:
        assert ok is False
        assert rm.get_last_deny() == "weekly_loss"
    elif dd >= RISK["max_total_drawdown"]:
        assert ok is False
        assert rm.get_last_deny() == "max_drawdown"
    elif ex_pct > RISK["max_exposure_pct"]:
        assert ok is False
        assert rm.get_last_deny() == "max_exposure"
    else:
        assert ok is True


@pytest.mark.parametrize("di", LEVELS)
@pytest.mark.parametrize("wi", LEVELS)
@pytest.mark.parametrize("ddi", LEVELS)
@pytest.mark.parametrize("ei", LEVELS)
def test_check_risk_matrix_dynamic_daily_branch(
    di: int, wi: int, ddi: int, ei: int
) -> None:
    """Düşük vol → dinamik günlük limit (check_dynamic_risk)."""
    rm = RiskManager(IC)
    eq, ox = _fill_rm(rm, di, wi, ddi, ei)
    vol = 0.009
    dyn_limit = max(0.02, min(0.05, vol * 2))
    ok = rm.check_risk(eq, ox, current_vol=vol)
    daily_pct = rm.daily_loss / eq
    weekly_pct = rm.weekly_loss / IC
    dd = (rm._peak_equity - eq) / rm._peak_equity if rm._peak_equity > 0 else 0.0
    ex_pct = ox / eq if eq > 0 else 1.0

    if daily_pct >= dyn_limit:
        assert ok is False
        assert rm.get_last_deny() == "dynamic_daily_loss"
    elif weekly_pct >= RISK["max_weekly_loss_pct"]:
        assert ok is False
    elif dd >= RISK["max_total_drawdown"]:
        assert ok is False
    elif ex_pct > RISK["max_exposure_pct"]:
        assert ok is False
    else:
        assert ok is True


@pytest.mark.parametrize("di", LEVELS)
@pytest.mark.parametrize("wi", LEVELS)
@pytest.mark.parametrize("ddi", LEVELS)
@pytest.mark.parametrize("ei", LEVELS)
def test_check_risk_matrix_vol_spike_after_clean_limits(
    di: int, wi: int, ddi: int, ei: int
) -> None:
    """Önceki limitler geçilmediyse vol spike dalı."""
    rm = RiskManager(IC)
    eq, ox = _fill_rm(rm, di, wi, ddi, ei)
    for _ in range(15):
        rm.record_volatility(0.008)
    vol = 0.07
    dyn_limit = max(0.02, min(0.05, vol * 2))
    daily_pct = rm.daily_loss / eq
    weekly_pct = rm.weekly_loss / IC
    dd = (rm._peak_equity - eq) / rm._peak_equity if rm._peak_equity > 0 else 0.0
    ex_pct = ox / eq if eq > 0 else 1.0
    pre_spike_ok = (
        daily_pct < dyn_limit
        and weekly_pct < RISK["max_weekly_loss_pct"]
        and dd < RISK["max_total_drawdown"]
        and ex_pct <= RISK["max_exposure_pct"]
    )
    ok = rm.check_risk(eq, ox, current_vol=vol)
    if pre_spike_ok:
        assert ok is False
        assert rm.get_last_deny() == "volatility_spike"
    else:
        assert ok is False


@pytest.mark.parametrize("layer", range(4))
@pytest.mark.parametrize("di", LEVELS)
@pytest.mark.parametrize("wi", LEVELS)
@pytest.mark.parametrize("ddi", LEVELS)
@pytest.mark.parametrize("ei", LEVELS)
def test_exposure_emergency_flag_matrix(
    layer: int, di: int, wi: int, ddi: int, ei: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RISK['exposure_breach_emergency'] True/False × 4^4 = 512 senaryo."""
    use_emg = (layer + di + wi) % 2 == 0
    monkeypatch.setitem(RISK, "exposure_breach_emergency", use_emg)
    rm = RiskManager(IC)
    eq, _ = _fill_rm(rm, 0, 0, 0, 0)
    ox = RISK["max_exposure_pct"] * eq * 1.15
    ok = rm.check_risk(eq, ox, current_vol=0.0)
    assert ok is False
    assert rm.get_last_deny() == "max_exposure"
    if use_emg:
        assert rm.emergency_stop is True
    else:
        assert rm.emergency_stop is False
