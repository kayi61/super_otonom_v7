"""
5000 gate — Aşama 32–38 (kalan property + tamamlayıcı → 5000 kontrol sonu).

Kaynak: ``super_otonom/test_5000.py`` (~3262–3496).

``test_10000.py`` için Aşama 39–60 pytest ayrımı ayrı PR/dosyalarla yapılabilir (bu modül 5000 script sonunu kapatır).
"""
from __future__ import annotations

import random
from pathlib import Path
from typing import Callable

import pytest
from super_otonom import config as so_config
from super_otonom.audit_log import AuditLog, DailyReconciler
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

def test_5000_phase32_ce_extended_properties(phase12_make_ce: Callable[..., CapitalEngine]) -> None:
    for trial in range(200):
        e = phase12_make_ce(_RNG.uniform(5000, 100000))
        for cycle in range(_RNG.randint(1, 8)):
            sym = f'C{trial}_{cycle}'
            n = _RNG.uniform(10, min(e.available_cash * 0.2, 3000))
            if n > 1 and e.available_cash > n * 1.1:
                price = _RNG.uniform(100, 50000)
                qty = n / price
                if e.open_position(sym, f'o{trial}_{cycle}', price, qty, n):
                    exit_p = price * _RNG.uniform(0.8, 1.2)
                    e.close_position(sym, f'c{trial}_{cycle}', exit_p, qty)
        
        assert _inv_ok(e), f'32.cycle_inv.{trial}'
    for trial in range(100):
        e = phase12_make_ce(_RNG.uniform(1000, 50000))
        for _ in range(_RNG.randint(1, 10)):
            e.record_fee('X', f'f{trial}_{_}', _RNG.uniform(0.01, 20))
        
        assert _inv_ok(e), f'32.fee_inv.{trial}'
    for trial in range(100):
        e = phase12_make_ce(_RNG.uniform(1000, 50000))
        expected_net = 0.0
        for _ in range(_RNG.randint(1, 10)):
            if _RNG.random() > 0.4:
                amt = _RNG.uniform(1, 500)
                e.deposit(amt)
                expected_net += amt
            elif e.available_cash > 10:
                amt = _RNG.uniform(1, min(e.available_cash * 0.1, 100))
                if e.withdrawal(amt):
                    expected_net -= amt
        
        assert abs(e._net_deposits - expected_net) < 0.01, f'32.dep_with.{trial}'

def test_5000_phase33_rm_ro_extended(make_rm: Callable[..., RiskManager], make_ro: Callable[..., RiskOntology]) -> None:
    for trial in range(100):
        rm = make_rm(10000)
        codes = [f'code_{_RNG.randint(0, 100)}' for _ in range(5)]
        rm.trigger_emergency(codes[0])
        for c in codes[1:]:
            rm.trigger_emergency(c)
        
        assert rm.emergency_reason == codes[0], f'33.latch.{trial}'
    for trial in range(100):
        ro = make_ro(_RNG.uniform(1000, 100000))
        for _ in range(20):
            ro.update(nav=_RNG.uniform(100, 200000))
        
        assert ro.peak_nav >= ro.nav, f'33.peak_ge_nav.{trial}'
    for trial in range(100):
        ro = make_ro(_RNG.uniform(1000, 100000))
        n0 = _RNG.uniform(5000, 50000)
        ro.update(nav=n0)
        for _ in range(5):
            ro.update(nav=_RNG.uniform(n0 * 0.1, n0 * 2))
        
        assert 0.0 <= ro.daily_loss_pct <= 1.0, f'33.loss_range.{trial}'

def test_5000_phase34_oe_ptg_extended(make_oe: Callable[[], OrderEngine]) -> None:
    for trial in range(100):
        oe = make_oe()
        n = _RNG.randint(10, 80)
        ids = [oe.intent(f'S{i}', _RNG.choice(['BUY', 'SELL']), 0.1, 100) for i in range(n)]
        
        assert len(set(ids)) == n, f'34.uuid.{trial}'
    for trial in range(100):
        limit = _RNG.uniform(100, 100000)
        ok, _ = fat_finger_check(limit, max_notional=limit)
        
        assert ok is False, f'34.ff_exact.{trial}'
    for trial in range(100):
        ts = _RNG.uniform(1000, 2000000)
        sym1 = f'SYM_A{trial}'
        sym2 = f'SYM_B{trial}'
        last = {sym1: ts}
        ok, _ = same_bar_guard(sym2, ts, last)
        
        assert ok is True, f'34.sb_diff.{trial}'

def test_5000_phase35_mi_cr_st_extended() -> None:
    mi35 = MarketImpactModel()
    for trial in range(100):
        est = mi35.estimate(_RNG.uniform(1, 500000), _RNG.uniform(100, 5000000), _RNG.uniform(0.001, 0.3))
        
        assert 0.0001 <= est.total_pct <= 0.02, f'35.mi.{trial}'
    cr35 = ConcentrationRiskManager()
    for trial in range(100):
        n_pos = _RNG.randint(0, 8)
        pos = {f'S{i}/USDT': {'size': _RNG.uniform(10, 10000)} for i in range(n_pos)}
        nav = _RNG.uniform(5000, 200000)
        hhi = cr35.concentration_score(pos, nav)
        
        assert hhi >= 0.0, f'35.hhi.{trial}'
    for trial in range(100):
        name = _RNG.choice(list(SCENARIOS.keys()))
        cap = _RNG.uniform(500, 200000)
        r = StressTestRunner(capital=cap).run_scenario(name, SCENARIOS[name])
        
        assert r.final_nav >= 0, f'35.st.{trial}'

