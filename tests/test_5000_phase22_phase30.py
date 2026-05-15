"""
5000 gate — Aşama 22–30 (property + tamamlayıcı).

Kaynak: ``super_otonom/test_5000.py`` (~2772–3050). Devam: ``tests/test_5000_phase32_phase38.py`` (32–38).
"""
from __future__ import annotations

import random
import tempfile
from pathlib import Path
from typing import Callable

import pytest
from super_otonom import config as so_config
from super_otonom.alert_manager import AlertManager
from super_otonom.capital_engine import CapitalEngine
from super_otonom.concentration_risk import ConcentrationRiskManager
from super_otonom.market_impact import MarketImpactModel
from super_otonom.order_engine import OrderEngine, OrderState
from super_otonom.pre_trade_gate import fat_finger_check, same_bar_guard
from super_otonom.risk_manager import RiskManager
from super_otonom.risk_ontology import RiskOntology
from super_otonom.stress_test import SCENARIOS, StressTestRunner

pytestmark = pytest.mark.fastrun
_RNG = random.Random(42)
_VALID_OE_STATES = set(OrderState)

@pytest.fixture(scope='module', autouse=True)
def _legacy_risk_trailing_stop_pct() -> None:
    prev = so_config.RISK.get('trailing_stop_pct')
    so_config.RISK['trailing_stop_pct'] = 0.02
    yield
    if prev is not None:
        so_config.RISK['trailing_stop_pct'] = prev

@pytest.fixture(autouse=True)
def _alert_webhook_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    import super_otonom.alert_manager as amod
    monkeypatch.setattr(amod, '_WEBHOOK_URL', '')

@pytest.fixture
def make_ro() -> Callable[..., RiskOntology]:

    def _make(nav: float=10000.0) -> RiskOntology:
        return RiskOntology(initial_nav=nav)
    return _make

@pytest.fixture
def make_rm() -> Callable[..., RiskManager]:

    def _make(cap: float=10000.0) -> RiskManager:
        return RiskManager(initial_capital=cap)
    return _make

@pytest.fixture
def make_oe(tmp_path: Path) -> Callable[[], OrderEngine]:
    counter = {'n': 0}

    def _make() -> OrderEngine:
        counter['n'] += 1
        d = tmp_path / f"oe_{counter['n']}"
        d.mkdir(exist_ok=True)
        return OrderEngine(order_log_file=str(d / 'o.jsonl'), pending_file=str(d / 'p.json'), max_retries=3)
    return _make

@pytest.fixture
def phase12_make_ce(tmp_path: Path) -> Callable[..., CapitalEngine]:
    counter = {'n': 0}

    def _make(cap: float=10000.0, reserve: float=0.0) -> CapitalEngine:
        counter['n'] += 1
        sub = tmp_path / f"ce_{counter['n']}"
        sub.mkdir(exist_ok=True)
        return CapitalEngine(cap, journal_file=str(sub / 'j.jsonl'), reserve_pct=reserve, max_position_pct=1.0)
    return _make

def _inv_ok(e: CapitalEngine, tol: float=0.01) -> bool:
    exp = e.initial_capital + e._net_deposits + e._realized_pnl + e._unrealized_pnl - e._fees_paid
    return abs(e.nav - exp) <= tol

def test_5000_phase22_ce_properties(phase12_make_ce: Callable[..., CapitalEngine]) -> None:
    for trial in range(200):
        cap = _RNG.uniform(500, 200000)
        e = phase12_make_ce(cap, reserve=_RNG.uniform(0, 0.1))
        for _ in range(_RNG.randint(1, 15)):
            op = _RNG.choice(['open', 'close', 'dep', 'with', 'fee', 'unreal', 'reserve', 'release'])
            try:
                if op == 'open' and len(e._positions) < 5 and (e.available_cash > 10):
                    n = _RNG.uniform(1, min(e.available_cash * 0.4, 5000))
                    e.open_position(f'S{trial}_{_}', f'o{trial}_{_}', _RNG.uniform(10, 60000), max(0.001, n / _RNG.uniform(100, 60000)), n)
                elif op == 'close' and e._positions:
                    sym = _RNG.choice(list(e._positions.keys()))
                    e.close_position(sym, f'c{trial}_{_}', _RNG.uniform(1, 60000), e._positions[sym].qty * _RNG.uniform(0.3, 1.0))
                elif op == 'dep':
                    e.deposit(_RNG.uniform(1, 500))
                elif op == 'with' and e.available_cash > 5:
                    e.withdrawal(_RNG.uniform(1, min(e.available_cash * 0.05, 50)))
                elif op == 'fee':
                    e.record_fee('X', f'f{trial}_{_}', _RNG.uniform(0.01, 5))
                elif op == 'unreal' and e._positions:
                    e.update_unrealized({s: _RNG.uniform(1, 70000) for s in e._positions})
                elif op == 'reserve' and e.available_cash > 10:
                    e.reserve_margin(f'r{trial}_{_}', _RNG.uniform(1, min(e.available_cash * 0.2, 500)))
                elif op == 'release' and e._reserved_margin > 0:
                    e.release_reservation(f'r{trial}', min(e._reserved_margin, _RNG.uniform(1, 100)))
            except Exception:
                pass
        
        assert _inv_ok(e), f'22.prop.inv.{trial}'
    for trial in range(100):
        e = phase12_make_ce(_RNG.uniform(1000, 50000))
        for _ in range(_RNG.randint(1, 5)):
            n = _RNG.uniform(1, min(e.available_cash * 0.3, 3000))
            if n > 1 and e.available_cash > n:
                e.open_position(f'T{trial}_{_}', f'o{trial}_{_}', _RNG.uniform(100, 50000), 1.0, n)
        if e._positions:
            e.update_unrealized({s: _RNG.uniform(100, 60000) for s in e._positions})
        actual = e._cash + e._margin_used + e._unrealized_pnl
        
        assert abs(e.nav - actual) < 0.01, f'22.prop.nav.{trial}'

