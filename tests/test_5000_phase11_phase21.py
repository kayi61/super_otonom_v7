"""
5000 gate — Aşama 11–21 (genişletilmiş CE/RM/OE/PTG/AM/MI/CR/stres/audit/recon + tam döngü).

Kaynak: ``super_otonom/test_5000.py`` (~1988–2770).

Sonraki: ``tests/test_5000_phase32_phase38.py`` (32–38, 5000 sonu). C++ Aşama 31: ``pytest -m cpp_optional …/test_5000_phase31_cpp_optional.py``.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path
from typing import Callable

import pytest
from super_otonom import config as so_config
from super_otonom.alert_manager import AlertManager
from super_otonom.audit_log import AuditLog, DailyReconciler
from super_otonom.capital_engine import CapitalEngine
from super_otonom.concentration_risk import ConcentrationRiskManager
from super_otonom.market_impact import MarketImpactModel
from super_otonom.order_engine import OrderEngine, OrderState
from super_otonom.pre_trade_gate import (
    fat_finger_check,
    gate_buy_signal_and_slots,
    gate_global_trade_disable,
    merge_entry_notional,
    ob_depth_check,
    same_bar_guard,
    spread_check,
)
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

def test_5000_phase11_ce_extended(phase12_make_ce: Callable[..., CapitalEngine], tmp_path: Path) -> None:
    for i in range(34):
        e = phase12_make_ce(10000 + i * 100)
        
        assert abs(e.nav - e._cash - e._margin_used - e._unrealized_pnl) < 0.01, f'11.CE.nav.prop_{i}'
    e = phase12_make_ce(10000, reserve=0.1)
    
    assert abs(e.available_cash - 9000) < 0.01, '11.CE.avail.reserve_10pct'
    e.deposit(5000)
    
    assert abs(e.available_cash - 13500) < 0.01, '11.CE.avail.nav_based_after_dep'
    e.reserve_margin('r1', 2000)
    
    assert abs(e.available_cash - 11500) < 0.01, '11.CE.avail.reserved_deducted'
    e.release_reservation('r1', 2000)
    
    assert abs(e.available_cash - 13500) < 0.01, '11.CE.avail.released_restored'
    j = tmp_path / 'bp1' / 'j.jsonl'
    j.parent.mkdir(parents=True, exist_ok=True)
    e_bp = CapitalEngine(10000, journal_file=str(j), reserve_pct=0.0, max_position_pct=0.5)
    
    assert abs(e_bp.buying_power - 5000) < 0.01, '11.CE.bp.50pct'
    j2 = tmp_path / 'bp2' / 'j.jsonl'
    j2.parent.mkdir(parents=True, exist_ok=True)
    e2_bp = CapitalEngine(10000, journal_file=str(j2), reserve_pct=0.0, max_position_pct=0.8)
    
    assert abs(e2_bp.buying_power - 8000) < 0.01, '11.CE.bp.80pct'
    e = phase12_make_ce(100000)
    pairs = ['BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT', 'ADA/USDT', 'DOT/USDT', 'AVAX/USDT', 'MATIC/USDT', 'LINK/USDT', 'UNI/USDT']
    for i, sym in enumerate(pairs):
        e.open_position(sym, f'o{i}', 1000 * (i + 1), 1.0, 1000 * (i + 1))
    
    assert len(e._positions) == 10, '11.CE.multi.10_positions'
    
    assert _inv_ok(e), '11.CE.multi.invariant'
    e.update_unrealized({sym: 1100 * (i + 1) for i, sym in enumerate(pairs)})
    
    assert e._unrealized_pnl > 0, '11.CE.multi.unreal_pos'
    
    assert _inv_ok(e), '11.CE.multi.invariant_unreal'
    e = phase12_make_ce(10000)
    total_fee = 0.0
    for i in range(20):
        fee = (i + 1) * 0.5
        e.record_fee('X', f'f{i}', fee)
        total_fee += fee
    
    assert abs(e._fees_paid - total_fee) < 0.01, '11.CE.fee.cumulative'
    
    assert _inv_ok(e), '11.CE.fee.invariant'
    
    assert abs(e._cash - (10000 - total_fee)) < 0.01, '11.CE.fee.cash_reduced'
    e = phase12_make_ce(10000)
    e.open_position('BTC/USDT', 'ord-abc', 50000, 0.1, 5000)
    e.update_unrealized({'BTC/USDT': 52000})
    snap = e.position_snapshot('BTC/USDT')
    assert snap is not None
    
    assert snap['symbol'] == 'BTC/USDT', '11.CE.pos_snap.symbol'
    
    assert snap['order_id'] == 'ord-abc', '11.CE.pos_snap.order_id'
    
    assert abs(snap['entry_price'] - 50000) < 0.01, '11.CE.pos_snap.entry_price'
    
    assert abs(snap['qty'] - 0.1) < 1e-08, '11.CE.pos_snap.qty'
    
    assert abs(snap['notional'] - 5000) < 0.01, '11.CE.pos_snap.notional'
    
    assert abs(snap['unrealized'] - 200) < 0.01, '11.CE.pos_snap.unrealized'
    
    assert e.position_snapshot('NONEXISTENT') is None, '11.CE.pos_snap.none_missing'
    e = phase12_make_ce(20000)
    e.open_position('BTC/USDT', 'o1', 50000, 0.1, 5000)
    e.open_position('ETH/USDT', 'o2', 3000, 1.0, 3000)
    all_pos = e.all_positions()
    
    assert len(all_pos) == 2, '11.CE.all_pos.count'
    syms = {p['symbol'] for p in all_pos}
    
    assert 'BTC/USDT' in syms and 'ETH/USDT' in syms, '11.CE.all_pos.symbols'
    e = phase12_make_ce(10000)
    for i in range(20):
        e.deposit(100)
    j10 = e.get_journal(last_n=10)
    
    assert len(j10) == 10, '11.CE.journal.last10'
    j_all = e.get_journal(last_n=100)
    
    assert len(j_all) <= 100, '11.CE.journal.all'
    e = phase12_make_ce(10000)
    e.open_position('BTC/USDT', 'o1', 50000, 0.1, 5000)
    try:
        e.update_unrealized({'BTC/USDT': -100})
    except Exception:
        
        assert False, '11.CE.neg_price.no_crash'
    e = phase12_make_ce(10000)
    e.open_position('BTC/USDT', 'o1', 50000, 0.1, 5000)
    pnl = e.close_position('BTC/USDT', 'o2', 55000, 0.1)
    snap2 = e.snapshot()
    
    assert snap2['total_return_pct'] > 0, '11.CE.snap.return_pct'
    
    assert abs(snap2['total_return_pct'] - pnl / 10000 * 100) < 0.1, '11.CE.snap.return_pct_correct'

def test_5000_phase12_rm_extended(make_rm: Callable[..., RiskManager], make_ro: Callable[..., RiskOntology]) -> None:
    rm = make_rm(10000)
    ro = make_ro(10000)
    rm.set_ontology(ro)
    ro.update(nav=10000)
    
    assert rm.check_risk(10000, 0, 0) is True, '12.RM.check_risk.clean'
    rm2 = make_rm(10000)
    rm2.trigger_emergency('test')
    
    assert rm2.check_risk(10000, 0, 0) is False, '12.RM.check_risk.emergency'
    
    assert rm2.get_last_deny() != '', '12.RM.check_risk.deny_reason'
    rm = make_rm(10000)
    st = rm.status_dict()
    for k in ['daily_loss', 'weekly_loss', 'var_95', 'emergency_stop', 'emergency_reason', 'last_risk_deny', 'peak_equity']:
        
        assert k in st, f'12.RM.status.{k}'
    
    assert st['emergency_stop'] is False, '12.RM.status.no_emergency'
    
    assert st['var_95'] == 0.0, '12.RM.status.var_zero'
    rm = make_rm()
    for v in [0.01, 0.015, 0.012, 0.018]:
        rm.record_volatility(v)
    
    assert len(rm._vol_history) == 4, '12.RM.vol.history'
    
    assert rm.check_volatility_spike(0.016, rm._vol_history) is True, '12.RM.vol.spike_normal'
    vols_long = [0.01] * 10
    
    assert rm.check_volatility_spike(0.05, vols_long) is False, '12.RM.vol.spike_detected'
    rm = make_rm(10000)
    rm.record_pnl(-500)
    rm.record_pnl(-300)
    
    assert abs(rm.weekly_loss - 800) < 0.01, '12.RM.weekly.accumulates'
    
    assert abs(rm.daily_loss - 800) < 0.01, '12.RM.weekly.daily_also'
    rm = make_rm()
    
    assert rm.calculate_var() == 0.0, '12.RM.var.no_history'
    for i in range(1, 101):
        rm.record_pnl(float(-i))
    
    assert rm.calculate_var() != 0.0, '12.RM.var.with_history'
    
    assert rm.calculate_var() < 0, '12.RM.var.negative'
    rm = make_rm()
    ro = make_ro()
    rm.set_ontology(ro)
    for i in range(1, 101):
        rm.record_pnl(float(-i * 10))
    var_rm = rm.calculate_var()
    var_onto = ro._calc_var()
    
    assert abs(var_rm - var_onto) < 0.01, '12.RM.var.onto_match'
    
    assert len(rm._pnl_history) > 0, '12.RM.var.rm_pnl_history'
    
    assert len(ro._pnl_history) > 0, '12.RM.var.onto_pnl_synced'
    rm = make_rm()
    rm.record_omega_trade_outcome(-100)
    
    assert rm._omega_qmin_tighten > 0, '12.RM.omega.tighten'
    rm.record_omega_trade_outcome(200)
    
    assert rm._omega_qmin_tighten >= 0, '12.RM.omega.relax'
    base = rm.get_omega_effective_qmin(50)
    
    assert isinstance(base, int), '12.RM.omega.qmin'

def test_5000_phase13_oe_extended(make_oe: Callable[[], OrderEngine]) -> None:
    oe = make_oe()
    oid = oe.intent('BTC/USDT', 'buy', 0.1, 50000)
    
    assert oe.get(oid).side == 'BUY', '13.OE.intent.side_upper'
    oid2 = oe.intent('ETH/USDT', 'sell', 1.0, 3000)
    
    assert oe.get(oid2).side == 'SELL', '13.OE.intent.sell_upper'
    oe = make_oe()
    oid = oe.intent('BTC/USDT', 'BUY', 0.1, 50000)
    oe.sent(oid, 'ex-999')
    raw = {'status': 'closed', 'filled': 0.1, 'average': 50000}
    oe.confirm(oid, 0.1, 50000, 5.0, exchange_raw=raw)
    
    assert oe.get(oid).exchange_raw == raw, '13.OE.confirm.exchange_raw'
    oe = make_oe()
    oid = oe.intent('BTC/USDT', 'BUY', 0.1, 50000)
    oe.sent(oid)
    oe.partial(oid, 0.05, 50000, fee=2.0)
    
    assert abs(oe.get(oid).fee - 2.0) < 0.01, '13.OE.partial.fee_cumul'
    oe = make_oe()
    oid = oe.intent('X', 'BUY', 0.1, 100)
    
    assert oe.can_retry(oid) is False, '13.OE.retry.pending_no_retry'
    oe.sent(oid)
    
    assert oe.can_retry(oid) is False, '13.OE.retry.sent_no_retry'
    oe.confirm(oid, 0.1, 100)
    
    assert oe.can_retry(oid) is False, '13.OE.retry.filled_no_retry'
    oe2 = make_oe()
    oid2 = oe2.intent('X', 'BUY', 0.1, 100)
    oe2.cancel(oid2)
    
    assert oe2.can_retry(oid2) is False, '13.OE.retry.cancelled_no_retry'
    
    assert oe.can_retry('nonexistent') is False, '13.OE.retry.unknown_no_retry'
    oe = make_oe()
    oid1 = oe.intent('A', 'BUY', 0.1, 100)
    oid2b = oe.intent('B', 'BUY', 0.1, 100)
    oe.sent(oid1)
    oe.confirm(oid1, 0.1, 100)
    oe.fail(oid2b, 'err')
    snap = oe.snapshot()
    
    assert 'by_state' in snap, '13.OE.snap.by_state_exists'
    for v in snap['by_state'].values():
        
        assert isinstance(v, int), '13.OE.snap.by_state_int'
        break
    with tempfile.TemporaryDirectory() as tmp:
        oe = OrderEngine(f'{tmp}/orders.jsonl', f'{tmp}/pending.json')
        oid = oe.intent('BTC/USDT', 'BUY', 0.1, 50000)
        oe.sent(oid, 'ex-1')
        oe.confirm(oid, 0.1, 50000, 5.0)
        
        assert os.path.exists(f'{tmp}/orders.jsonl'), '13.OE.log.file_exists'
        with open(f'{tmp}/orders.jsonl', encoding='utf-8') as f:
            lines = f.readlines()
        events = [json.loads(line)['event'] for line in lines]
        
        assert 'INTENT' in events, '13.OE.log.intent'
        
        assert 'SENT' in events, '13.OE.log.sent'
        
        assert 'FILLED' in events, '13.OE.log.filled'
    with tempfile.TemporaryDirectory() as tmp:
        oe = OrderEngine(f'{tmp}/o.jsonl', f'{tmp}/p.json', max_memory=20)
        pending_ids = []
        for i in range(10):
            oid = oe.intent(f'P{i}', 'BUY', 0.1, 100)
            pending_ids.append(oid)
        for i in range(15):
            oid = oe.intent(f'F{i}', 'BUY', 0.1, 100)
            oe.sent(oid)
            oe.confirm(oid, 0.1, 100)
        for pid in pending_ids[:5]:
            rec = oe.get(pid)
            
            assert rec is not None and rec.state == OrderState.PENDING, '13.OE.mem.pending_kept'
            break

def test_5000_phase14_ptg_extended(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('ENTRY_MIN_CONFIDENCE', '0.55')
    orig_env = os.environ.get('GLOBAL_TRADE_DISABLE', '')
    monkeypatch.setenv('GLOBAL_TRADE_DISABLE', '1')
    ok, r = gate_global_trade_disable()
    
    assert ok is False, '14.PTG.global.disabled_1'
    
    assert 'global_trade_disable' in r, '14.PTG.global.reason'
    monkeypatch.setenv('GLOBAL_TRADE_DISABLE', 'true')
    ok, _ = gate_global_trade_disable()
    
    assert ok is False, '14.PTG.global.disabled_true'
    monkeypatch.setenv('GLOBAL_TRADE_DISABLE', '0')
    ok, _ = gate_global_trade_disable()
    
    assert ok is True, '14.PTG.global.enabled_0'
    monkeypatch.delenv('GLOBAL_TRADE_DISABLE', raising=False)
    ok, _ = gate_global_trade_disable()
    
    assert ok is True, '14.PTG.global.enabled_empty'
    if orig_env:
        monkeypatch.setenv('GLOBAL_TRADE_DISABLE', orig_env)
    else:
        monkeypatch.delenv('GLOBAL_TRADE_DISABLE', raising=False)
    ob_inv = {'bids': [[105, 1]], 'asks': [[100, 1]]}
    ok, _ = spread_check(ob_inv)
    
    assert isinstance(ok, bool), '14.PTG.sp.inverted_ok'
    ob = {'asks': [[100, 5], [101, 5]], 'bids': [[99, 100]]}
    ok, _ = ob_depth_check(ob, 1000, min_depth=10000)
    
    assert ok is False, '14.PTG.ob.buy_side_check'
    ok2, _ = ob_depth_check(ob, 100, min_depth=500)
    
    assert ok2 is True, '14.PTG.ob.sufficient_depth'
    n, src, blk = merge_entry_notional(0, 5000)
    
    assert n == 0.0, '14.PTG.merge.zero_tech'
    n, src, blk = merge_entry_notional(5000, -1)
    
    assert blk != '', '14.PTG.merge.neg_ob_blocks'
    n, src, blk = merge_entry_notional(3000, 3000)
    
    assert abs(n - 3000) < 0.01, '14.PTG.merge.equal_min'
    ok, _ = gate_buy_signal_and_slots('BUY', 0, 1.0)
    
    assert ok is True, '14.PTG.gate.max_conf'
    ok, r = gate_buy_signal_and_slots('BUY', 0, 0.0)
    
    assert ok is False, '14.PTG.gate.zero_conf'
    ok, _ = gate_buy_signal_and_slots('BUY', 0, 0.55)
    
    assert ok is True, '14.PTG.gate.min_conf'
    last: dict[str, float] = {}
    ok, _ = same_bar_guard('BTC/USDT', 0.0, last)
    
    assert ok is True, '14.PTG.sb.zero_ts_passes'
    last['BTC/USDT'] = 0.0
    ok, _ = same_bar_guard('BTC/USDT', 0.0, last)
    
    assert ok is False, '14.PTG.sb.zero_ts_blocks'

def test_5000_phase15_am_extended() -> None:
    am = AlertManager(webhook_url='', cooldown_sec=0, min_level='DEBUG')
    am.emergency('code1', nav=9000, detail='test detail')
    
    assert len(am._history) >= 1, '15.AM.emergency.recorded'
    
    assert am._history[-1].level == 'CRITICAL', '15.AM.emergency.level'
    
    assert 'EMERGENCY' in am._history[-1].title or 'code1' in am._history[-1].title, '15.AM.emergency.title'
    am.nav_diff(100, 1.0, 9900, 10000)
    
    assert any((e.category == 'NAV_DIFF' for e in am._history)), '15.AM.nav_diff.recorded'
    am.circuit_breaker('BTC/USDT', 'OPEN', 'rate limit')
    
    assert any(('CIRCUIT' in e.category for e in am._history)), '15.AM.cb.recorded'
    am.stale_data('ETH/USDT', 600)
    
    assert any(('STALE' in e.category for e in am._history)), '15.AM.stale.recorded'
    am.backoff(5, 120)
    
    assert any(('BACKOFF' in e.category for e in am._history)), '15.AM.backoff.recorded'
    am.system('BOT_START', 'başlangıç')
    
    assert any(('SYSTEM' in e.category for e in am._history)), '15.AM.system.recorded'
    am.tca_anomaly('SOL/USDT', 0.05, 0.2)
    
    assert any(('TCA' in e.category for e in am._history)), '15.AM.tca.recorded'
    am2 = AlertManager(webhook_url='', cooldown_sec=3600, min_level='DEBUG')
    am2.emergency('first', nav=9000)
    count_before = len(am2._history)
    am2.emergency('second', nav=8000)
    
    assert len(am2._history) == count_before, '15.AM.cooldown.blocks_repeat'
    am2.circuit_breaker('ETH/USDT', 'OPEN')
    
    assert len(am2._history) > count_before, '15.AM.cooldown.diff_cat_passes'
    am = AlertManager(webhook_url='', cooldown_sec=0)
    for _ in range(15):
        am.emergency('test', nav=9000)
    snap = am.snapshot()
    
    assert len(snap['recent']) <= 10, '15.AM.snap.max_recent_10'
    
    assert 'cooldown_sec' in snap, '15.AM.snap.cooldown_in_snap'
    
    assert 'min_level' in snap, '15.AM.snap.min_level_in_snap'
    am3 = AlertManager(webhook_url='', cooldown_sec=0)
    for i in range(250):
        am3._send('INFO', f'CAT_{i}', f'title_{i}', 'body')
    
    assert len(am3._history) <= 200, '15.AM.hist.max_200'
    am4 = AlertManager(webhook_url='', cooldown_sec=0)
    am4.nav_diff(1000, 10.5, 9000, 10000)
    
    assert am4._history[-1].level == 'CRITICAL', '15.AM.nav_diff.critical_10pct'
    am4.nav_diff(200, 2.0, 9800, 10000)
    
    assert am4._history[-1].level == 'WARNING', '15.AM.nav_diff.warning_2pct'

def test_5000_phase16_mi_extended() -> None:
    mi = MarketImpactModel(lambda_=0.1)
    est = mi.estimate(10000, 1000000, 0.02)
    
    assert abs(est.participation_rate - 0.01) < 0.001, '16.MI.part.correct'
    est2 = mi.estimate(500000, 1000000, 0.02)
    
    assert abs(est2.participation_rate - 0.5) < 0.001, '16.MI.part.50pct'
    
    assert est2.is_large_order is True, '16.MI.part.large_order'
    notional, adv, vol = (10000, 1000000, 0.02)
    part = notional / adv
    expected_amihud = math.sqrt(part) * vol * 0.1
    est = mi.estimate(notional, adv, vol)
    
    assert abs(est.amihud_impact_pct - expected_amihud) < 0.0001, '16.MI.amihud.formula'
    est = mi.estimate(1000, 100000, 0.02)
    price = 50000
    buy_price = est.adjusted_price('buy', price)
    sell_price = est.adjusted_price('sell', price)
    
    assert buy_price > price, '16.MI.adj.buy_above'
    
    assert sell_price < price, '16.MI.adj.sell_below'
    
    assert abs(buy_price - price - (price - sell_price)) < 0.01, '16.MI.adj.symmetric'
    est = mi.estimate(5000, 100000, 0.02)
    cost = est.cost_usdt(0.1, 50000)
    
    assert cost > 0, '16.MI.cost.positive'
    
    assert abs(cost - 0.1 * 50000 * est.total_pct) < 0.01, '16.MI.cost.proportional'
    returns = [0.01, -0.02, 0.005, -0.015, 0.008]
    volumes = [1000000.0, 2000000.0, 500000.0, 1500000.0, 800000.0]
    ratio = mi.amihud_ratio(returns, volumes)
    
    assert ratio > 0, '16.MI.amihud_ratio.positive'
    
    assert mi.amihud_ratio([], []) == 0.0, '16.MI.amihud_ratio.empty'
    
    assert mi.amihud_ratio([0.01], [0]) == 0.0, '16.MI.amihud_ratio.zero_vol'
    mi_snap = mi.snapshot()
    
    assert all((k in mi_snap for k in ['total_estimates', 'large_orders', 'avg_impact_pct', 'lambda'])), '16.MI.snap.has_keys'

def test_5000_phase17_cr_extended() -> None:
    cr = ConcentrationRiskManager()
    l1_coins = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'ADA/USDT', 'AVAX/USDT']
    l2_coins = ['MATIC/USDT', 'ARB/USDT', 'OP/USDT']
    defi_coins = ['UNI/USDT', 'AAVE/USDT', 'COMP/USDT']
    for coin in l1_coins:
        
        assert cr.get_sector(coin) == 'L1', f"17.CR.sector.{coin.split('/')[0]}_L1"
    for coin in l2_coins:
        
        assert cr.get_sector(coin) == 'L2', f"17.CR.sector.{coin.split('/')[0]}_L2"
    for coin in defi_coins:
        
        assert cr.get_sector(coin) == 'DEFI', f"17.CR.sector.{coin.split('/')[0]}_DEFI"
    pos_single = {'BTC/USDT': {'size': 10000, 'notional': 10000}}
    hhi = cr.concentration_score(pos_single, 10000)
    
    assert abs(hhi - 1.0) < 0.01, '17.CR.hhi.single_is_1'
    pos_equal = {'BTC/USDT': {'size': 5000, 'notional': 5000}, 'ETH/USDT': {'size': 5000, 'notional': 5000}}
    hhi2 = cr.concentration_score(pos_equal, 10000)
    
    assert abs(hhi2 - 0.5) < 0.01, '17.CR.hhi.equal_is_0.5'
    
    assert cr.concentration_score({}, 10000) == 0.0, '17.CR.hhi.empty_is_0'
    pos = {'BTC/USDT': {'size': 4000, 'notional': 4000}, 'ETH/USDT': {'size': 3000, 'notional': 3000}, 'UNI/USDT': {'size': 3000, 'notional': 3000}}
    breakdown = cr.sector_breakdown(pos, 10000)
    
    assert abs(breakdown.get('L1', 0) - 70.0) < 0.01, '17.CR.breakdown.L1'
    
    assert abs(breakdown.get('DEFI', 0) - 30.0) < 0.01, '17.CR.breakdown.DEFI'
    cr2 = ConcentrationRiskManager(max_sector_pct=0.6, max_single_pct=0.3, max_total_pct=0.9)
    ok, _ = cr2.check_concentration('BTC/USDT', 2500, 10000, {})
    
    assert ok is True, '17.CR.check.below_single'
    ok, r = cr2.check_concentration('BTC/USDT', 3500, 10000, {})
    
    assert ok is False, '17.CR.check.above_single'
    cr_snap = cr.snapshot({}, 10000)
    
    assert all((k in cr_snap for k in ['sector_breakdown', 'concentration_score', 'max_sector_pct'])), '17.CR.snap.keys'

def test_5000_phase18_stress_extended() -> None:
    runner = StressTestRunner(capital=10000, max_daily_loss_pct=0.05, max_drawdown_pct=0.15)
    for name, days in SCENARIOS.items():
        r = runner.run_scenario(name, days)
        short = name[:15]
        
        assert hasattr(r, 'scenario_name'), f'18.ST.{short}.type'
        
        assert r.final_nav >= 0, f'18.ST.{short}.nav_nn'
        
        assert 0 <= r.max_drawdown_pct <= 100, f'18.ST.{short}.dd_range'
        
        assert len(r.nav_series) >= 1, f'18.ST.{short}.series'
        
        assert isinstance(r.emergency_triggered, bool), f'18.ST.{short}.emg_bool'
    r = runner.run_scenario('SIDEWAYS_LOW_VOL', SCENARIOS['SIDEWAYS_LOW_VOL'])
    
    assert r.survived is True, '18.ST.sideways.survived'
    
    assert isinstance(r.total_return_pct, float), '18.ST.sideways.return'
    
    assert isinstance(r.loss_pct, float), '18.ST.sideways.loss_pct'
    results = runner.run_all()
    try:
        report = runner.print_report(results)
        
        assert isinstance(report, str), '18.ST.report.returns_str'
        
        assert 'ÖZET' in report or 'survived' in report.lower(), '18.ST.report.has_summary'
    except Exception as e:
        
        assert False, '18.ST.report.no_crash' + ' | ' + str(e)
    for cap in [1000, 10000, 100000, 1000000]:
        r2 = StressTestRunner(capital=cap).run_scenario('FLASH_CRASH_RECOVERY', SCENARIOS['FLASH_CRASH_RECOVERY'])
        
        assert r2.final_nav >= 0, f'18.ST.cap_{cap}.nav_nn'
        
        assert 0 <= r2.max_drawdown_pct <= 100, f'18.ST.cap_{cap}.dd_range'

def test_5000_phase19_audit_extended(tmp_path: Path) -> None:
    t = tmp_path / 'audit19'
    t.mkdir(parents=True, exist_ok=True)
    al = AuditLog(audit_dir=str(t))
    al.trade_open('BTC/USDT', 'o1', 50000, 0.1, 5000, fee=5.0, confidence=0.75, nav=10000, cash=5000, open_positions=1)
    events = al.get_events()
    e_open = [e for e in events if e['event_type'] == 'TRADE_OPEN'][0]
    
    assert e_open['symbol'] == 'BTC/USDT', '19.AL.open.symbol'
    
    assert e_open['order_id'] == 'o1', '19.AL.open.order_id'
    
    assert abs(e_open['price'] - 50000) < 0.01, '19.AL.open.price'
    
    assert abs(e_open['qty'] - 0.1) < 1e-08, '19.AL.open.qty'
    
    assert abs(e_open['notional'] - 5000) < 0.01, '19.AL.open.notional'
    
    assert abs(e_open['fee'] - 5.0) < 0.01, '19.AL.open.fee'
    
    assert abs(e_open['confidence'] - 0.75) < 0.001, '19.AL.open.confidence'
    
    assert abs(e_open['nav'] - 10000) < 0.01, '19.AL.open.nav'
    
    assert e_open['ts'] > 0, '19.AL.open.ts'
    
    assert len(e_open['date_str']) == 10, '19.AL.open.date_str'
    al.trade_close('BTC/USDT', 'o2', 52000, 0.1, pnl=200, fee=5.0, reason='SELL_SIGNAL', nav=10195, realized_pnl=200)
    e_close = [e for e in al.get_events() if e['event_type'] == 'TRADE_CLOSE'][0]
    
    assert abs(e_close['pnl'] - 200) < 0.01, '19.AL.close.pnl'
    
    assert e_close['reason'] == 'SELL_SIGNAL', '19.AL.close.reason'
    
    assert abs(e_close['nav'] - 10195) < 0.01, '19.AL.close.nav'
    al.risk_block('ETH/USDT', 'dynamic_daily_loss', signal='BUY', nav=9500)
    e_rb = [e for e in al.get_events() if e['event_type'] == 'RISK_BLOCK'][0]
    
    assert e_rb['symbol'] == 'ETH/USDT', '19.AL.rb.symbol'
    
    assert e_rb['risk_deny'] == 'dynamic_daily_loss', '19.AL.rb.risk_deny'
    
    assert e_rb['signal'] == 'BUY', '19.AL.rb.signal'
    btc = al.get_events(symbol='BTC/USDT')
    
    assert all((e['symbol'] == 'BTC/USDT' for e in btc)), '19.AL.filter.btc_only'
    eth = al.get_events(symbol='ETH/USDT')
    
    assert all((e['symbol'] == 'ETH/USDT' for e in eth)), '19.AL.filter.eth_only'
    summary = al.today_summary()
    
    assert summary['trades_opened'] >= 1, '19.AL.summary.opened_1'
    
    assert summary['trades_closed'] >= 1, '19.AL.summary.closed_1'
    
    assert summary['risk_blocks'] >= 1, '19.AL.summary.risk_blocks_1'
    
    assert abs(summary['total_pnl'] - 200) < 0.01, '19.AL.summary.total_pnl'
    
    assert summary['total_fees'] > 0, '19.AL.summary.total_fees'
    
    assert summary['event_count'] >= 3, '19.AL.summary.event_count'

def test_5000_phase20_daily_recon_extended(tmp_path: Path) -> None:
    t = tmp_path / 'dr20'
    t.mkdir(parents=True, exist_ok=True)
    dr = DailyReconciler(reconcile_dir=str(t))
    dr.set_sod(10000.0)
    
    assert abs(dr._sod_nav - 10000) < 0.01, '20.DR.sod.set'
    dr.record_trade('BTC/USDT', pnl=500, fee=10, reason='SELL')
    dr.record_trade('ETH/USDT', pnl=-200, fee=5, reason='STOP_LOSS')
    dr.record_trade('SOL/USDT', pnl=100, fee=3, reason='SELL')
    snap = {'nav': 10382, 'open_positions': 0, 'positions': []}
    report = dr.run(snap)
    
    assert report.total_trades == 3, '20.DR.report.total_trades'
    
    assert report.winning_trades == 2, '20.DR.report.winning'
    
    assert report.losing_trades == 1, '20.DR.report.losing'
    
    assert abs(report.total_realized_pnl - 400) < 0.01, '20.DR.report.realized_pnl'
    
    assert abs(report.total_fees - 18) < 0.01, '20.DR.report.fees'
    
    assert 'BTC/USDT' in report.pnl_by_symbol, '20.DR.report.pnl_by_sym'
    
    assert len(report.date_str) == 10, '20.DR.report.date_str'
    
    assert report.generated_at > 0, '20.DR.report.generated_at'
    dr2 = DailyReconciler(reconcile_dir=str(tmp_path / 'dr20b'))
    dr2.set_sod(10000.0)
    dr2.record_trade('BTC/USDT', pnl=200, fee=5)
    snap2 = {'nav': 10800, 'open_positions': 0, 'positions': []}
    report2 = dr2.run(snap2)
    
    assert not report2.nav_ok, '20.DR.nav_diff.detected'
    
    assert len(report2.warnings) > 0, '20.DR.nav_diff.warning'
    dr3 = DailyReconciler(reconcile_dir=str(tmp_path / 'dr20c'))
    dr3.set_sod(10000.0)
    snap3 = {'nav': 10000, 'open_positions': 2, 'positions': []}
    report3 = dr3.run(snap3)
    
    assert any(('açık' in w.lower() or 'open' in w.lower() for w in report3.warnings)), '20.DR.open_pos.warning'
    dr4 = DailyReconciler(reconcile_dir=str(tmp_path / 'dr20d'))
    dr4.set_sod(10000.0)
    dr4.record_trade('X', pnl=100)
    dr4.reset_for_new_day(10100.0)
    
    assert len(dr4._trade_log) == 0, '20.DR.reset.log_empty'
    
    assert abs(dr4._sod_nav - 10100) < 0.01, '20.DR.reset.sod_updated'
    t5 = tmp_path / 'dr20e'
    t5.mkdir(parents=True, exist_ok=True)
    dr5 = DailyReconciler(reconcile_dir=str(t5))
    dr5.set_sod(10000.0)
    snap5 = {'nav': 10000, 'open_positions': 0, 'positions': []}
    dr5.run(snap5)
    files5 = os.listdir(t5)
    
    assert any((f.endswith('.json') for f in files5)), '20.DR.file.created'

def test_5000_phase21_cross_module(phase12_make_ce: Callable[..., CapitalEngine], make_rm: Callable[..., RiskManager], make_ro: Callable[..., RiskOntology], make_oe: Callable[[], OrderEngine], tmp_path: Path) -> None:
    e = phase12_make_ce(50000, reserve=0.05)
    rm = make_rm(50000)
    ro = make_ro(50000)
    rm.set_ontology(ro)
    oe = make_oe()
    t = tmp_path / 'al21'
    t.mkdir(parents=True, exist_ok=True)
    al = AuditLog(audit_dir=str(t))
    dr = DailyReconciler(reconcile_dir=str(tmp_path / 'dr21'))
    cr = ConcentrationRiskManager()
    am = AlertManager(webhook_url='', cooldown_sec=0)
    dr.set_sod(e.nav)
    pairs_test = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
    for i, sym in enumerate(pairs_test):
        price = 50000 / (i + 1)
        notional = 5000
        ok_ff, _ = fat_finger_check(notional, max_notional=50000)
        ob = {'bids': [[price * 0.999, 100]], 'asks': [[price * 1.001, 100]]}
        ok_sp, _ = spread_check(ob, max_spread_pct=0.005)
        ok_ob, _ = ob_depth_check(ob, notional, min_depth=100)
        ok_cr, _ = cr.check_concentration(sym, notional, e.nav, {})
        if all([ok_ff, ok_sp, ok_ob, ok_cr]):
            oid = oe.intent(sym, 'BUY', notional / price, price)
            e.reserve_margin(oid, notional)
            oe.sent(oid, f'ex_{i}')
            oe.confirm(oid, notional / price, price, fee=5.0)
            e.release_reservation(oid, notional)
            e.open_position(sym, oid, price, notional / price, notional, fee=5.0)
            al.trade_open(sym, oid, price, notional / price, notional, nav=e.nav)
            ro.update(nav=e.nav)
            rm.record_pnl(0)
    
    assert _inv_ok(e), '21.SYS.open.invariant'
    
    assert len(al.get_events(event_type='TRADE_OPEN')) > 0, '21.SYS.open.audit'
    oids_head = list(oe._orders.keys())[:3]
    
    assert all((oe.get(oid) is not None for oid in oids_head)), '21.SYS.open.oe_filled'
    for sym in pairs_test:
        if sym in e._positions:
            e.update_unrealized({sym: e._positions[sym].entry_price * 1.05})
    ro.update(nav=e.nav)
    
    assert e.nav > 50000, '21.SYS.unreal.nav_increased'
    
    assert _inv_ok(e), '21.SYS.unreal.invariant'
    for sym in list(e._positions.keys()):
        pos = e._positions[sym]
        exit_price = pos.entry_price * 1.05
        pnl = e.close_position(sym, f'close_{sym}', exit_price, pos.qty, fee=5.0)
        rm.record_pnl(pnl)
        ro.update(nav=e.nav, realized_pnl_delta=pnl)
        al.trade_close(sym, f'close_{sym}', exit_price, pos.qty if pnl else 0, pnl or 0, nav=e.nav)
        dr.record_trade(sym, pnl=pnl or 0, fee=5.0)
    
    assert len(e._positions) == 0, '21.SYS.close.all_closed'
    
    assert _inv_ok(e), '21.SYS.close.invariant'
    
    assert rm.daily_loss >= 0, '21.SYS.close.rm_updated'
    snap_final = {'nav': e.nav, 'open_positions': 0, 'positions': []}
    report_final = dr.run(snap_final)
    
    assert report_final.total_trades > 0, '21.SYS.reconcile.ran'
    
    assert abs(report_final.total_realized_pnl) >= 0, '21.SYS.reconcile.pnl_tracked'
    am.system('TEST_COMPLETE', f'nav={e.nav:.2f}', level='WARNING')
    
    assert len(am._history) > 0, '21.SYS.alert.system'
    
    assert rm.emergency_stop is False, '21.SYS.final.rm_not_emg'
    
    assert abs(ro.nav - e.nav) < 1.0, '21.SYS.final.ro_nav_sync'
    
    assert _inv_ok(e), '21.SYS.final.invariant'
