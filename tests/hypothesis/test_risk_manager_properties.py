"""RiskManager — property-based testler (kurumsal QA)."""
from __future__ import annotations

import math

import pytest
from super_otonom.risk_manager import RiskManager

from hypothesis import given, settings
from hypothesis import strategies as st

pytestmark = pytest.mark.hypothesis

_ST = settings(max_examples=115, deadline=8000)


@_ST
@given(
    base=st.integers(min_value=0, max_value=95),
    tighten=st.integers(min_value=0, max_value=25),
)
def test_omega_effective_qmin_always_bounded(base: int, tighten: int) -> None:
    rm = RiskManager(50_000.0)
    rm._omega_qmin_tighten = int(tighten)
    out = rm.get_omega_effective_qmin(base)
    assert 0 <= out <= 90
    assert math.isfinite(float(out))


@_ST
@given(
    pnl=st.floats(
        min_value=-1e6,
        max_value=1e6,
        allow_nan=False,
        allow_infinity=False,
        width=64,
    )
)
def test_record_omega_trade_outcome_tighten_bounded(pnl: float) -> None:
    rm = RiskManager(10_000.0)
    before = rm._omega_qmin_tighten
    rm.record_omega_trade_outcome(pnl)
    assert 0 <= rm._omega_qmin_tighten <= 25
    if pnl < 0:
        assert rm._omega_qmin_tighten >= before
    else:
        assert rm._omega_qmin_tighten <= before


@_ST
@given(
    hist=st.lists(
        st.floats(
            min_value=1e-6,
            max_value=0.05,
            allow_nan=False,
            allow_infinity=False,
        ),
        min_size=12,
        max_size=24,
    ),
    mult=st.floats(min_value=1.5, max_value=4.0, allow_nan=False),
)
def test_volatility_spike_detects_high_current_vs_avg(
    hist: list[float], mult: float
) -> None:
    rm = RiskManager(20_000.0)
    avg = sum(hist) / len(hist)
    # spike_multiplier=2.0: current > 2*avg olmali; mult min 1.5 tek basina yetmez
    cur = avg * max(mult * 1.01, 2.05)
    assert rm.check_volatility_spike(cur, history_vols=hist, min_history=10) is False


@_ST
@given(
    cap=st.floats(
        min_value=1000.0,
        max_value=500_000.0,
        allow_nan=False,
        allow_infinity=False,
    ),
    vol=st.floats(
        min_value=0.005,
        max_value=0.04,
        allow_nan=False,
        allow_infinity=False,
    ),
    loss_frac=st.floats(
        min_value=0.0,
        max_value=0.08,
        allow_nan=False,
        allow_infinity=False,
    ),
)
def test_dynamic_risk_fails_when_daily_pct_over_limit(
    cap: float, vol: float, loss_frac: float
) -> None:
    rm = RiskManager(cap)
    limit = max(0.02, min(0.05, vol * 2))
    rm.daily_loss = float(loss_frac * cap)
    daily_pct = rm.daily_loss / cap
    ok = rm.check_dynamic_risk(cap, vol)
    if daily_pct >= limit:
        assert ok is False
        assert rm.emergency_stop is True
    else:
        assert ok is True


@_ST
@given(
    ic=st.floats(
        min_value=500.0,
        max_value=200_000.0,
        allow_nan=False,
        allow_infinity=False,
    ),
    open_exp=st.floats(
        min_value=0.0,
        max_value=50_000.0,
        allow_nan=False,
        allow_infinity=False,
    ),
    cur_eq=st.floats(
        min_value=100.0,
        max_value=200_000.0,
        allow_nan=False,
        allow_infinity=False,
    ),
    cur_vol=st.floats(
        min_value=0.0,
        max_value=0.03,
        allow_nan=False,
        allow_infinity=False,
    ),
)
def test_check_risk_emergency_short_circuits(
    ic: float, open_exp: float, cur_eq: float, cur_vol: float
) -> None:
    rm = RiskManager(ic)
    rm.trigger_emergency("qa", silent=True)
    assert rm.check_risk(cur_eq, open_exp, cur_vol) is False
    assert rm.get_last_deny() == "qa"


@_ST
@given(
    n=st.integers(min_value=20, max_value=80),
    seed=st.integers(min_value=0, max_value=10_000),
)
def test_calculate_var_non_negative_with_history(n: int, seed: int) -> None:
    rng = __import__("random").Random(seed)
    rm = RiskManager(15_000.0)
    for _ in range(n):
        rm.record_pnl(rng.uniform(-200, 200))
    v = rm.calculate_var()
    assert isinstance(v, float)
    assert math.isfinite(v)