def test_5000_phase23_ro_rm_properties(make_ro: Callable[..., RiskOntology], make_rm: Callable[..., RiskManager]) -> None:
    for trial in range(50):
        ro = make_ro(_RNG.uniform(1000, 100000))
        for _ in range(20):
            ro.update(nav=_RNG.uniform(100, 200000))
        
        assert ro.peak_nav >= ro.nav, f'23.peak.{trial}'
    for trial in range(50):
        ro = make_ro(_RNG.uniform(1000, 100000))
        n0 = _RNG.uniform(5000, 50000)
        ro.update(nav=n0)
        for _ in range(10):
            ro.update(nav=_RNG.uniform(n0 * 0.3, n0 * 1.5))
        
        assert ro.daily_loss_pct >= 0.0, f'23.loss_nn.{trial}'
    for trial in range(50):
        ro = make_ro(10000)
        for _ in range(10):
            ro.update(nav=_RNG.uniform(5000, 15000))
        exp_dd = max(0, (ro.peak_nav - ro.nav) / ro.peak_nav) if ro.peak_nav > 0 else 0
        
        assert abs(ro.intraday_dd_pct - exp_dd) < 0.01, f'23.dd.{trial}'
    for trial in range(50):
        rm = make_rm(10000)
        tl = 0.0
        for _ in range(_RNG.randint(1, 20)):
            p = _RNG.uniform(-500, 500)
            rm.record_pnl(p)
            if p < 0:
                tl += abs(p)
        
        assert abs(rm.daily_loss - tl) < 0.01, f'23.rm_loss.{trial}'
    for trial in range(50):
        rm = make_rm(10000)
        rm.trigger_emergency(f'first_{trial}')
        rm.trigger_emergency(f'second_{trial}')
        
        assert rm.emergency_reason == f'first_{trial}', f'23.latch.{trial}'
    for trial in range(50):
        rm = make_rm()
        ro = make_ro()
        rm.set_ontology(ro)
        for i in range(1, _RNG.randint(50, 150)):
            rm.record_pnl(_RNG.uniform(-200, 200))
        
        assert abs(rm.calculate_var() - ro._calc_var()) < 0.01, f'23.var_sync.{trial}'

def test_5000_phase24_oe_properties(make_oe: Callable[[], OrderEngine]) -> None:
    for trial in range(100):
        oe = make_oe()
        ids = [oe.intent(f'S{_RNG.randint(0, 10)}', 'BUY', 0.1, 100) for _ in range(_RNG.randint(5, 50))]
        
        assert len(set(ids)) == len(ids), f'24.uuid.{trial}'
    for trial in range(100):
        with tempfile.TemporaryDirectory() as tmp:
            oe = OrderEngine(f'{tmp}/o.jsonl', f'{tmp}/p.json')
            oid = oe.intent('X', 'BUY', 0.1, 100)
            for a in [_RNG.choice(['sent', 'confirm', 'fail', 'cancel']) for _ in range(3)]:
                try:
                    prev = oe.get(oid).state
                    if a == 'sent' and prev == OrderState.PENDING:
                        oe.sent(oid)
                    elif a == 'confirm' and prev in (OrderState.SENT, OrderState.PARTIAL):
                        oe.confirm(oid, 0.1, 100)
                    elif a == 'fail':
                        oe.fail(oid, 'err')
                    elif a == 'cancel' and prev not in (OrderState.FILLED,):
                        oe.cancel(oid)
                except Exception:
                    pass
            
            assert oe.get(oid).state in _VALID_OE_STATES, f'24.state.{trial}'

def test_5000_phase25_ptg_properties() -> None:
    for trial in range(80):
        limit = _RNG.uniform(100, 100000)
        ok, _ = fat_finger_check(limit + _RNG.uniform(0.01, 10000), max_notional=limit)
        
        assert ok is False, f'25.ff_block.{trial}'
    for trial in range(60):
        limit = _RNG.uniform(1000, 100000)
        ok, _ = fat_finger_check(_RNG.uniform(0.01, limit * 0.9), max_notional=limit)
        
        assert ok is True, f'25.ff_pass.{trial}'
    for trial in range(60):
        ts = _RNG.uniform(1000, 2000000)
        sym = f'SYM{trial}/USDT'
        ok, _ = same_bar_guard(sym, ts, {sym: ts})
        
        assert ok is False, f'25.sb.{trial}'

