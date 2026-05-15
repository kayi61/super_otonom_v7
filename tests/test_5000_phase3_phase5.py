"""
5000 gate — Aşama 3–5 (RiskOntology + RiskManager, OrderEngine + Recon, PTG + Alert).

Kaynak: ``super_otonom/test_5000.py`` (~676–1270).
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock

import pytest
from super_otonom import config as so_config
from super_otonom.alert_manager import AlertManager
from super_otonom.order_engine import OrderEngine, OrderState
from super_otonom.pre_trade_gate import (
    fat_finger_check,
    gate_buy_signal_and_slots,
    merge_entry_notional,
    ob_depth_check,
    same_bar_guard,
    spread_check,
)
from super_otonom.reconciliation_engine import ReconciliationEngine
from super_otonom.risk_manager import RiskManager
from super_otonom.risk_ontology import RiskOntology

pytestmark = pytest.mark.fastrun

@pytest.fixture(scope='module', autouse=True)
def _legacy_risk_trailing_stop_pct() -> None:
    """``super_otonom/test_5000.py`` injects ``trailing_stop_pct`` 0.02; package default is higher."""
    prev = so_config.RISK.get('trailing_stop_pct')
    so_config.RISK['trailing_stop_pct'] = 0.02
    yield
    if prev is not None:
        so_config.RISK['trailing_stop_pct'] = prev

@pytest.fixture(autouse=True)
def _alert_webhook_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """``AlertManager(webhook_url="")`` ile bile config webhook kullanılmasın."""
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

async def _run_startup(nav: float, ex_nav: float, tmp: Path) -> tuple[Any, ReconciliationEngine]:
    oe_m = MagicMock()
    oe_m.recover = AsyncMock(return_value=[])
    recon, _cap = _make_recon(nav, tmp, oe_m)
    handler = _make_handler(ex_nav)
    result = await recon.startup_handshake(handler)
    return (result, recon)

def test_5000_phase3_risk_ontology_and_manager(make_ro: Callable[..., RiskOntology], make_rm: Callable[..., RiskManager]) -> None:
    ro = make_ro(10000)
    
    assert abs(ro.nav - 10000) < 0.01, '3.RO.init.nav'
    
    assert abs(ro.sod_nav - 10000) < 0.01, '3.RO.init.sod_nav'
    
    assert abs(ro.sow_nav - 10000) < 0.01, '3.RO.init.sow_nav'
    
    assert abs(ro.peak_nav - 10000) < 0.01, '3.RO.init.peak_nav'
    
    assert abs(ro.intraday_dd_pct) < 0.001, '3.RO.init.dd_zero'
    
    assert abs(ro.daily_loss_pct) < 0.001, '3.RO.init.daily_loss_zero'
    
    assert abs(ro.weekly_loss_pct) < 0.001, '3.RO.init.weekly_loss_zero'
    
    assert abs(ro.gross_exp) < 0.01, '3.RO.init.gross_exp_zero'
    
    assert ro.var_1d == 0.0, '3.RO.init.var_zero'
    ro = make_ro(10000)
    ro.update(nav=10000)
    ro.update(nav=9000)
    
    assert abs(ro.daily_loss_pct - 0.1) < 0.01, '3.RO.update.daily_loss'
    
    assert abs(ro.peak_nav - 10000) < 0.01, '3.RO.update.peak_nav'
    
    assert abs(ro.intraday_dd_pct - 0.1) < 0.01, '3.RO.update.dd_correct'
    ro.update(nav=11000)
    
    assert abs(ro.peak_nav - 11000) < 0.01, '3.RO.update.peak_updated'
    
    assert abs(ro.intraday_dd_pct) < 0.01, '3.RO.update.dd_zero_new_peak'
    ro = make_ro(10000)
    ro.update(nav=10000)
    ro.update(nav=12000)
    
    assert ro.daily_loss_pct >= 0.0, '3.RO.update.daily_loss_no_neg'
    ro = make_ro(10000)
    ro.update(nav=12000)
    ro._day_start = time.time() - 90000
    ro.update(nav=12500)
    
    assert abs(ro.sod_nav - 12500) < 0.01, '3.RO.timing.sod_nav_correct'
    ro = make_ro(10000)
    for i in range(1, 100):
        ro.update(nav=10000, realized_pnl_delta=float(-i * 10))
    
    assert ro.var_1d == 0.0, '3.RO.var.zero_below_100'
    ro.update(nav=10000, realized_pnl_delta=-1000.0)
    
    assert ro.var_1d != 0.0, '3.RO.var.nonzero_at_100'
    ro = make_ro(10000)
    for i in range(1, 201):
        ro.update(nav=10000, realized_pnl_delta=-float(i * 10))
    
    assert ro.var_1d < 0, '3.RO.var.negative_value'
    ro = make_ro(10000)
    positions = {'BTC/USDT': {'entry': 50000, 'qty': 0.1}, 'ETH/USDT': {'entry': 3000, 'qty': 1.0}}
    ro.update(nav=10000, positions=positions)
    
    assert ro.gross_exp > 0, '3.RO.exposure.gross_exp'
    
    assert ro.exp_pct > 0, '3.RO.exposure.exp_pct'
    
    assert abs(ro.gross_exp - ro.net_exp) < 0.01, '3.RO.exposure.long_only'
    ro = make_ro(10000)
    ro.update(nav=10000, current_vol=0.001)
    
    assert ro.dynamic_daily_limit >= 0.02, '3.RO.dynlim.min_2pct'
    ro.update(nav=10000, current_vol=0.1)
    
    assert ro.dynamic_daily_limit <= 0.05, '3.RO.dynlim.max_5pct'
    ro.update(nav=10000, current_vol=0.015)
    
    assert 0.02 <= ro.dynamic_daily_limit <= 0.05, '3.RO.dynlim.mid'
    ro = make_ro(10000)
    ro.update(nav=10000)
    ro.dynamic_daily_limit = 0.03
    ro.update(nav=9600)
    
    assert ro.is_daily_limit_breached(), '3.RO.breach.daily_triggered'
    ro2 = make_ro(10000)
    ro2.update(nav=10000)
    ro2.update(nav=8400)
    
    assert ro2.is_drawdown_breached(0.15), '3.RO.breach.drawdown_triggered'
    
    assert not ro2.is_drawdown_breached(0.2), '3.RO.breach.drawdown_not_mild'
    ro3 = make_ro(10000)
    positions = {'BTC/USDT': {'entry': 50000, 'qty': 0.2}}
    ro3.update(nav=10000, positions=positions)
    
    assert ro3.is_exposure_breached(0.9), '3.RO.breach.exposure'
    ro = make_ro(10000)
    ro.update(nav=10500)
    ro.update(nav=10000, current_vol=0.02)
    d = ro.to_dict()
    ro2 = RiskOntology.from_dict(d)
    
    assert abs(ro2.nav - ro.nav) < 0.01, '3.RO.serial.nav'
    
    assert abs(ro2.sod_nav - ro.sod_nav) < 0.01, '3.RO.serial.sod_nav'
    
    assert abs(ro2.peak_nav - ro.peak_nav) < 0.01, '3.RO.serial.peak_nav'
    
    assert abs(ro2.dynamic_daily_limit - ro.dynamic_daily_limit) < 0.001, '3.RO.serial.dyn_limit'
    for k in ['initial_nav', 'nav', 'sod_nav', 'sow_nav', 'peak_nav', 'dynamic_daily_limit']:
        
        assert k in d, f'3.RO.serial.key_{k}'
    snap = ro.snapshot()
    for k in ['nav', 'sod_nav', 'sow_nav', 'peak_nav', 'intraday_dd_pct', 'daily_loss_pct', 'weekly_loss_pct', 'dynamic_daily_limit', 'gross_exp', 'net_exp', 'exp_pct', 'var_1d']:
        
        assert k in snap, f'3.RO.snap.{k}'
    rm = make_rm()
    
    assert rm.emergency_stop is False, '3.RM.init.no_emergency'
    
    assert rm.emergency_reason is None, '3.RM.init.no_reason'
    
    assert abs(rm.daily_loss) < 0.01, '3.RM.init.daily_loss_zero'
    
    assert abs(rm.weekly_loss) < 0.01, '3.RM.init.weekly_loss_zero'
    
    assert rm._onto is None, '3.RM.init.onto_none'
    rm = make_rm()
    rm.trigger_emergency('test_code')
    
    assert rm.emergency_stop is True, '3.RM.emg.triggered'
    
    assert rm.emergency_reason == 'test_code', '3.RM.emg.reason'
    
    assert rm.check_risk(10000, 0, 0) is False, '3.RM.emg.check_risk_false'
    rm.reset_emergency()
    
    assert rm.emergency_stop is False, '3.RM.emg.reset'
    
    assert rm.emergency_reason is None, '3.RM.emg.reason_none'
    rm2 = make_rm()
    rm2.trigger_emergency('silent_test', silent=True)
    
    assert rm2.emergency_stop is True, '3.RM.emg.silent_still_triggers'
    rm = make_rm()
    rm.record_pnl(-100)
    rm.record_pnl(-200)
    
    assert abs(rm.daily_loss - 300) < 0.01, '3.RM.pnl.daily_loss'
    
    assert abs(rm.weekly_loss - 300) < 0.01, '3.RM.pnl.weekly_loss'
    rm.record_pnl(500)
    
    assert abs(rm.daily_loss - 300) < 0.01, '3.RM.pnl.profit_no_loss'
    rm = make_rm()
    ro = make_ro()
    rm.set_ontology(ro)
    rm.record_pnl(-50)
    
    assert len(ro._pnl_history) > 0, '3.RM.pnl.onto_synced'
    rm = make_rm(10000)
    rm.daily_loss = 300.0
    
    assert rm.check_dynamic_risk(10000, 0.02) is True, '3.RM.dyn.ok_below'
    rm2 = make_rm(10000)
    rm2.daily_loss = 500.0
    
    assert rm2.check_dynamic_risk(10000, 0.02) is False, '3.RM.dyn.blocks_above'
    rm3 = make_rm(10000)
    rm3.daily_loss = 800.0
    result = rm3.check_dynamic_risk(20000, 0.02)
    
    assert result is False, '3.RM.dyn.equity_denominator'
    rm4 = make_rm(10000)
    rm4.daily_loss = 100.0
    
    assert rm4.check_dynamic_risk(10000, 0.001) is True, '3.RM.dyn.clamp_low'
    rm = make_rm()
    
    assert rm.should_trailing_stop(100, 102, 105) is True, '3.RM.trail.triggers'
    
    assert rm.should_trailing_stop(100, 104, 105) is False, '3.RM.trail.no_trigger'
    
    assert rm.should_trailing_stop(100, 100, 100) is False, '3.RM.trail.no_trigger_flat'
    rm = make_rm()
    ro = make_ro()
    rm.set_ontology(ro)
    for i in range(1, 101):
        rm.record_pnl(float(-i * 10))
    var_rm = rm.calculate_var()
    var_onto = ro._calc_var()
    
    assert abs(var_rm - var_onto) < 0.01, '3.RM.var.uses_onto'
    
    assert var_rm < 0, '3.RM.var.negative'
    rm2 = make_rm()
    
    assert rm2.calculate_var() == 0.0, '3.RM.var.zero_no_history'
    rm = make_rm()
    rm._warn_if_onto_missing()
    
    assert rm._onto_warned is True, '3.RM.warn.warned_flag'
    rm._warn_if_onto_missing()
    
    assert rm._onto_warned is True, '3.RM.warn.only_once'
    rm = make_rm()
    vols = [0.01] * 20
    
    assert rm.check_volatility_spike(0.01, vols) is True, '3.RM.volspike.normal'
    
    assert rm.check_volatility_spike(0.05, vols) is False, '3.RM.volspike.spike'
    
    assert rm.check_volatility_spike(0.05, [0.01]) is True, '3.RM.volspike.min_history'

def test_5000_phase4_order_engine_and_reconciliation(make_oe: Callable[[], OrderEngine], tmp_path: Path) -> None:
    oe = make_oe()
    oid = oe.intent('BTC/USDT', 'BUY', 0.1, 50000)
    
    assert isinstance(oid, str), '4.OE.intent.returns_str'
    
    assert oid.startswith('so_'), '4.OE.intent.prefix_so'
    
    assert len(oid) > 10, '4.OE.intent.length'
    
    assert oe.get(oid).state == OrderState.PENDING, '4.OE.intent.state_pending'
    
    assert oe.get(oid).symbol == 'BTC/USDT', '4.OE.intent.symbol'
    
    assert oe.get(oid).side == 'BUY', '4.OE.intent.side'
    
    assert abs(oe.get(oid).qty - 0.1) < 1e-08, '4.OE.intent.qty'
    
    assert abs(oe.get(oid).price - 50000) < 0.01, '4.OE.intent.price'
    
    assert abs(oe.get(oid).notional - 5000) < 0.01, '4.OE.intent.notional'
    
    assert oe.get(oid).created_at > 0, '4.OE.intent.created_at'
    oe2 = make_oe()
    ids = {oe2.intent('X', 'BUY', 0.1, 100) for _ in range(200)}
    
    assert len(ids) == 200, '4.OE.intent.200_unique'
    oe = make_oe()
    oid = oe.intent('BTC/USDT', 'BUY', 0.1, 50000)
    oe.sent(oid, 'ex-123')
    
    assert oe.get(oid).state == OrderState.SENT, '4.OE.sent.state'
    
    assert oe.get(oid).exchange_order_id == 'ex-123', '4.OE.sent.exchange_id'
    oe.confirm(oid, 0.1, 50100, 5.0)
    
    assert oe.get(oid).state == OrderState.FILLED, '4.OE.confirm.state'
    
    assert abs(oe.get(oid).filled_qty - 0.1) < 1e-08, '4.OE.confirm.filled_qty'
    
    assert abs(oe.get(oid).fill_price - 50100) < 0.01, '4.OE.confirm.fill_price'
    
    assert abs(oe.get(oid).fee - 5.0) < 0.01, '4.OE.confirm.fee'
    ok = oe.confirm(oid, 0.1, 50100, 5.0)
    
    assert ok is True, '4.OE.confirm.idempotent'
    
    assert oe.get(oid).state == OrderState.FILLED, '4.OE.confirm.state_unchanged'
    oe2 = make_oe()
    oid2 = oe2.intent('ETH/USDT', 'BUY', 1.0, 3000)
    oe2.fail(oid2, 'timeout')
    
    assert oe2.get(oid2).state == OrderState.FAILED, '4.OE.fail.state'
    
    assert oe2.get(oid2).retry_count == 1, '4.OE.fail.retry_count'
    
    assert 'timeout' in oe2.get(oid2).error_msg, '4.OE.fail.error_msg'
    oe3 = make_oe()
    oid3 = oe3.intent('SOL/USDT', 'BUY', 5.0, 100)
    oe3.cancel(oid3, 'stale')
    
    assert oe3.get(oid3).state == OrderState.CANCELLED, '4.OE.cancel.state'
    oe4 = make_oe()
    oid4 = oe4.intent('BTC/USDT', 'BUY', 0.1, 50000)
    oe4.sent(oid4)
    oe4.partial(oid4, 0.05, 50000, 2.0)
    
    assert oe4.get(oid4).state == OrderState.PARTIAL, '4.OE.partial.state'
    
    assert abs(oe4.get(oid4).filled_qty - 0.05) < 1e-08, '4.OE.partial.filled_qty'
    oe = make_oe()
    oid = oe.intent('BTC/USDT', 'BUY', 0.1, 50000)
    
    assert oe.is_duplicate(oid) is False, '4.OE.dup.pending_not_dup'
    oe.sent(oid)
    
    assert oe.is_duplicate(oid) is True, '4.OE.dup.sent_is_dup'
    oe.confirm(oid, 0.1, 50000)
    
    assert oe.is_duplicate(oid) is True, '4.OE.dup.filled_is_dup'
    oe2 = make_oe()
    oid2 = oe2.intent('ETH/USDT', 'BUY', 1.0, 3000)
    oe2.fail(oid2, 'err')
    
    assert oe2.is_duplicate(oid2) is False, '4.OE.dup.failed_not_dup'
    
    assert oe.is_duplicate('nonexistent') is False, '4.OE.dup.unknown_not_dup'
    oe = make_oe()
    oid = oe.intent('BTC/USDT', 'BUY', 0.1, 50000)
    oe.fail(oid, 't1')
    
    assert oe.can_retry(oid) is True, '4.OE.retry.can_retry_1'
    oe.fail(oid, 't2')
    
    assert oe.can_retry(oid) is True, '4.OE.retry.can_retry_2'
    oe.fail(oid, 't3')
    
    assert oe.can_retry(oid) is False, '4.OE.retry.no_retry_max'
    
    assert oe.get(oid).retry_count == 3, '4.OE.retry.retry_count_3'
    with tempfile.TemporaryDirectory() as tmp:
        oe1 = OrderEngine(f'{tmp}/o.jsonl', f'{tmp}/p.json')
        oid_p = oe1.intent('BTC/USDT', 'BUY', 0.1, 50000)
        oid_f = oe1.intent('ETH/USDT', 'BUY', 1.0, 3000)
        oe1.sent(oid_f)
        oe1.confirm(oid_f, 1.0, 3000)
        oe2 = OrderEngine(f'{tmp}/o.jsonl', f'{tmp}/p.json')
        
        assert oe2.get(oid_p) is not None, '4.OE.persist.pending_loaded'
        
        assert oe2.get(oid_p).state == OrderState.PENDING, '4.OE.persist.pending_state'
        
        assert oe2.get(oid_p).symbol == 'BTC/USDT', '4.OE.persist.symbol'
        with open(f'{tmp}/p.json', encoding='utf-8') as f:
            pdata = json.load(f)
        
        assert oid_f not in pdata, '4.OE.persist.filled_not_saved'
        
        assert oid_p in pdata, '4.OE.persist.pending_in_file'
    oe3 = make_oe()
    oe3.intent('BTC/USDT', 'BUY', 0.1, 50000)
    log_dir = os.path.dirname(oe3._order_log_file)
    
    assert not any((f.endswith('.tmp') for f in os.listdir(log_dir))), '4.OE.persist.no_tmp'
    with tempfile.TemporaryDirectory() as _tmp46:
        _oe46 = OrderEngine(f'{_tmp46}/o.jsonl', f'{_tmp46}/p.json')
        _ids46 = [_oe46.intent('S', 'BUY', 0.1, 100) for _ in range(5)]
        _oe46.sent(_ids46[0])
        _oe46.confirm(_ids46[0], 0.1, 100)
        _oe46.fail(_ids46[1], 'err')
        _pending46 = _oe46.pending_orders()
        
        assert len(_pending46) == 3, '4.OE.query.pending_count'
        _retryable46 = _oe46.failed_retryable()
        
        assert len(_retryable46) == 1, '4.OE.query.retryable'
    with tempfile.TemporaryDirectory() as _tmp47:
        _oe47 = OrderEngine(f'{_tmp47}/o.jsonl', f'{_tmp47}/p.json')
        _k47_1 = _oe47.intent('X', 'BUY', 0.1, 100)
        _k47_2 = _oe47.intent('Y', 'BUY', 0.1, 100)
        _k47_3 = _oe47.intent('Z', 'BUY', 0.1, 100)
        _oe47.sent(_k47_1)
        _oe47.confirm(_k47_1, 0.1, 100)
        _snap47 = _oe47.snapshot()
        
        assert _snap47['total_orders'] == 3, '4.OE.snap.total'
        
        assert _snap47['filled_count'] == 1, '4.OE.snap.filled_1'
        
        assert 'by_state' in _snap47, '4.OE.snap.by_state'
    oe = make_oe()
    for i in range(100):
        oid_tmp = oe.intent(f'S{i}', 'BUY', 0.1, 100)
        oe.sent(oid_tmp)
        oe.confirm(oid_tmp, 0.1, 100)
    
    assert len(oe._orders) < 200, '4.OE.mem.reasonable'
    result = asyncio.run(_run_startup(10000, 10000, tmp_path))[0]
    
    assert result.nav_ok is True, '4.RE.startup.match_ok'
    
    assert result.hard_blocked is False, '4.RE.startup.not_blocked'
    
    assert result.passed is True, '4.RE.startup.passed'
    result = asyncio.run(_run_startup(10000, 10100, tmp_path))[0]
    
    assert result.nav_ok is True, '4.RE.startup.1pct_ok'
    result = asyncio.run(_run_startup(10000, 9500, tmp_path))[0]
    
    assert result.nav_ok is False, '4.RE.startup.5pct_warn'
    
    assert result.hard_blocked is False, '4.RE.startup.5pct_no_block'
    result = asyncio.run(_run_startup(10000, 8500, tmp_path))[0]
    
    assert result.hard_blocked is True, '4.RE.startup.15pct_blocked'
    result, recon = asyncio.run(_run_startup(10000, 10000, tmp_path))
    t_files = os.listdir(recon._dir)
    
    assert any(('recon_' in f for f in t_files)), '4.RE.startup.file_saved'
    oe_m0 = MagicMock()
    oe_m0.recover = AsyncMock(return_value=[])
    
    assert _make_recon(10000, tmp_path, oe_m0)[0].snapshot() == {'status': 'never_run'}, '4.RE.snap.never_run'
    result, recon2 = asyncio.run(_run_startup(10000, 10000, tmp_path))
    snap = recon2.snapshot()
    
    assert all((k in snap for k in ['last_run_ts', 'nav_diff', 'passed'])), '4.RE.snap.has_keys'
    
    assert all((hasattr(result, f) for f in ['local_nav', 'exchange_nav', 'nav_diff', 'nav_diff_pct', 'nav_ok', 'hard_blocked'])), '4.RE.result.nav_fields'
    
    assert all((hasattr(result, f) for f in ['local_positions', 'exchange_positions', 'position_mismatch'])), '4.RE.result.position_fields'
    
    assert isinstance(result.warnings, list), '4.RE.result.warnings'

def test_5000_phase5_pre_trade_gate_and_alerts() -> None:
    ok, r = fat_finger_check(1000, max_notional=50000)
    
    assert ok is True, '5.PTG.ff.small_passes'
    ok, r = fat_finger_check(50001, max_notional=50000)
    
    assert ok is False, '5.PTG.ff.big_blocks'
    
    assert 'fat_finger' in r, '5.PTG.ff.reason_contains_fat'
    ok, r = fat_finger_check(50000, max_notional=50000)
    
    assert ok is False, '5.PTG.ff.exact_limit_blocks'
    ok, r = fat_finger_check(0, max_notional=50000)
    
    assert ok is True, '5.PTG.ff.zero_passes'
    ok, r = fat_finger_check(10000)
    
    assert ok is True, '5.PTG.ff.default_limit'
    ob_normal = {'bids': [[100, 1]], 'asks': [[100.1, 1]]}
    ob_wide = {'bids': [[100, 1]], 'asks': [[101, 1]]}
    ob_empty: dict = {}
    ob_no_ask = {'bids': [[100, 1]], 'asks': []}
    ok, _ = spread_check(ob_normal, max_spread_pct=0.005)
    
    assert ok is True, '5.PTG.sp.normal_passes'
    ok, r = spread_check(ob_wide, max_spread_pct=0.005)
    
    assert ok is False, '5.PTG.sp.wide_blocks'
    
    assert 'spread' in r, '5.PTG.sp.wide_reason'
    ok, _ = spread_check(ob_empty)
    
    assert ok is True, '5.PTG.sp.empty_ob_passes'
    ok, _ = spread_check(ob_no_ask)
    
    assert ok is True, '5.PTG.sp.no_ask_passes'
    ob_exact = {'bids': [[100, 1]], 'asks': [[100.5, 1]]}
    ok, _ = spread_check(ob_exact, max_spread_pct=0.005)
    
    assert ok is True, '5.PTG.sp.exact_below'
    ob_deep = {'asks': [[100, 1000], [101, 1000]]}
    ob_shallow = {'asks': [[100, 1]]}
    ob_none = {'asks': []}
    ok, _ = ob_depth_check(ob_deep, 1000, min_depth=1000)
    
    assert ok is True, '5.PTG.ob.deep_passes'
    ok, r = ob_depth_check(ob_shallow, 10000, min_depth=50000)
    
    assert ok is False, '5.PTG.ob.shallow_blocks'
    
    assert 'depth' in r or 'ob' in r.lower(), '5.PTG.ob.reason'
    ok, _ = ob_depth_check(ob_none, 100)
    
    assert ok is True, '5.PTG.ob.empty_passes'
    ok, _ = ob_depth_check({}, 100)
    
    assert ok is True, '5.PTG.ob.no_key_passes'
    last = {'BTC/USDT': 1000.0}
    ok, r = same_bar_guard('BTC/USDT', 1000.0, last)
    
    assert ok is False, '5.PTG.sb.same_blocks'
    
    assert 'duplicate' in r or 'same' in r.lower(), '5.PTG.sb.reason'
    ok, _ = same_bar_guard('BTC/USDT', 2000.0, last)
    
    assert ok is True, '5.PTG.sb.new_bar_passes'
    ok, _ = same_bar_guard('ETH/USDT', 1000.0, last)
    
    assert ok is True, '5.PTG.sb.diff_symbol_passes'
    ok, _ = same_bar_guard('BTC/USDT', 1000.0, {})
    
    assert ok is True, '5.PTG.sb.empty_dict_passes'
    n, src, blk = merge_entry_notional(5000, 3000)
    
    assert abs(n - 3000) < 0.01, '5.PTG.merge.takes_min'
    
    assert src != '', '5.PTG.merge.source'
    
    assert blk == '', '5.PTG.merge.no_block'
    n, src, blk = merge_entry_notional(5000, 0)
    
    assert blk != '', '5.PTG.merge.ob_zero_blocks'
    
    assert n == 0.0, '5.PTG.merge.ob_zero_notional'
    n, src, blk = merge_entry_notional(5000, None)
    
    assert abs(n - 5000) < 0.01, '5.PTG.merge.none_ob'
    
    assert 'technical' in src, '5.PTG.merge.none_source'
    n, src, blk = merge_entry_notional(3000, 5000)
    
    assert abs(n - 3000) < 0.01, '5.PTG.merge.tech_smaller'
    ok, _ = gate_buy_signal_and_slots('HOLD', 0, 0.8)
    
    assert ok is True, '5.PTG.gate.hold_passes'
    ok, _ = gate_buy_signal_and_slots('SELL', 0, 0.8)
    
    assert ok is True, '5.PTG.gate.sell_passes'
    ok, r = gate_buy_signal_and_slots('BUY', 5, 0.8)
    
    assert ok is False, '5.PTG.gate.max_pos_blocks'
    
    assert 'max_open' in r, '5.PTG.gate.max_pos_reason'
    ok, r = gate_buy_signal_and_slots('BUY', 0, 0.3)
    
    assert ok is False, '5.PTG.gate.low_conf_blocks'
    
    assert 'confidence' in r, '5.PTG.gate.conf_reason'
    ok, _ = gate_buy_signal_and_slots('BUY', 0, 0.8)
    
    assert ok is True, '5.PTG.gate.buy_passes'
    am = AlertManager(webhook_url='', cooldown_sec=0, min_level='DEBUG')
    
    assert am._webhook == '', '5.AM.init.no_webhook'
    
    assert 'webhook_active' in am.snapshot(), '5.AM.init.snapshot'
    am.emergency('test_code', nav=9000)
    
    assert len(am._history) > 0, '5.AM.event.emergency_recorded'
    
    assert am._history[-1].level == 'CRITICAL', '5.AM.event.emergency_critical'
    am.nav_diff(diff=500, diff_pct=5.0, local=9500, exchange=10000)
    
    assert len(am._history) >= 2, '5.AM.event.nav_diff_recorded'
    am.circuit_breaker('BTC/USDT', 'OPEN')
    
    assert len(am._history) >= 3, '5.AM.event.cb_recorded'
    am.stale_data('ETH/USDT', 400.0)
    
    assert len(am._history) >= 4, '5.AM.event.stale_recorded'
    am.tca_anomaly('BTC/USDT', 0.05, 0.2)
    
    assert len(am._history) >= 5, '5.AM.event.tca_recorded'
    am2 = AlertManager(webhook_url='', cooldown_sec=300, min_level='DEBUG')
    am2.emergency('test', nav=9000)
    len_before = len(am2._history)
    am2.emergency('test', nav=9000)
    
    assert len(am2._history) == len_before, '5.AM.cooldown.no_duplicate'
    am3 = AlertManager(webhook_url='', cooldown_sec=0, min_level='CRITICAL')
    am3.system('test', level='INFO')
    
    assert len(am3._history) == 0, '5.AM.filter.info_filtered'
    am3.emergency('test', nav=9000)
    
    assert len(am3._history) == 1, '5.AM.filter.critical_passes'
    snap = am.snapshot()
    
    assert snap['total_alerts'] > 0, '5.AM.snap.total'
    
    assert 'recent' in snap, '5.AM.snap.recent'
    
    assert snap['webhook_active'] is False, '5.AM.snap.webhook_active'
