"""
5000 gate — Aşama 1–2 (syntax + yüzey API + CapitalEngine derin).

Kaynak: ``super_otonom/test_5000.py`` (satır ~139–673) pytest + fixture kalıbına taşındı.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Callable, Dict

import pytest
from super_otonom.capital_engine import CapitalEngine

pytestmark = pytest.mark.fastrun

def _inv_ok(e: CapitalEngine, tol: float=0.01) -> bool:
    exp = e.initial_capital + e._net_deposits + e._realized_pnl + e._unrealized_pnl - e._fees_paid
    return abs(e.nav - exp) <= tol

@pytest.fixture(scope='module')
def phase1_module_sources() -> Dict[str, str]:
    root = Path(__file__).resolve().parents[1] / 'super_otonom'
    names = ['capital_engine', 'risk_ontology', 'risk_manager', 'order_engine', 'reconciliation_engine', 'pre_trade_gate', 'alert_manager', 'market_impact', 'concentration_risk', 'stress_test', 'audit_log']
    out: Dict[str, str] = {}
    for name in names:
        out[name] = (root / f'{name}.py').read_text(encoding='utf-8')
    return out

@pytest.fixture
def phase12_make_ce(tmp_path: Path) -> Callable[..., CapitalEngine]:
    """Legacy ``make_ce(cap, reserve=0)`` — her çağrı ayrı journal dizini."""
    counter = {'n': 0}

    def _make(cap: float=10000.0, reserve: float=0.0) -> CapitalEngine:
        counter['n'] += 1
        sub = tmp_path / f"ce_{counter['n']}"
        sub.mkdir(exist_ok=True)
        return CapitalEngine(cap, journal_file=str(sub / 'j.jsonl'), reserve_pct=reserve, max_position_pct=1.0)
    return _make

def test_5000_phase1_syntax_and_surface_api(phase1_module_sources: Dict[str, str]) -> None:
    """Aşama 1 — syntax, sınıf/metot varlığı, sabitler, import ipuçları."""
    src = phase1_module_sources
    ce_src = src['capital_engine']
    ro_src = src['risk_ontology']
    rm_src = src['risk_manager']
    oe_src = src['order_engine']
    re_src = src['reconciliation_engine']
    ptg_src = src['pre_trade_gate']
    am_src = src['alert_manager']
    mi_src = src['market_impact']
    cr_src = src['concentration_risk']
    st_src = src['stress_test']
    al_src = src['audit_log']
    for name, body in [('capital_engine', ce_src), ('risk_ontology', ro_src), ('risk_manager', rm_src), ('order_engine', oe_src), ('reconciliation_engine', re_src), ('pre_trade_gate', ptg_src), ('alert_manager', am_src), ('market_impact', mi_src), ('concentration_risk', cr_src), ('stress_test', st_src), ('audit_log', al_src)]:
        try:
            ast.parse(body)
        except SyntaxError as exc:
            
            assert False, f'1.syntax.{name}' + ' | ' + str(exc)
    
    assert 'class CapitalEngine:' in ce_src, '1.class.CapitalEngine'
    
    assert 'class JournalEntry' in ce_src, '1.class.JournalEntry'
    
    assert 'class PositionLedger' in ce_src, '1.class.PositionLedger'
    
    assert 'class RiskOntology' in ro_src, '1.class.RiskOntology'
    
    assert 'class RiskManager:' in rm_src, '1.class.RiskManager'
    
    assert 'class OrderEngine:' in oe_src, '1.class.OrderEngine'
    
    assert 'class OrderState' in oe_src, '1.class.OrderState'
    
    assert 'class OrderRecord' in oe_src, '1.class.OrderRecord'
    
    assert 'class ReconciliationEngine' in re_src, '1.class.ReconciliationEngine'
    
    assert 'class ReconResult' in re_src, '1.class.ReconResult'
    
    assert 'class AlertManager:' in am_src, '1.class.AlertManager'
    
    assert 'class AlertEvent' in am_src, '1.class.AlertEvent'
    
    assert 'class MarketImpactModel' in mi_src, '1.class.MarketImpactModel'
    
    assert 'class ImpactEstimate' in mi_src, '1.class.ImpactEstimate'
    
    assert 'class ConcentrationRiskManager' in cr_src, '1.class.ConcentrationRisk'
    
    assert 'class StressTestRunner' in st_src, '1.class.StressTestRunner'
    
    assert 'class AuditLog' in al_src, '1.class.AuditLog'
    
    assert 'class DailyReconciler' in al_src, '1.class.DailyReconciler'
    for m in ['open_position', 'close_position', 'update_unrealized', 'record_fee', 'deposit', 'withdrawal', 'reserve_margin', 'release_reservation', 'snapshot', 'to_dict', 'from_dict', '_check_invariant', '_record', 'get_journal', 'position_snapshot', 'all_positions']:
        
        assert f'def {m}(' in ce_src, f'1.method.CE.{m}'
    for p in ['nav', 'available_cash', 'equity', 'free_capital', 'buying_power']:
        
        assert f'def {p}(' in ce_src, f'1.prop.CE.{p}'
    for m in ['update', 'snapshot', 'to_dict', 'from_dict', 'is_daily_limit_breached', 'is_weekly_limit_breached', 'is_drawdown_breached', 'is_exposure_breached', '_calc_var', '_update_exposure', '_maybe_reset_day', '_maybe_reset_week']:
        
        assert f'def {m}(' in ro_src, f'1.method.RO.{m}'
    for m in ['check_risk', 'check_dynamic_risk', 'trigger_emergency', 'reset_emergency', 'record_pnl', 'set_ontology', 'status_dict', 'calculate_var', 'should_trailing_stop', 'record_volatility', 'check_volatility_spike', '_warn_if_onto_missing', 'get_last_deny']:
        
        assert f'def {m}(' in rm_src, f'1.method.RM.{m}'
    for m in ['intent', 'sent', 'confirm', 'partial', 'fail', 'cancel', 'is_duplicate', 'can_retry', 'recover', 'snapshot', '_write_log', '_save_pending', '_load_pending', 'pending_orders', 'failed_retryable']:
        
        assert f'def {m}(' in oe_src, f'1.method.OE.{m}'
    for f_name in ['gate_global_trade_disable', 'gate_buy_signal_and_slots', 'merge_entry_notional', 'fat_finger_check', 'spread_check', 'ob_depth_check', 'same_bar_guard', 'gate_buy_size_and_exposure']:
        
        assert f'def {f_name}(' in ptg_src, f'1.func.PTG.{f_name}'
    for m in ['emergency', 'nav_diff', 'circuit_breaker', 'stale_data', 'backoff', 'system', 'tca_anomaly', 'snapshot', '_send', '_post_webhook']:
        
        assert f'def {m}(' in am_src, f'1.method.AM.{m}'
    for m in ['estimate', 'amihud_ratio', 'snapshot']:
        
        assert f'def {m}(' in mi_src, f'1.method.MI.{m}'
    for m in ['check_concentration', 'sector_breakdown', 'concentration_score', 'get_sector', 'snapshot']:
        
        assert f'def {m}(' in cr_src, f'1.method.CR.{m}'
    for m in ['run_scenario', 'run_all', 'print_report']:
        
        assert f'def {m}(' in st_src, f'1.method.ST.{m}'
    for m in ['trade_open', 'trade_close', 'risk_block', 'emergency', 'signal_event', 'system_event', 'get_events', 'today_summary']:
        
        assert f'def {m}(' in al_src, f'1.method.AL.{m}'
    
    assert '_INVARIANT_TOLERANCE' in ce_src, '1.const.CE.INVARIANT_TOLERANCE'
    
    assert '_JOURNAL_MAX_BYTES' in ce_src, '1.const.CE.JOURNAL_MAX_BYTES'
    
    assert '_JOURNAL_FILE' in ce_src, '1.const.CE.JOURNAL_FILE'
    
    assert '_ORDER_LOG_FILE' in oe_src, '1.const.OE.ORDER_LOG_FILE'
    
    assert '_PENDING_FILE' in oe_src, '1.const.OE.PENDING_FILE'
    
    assert '_RECON_TOLERANCE' in re_src, '1.const.RE.RECON_TOLERANCE'
    
    assert '_HARD_BLOCK_PCT' in re_src, '1.const.RE.HARD_BLOCK_PCT'
    
    assert '_WEBHOOK_URL' in am_src, '1.const.AM.WEBHOOK_URL'
    
    assert '_COOLDOWN_SEC' in am_src, '1.const.AM.COOLDOWN_SEC'
    
    assert '_DEFAULT_LAMBDA' in mi_src, '1.const.MI.DEFAULT_LAMBDA'
    
    assert '_DEFAULT_MAX_SECTOR_PCT' in cr_src, '1.const.CR.MAX_SECTOR_PCT'
    
    assert '_MAX_NOTIONAL_PER_ORDER' in ptg_src, '1.const.PTG.MAX_NOTIONAL'
    
    assert '_MAX_SPREAD_PCT' in ptg_src, '1.const.PTG.MAX_SPREAD'
    
    assert '_MIN_OB_DEPTH' in ptg_src, '1.const.PTG.MIN_OB_DEPTH'
    for src_name, body in [('ce', ce_src), ('ro', ro_src), ('rm', rm_src), ('oe', oe_src)]:
        
        assert 'from __future__ import annotations' in body, f'1.ann.futures.{src_name}'
        
        assert 'import logging' in body, f'1.ann.logging.{src_name}'
        
        assert 'from typing import' in body, f'1.ann.typing.{src_name}'
        
        assert 'import os' in body or 'os.' in body or src_name in ('ro', 'rm'), f'1.ann.os.{src_name}'
        
        assert 'import time' in body, f'1.ann.time.{src_name}'
        
        assert 'import json' in body or src_name in ('ro', 'rm'), f'1.ann.json.{src_name}'

def test_5000_phase2_capital_engine_deep(phase12_make_ce: Callable[..., CapitalEngine], tmp_path: Path) -> None:
    """Aşama 2 — CapitalEngine davranışları (legacy test_5000 ile aynı sıra)."""
    make_ce = phase12_make_ce
    e = make_ce(10000)
    
    assert abs(e.nav - 10000) < 0.01, '2.CE.init.nav_eq_capital'
    
    assert abs(e._cash - 10000) < 0.01, '2.CE.init.cash_eq_capital'
    
    assert e._margin_used == 0.0, '2.CE.init.margin_zero'
    
    assert e._reserved_margin == 0.0, '2.CE.init.reserved_zero'
    
    assert e._unrealized_pnl == 0.0, '2.CE.init.unrealized_zero'
    
    assert e._realized_pnl == 0.0, '2.CE.init.realized_zero'
    
    assert e._fees_paid == 0.0, '2.CE.init.fees_zero'
    
    assert e._net_deposits == 0.0, '2.CE.init.net_deposits_zero'
    
    assert len(e._positions) == 0, '2.CE.init.positions_empty'
    
    assert len(e._journal) == 0, '2.CE.init.journal_empty'
    
    assert _inv_ok(e), '2.CE.init.invariant_ok'
    
    assert abs(e.available_cash - 10000) < 0.01, '2.CE.init.available_eq_cash'
    
    assert abs(e.equity - e.nav) < 0.01, '2.CE.init.equity_eq_nav'
    
    assert abs(e.free_capital - e.available_cash) < 0.01, '2.CE.init.free_capital_eq_avail'
    e = make_ce(10000)
    ok = e.open_position('BTC/USDT', 'o1', 50000, 0.1, 5000)
    
    assert ok is True, '2.CE.open.returns_true'
    
    assert e._cash < 10000, '2.CE.open.cash_reduced'
    
    assert abs(e._cash - 5000) < 0.01, '2.CE.open.cash_correct'
    
    assert abs(e._margin_used - 5000) < 0.01, '2.CE.open.margin_increased'
    
    assert abs(e.nav - 10000) < 0.01, '2.CE.open.nav_unchanged'
    
    assert 'BTC/USDT' in e._positions, '2.CE.open.position_exists'
    
    assert abs(e._positions['BTC/USDT'].entry_price - 50000) < 0.01, '2.CE.open.position_entry'
    
    assert abs(e._positions['BTC/USDT'].qty - 0.1) < 1e-08, '2.CE.open.position_qty'
    
    assert abs(e._positions['BTC/USDT'].notional - 5000) < 0.01, '2.CE.open.position_notional'
    
    assert _inv_ok(e), '2.CE.open.invariant'
    
    assert any((j.event == 'OPEN' for j in e._journal)), '2.CE.open.journal_entry'
    
    assert e.available_cash < 10000, '2.CE.open.available_reduced'
    e2 = make_ce(10000)
    e2.open_position('BTC/USDT', 'o1', 50000, 0.1, 5000, fee=10.0)
    
    assert abs(e2._cash - 4990) < 0.01, '2.CE.open.fee_deducted'
    
    assert abs(e2._fees_paid - 10) < 0.01, '2.CE.open.fees_paid'
    
    assert abs(e2.nav - 9990) < 0.01, '2.CE.open.nav_with_fee'
    
    assert _inv_ok(e2), '2.CE.open.invariant_with_fee'
    e3 = make_ce(10000)
    e3.open_position('BTC/USDT', 'o1', 50000, 0.1, 5000)
    ok2 = e3.open_position('BTC/USDT', 'o2', 51000, 0.05, 2550)
    
    assert ok2 is False, '2.CE.open.duplicate_rejected'
    
    assert abs(e3._margin_used - 5000) < 0.01, '2.CE.open.duplicate_margin_unchanged'
    e4 = make_ce(1000)
    ok3 = e4.open_position('BTC/USDT', 'o1', 50000, 0.1, 5000)
    
    assert ok3 is False, '2.CE.open.insufficient_rejected'
    
    assert e4._margin_used == 0.0, '2.CE.open.insufficient_margin_zero'
    e5 = make_ce(10000)
    e5.reserve_margin('r1', 8000)
    ok4 = e5.open_position('BTC/USDT', 'o1', 50000, 0.06, 3000)
    
    assert ok4 is False, '2.CE.open.reserved_blocks'
    e = make_ce(10000)
    e.open_position('BTC/USDT', 'o1', 50000, 0.1, 5000)
    pnl = e.close_position('BTC/USDT', 'o2', 52000, 0.1)
    
    assert abs(pnl - 200) < 0.01, '2.CE.close.pnl_correct'
    
    assert abs(e._realized_pnl - 200) < 0.01, '2.CE.close.realized_updated'
    
    assert abs(e._margin_used) < 0.01, '2.CE.close.margin_zero'
    
    assert 'BTC/USDT' not in e._positions, '2.CE.close.position_removed'
    
    assert e._cash > 5000, '2.CE.close.cash_restored'
    
    assert e.nav > 10000, '2.CE.close.nav_increased'
    
    assert _inv_ok(e), '2.CE.close.invariant'
    
    assert any((j.event in ('CLOSE', 'PARTIAL_CLOSE') for j in e._journal)), '2.CE.close.journal_close'
    e = make_ce(10000)
    e.open_position('BTC/USDT', 'o1', 50000, 0.1, 5000)
    pnl = e.close_position('BTC/USDT', 'o2', 48000, 0.1)
    
    assert abs(pnl - -200) < 0.01, '2.CE.close.loss_correct'
    
    assert e._realized_pnl < 0, '2.CE.close.realized_negative'
    
    assert e._cash >= 0, '2.CE.close.cash_nonneg'
    
    assert _inv_ok(e), '2.CE.close.invariant_loss'
    e = make_ce(10000)
    e.open_position('BTC/USDT', 'o1', 50000, 0.1, 5000)
    pnl = e.close_position('BTC/USDT', 'o2', 0.0, 0.1)
    
    assert pnl is not None, '2.CE.close.zero_price'
    
    assert e._cash >= 0, '2.CE.close.cash_nonneg_extreme'
    
    assert e._margin_used >= 0, '2.CE.close.margin_nonneg'
    e = make_ce(10000)
    e.open_position('BTC/USDT', 'o1', 50000, 0.1, 5000)
    pnl = e.close_position('BTC/USDT', 'o2', 52000, 0.1, fee=5.0)
    
    assert abs(e._fees_paid - 5.0) < 0.01, '2.CE.close.fee_deducted'
    
    assert _inv_ok(e), '2.CE.close.invariant_with_fee'
    e = make_ce(10000)
    result = e.close_position('NONEXISTENT', 'o1', 100, 1.0)
    
    assert result is None, '2.CE.close.unknown_none'
    e = make_ce(10000)
    e.open_position('BTC/USDT', 'o1', 50000, 0.1, 5000)
    pnl = e.close_position('BTC/USDT', 'o2', 52000, 0.05)
    
    assert abs(pnl - 100) < 0.01, '2.CE.partial.pnl_correct'
    
    assert 'BTC/USDT' in e._positions, '2.CE.partial.position_remains'
    
    assert abs(e._positions['BTC/USDT'].qty - 0.05) < 1e-08, '2.CE.partial.qty_reduced'
    
    assert abs(e._margin_used - 2500) < 1.0, '2.CE.partial.margin_halved'
    
    assert _inv_ok(e), '2.CE.partial.invariant'
    pnl2 = e.close_position('BTC/USDT', 'o3', 53000, 0.03)
    
    assert pnl2 is not None, '2.CE.partial.second_pnl'
    
    assert _inv_ok(e), '2.CE.partial.invariant_after2'
    e = make_ce(10000)
    e.open_position('BTC/USDT', 'o1', 50000, 0.1, 5000)
    e.close_position('BTC/USDT', 'o2', 51000, 0.04)
    e.close_position('BTC/USDT', 'o3', 52000, 0.06)
    
    assert 'BTC/USDT' not in e._positions, '2.CE.partial.all_closed'
    
    assert abs(e._margin_used) < 0.01, '2.CE.partial.margin_zero_all'
    
    assert _inv_ok(e), '2.CE.partial.invariant_final'
    e = make_ce(10000)
    e.open_position('BTC/USDT', 'o1', 50000, 0.1, 5000)
    e.update_unrealized({'BTC/USDT': 52000})
    
    assert abs(e._unrealized_pnl - 200) < 0.01, '2.CE.unreal.correct'
    
    assert e.nav > 10000, '2.CE.unreal.nav_increased'
    
    assert _inv_ok(e), '2.CE.unreal.invariant'
    for price in [51000, 52000, 53000, 51000]:
        e.update_unrealized({'BTC/USDT': price})
    expected = (51000 - 50000) * 0.1
    
    assert abs(e._unrealized_pnl - expected) < 0.01, '2.CE.unreal.latest_wins'
    
    assert _inv_ok(e), '2.CE.unreal.invariant_multi'
    e = make_ce(10000)
    e.open_position('BTC/USDT', 'o1', 50000, 0.1, 5000)
    for i in range(1000):
        e.update_unrealized({'BTC/USDT': 50000 + i * 5})
    expected = (50000 + 999 * 5 - 50000) * 0.1
    
    assert abs(e._unrealized_pnl - expected) < 0.01, '2.CE.unreal.no_drift'
    
    assert _inv_ok(e), '2.CE.unreal.invariant_1000'
    e = make_ce(10000)
    e.open_position('BTC/USDT', 'o1', 50000, 0.1, 5000)
    e.update_unrealized({'BTC/USDT': 55000})
    e.close_position('BTC/USDT', 'o2', 55000, 0.1)
    
    assert abs(e._unrealized_pnl) < 0.01, '2.CE.unreal.zero_after_close'
    
    assert _inv_ok(e), '2.CE.unreal.inv_after_close'
    e = make_ce(10000)
    e.open_position('BTC/USDT', 'o1', 50000, 0.1, 5000)
    e.update_unrealized({'NONEXISTENT': 99999})
    
    assert abs(e._unrealized_pnl) < 0.01, '2.CE.unreal.unknown_ignored'
    e = make_ce(10000)
    e.deposit(2000)
    
    assert abs(e.nav - 12000) < 0.01, '2.CE.deposit.nav_correct'
    
    assert abs(e._cash - 12000) < 0.01, '2.CE.deposit.cash_correct'
    
    assert abs(e._net_deposits - 2000) < 0.01, '2.CE.deposit.net_deposits'
    
    assert _inv_ok(e), '2.CE.deposit.invariant'
    e.withdrawal(500)
    
    assert abs(e.nav - 11500) < 0.01, '2.CE.withdraw.nav_correct'
    
    assert abs(e._net_deposits - 1500) < 0.01, '2.CE.withdraw.net_deposits'
    
    assert _inv_ok(e), '2.CE.withdraw.invariant'
    e = make_ce(10000)
    for _ in range(5):
        e.deposit(100)
    for _ in range(3):
        e.withdrawal(50)
    
    assert abs(e._net_deposits - 350) < 0.01, '2.CE.multi.net_deposits'
    
    assert _inv_ok(e), '2.CE.multi.invariant'
    e = make_ce(1000)
    ok = e.withdrawal(5000)
    
    assert ok is False, '2.CE.withdraw.insufficient'
    
    assert abs(e.nav - 1000) < 0.01, '2.CE.withdraw.nav_unchanged'
    e = make_ce(10000)
    e.deposit(5000)
    e.open_position('BTC/USDT', 'o1', 50000, 0.1, 5000)
    pnl = e.close_position('BTC/USDT', 'o2', 52000, 0.1)
    
    assert _inv_ok(e), '2.CE.deposit_trade.invariant'
    
    assert abs(pnl - 200) < 0.01, '2.CE.deposit_trade.pnl_correct'
    e = make_ce(10000)
    e.reserve_margin('r1', 3000)
    
    assert abs(e.available_cash - 7000) < 0.01, '2.CE.reserve.available_reduced'
    
    assert abs(e.nav - 10000) < 0.01, '2.CE.reserve.nav_unchanged'
    
    assert abs(e._reserved_margin - 3000) < 0.01, '2.CE.reserve.reserved_correct'
    e.release_reservation('r1', 3000)
    
    assert abs(e.available_cash - 10000) < 0.01, '2.CE.release.available_restored'
    
    assert abs(e._reserved_margin) < 0.01, '2.CE.release.reserved_zero'
    e = make_ce(10000)
    e.reserve_margin('r1', 2000)
    e.reserve_margin('r2', 3000)
    
    assert abs(e._reserved_margin - 5000) < 0.01, '2.CE.reserve.multi_total'
    
    assert abs(e.available_cash - 5000) < 0.01, '2.CE.reserve.multi_available'
    e = make_ce(1000)
    ok = e.reserve_margin('r1', 5000)
    
    assert ok is False, '2.CE.reserve.insufficient'
    e = make_ce(10000, reserve=0.05)
    e.open_position('BTC/USDT', 'o1', 50000, 0.1, 5000)
    e.deposit(1000)
    e.reserve_margin('r1', 500)
    e.update_unrealized({'BTC/USDT': 52000})
    d = e.to_dict()
    serial_dir = tmp_path / 'serial_round'
    serial_dir.mkdir(exist_ok=True)
    e2 = CapitalEngine.from_dict(d, journal_file=str(serial_dir / 'j2.jsonl'))
    
    assert abs(e2.nav - e.nav) < 0.01, '2.CE.serial.nav'
    
    assert abs(e2._cash - e._cash) < 0.01, '2.CE.serial.cash'
    
    assert abs(e2._margin_used - e._margin_used) < 0.01, '2.CE.serial.margin'
    
    assert abs(e2._reserved_margin - e._reserved_margin) < 0.01, '2.CE.serial.reserved'
    
    assert abs(e2._unrealized_pnl - e._unrealized_pnl) < 0.01, '2.CE.serial.unrealized'
    
    assert abs(e2._realized_pnl - e._realized_pnl) < 0.01, '2.CE.serial.realized'
    
    assert abs(e2._fees_paid - e._fees_paid) < 0.01, '2.CE.serial.fees'
    
    assert abs(e2._net_deposits - e._net_deposits) < 0.01, '2.CE.serial.net_deposits'
    
    assert 'BTC/USDT' in e2._positions, '2.CE.serial.position_exists'
    
    assert abs(e2._reserve_pct - e._reserve_pct) < 0.001, '2.CE.serial.reserve_pct'
    
    assert _inv_ok(e2), '2.CE.serial.invariant'
    d = e.to_dict()
    for key in ['initial_capital', 'cash', 'margin_used', 'reserved_margin', 'unrealized_pnl', 'realized_pnl', 'fees_paid', 'net_deposits', 'reserve_pct', 'max_position_pct', 'positions']:
        
        assert key in d, f'2.CE.serial.key_{key}'
    e = make_ce(10000)
    e.open_position('BTC/USDT', 'o1', 50000, 0.1, 5000)
    snap = e.snapshot()
    for k in ['nav', 'cash', 'margin_used', 'reserved_margin', 'unrealized_pnl', 'realized_pnl', 'fees_paid', 'net_deposits', 'available_cash', 'buying_power', 'open_positions', 'total_return_pct', 'journal_entries']:
        
        assert k in snap, f'2.CE.snap.key_{k}'
    
    assert abs(snap['nav'] - 10000) < 0.01, '2.CE.snap.nav_correct'
    
    assert snap['open_positions'] == 1, '2.CE.snap.open_pos_1'
    
    assert abs(snap['total_return_pct']) < 0.01, '2.CE.snap.return_pct_zero'
    e = make_ce(10000)
    e.open_position('BTC/USDT', 'o1', 50000, 0.1, 5000)
    e.record_fee('BTC/USDT', 'o1', 10.0)
    e.close_position('BTC/USDT', 'o2', 52000, 0.1)
    journal = e.get_journal()
    events = [j['event'] for j in journal]
    
    assert 'OPEN' in events, '2.CE.journal.has_open'
    
    assert 'FEE' in events, '2.CE.journal.has_fee'
    
    assert 'CLOSE' in events or 'PARTIAL_CLOSE' in events, '2.CE.journal.has_close'
    
    assert all(('ts' in j for j in journal)), '2.CE.journal.has_ts'
    
    assert all(('snap_nav' in j for j in journal)), '2.CE.journal.has_snap_nav'
    
    assert all((j['snap_nav'] >= 0 for j in journal)), '2.CE.journal.snap_nav_correct'
    e = make_ce(50000)
    symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'ADA/USDT', 'DOT/USDT']
    for i, sym in enumerate(symbols):
        e.open_position(sym, f'o{i}', 1000 * (i + 1), 1.0, 1000 * (i + 1))
    
    assert len(e._positions) == 5, '2.CE.multi_pos.count'
    
    assert abs(e._margin_used - sum((1000 * (i + 1) for i in range(5)))) < 0.01, '2.CE.multi_pos.margin_sum'
    
    assert _inv_ok(e), '2.CE.multi_pos.invariant'
    prices = {sym: 1000 * (i + 2) for i, sym in enumerate(symbols)}
    e.update_unrealized(prices)
    
    assert e._unrealized_pnl > 0, '2.CE.multi_pos.unreal_pos'
    
    assert _inv_ok(e), '2.CE.multi_pos.invariant_unreal'
    for i, sym in enumerate(symbols):
        e.close_position(sym, f'c{i}', 1000 * (i + 2), 1.0)
    
    assert len(e._positions) == 0, '2.CE.multi_pos.all_closed'
    
    assert abs(e._margin_used) < 0.01, '2.CE.multi_pos.margin_zero'
    
    assert abs(e._unrealized_pnl) < 0.01, '2.CE.multi_pos.unreal_zero'
    
    assert _inv_ok(e), '2.CE.multi_pos.invariant_final'
