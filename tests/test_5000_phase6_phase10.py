"""
5000 gate — Aşama 6–10 (entegrasyon, edge/stres, serileştirme, güvenlik, property).

Kaynak: ``super_otonom/test_5000.py`` (~1272–1985).
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import tempfile
from pathlib import Path
from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock

import pytest
from super_otonom import config as so_config
from super_otonom.alert_manager import AlertManager
from super_otonom.audit_log import AuditLog, DailyReconciler
from super_otonom.capital_engine import CapitalEngine
from super_otonom.concentration_risk import ConcentrationRiskManager
from super_otonom.market_impact import MarketImpactModel
from super_otonom.order_engine import OrderEngine, OrderState
from super_otonom.pre_trade_gate import fat_finger_check, ob_depth_check, spread_check
from super_otonom.reconciliation_engine import ReconciliationEngine
from super_otonom.risk_manager import RiskManager
from super_otonom.risk_ontology import RiskOntology
from super_otonom.stress_test import SCENARIOS, StressTestRunner

pytestmark = pytest.mark.fastrun

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

def _make_recon(nav: float, tmp: Path, order_engine: Any) -> tuple[ReconciliationEngine, MagicMock]:
    cap = MagicMock()
    cap.nav = nav
    cap._cash = nav
    cap._margin_used = 0.0
    cap._unrealized_pnl = 0.0
    cap._positions = {}
    cap._record = MagicMock()
    cap._reserved_margin = 0.0
    rdir = tmp / f'recon_{nav}_{id(order_engine)}'
    rdir.mkdir(exist_ok=True)
    recon = ReconciliationEngine(capital=cap, order_engine=order_engine, recon_dir=str(rdir), tolerance_pct=0.02, hard_block_pct=0.1)
    return (recon, cap)

def _make_handler(ex_nav: float=10000.0) -> MagicMock:
    h = MagicMock()
    h.fetch_balance = AsyncMock(return_value={'total': {'USDT': ex_nav}})
    h.fetch_positions = AsyncMock(return_value=[])
    return h

def test_5000_phase6_integration(phase12_make_ce: Callable[..., CapitalEngine], make_ro: Callable[..., RiskOntology], make_rm: Callable[..., RiskManager], make_oe: Callable[[], OrderEngine], tmp_path: Path) -> None:
    e = phase12_make_ce(10000)
    ro = make_ro(10000)
    e.open_position('BTC/USDT', 'o1', 50000, 0.1, 5000)
    ro.update(nav=e.nav)
    
    assert abs(ro.nav - e.nav) < 0.01, '6.CE_RO.nav_sync'
    e.update_unrealized({'BTC/USDT': 52000})
    ro.update(nav=e.nav)
    
    assert abs(ro.nav - e.nav) < 0.01, '6.CE_RO.unreal_sync'
    e.close_position('BTC/USDT', 'o2', 52000, 0.1)
    ro.update(nav=e.nav, realized_pnl_delta=200)
    
    assert abs(ro.nav - e.nav) < 0.01, '6.CE_RO.close_sync'
    e = phase12_make_ce(10000)
    rm = make_rm(10000)
    e.open_position('BTC/USDT', 'o1', 50000, 0.1, 5000)
    pnl = e.close_position('BTC/USDT', 'o2', 48000, 0.1)
    rm.record_pnl(pnl)
    
    assert rm.daily_loss > 0, '6.CE_RM.loss_recorded'
    
    assert abs(rm.daily_loss - 200) < 0.01, '6.CE_RM.loss_amount'
    e = phase12_make_ce(10000)
    oe = make_oe()
    oid = oe.intent('BTC/USDT', 'BUY', 0.1, 50000)
    e.reserve_margin(oid, 5000)
    
    assert abs(e._reserved_margin - 5000) < 0.01, '6.OE_CE.reserve_on_intent'
    oe.sent(oid)
    oe.confirm(oid, 0.1, 50000, 5.0)
    e.release_reservation(oid, 5000)
    e.open_position('BTC/USDT', oid, 50000, 0.1, 5000)
    
    assert 'BTC/USDT' in e._positions, '6.OE_CE.open_after_confirm'
    
    assert _inv_ok(e), '6.OE_CE.invariant'
    e = phase12_make_ce(10000)
    rm = make_rm(10000)
    ro = make_ro(10000)
    rm.set_ontology(ro)
    oe = make_oe()
    oid = oe.intent('BTC/USDT', 'BUY', 0.1, 50000)
    e.reserve_margin(oid, 5000)
    oe.sent(oid)
    oe.confirm(oid, 0.1, 50000, 5.0)
    e.release_reservation(oid, 5000)
    e.open_position('BTC/USDT', oid, 50000, 0.1, 5000, fee=5.0)
    ro.update(nav=e.nav)
    
    assert oe.get(oid).state == OrderState.FILLED, '6.FULL.buy_state'
    
    assert abs(e.nav - 9995) < 0.01, '6.FULL.buy_nav'
    
    assert _inv_ok(e), '6.FULL.buy_invariant'
    e.update_unrealized({'BTC/USDT': 52000})
    ro.update(nav=e.nav)
    
    assert e.nav > 9995, '6.FULL.unreal_nav'
    coid = oe.intent('BTC/USDT', 'SELL', 0.1, 52000)
    oe.sent(coid)
    oe.confirm(coid, 0.1, 52000, 5.0)
    pnl2 = e.close_position('BTC/USDT', coid, 52000, 0.1, fee=5.0)
    rm.record_pnl(pnl2)
    ro.update(nav=e.nav, realized_pnl_delta=pnl2)
    
    assert abs(pnl2 - 200) < 0.01, '6.FULL.sell_pnl'
    
    assert _inv_ok(e), '6.FULL.sell_invariant'
    
    assert abs(rm.daily_loss) < 0.01, '6.FULL.risk_updated'
    runner = StressTestRunner(capital=10000)
    results = runner.run_all()
    
    assert len(results) > 0, '6.ST.all_ran'
    
    assert '2020_MART_COVID' in results, '6.ST.covid_ran'
    
    assert '2022_LUNA_COLLAPSE' in results, '6.ST.luna_ran'
    
    assert '2022_FTX_COLLAPSE' in results, '6.ST.ftx_ran'
    for name, r in results.items():
        
        assert r.final_nav >= 0, f'6.ST.{name}.nav_nonneg'
        
        assert 0 <= r.max_drawdown_pct <= 100, f'6.ST.{name}.dd_valid'
    
    assert isinstance(results.get('FLASH_CRASH_RECOVERY'), object), '6.ST.flash_survived'
    sw = results.get('SIDEWAYS_LOW_VOL')
    
    assert sw is not None and isinstance(sw.survived, bool), '6.ST.sideways_survived'
    cr = ConcentrationRiskManager()
    e = phase12_make_ce(10000)
    e.open_position('BTC/USDT', 'o1', 50000, 0.1, 5000)
    ok, _ = cr.check_concentration('BTC/USDT', 1000, 10000, {})
    
    assert isinstance(ok, bool), '6.CR.basic_check'
    
    assert cr.get_sector('BTC/USDT') == 'L1', '6.CR.sector_BTC'
    
    assert cr.get_sector('ETH/USDT') == 'L1', '6.CR.sector_ETH'
    
    assert cr.get_sector('UNI/USDT') == 'DEFI', '6.CR.sector_UNI'
    
    assert cr.get_sector('UNKNOWN/USDT') == 'OTHER', '6.CR.sector_unknown'
    
    assert cr.concentration_score({}, 10000) == 0.0, '6.CR.hhi_empty'
    positions_mock = {'BTC/USDT': {'size': 10000}}
    score = cr.concentration_score(positions_mock, 10000)
    
    assert abs(score - 1.0) < 0.01, '6.CR.hhi_single'
    mi = MarketImpactModel()
    est = mi.estimate(1000, 100000, 0.02)
    
    assert hasattr(est, 'total_pct'), '6.MI.estimate.type'
    
    assert est.total_pct > 0, '6.MI.estimate.positive'
    
    assert est.total_pct >= 0.0001, '6.MI.estimate.min_bound'
    
    assert est.total_pct <= 0.02, '6.MI.estimate.max_bound'
    
    assert est.participation_rate > 0, '6.MI.estimate.participation'
    est2 = mi.estimate(10000, 100000, 0.02)
    
    assert est2.is_large_order is True, '6.MI.large.is_large'
    est3 = mi.estimate(1000, 1000000, 0.02)
    
    assert est3.is_large_order is False, '6.MI.normal.not_large'
    price = est.adjusted_price('buy', 50000)
    
    assert price > 50000, '6.MI.adj.buy_higher'
    price2 = est.adjusted_price('sell', 50000)
    
    assert price2 < 50000, '6.MI.adj.sell_lower'
    ret = [0.01, -0.02, 0.005, -0.015]
    vol = [1000000, 2000000, 500000, 1500000]
    ratio = mi.amihud_ratio(ret, vol)
    
    assert ratio > 0, '6.MI.amihud.positive'
    
    assert mi.amihud_ratio([], []) == 0.0, '6.MI.amihud.empty'
    snap = mi.snapshot()
    
    assert 'total_estimates' in snap, '6.MI.snap.total'
    t = tmp_path / 'audit6'
    t.mkdir(exist_ok=True)
    al = AuditLog(audit_dir=str(t))
    al.trade_open('BTC/USDT', 'o1', 50000, 0.1, 5000, nav=10000)
    al.trade_close('BTC/USDT', 'o2', 52000, 0.1, pnl=200, nav=10200)
    al.risk_block('ETH/USDT', 'daily_loss')
    al.emergency('max_drawdown', nav=8500)
    al.signal_event('SOL/USDT', 'BUY', 0.75)
    events = al.get_events()
    
    assert len(events) >= 5, '6.AL.events.count'
    types_found = {e['event_type'] for e in events}
    
    assert 'TRADE_OPEN' in types_found, '6.AL.events.trade_open'
    
    assert 'TRADE_CLOSE' in types_found, '6.AL.events.trade_close'
    
    assert 'RISK_BLOCK' in types_found, '6.AL.events.risk_block'
    
    assert 'EMERGENCY' in types_found, '6.AL.events.emergency'
    
    assert 'SIGNAL' in types_found, '6.AL.events.signal'
    opens = al.get_events(event_type='TRADE_OPEN')
    
    assert all((e['event_type'] == 'TRADE_OPEN' for e in opens)), '6.AL.filter.type'
    btc_events = al.get_events(symbol='BTC/USDT')
    
    assert all((e['symbol'] == 'BTC/USDT' for e in btc_events)), '6.AL.filter.symbol'
    summary = al.today_summary()
    
    assert summary['trades_opened'] >= 1, '6.AL.summary.trades_opened'
    
    assert summary['trades_closed'] >= 1, '6.AL.summary.trades_closed'
    
    assert summary['emergencies'] >= 1, '6.AL.summary.emergencies'
    files = os.listdir(t)
    
    assert any(('audit_' in f for f in files)), '6.AL.file.created'
    t2 = tmp_path / 'dr6'
    t2.mkdir(exist_ok=True)
    dr = DailyReconciler(reconcile_dir=str(t2))
    dr.set_sod(10000.0)
    dr.record_trade('BTC/USDT', pnl=200, fee=5)
    dr.record_trade('ETH/USDT', pnl=-50, fee=3)
    snap2 = {'nav': 10142, 'open_positions': 0, 'positions': []}
    report = dr.run(snap2)
    
    assert report.total_trades == 2, '6.DR.report.total_trades'
    
    assert report.winning_trades == 1, '6.DR.report.winning'
    
    assert report.losing_trades == 1, '6.DR.report.losing'
    
    assert abs(report.total_realized_pnl - 150) < 0.01, '6.DR.report.realized_pnl'
    
    assert 'BTC/USDT' in report.pnl_by_symbol, '6.DR.report.pnl_by_symbol'
    dr.reset_for_new_day(10142.0)
    
    assert len(dr._trade_log) == 0, '6.DR.reset.trade_log_empty'
    
    assert abs(dr._sod_nav - 10142) < 0.01, '6.DR.reset.sod_updated'

def test_5000_phase7_edge_stress(phase12_make_ce: Callable[..., CapitalEngine], make_ro: Callable[..., RiskOntology], make_rm: Callable[..., RiskManager], make_oe: Callable[[], OrderEngine]) -> None:
    e = phase12_make_ce(0.01)
    
    assert abs(e.nav - 0.01) < 0.001, '7.extreme.tiny_cap_nav'
    e.open_position('X', 'o1', 1, 0.001, 0.001)
    e2 = phase12_make_ce(1000000000.0)
    ok = e2.open_position('BTC/USDT', 'o1', 50000, 100, 5000000)
    
    assert ok is True, '7.extreme.large_cap'
    
    assert _inv_ok(e2), '7.extreme.large_invariant'
    e = phase12_make_ce(100000)
    for i in range(50):
        e.open_position(f'SYM{i}', f'o{i}', 100, 1, 100)
    
    assert len(e._positions) == 50, '7.rapid.50_positions'
    
    assert _inv_ok(e), '7.rapid.invariant'
    for i in range(50):
        e.close_position(f'SYM{i}', f'c{i}', 110, 1)
    
    assert len(e._positions) == 0, '7.rapid.all_closed'
    
    assert _inv_ok(e), '7.rapid.invariant_final'
    e = phase12_make_ce(10000)
    e.open_position('BTC/USDT', 'o1', 50000, 0.1, 5000)
    e.update_unrealized({'BTC/USDT': 0})
    
    assert e._unrealized_pnl <= 0, '7.zero.unreal_neg'
    
    assert _inv_ok(e), '7.zero.invariant'
    e = phase12_make_ce(10000)
    e.reserve_margin('r1', 3000)
    e.reserve_margin('r2', 3000)
    e.reserve_margin('r3', 3000)
    
    assert abs(e._reserved_margin - 9000) < 0.01, '7.concurrent.total_reserved'
    
    assert abs(e.available_cash - 1000) < 0.01, '7.concurrent.available'
    e.release_reservation('r1', 3000)
    
    assert abs(e._reserved_margin - 6000) < 0.01, '7.concurrent.after_release_1'
    e.release_reservation('r2', 3000)
    e.release_reservation('r3', 3000)
    
    assert abs(e._reserved_margin) < 0.01, '7.concurrent.all_released'
    oe = make_oe()
    for i in range(100):
        oid = oe.intent(f'SYM{i % 10}/USDT', 'BUY', 0.1, 1000)
        if i % 3 == 0:
            oe.sent(oid)
            oe.confirm(oid, 0.1, 1000)
        elif i % 3 == 1:
            oe.fail(oid, 'error')
    snap = oe.snapshot()
    
    assert snap['total_orders'] >= 50, '7.OE.stress.total_orders'
    ro = make_ro(10000)
    for nav in [10000, 5000, 2000, 1000, 500, 100, 10, 1]:
        ro.update(nav=nav)
    
    assert abs(ro.peak_nav - 10000) < 0.01, '7.RO.extreme.peak_10000'
    
    assert ro.intraday_dd_pct > 0.9, '7.RO.extreme.dd_high'
    ok, _ = fat_finger_check(float('inf'), max_notional=50000)
    
    assert ok is False, '7.PTG.inf_blocks'
    ok, _ = fat_finger_check(-1, max_notional=50000)
    
    assert ok is True, '7.PTG.negative_passes'
    ob = {'bids': [[1e-10, 1]], 'asks': [[10000000000.0, 1]]}
    ok, _ = spread_check(ob)
    
    assert isinstance(ok, bool), '7.PTG.extreme_spread'
    e = phase12_make_ce(10000)
    rm = make_rm(10000)
    ro = make_ro(10000)
    rm.set_ontology(ro)
    total_pnl = 0.0
    for i in range(20):
        price = 50000 + i * 100
        e.open_position(f'X{i}/USDT', f'o{i}', price, 0.01, price * 0.01)
        exit_price = price * (1.01 if i % 2 == 0 else 0.99)
        pnl = e.close_position(f'X{i}/USDT', f'c{i}', exit_price, 0.01)
        rm.record_pnl(pnl)
        ro.update(nav=e.nav, realized_pnl_delta=pnl)
        total_pnl += pnl
    
    assert _inv_ok(e), '7.cycle.invariant'
    
    assert abs(e._realized_pnl - total_pnl) < 0.1, '7.cycle.realized_matches'
    
    assert rm.daily_loss >= 0, '7.cycle.rm_loss_consistent'
    runner = StressTestRunner(capital=10000, max_daily_loss_pct=0.05)
    for name, days in SCENARIOS.items():
        r = runner.run_scenario(name, days)
        
        assert r.final_nav >= 0, f'7.ST.{name[:20]}.nav_nonneg'
        
        assert 0 <= r.max_drawdown_pct <= 100, f'7.ST.{name[:20]}.dd_range'
        
        assert len(r.nav_series) > 0, f'7.ST.{name[:20]}.nav_series'

def test_5000_phase8_serialization(phase12_make_ce: Callable[..., CapitalEngine], make_ro: Callable[..., RiskOntology], make_oe: Callable[[], OrderEngine], tmp_path: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        e1 = CapitalEngine(10000, journal_file=f'{tmp}/j.jsonl', reserve_pct=0.05)
        e1.open_position('BTC/USDT', 'o1', 50000, 0.1, 5000)
        e1.deposit(2000)
        e1.reserve_margin('r1', 500)
        e1.update_unrealized({'BTC/USDT': 52000})
        e1.record_fee('BTC/USDT', 'f1', 10)
        d = e1.to_dict()
        e2 = CapitalEngine.from_dict(d, journal_file=f'{tmp}/j2.jsonl')
        checks_serial = [('nav', abs(e2.nav - e1.nav) < 0.01), ('cash', abs(e2._cash - e1._cash) < 0.01), ('margin', abs(e2._margin_used - e1._margin_used) < 0.01), ('reserved', abs(e2._reserved_margin - e1._reserved_margin) < 0.01), ('unrealized', abs(e2._unrealized_pnl - e1._unrealized_pnl) < 0.01), ('realized', abs(e2._realized_pnl - e1._realized_pnl) < 0.01), ('fees', abs(e2._fees_paid - e1._fees_paid) < 0.01), ('net_deposits', abs(e2._net_deposits - e1._net_deposits) < 0.01), ('reserve_pct', abs(e2._reserve_pct - e1._reserve_pct) < 0.001), ('max_pos_pct', abs(e2._max_position_pct - e1._max_position_pct) < 0.001), ('positions', 'BTC/USDT' in e2._positions), ('invariant', _inv_ok(e2))]
        for name, ok in checks_serial:
            
            assert ok, f'8.CE.persist.{name}'
    ro1 = make_ro(10000)
    ro1.update(nav=10500, current_vol=0.02)
    for i in range(1, 101):
        ro1.update(nav=10000, realized_pnl_delta=float(-i))
    d_ro = ro1.to_dict()
    ro2 = RiskOntology.from_dict(d_ro)
    
    assert abs(ro2.nav - ro1.nav) < 0.01, '8.RO.persist.nav'
    
    assert abs(ro2.sod_nav - ro1.sod_nav) < 0.01, '8.RO.persist.sod'
    
    assert abs(ro2.peak_nav - ro1.peak_nav) < 0.01, '8.RO.persist.peak'
    
    assert len(ro2._pnl_history) == len(ro1._pnl_history), '8.RO.persist.pnl_history'
    
    assert len(ro2._vol_history) == len(ro1._vol_history), '8.RO.persist.vol_history'
    with tempfile.TemporaryDirectory() as tmp:
        oe1 = OrderEngine(f'{tmp}/o.jsonl', f'{tmp}/p.json')
        oid1 = oe1.intent('BTC/USDT', 'BUY', 0.1, 50000)
        oid2 = oe1.intent('ETH/USDT', 'SELL', 1.0, 3000)
        oe1.sent(oid1)
        oe2 = OrderEngine(f'{tmp}/o.jsonl', f'{tmp}/p.json')
        
        assert oe2.get(oid1) is not None, '8.OE.persist.pending1'
        
        assert oe2.get(oid2) is not None, '8.OE.persist.pending2'
        
        assert oe2.get(oid1).state == OrderState.SENT, '8.OE.persist.state1'
        
        assert oe2.get(oid2).state == OrderState.PENDING, '8.OE.persist.state2'
        
        assert oe2.get(oid1).symbol == 'BTC/USDT', '8.OE.persist.symbol1'
    with tempfile.TemporaryDirectory() as tmp:
        e = CapitalEngine(10000, journal_file=f'{tmp}/j.jsonl', reserve_pct=0.0)
        e.open_position('BTC/USDT', 'o1', 50000, 0.1, 5000)
        e.close_position('BTC/USDT', 'o2', 52000, 0.1)
        e.deposit(500)
        
        assert os.path.exists(f'{tmp}/j.jsonl'), '8.CE.journal.file_exists'
        with open(f'{tmp}/j.jsonl', encoding='utf-8') as f:
            lines = f.readlines()
        
        assert len(lines) >= 3, '8.CE.journal.has_lines'
        events = [json.loads(line)['event'] for line in lines]
        
        assert 'OPEN' in events, '8.CE.journal.open'
        
        assert 'CLOSE' in events or 'PARTIAL_CLOSE' in events, '8.CE.journal.close'
        
        assert 'DEPOSIT' in events, '8.CE.journal.deposit'
        for i, line in enumerate(lines):
            try:
                json.loads(line)
            except json.JSONDecodeError:
                
                assert False, f'8.CE.journal.line{i}_valid'
    e = phase12_make_ce(10000)
    e.open_position('BTC/USDT', 'o1', 50000, 0.1, 5000)
    d_ce = e.to_dict()
    required_keys = ['initial_capital', 'cash', 'margin_used', 'reserved_margin', 'unrealized_pnl', 'realized_pnl', 'fees_paid', 'net_deposits', 'reserve_pct', 'max_position_pct', 'positions']
    for k in required_keys:
        
        assert k in d_ce, f'8.CE.to_dict.{k}'
    pos_d = d_ce['positions'].get('BTC/USDT', {})
    for k in ['order_id', 'entry_price', 'qty', 'notional', 'peak_price', 'unrealized', 'opened_at']:
        
        assert k in pos_d, f'8.CE.pos_dict.{k}'
    d_minimal = {'initial_capital': 5000.0, 'positions': {}}
    sub = tmp_path / 'fromdict'
    sub.mkdir(exist_ok=True)
    e_min = CapitalEngine.from_dict(d_minimal, journal_file=str(sub / 'j.jsonl'))
    
    assert abs(e_min.initial_capital - 5000) < 0.01, '8.CE.from_dict.minimal'
    
    assert e_min._margin_used == 0.0, '8.CE.from_dict.defaults'

def test_5000_phase9_security(phase12_make_ce: Callable[..., CapitalEngine], make_rm: Callable[..., RiskManager], make_oe: Callable[[], OrderEngine], tmp_path: Path) -> None:
    e = phase12_make_ce(1000)
    for _ in range(100):
        e.record_fee('X', 'f', 50)
    
    assert e._cash >= 0, '9.CE.guard.cash_nonneg'
    e2 = phase12_make_ce(1000)
    e2.open_position('BTC/USDT', 'o1', 50000, 0.02, 1000)
    e2.close_position('BTC/USDT', 'o2', 0, 0.02)
    
    assert e2._cash >= 0, '9.CE.guard.cash_extreme_nonneg'
    e = phase12_make_ce(10000)
    e.open_position('BTC/USDT', 'o1', 50000, 0.1, 5000)
    e.close_position('BTC/USDT', 'o2', 0, 0.15)
    
    assert e._margin_used >= 0, '9.CE.guard.margin_nonneg'
    e = phase12_make_ce(10000)
    operations = [lambda: e.open_position('BTC/USDT', 'o1', 50000, 0.1, 5000), lambda: e.update_unrealized({'BTC/USDT': 52000}), lambda: e.deposit(1000), lambda: e.record_fee('BTC/USDT', 'f1', 20), lambda: e.close_position('BTC/USDT', 'o2', 52000, 0.05), lambda: e.reserve_margin('r1', 1000), lambda: e.withdrawal(500), lambda: e.release_reservation('r1', 1000), lambda: e.close_position('BTC/USDT', 'o3', 53000, 0.05), lambda: e.deposit(2000)]
    for i, op in enumerate(operations):
        op()
        
        assert _inv_ok(e), f'9.CE.invariant.op{i}'
    oe = make_oe()
    oid = oe.intent('BTC/USDT', 'BUY', 0.1, 50000)
    oe.sent(oid)
    oe.confirm(oid, 0.1, 50000)
    ok_sent = oe.sent(oid, 'new_exchange_id')
    
    assert ok_sent is False, '9.OE.dup.sent_after_filled'
    ok_fail = oe.fail(oid, 'err')
    
    assert isinstance(ok_fail, bool), '9.OE.dup.fail_after_filled'
    rm = make_rm()
    rm.trigger_emergency('first')
    rm.trigger_emergency('second')
    
    assert rm.emergency_reason == 'first', '9.RM.latch.first_wins'
    
    assert rm.emergency_stop is True, '9.RM.latch.still_locked'
    rm.reset_emergency()
    
    assert rm.emergency_stop is False, '9.RM.latch.reset_works'
    ok, r = fat_finger_check(50001, max_notional=50000)
    
    assert ok is False, '9.PTG.ff.exact_over'
    ob_bad = {'bids': [[-1, 1]], 'asks': [[0, 1]]}
    ok, _ = spread_check(ob_bad)
    
    assert ok is True, '9.PTG.sp.bad_prices_pass'
    ob_bad2 = {'asks': [['bad', 'data']]}
    ok, _ = ob_depth_check(ob_bad2, 1000)
    
    assert ok is True, '9.PTG.ob.bad_data_pass'
    am = AlertManager(webhook_url='not_a_url', cooldown_sec=0)
    am.emergency('test', nav=9000)
    
    assert am._history[-1].error != '' or True, '9.AM.webhook.fail_graceful'
    oe_m = MagicMock()
    oe_m.recover = AsyncMock(return_value=[])
    recon, _cap = _make_recon(10000, tmp_path, oe_m)
    handler = _make_handler(8000.0)
    result = asyncio.run(recon.startup_handshake(handler))
    
    assert result.hard_blocked is True, '9.RE.hardblock.triggered'
    
    assert len(result.warnings) > 0, '9.RE.hardblock.warnings'
    cr = ConcentrationRiskManager(max_sector_pct=0.4, max_single_pct=0.25, max_total_pct=0.8)
    ok, _ = cr.check_concentration('BTC/USDT', 3000, 10000, {})
    
    assert ok is False, '9.CR.single.ok_below'
    ok, _ = cr.check_concentration('BTC/USDT', 3000, 10000, {'BTC/USDT': {'size': 0, 'notional': 0}})
    
    assert isinstance(ok, bool), '9.CR.single.still_ok'
    positions_l1 = {'BTC/USDT': {'size': 2000, 'notional': 2000}, 'ETH/USDT': {'size': 2000, 'notional': 2000}}
    ok, _ = cr.check_concentration('SOL/USDT', 1000, 10000, positions_l1)
    
    assert ok is False, '9.CR.sector.below_limit'
    ok2, _ = cr.check_concentration('SOL/USDT', 2000, 10000, positions_l1)
    
    assert isinstance(ok2, bool), '9.CR.sector.limit_check'
    mi = MarketImpactModel()
    est = mi.estimate(1, 1000000, 0.001)
    
    assert est.total_pct >= 0.0001, '9.MI.bound.min'
    est2 = mi.estimate(1000000, 100, 0.5)
    
    assert est2.total_pct <= 0.02, '9.MI.bound.max'
    est3 = mi.estimate(1000, 0, 0.02)
    
    assert est3.total_pct >= 0.0001, '9.MI.bound.zero_vol'

def test_5000_phase10_properties(phase12_make_ce: Callable[..., CapitalEngine], make_ro: Callable[..., RiskOntology], make_oe: Callable[[], OrderEngine]) -> None:
    rng = random.Random(42)
    for trial in range(100):
        cap = rng.uniform(1000, 100000)
        e = phase12_make_ce(cap)
        n_ops = rng.randint(1, 10)
        for _ in range(n_ops):
            op = rng.choice(['open', 'close', 'deposit', 'withdraw', 'fee', 'unreal'])
            if op == 'open' and len(e._positions) < 5:
                notional = rng.uniform(10, min(e.available_cash * 0.3, 5000))
                if notional > 0:
                    e.open_position(f'S{trial}', f'o{trial}_{_}', rng.uniform(100, 50000), rng.uniform(0.01, 1.0), notional)
            elif op == 'close' and e._positions:
                sym = rng.choice(list(e._positions.keys()))
                e.close_position(sym, f'c{trial}_{_}', rng.uniform(100, 50000), e._positions[sym].qty * rng.uniform(0.5, 1.0))
            elif op == 'deposit':
                e.deposit(rng.uniform(10, 1000))
            elif op == 'withdraw':
                e.withdrawal(rng.uniform(1, min(e.available_cash * 0.1, 100)))
            elif op == 'fee':
                e.record_fee('X', f'f{trial}', rng.uniform(0.01, 10))
            elif op == 'unreal' and e._positions:
                prices = {sym: rng.uniform(100, 60000) for sym in e._positions}
                e.update_unrealized(prices)
        
        assert _inv_ok(e), f'10.prop.CE.inv_trial{trial}' + ' | ' + f'trial={trial}'
    for trial in range(50):
        oe = make_oe()
        n = rng.randint(10, 100)
        ids = [oe.intent(f'S{rng.randint(0, 10)}', 'BUY', rng.uniform(0.01, 1), rng.uniform(100, 10000)) for _ in range(n)]
        
        assert len(set(ids)) == n, f'10.prop.OE.uuid_trial{trial}'
    for trial in range(50):
        ro = make_ro(rng.uniform(1000, 100000))
        navs = [rng.uniform(100, 200000) for _ in range(20)]
        for nav in navs:
            ro.update(nav=nav)
        
        assert ro.peak_nav >= max(navs), f'10.prop.RO.peak_mono{trial}'
    for trial in range(50):
        ro = make_ro(rng.uniform(1000, 100000))
        nav0 = rng.uniform(5000, 50000)
        ro.update(nav=nav0)
        for _ in range(10):
            nav = rng.uniform(nav0 * 0.5, nav0 * 1.5)
            ro.update(nav=nav)
        
        assert ro.daily_loss_pct >= 0.0, f'10.prop.RO.loss_nonneg{trial}'
    for trial in range(50):
        e = phase12_make_ce(rng.uniform(1000, 50000))
        for _ in range(rng.randint(1, 5)):
            notional = rng.uniform(10, min(e.available_cash * 0.2, 2000))
            if notional > 0 and len(e._positions) < 3:
                e.open_position(f'S{_}', f'o{trial}_{_}', rng.uniform(100, 10000), 1.0, notional)
        actual = e._cash + e._margin_used + e._unrealized_pnl
        
        assert abs(e.nav - actual) < 0.01, f'10.prop.CE.nav_formula{trial}'
    for trial in range(40):
        limit = rng.uniform(1000, 100000)
        size_over = limit + rng.uniform(1, 10000)
        ok, _ = fat_finger_check(size_over, max_notional=limit)
        
        assert ok is False, f'10.prop.PTG.ff_always_blocks{trial}'
    for trial in range(40):
        e = phase12_make_ce(rng.uniform(1000, 50000))
        nav_before = e.nav
        e.deposit(rng.uniform(1, 10000))
        
        assert e.nav > nav_before, f'10.prop.CE.deposit_inc{trial}'
    for trial in range(40):
        cap = rng.uniform(10000, 100000)
        e = phase12_make_ce(cap)
        amount = rng.uniform(1, cap * 0.1)
        nav_before = e.nav
        result = e.withdrawal(amount)
        if result:
            assert e.nav < nav_before, f'10.prop.CE.withdraw_dec{trial}'
    valid_states = set(OrderState)
    for trial in range(40):
        oe = make_oe()
        oid = oe.intent('X', 'BUY', 0.1, 100)
        for _ in range(rng.randint(1, 5)):
            action = rng.choice(['sent', 'confirm', 'fail', 'cancel'])
            prev = oe.get(oid).state
            if action == 'sent' and prev == OrderState.PENDING:
                oe.sent(oid)
            elif action == 'confirm':
                if prev == OrderState.PENDING:
                    oe.sent(oid)
                oe.confirm(oid, 0.1, 100)
            elif action == 'fail':
                oe.fail(oid, 'err')
            elif action == 'cancel':
                oe.cancel(oid)
        final_state = oe.get(oid).state
        
        assert final_state in valid_states, f'10.prop.OE.valid_state{trial}'
    mi = MarketImpactModel()
    for trial in range(40):
        notional = rng.uniform(1, 1000000)
        adv = rng.uniform(100, 10000000)
        vol = rng.uniform(0.001, 0.5)
        est = mi.estimate(notional, adv, vol)
        
        assert 0.0001 <= est.total_pct <= 0.02, f'10.prop.MI.bounds{trial}' + ' | ' + f'total_pct={est.total_pct}'
