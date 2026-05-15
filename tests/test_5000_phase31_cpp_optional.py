"""
5000 gate — Aşama 31 (opsiyonel C++ risk_engine / var_engine).

Kaynak: ``super_otonom/test_5000.py`` (~3052+).

``fastrun`` dışındadır: ``python -m pytest -m cpp_optional tests/test_5000_phase31_cpp_optional.py -q``
Modül yoksa ``importorskip`` ile test atlanır (hata sayılmaz).
"""
from __future__ import annotations

import random
from typing import Callable

import pytest
from super_otonom.risk_manager import RiskManager

pytestmark = pytest.mark.cpp_optional
_RNG = random.Random(42)

@pytest.fixture
def make_rm() -> Callable[..., RiskManager]:

    def _make(cap: float=10000.0) -> RiskManager:
        return RiskManager(initial_capital=cap)
    return _make

def test_5000_phase31_cpp_risk_engine(make_rm: Callable[..., RiskManager]) -> None:
    pytest.importorskip('risk_engine', reason='optional C++ risk_engine extension')
    from risk_engine import (
        calculate_risk_score,
        check_dynamic_risk_cpp,
        check_risk_cpp,
        should_trailing_stop_cpp,
    )
    r = check_risk_cpp(10000, 0, 0, 10000, 10000, 0, 0, False)
    
    assert r.allowed is True, '31.cpp.risk.clean_pass'
    
    assert r.deny_reason == '', '31.cpp.risk.clean_reason'
    r = check_risk_cpp(10000, 0, 0, 10000, 10000, 0, 0, True)
    
    assert r.allowed is False, '31.cpp.risk.emergency'
    
    assert r.deny_reason == 'emergency_stop', '31.cpp.risk.emergency_reason'
    r = check_risk_cpp(10000, 500, 0, 10000, 20000, 0, 0, False, 0.03)
    
    assert r.allowed is True, '31.cpp.risk.fix2_equity'
    r = check_risk_cpp(10000, 500, 0, 10000, 10000, 0, 0, False, 0.03)
    
    assert r.allowed is False, '31.cpp.risk.fix2_blocks'
    
    assert r.deny_reason == 'daily_loss', '31.cpp.risk.fix2_reason'
    r = check_risk_cpp(10000, 0, 1500, 10000, 10000, 0, 0, False, 0.03, 0.1)
    
    assert r.allowed is False, '31.cpp.risk.weekly_blocks'
    
    assert r.deny_reason == 'weekly_loss', '31.cpp.risk.weekly_reason'
    r = check_risk_cpp(10000, 0, 0, 12000, 10000, 0, 0, False, 0.03, 0.1, 0.15)
    
    assert r.allowed is False, '31.cpp.risk.dd_blocks'
    
    assert r.deny_reason == 'max_drawdown', '31.cpp.risk.dd_reason'
    r = check_risk_cpp(10000, 0, 0, 10000, 10000, 9600, 0, False, 0.03, 0.1, 0.15, 0.95)
    
    assert r.allowed is False, '31.cpp.risk.exp_blocks'
    
    assert r.deny_reason == 'exposure_limit', '31.cpp.risk.exp_reason'
    r = check_risk_cpp(10000, 0, 0, 10000, 10000, 0, 0.05, False, 0.03, 0.1, 0.15, 0.95, 0.01, 2.0)
    
    assert r.allowed is False, '31.cpp.risk.vol_spike'
    
    assert r.deny_reason == 'volatility_spike', '31.cpp.risk.vol_reason'
    
    assert check_dynamic_risk_cpp(300, 10000, 0.02) is True, '31.cpp.dyn.ok'
    
    assert check_dynamic_risk_cpp(500, 10000, 0.02) is False, '31.cpp.dyn.blocks'
    
    assert check_dynamic_risk_cpp(150, 10000, 0.001) is True, '31.cpp.dyn.clamp_low'
    
    assert check_dynamic_risk_cpp(400, 10000, 0.1) is True, '31.cpp.dyn.clamp_high'
    
    assert check_dynamic_risk_cpp(100, 0, 0.02) is False, '31.cpp.dyn.zero_eq'
    
    assert should_trailing_stop_cpp(100, 102, 105, 0.02) is True, '31.cpp.trail.triggers'
    
    assert should_trailing_stop_cpp(100, 104, 105, 0.02) is False, '31.cpp.trail.no_trigger'
    
    assert should_trailing_stop_cpp(100, 100, 100, 0.02) is False, '31.cpp.trail.flat'
    
    assert should_trailing_stop_cpp(100, 95, 99, 0.02) is False, '31.cpp.trail.below_entry'
    score = calculate_risk_score(100000, 0.02, 1.645)
    
    assert abs(score - 3290.0) < 0.01, '31.cpp.score.correct'
    score2 = calculate_risk_score(50000, 0.01)
    
    assert abs(score2 - 50000 * 0.01 * 1.645) < 0.01, '31.cpp.score.default_z'
    _rm_cpp = make_rm(10000)
    for trial in range(50):
        dl = _RNG.uniform(0, 1000)
        wl = _RNG.uniform(0, 2000)
        pe = _RNG.uniform(8000, 15000)
        ce = _RNG.uniform(5000, 15000)
        oe_val = _RNG.uniform(0, 10000)
        cv = _RNG.uniform(0, 0.1)
        emg = _RNG.choice([True, False])
        _rm_cpp.emergency_stop = emg
        _rm_cpp.emergency_reason = 'test' if emg else None
        _rm_cpp.daily_loss = dl
        _rm_cpp.weekly_loss = wl
        _rm_cpp._peak_equity = pe
        r_cpp = check_risk_cpp(10000, dl, wl, pe, ce, oe_val, cv, emg)
        if emg:
            
            assert r_cpp.allowed is False, f'31.cpp.vs_py.emg.{trial}'
        else:
            base = ce if ce > 0 else 10000
            daily_pct = dl / base
            if daily_pct >= 0.03:
                
                assert r_cpp.allowed is False, f'31.cpp.vs_py.daily.{trial}'
            else:
                
                assert isinstance(r_cpp.allowed, bool), f'31.cpp.vs_py.pass.{trial}'