def test_5000_phase26_mi_cr_properties() -> None:
    mi26 = MarketImpactModel()
    for trial in range(100):
        est = mi26.estimate(_RNG.uniform(1, 1000000), _RNG.uniform(100, 10000000), _RNG.uniform(0.001, 0.5))
        
        assert 0.0001 <= est.total_pct <= 0.02, f'26.mi_bounds.{trial}'
    cr26 = ConcentrationRiskManager()
    for trial in range(50):
        pos = {f'S{i}/USDT': {'size': _RNG.uniform(100, 5000)} for i in range(_RNG.randint(0, 5))}
        
        assert 0.0 <= cr26.concentration_score(pos, _RNG.uniform(10000, 100000)) <= 1.0, f'26.hhi.{trial}'
    for trial in range(50):
        est = mi26.estimate(_RNG.uniform(100, 10000), _RNG.uniform(10000, 1000000), _RNG.uniform(0.005, 0.1))
        p = _RNG.uniform(100, 60000)
        
        assert est.adjusted_price('buy', p) >= p, f'26.mi_buy.{trial}'
        
        assert est.adjusted_price('sell', p) <= p, f'26.mi_sell.{trial}'

def test_5000_phase27_stress_properties() -> None:
    for trial, (name, days) in enumerate(list(SCENARIOS.items()) * 10):
        r = StressTestRunner(capital=_RNG.uniform(1000, 100000)).run_scenario(name, days)
        
        assert r.final_nav >= 0, f'27.st_nav.{trial}'
    for trial, (name, days) in enumerate(list(SCENARIOS.items()) * 7):
        r = StressTestRunner(capital=10000).run_scenario(name, days)
        
        assert 0 <= r.max_drawdown_pct <= 100, f'27.st_dd.{trial}'

def test_5000_phase28_ce_deposit_withdraw(phase12_make_ce: Callable[..., CapitalEngine]) -> None:
    for trial in range(50):
        e = phase12_make_ce(_RNG.uniform(1000, 50000))
        nb = e.nav
        e.deposit(_RNG.uniform(1, 10000))
        
        assert e.nav > nb, f'28.dep_inc.{trial}'
    for trial in range(50):
        cap = _RNG.uniform(1000, 50000)
        e = phase12_make_ce(cap)
        nb = e.nav
        result = e.withdrawal(_RNG.uniform(1, cap * 2))
        
        assert result and e.nav < nb or (not result and abs(e.nav - nb) < 0.01), f'28.with.{trial}'

def test_5000_phase29_am_properties() -> None:
    am29 = AlertManager(webhook_url='', cooldown_sec=0, min_level='DEBUG')
    for i in range(250):
        am29._send('INFO', f'CAT_{i}', f't_{i}', 'b')
    
    assert len(am29._history) <= 200, '29.hist_max'
    for trial in range(19):
        am_t = AlertManager(webhook_url='', cooldown_sec=9999, min_level='DEBUG')
        am_t.emergency('test', nav=9000)
        c1 = len(am_t._history)
        am_t.emergency('test2', nav=8000)
        
        assert len(am_t._history) == c1, f'29.cooldown.{trial}'

def test_5000_phase30_final_sanity(phase12_make_ce: Callable[..., CapitalEngine], make_ro: Callable[..., RiskOntology]) -> None:
    for trial in range(20):
        e = phase12_make_ce(_RNG.uniform(100, 10000))
        for _ in range(10):
            e.record_fee('X', f'f{trial}_{_}', _RNG.uniform(0.1, 50))
        
        assert e._cash >= 0, f'30.cash_nn.{trial}'
    for trial in range(20):
        e = phase12_make_ce(_RNG.uniform(5000, 50000))
        n = _RNG.uniform(100, 2000)
        e.open_position(f'S{trial}', f'o{trial}', 1000, 1.0, n)
        e.close_position(f'S{trial}', f'c{trial}', _RNG.uniform(0, 2000), 1.0)
        
        assert e._margin_used >= 0, f'30.margin_nn.{trial}'
    for trial in range(14):
        ro = make_ro(10000)
        for i in range(1, _RNG.randint(50, 200)):
            ro.update(nav=10000, realized_pnl_delta=_RNG.uniform(-500, 500))
        
        assert ro.var_1d <= 0, f'30.var_sign.{trial}'
    for trial in range(14):
        with tempfile.TemporaryDirectory() as tmp:
            oe1 = OrderEngine(f'{tmp}/o.jsonl', f'{tmp}/p.json')
            oids = [oe1.intent(f'S{i}', 'BUY', 0.1, 100) for i in range(3)]
            oe2 = OrderEngine(f'{tmp}/o.jsonl', f'{tmp}/p.json')
            loaded = sum((1 for oid in oids if oe2.get(oid) is not None))
            
            assert loaded == 3, f'30.oe_persist.{trial}'