def test_5000_phase36_audit_reconciler_extended(tmp_path: Path) -> None:
    for trial in range(100):
        t = tmp_path / f'al36_{trial}'
        t.mkdir(parents=True, exist_ok=True)
        al36 = AuditLog(audit_dir=str(t))
        n_events = _RNG.randint(1, 10)
        for i in range(n_events):
            al36.trade_open(f'S{i}', f'o{i}', 1000, 0.1, 100, nav=10000)
        events = al36.get_events()
        
        assert len(events) == n_events, f'36.al.count.{trial}'
    for trial in range(100):
        rdir = tmp_path / f'dr36_{trial}'
        rdir.mkdir(parents=True, exist_ok=True)
        dr36 = DailyReconciler(reconcile_dir=str(rdir))
        dr36.set_sod(10000)
        total_pnl = 0.0
        for _ in range(_RNG.randint(1, 5)):
            pnl = _RNG.uniform(-500, 500)
            dr36.record_trade(f'S{_}', pnl=pnl, fee=1)
            total_pnl += pnl
        snap = {'nav': 10000 + total_pnl, 'open_positions': 0, 'positions': []}
        report = dr36.run(snap)
        
        assert abs(report.total_realized_pnl - total_pnl) < 0.01, f'36.dr.pnl.{trial}'

def test_5000_phase37_integration_cycles(phase12_make_ce: Callable[..., CapitalEngine], make_rm: Callable[..., RiskManager], make_ro: Callable[..., RiskOntology]) -> None:
    for trial in range(50):
        e = phase12_make_ce(_RNG.uniform(10000, 100000))
        rm = make_rm(e.initial_capital)
        ro = make_ro(e.initial_capital)
        rm.set_ontology(ro)
        price = _RNG.uniform(100, 50000)
        notional = _RNG.uniform(100, min(e.available_cash * 0.3, 5000))
        qty = notional / price
        e.open_position(f'T{trial}', f'o{trial}', price, qty, notional)
        ro.update(nav=e.nav)
        exit_price = price * _RNG.uniform(0.8, 1.2)
        pnl = e.close_position(f'T{trial}', f'c{trial}', exit_price, qty)
        if pnl is not None:
            rm.record_pnl(pnl)
        ro.update(nav=e.nav)
        
        assert _inv_ok(e), f'37.cycle.inv.{trial}'
        
        assert abs(e._margin_used) < 0.01, f'37.cycle.margin0.{trial}'
    rm37 = make_rm(10000)
    rm37.daily_loss = 500
    result = rm37.check_risk(10000, 0, 0)
    
    assert result is False, '37.deny.result'
    
    assert rm37.get_last_deny() != '', '37.deny.reason'
    rm37.reset_emergency()
    rm37.daily_loss = 0
    result2 = rm37.check_risk(10000, 0, 0)
    
    assert result2 is True, '37.deny.reset_ok'

def test_5000_phase38_final_complementary(phase12_make_ce: Callable[..., CapitalEngine], make_ro: Callable[..., RiskOntology], make_oe: Callable[[], OrderEngine]) -> None:
    for trial in range(50):
        e = phase12_make_ce(_RNG.uniform(1000, 50000), reserve=_RNG.uniform(0, 0.15))
        for _ in range(_RNG.randint(1, 5)):
            e.reserve_margin(f'r{trial}_{_}', _RNG.uniform(1, min(e.available_cash * 0.3 + 1, 500)))
        
        assert e.available_cash >= 0, f'38.avail_nn.{trial}'
    for trial in range(50):
        ro = make_ro(_RNG.uniform(1000, 50000))
        for _ in range(10):
            ro.update(nav=_RNG.uniform(100, 100000))
        
        assert ro.weekly_loss_pct >= 0, f'38.weekly_nn.{trial}'
    for trial in range(52):
        oe = make_oe()
        oid = oe.intent('X', 'BUY', 0.1, 100)
        oe.sent(oid)
        oe.confirm(oid, 0.1, 100)
        oe.fail(oid, 'late')
        oe.cancel(oid, 'stale')
        
        assert oe.get(oid).state == OrderState.FILLED, f'38.filled_final.{trial}'
    mi38 = MarketImpactModel()
    for trial in range(50):
        est = mi38.estimate(_RNG.uniform(100, 50000), _RNG.uniform(10000, 5000000), _RNG.uniform(0.005, 0.1))
        p = _RNG.uniform(100, 60000)
        
        assert est.adjusted_price('buy', p) >= est.adjusted_price('sell', p), f'38.mi_bs.{trial}'