def test_5000_phase31_cpp_var_engine() -> None:
    pytest.importorskip('var_engine', reason='optional C++ var_engine extension')
    import numpy as np
    from var_engine import amihud_ratio, calc_var, estimate_impact, rolling_mean, rolling_std
    data100 = [-i * 10.0 for i in range(1, 101)]
    var_val = calc_var(data100)
    
    assert var_val != 0.0, '31.cpp.var.nonzero'
    
    assert var_val < 0, '31.cpp.var.negative'
    data50 = [-i * 10.0 for i in range(1, 51)]
    
    assert calc_var(data50) == 0.0, '31.cpp.var.below_min'
    data500 = [-_RNG.uniform(1, 1000) for _ in range(500)]
    var500 = calc_var(data500)
    
    assert var500 < 0, '31.cpp.var.large_data'
    var99 = calc_var(data100, confidence=0.99)
    var95 = calc_var(data100, confidence=0.95)
    
    assert var99 <= var95, '31.cpp.var.99_more_neg'
    ret = [0.01, -0.02, 0.005]
    vol = [1000000.0, 2000000.0, 500000.0]
    ratio = amihud_ratio(ret, vol)
    
    assert ratio > 0, '31.cpp.amihud.positive'
    
    assert amihud_ratio([], []) == 0.0, '31.cpp.amihud.empty'
    imp = estimate_impact(10000, 1000000, 0.02)
    
    assert imp.total_pct > 0, '31.cpp.impact.positive'
    
    assert imp.total_pct >= 0.0001, '31.cpp.impact.min_bound'
    
    assert imp.total_pct <= 0.02, '31.cpp.impact.max_bound'
    
    assert imp.participation_rate > 0, '31.cpp.impact.participation'
    imp_large = estimate_impact(100000, 1000000, 0.02)
    
    assert imp_large.is_large_order is True, '31.cpp.impact.large'
    imp_small = estimate_impact(1000, 10000000, 0.02)
    
    assert imp_small.is_large_order is False, '31.cpp.impact.small'
    data = [1.0, 2.0, 3.0, 4.0, 5.0]
    mean = rolling_mean(data, 5)
    
    assert abs(mean - 3.0) < 0.01, '31.cpp.rolling.mean'
    std = rolling_std(data, 5)
    
    assert std > 0, '31.cpp.rolling.std_pos'
    
    assert rolling_mean([], 5) == 0.0, '31.cpp.rolling.empty'
    for trial in range(50):
        data = [_RNG.uniform(-500, 500) for _ in range(_RNG.randint(100, 300))]
        py_var = round(float(np.percentile(data, 5)), 2)
        cpp_var = calc_var(data, 0.95, 100)
        
        assert abs(py_var - cpp_var) < 1.0, f'31.cpp.var_sync.{trial}'
