"""
tests/test_capital_engine.py
─────────────────────────────────────────────────────────────────────────────
CapitalEngine v1.0 — birim ve property testleri

Kapsam:
  - Ledger invariant (her işlem sonrası nav doğrulanır)
  - open/close/fee/deposit/withdrawal doğruluğu
  - available_cash ve buying_power hesabı
  - Partial fill muhasebesi
  - Yetersiz nakit koruması
  - Serileştirme (to_dict / from_dict round-trip)
  - Hypothesis property testleri
"""

from __future__ import annotations

import os
import sys

import pytest

from hypothesis import assume, given, settings
from hypothesis import strategies as st

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from capital_engine import CapitalEngine

# ── Yardımcılar ──────────────────────────────────────────────────────────────


def make_engine(capital: float = 10_000.0) -> CapitalEngine:
    return CapitalEngine(
        initial_capital=capital,
        journal_file="/tmp/test_journal.jsonl",
        reserve_pct=0.05,
        max_position_pct=0.95,
    )


def _invariant_ok(engine: CapitalEngine) -> bool:
    expected = (
        engine.initial_capital + engine._realized_pnl + engine._unrealized_pnl - engine._fees_paid
    )
    return abs(engine.nav - expected) < 0.01


# ── Temel ledger testleri ─────────────────────────────────────────────────────


class TestBasicLedger:
    def test_initial_state(self):
        e = make_engine(10_000)
        assert e.nav == 10_000.0
        assert e._cash == 10_000.0
        assert e._margin_used == 0.0
        assert e._unrealized_pnl == 0.0
        assert e._realized_pnl == 0.0
        assert e._fees_paid == 0.0
        assert _invariant_ok(e)

    def test_available_cash_respects_reserve(self):
        e = make_engine(10_000)
        # reserve = %5 → 500 → available = 9500
        assert e.available_cash == pytest.approx(9_500.0)

    def test_buying_power(self):
        e = make_engine(10_000)
        # available=9500, max_position=95% → 9025
        assert e.buying_power == pytest.approx(9_025.0)

    def test_open_position_updates_ledger(self):
        e = make_engine(10_000)
        ok = e.open_position("BTC/USDT", "ord-1", 50_000.0, 0.02, 1_000.0, fee=1.0)
        assert ok is True
        assert e._margin_used == pytest.approx(1_000.0)
        assert e._cash == pytest.approx(10_000.0 - 1_000.0 - 1.0)
        assert e._fees_paid == pytest.approx(1.0)
        assert _invariant_ok(e)

    def test_close_position_profit(self):
        e = make_engine(10_000)
        e.open_position("BTC/USDT", "ord-1", 50_000.0, 0.02, 1_000.0)
        pnl = e.close_position("BTC/USDT", "ord-2", 55_000.0, 0.02, fee=1.0)
        # pnl = (55000 - 50000) * 0.02 = 100
        assert pnl == pytest.approx(100.0)
        assert e._margin_used == pytest.approx(0.0)
        assert e._realized_pnl == pytest.approx(100.0)
        assert e._fees_paid == pytest.approx(1.0)
        assert _invariant_ok(e)

    def test_close_position_loss(self):
        e = make_engine(10_000)
        e.open_position("ETH/USDT", "ord-1", 3_000.0, 0.5, 1_500.0)
        pnl = e.close_position("ETH/USDT", "ord-2", 2_700.0, 0.5)
        # pnl = (2700 - 3000) * 0.5 = -150
        assert pnl == pytest.approx(-150.0)
        assert e._realized_pnl == pytest.approx(-150.0)
        assert e._cash >= 0.0  # asla negatif
        assert _invariant_ok(e)

    def test_nav_equals_equity_property(self):
        e = make_engine(10_000)
        e.open_position("BTC/USDT", "ord-1", 50_000.0, 0.02, 1_000.0)
        assert e.equity == e.nav

    def test_free_capital_equals_available_cash(self):
        e = make_engine(10_000)
        e.open_position("BTC/USDT", "ord-1", 50_000.0, 0.02, 1_000.0)
        assert e.free_capital == e.available_cash

    def test_invariant_after_multiple_trades(self):
        e = make_engine(20_000)
        e.open_position("BTC/USDT", "ord-1", 50_000.0, 0.1, 5_000.0, fee=5.0)
        e.open_position("ETH/USDT", "ord-2", 3_000.0, 1.0, 3_000.0, fee=3.0)
        assert _invariant_ok(e)
        e.close_position("BTC/USDT", "ord-3", 52_000.0, 0.1, fee=5.0)
        assert _invariant_ok(e)
        e.close_position("ETH/USDT", "ord-4", 2_800.0, 1.0, fee=3.0)
        assert _invariant_ok(e)


# ── Kenar durumlar ────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_insufficient_cash_blocked(self):
        e = make_engine(1_000)
        ok = e.open_position("BTC/USDT", "ord-1", 50_000.0, 1.0, 2_000.0)
        assert ok is False
        assert e._margin_used == 0.0
        assert _invariant_ok(e)

    def test_duplicate_symbol_blocked(self):
        e = make_engine(10_000)
        e.open_position("BTC/USDT", "ord-1", 50_000.0, 0.02, 1_000.0)
        ok = e.open_position("BTC/USDT", "ord-2", 51_000.0, 0.02, 1_000.0)
        assert ok is False
        assert e._margin_used == pytest.approx(1_000.0)

    def test_close_nonexistent_returns_none(self):
        e = make_engine(10_000)
        result = e.close_position("XYZ/USDT", "ord-1", 100.0, 1.0)
        assert result is None

    def test_cash_never_negative_on_large_loss(self):
        """
        Extreme senaryo: exit_price sıfır (teorik maksimum kayıp).
        cash negatife düşmemeli.
        """
        e = make_engine(10_000)
        e.open_position("BTC/USDT", "ord-1", 50_000.0, 0.02, 1_000.0)
        e.close_position("BTC/USDT", "ord-2", 0.0, 0.02)
        assert e._cash >= 0.0

    def test_withdrawal_insufficient(self):
        e = make_engine(1_000)
        ok = e.withdrawal(5_000.0)
        assert ok is False
        assert e._cash == pytest.approx(1_000.0)

    def test_withdrawal_ok(self):
        e = make_engine(10_000)
        ok = e.withdrawal(1_000.0)
        assert ok is True
        assert e._cash == pytest.approx(9_000.0)

    def test_deposit_increases_nav(self):
        e = make_engine(10_000)
        e.deposit(5_000.0)
        assert e._cash == pytest.approx(15_000.0)
        assert e.nav == pytest.approx(15_000.0)


# ── Unrealized PnL ───────────────────────────────────────────────────────────


class TestUnrealizedPnL:
    def test_update_unrealized_increases_nav(self):
        e = make_engine(10_000)
        e.open_position("BTC/USDT", "ord-1", 50_000.0, 0.1, 5_000.0)
        nav_before = e.nav
        e.update_unrealized({"BTC/USDT": 55_000.0})
        # unrealized = (55000 - 50000) * 0.1 = 500
        assert e._unrealized_pnl == pytest.approx(500.0)
        assert e.nav == pytest.approx(nav_before + 500.0)
        assert _invariant_ok(e)

    def test_unrealized_cleared_on_close(self):
        e = make_engine(10_000)
        e.open_position("BTC/USDT", "ord-1", 50_000.0, 0.1, 5_000.0)
        e.update_unrealized({"BTC/USDT": 55_000.0})
        assert e._unrealized_pnl != 0.0
        e.close_position("BTC/USDT", "ord-2", 55_000.0, 0.1)
        # Kapanışta unrealized temizlendi, realized'a geçti
        assert e._unrealized_pnl == pytest.approx(0.0)
        assert e._realized_pnl == pytest.approx(500.0)
        assert _invariant_ok(e)


# ── Partial fill ─────────────────────────────────────────────────────────────


class TestPartialFill:
    def test_partial_fill_correct_pnl(self):
        e = make_engine(10_000)
        # Açılış: 0.1 BTC @ 50000 → notional=5000 (kapital içinde)
        e.open_position("BTC/USDT", "ord-1", 50_000.0, 0.1, 5_000.0)
        # Kısmi kapanış: sadece 0.05 BTC doldu (yarısı)
        pnl = e.close_position("BTC/USDT", "ord-2", 52_000.0, 0.05)
        # pnl = (52000 - 50000) * 0.05 = 100
        assert pnl == pytest.approx(100.0)
        assert _invariant_ok(e)


# ── Journal ───────────────────────────────────────────────────────────────────


class TestJournal:
    def test_journal_records_open_and_close(self):
        e = make_engine(10_000)
        e.open_position("BTC/USDT", "ord-1", 50_000.0, 0.02, 1_000.0, fee=1.0)
        e.close_position("BTC/USDT", "ord-2", 52_000.0, 0.02, fee=1.0)
        journal = e.get_journal()
        events = [j["event"] for j in journal]
        assert "OPEN" in events
        assert "CLOSE" in events
        assert "FEE" in events

    def test_journal_snapshot_consistent(self):
        e = make_engine(10_000)
        e.open_position("BTC/USDT", "ord-1", 50_000.0, 0.02, 1_000.0)
        last = e.get_journal()[-1]
        assert last["snap_margin_used"] == pytest.approx(1_000.0, abs=0.01)
        assert last["snap_nav"] == pytest.approx(e.nav, abs=0.01)


# ── Serileştirme ──────────────────────────────────────────────────────────────


class TestSerialization:
    def test_round_trip_no_positions(self):
        e = make_engine(10_000)
        d = e.to_dict()
        e2 = CapitalEngine.from_dict(d, journal_file="/tmp/test_journal2.jsonl")
        assert e2.nav == pytest.approx(e.nav)
        assert e2._cash == pytest.approx(e._cash)
        assert e2._realized_pnl == pytest.approx(e._realized_pnl)

    def test_round_trip_with_open_position(self):
        e = make_engine(10_000)
        e.open_position("BTC/USDT", "ord-1", 50_000.0, 0.02, 1_000.0)
        d = e.to_dict()
        e2 = CapitalEngine.from_dict(d, journal_file="/tmp/test_journal3.jsonl")
        assert e2.nav == pytest.approx(e.nav)
        assert e2._margin_used == pytest.approx(e._margin_used)
        assert "BTC/USDT" in e2._positions

    def test_snapshot_keys(self):
        e = make_engine(10_000)
        snap = e.snapshot()
        for key in [
            "nav",
            "cash",
            "margin_used",
            "unrealized_pnl",
            "realized_pnl",
            "fees_paid",
            "available_cash",
            "buying_power",
            "open_positions",
            "total_return_pct",
        ]:
            assert key in snap


# ── Hypothesis property testleri ─────────────────────────────────────────────


@given(
    capital=st.floats(min_value=1_000, max_value=1_000_000, allow_nan=False, allow_infinity=False),
    entry=st.floats(min_value=1.0, max_value=100_000.0, allow_nan=False, allow_infinity=False),
    qty=st.floats(min_value=0.001, max_value=10.0, allow_nan=False, allow_infinity=False),
    exit_mult=st.floats(min_value=0.5, max_value=2.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=200)
def test_invariant_always_holds(capital, entry, qty, exit_mult):
    """nav invariantı her koşulda sağlanmalı."""
    e = make_engine(capital)
    notional = entry * qty
    assume(notional < e.available_cash)
    ok = e.open_position("X/Y", "ord-1", entry, qty, notional)
    if not ok:
        return
    assert _invariant_ok(e)
    exit_price = entry * exit_mult
    e.close_position("X/Y", "ord-2", exit_price, qty)
    assert _invariant_ok(e)
    assert e._cash >= 0.0


@given(
    capital=st.floats(min_value=1_000, max_value=100_000, allow_nan=False, allow_infinity=False),
    fee=st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=150)
def test_fees_never_exceed_cash(capital, fee):
    """Ücret ödemesi cash'i negatife götürmemeli."""
    e = make_engine(capital)
    e.record_fee("X/Y", "ord-1", fee)
    assert e._cash >= 0.0


@given(
    capital=st.floats(min_value=10_000, max_value=1_000_000, allow_nan=False, allow_infinity=False),
    n_trades=st.integers(min_value=1, max_value=10),
    price_changes=st.lists(
        st.floats(min_value=0.8, max_value=1.2, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=10,
    ),
)
@settings(max_examples=100)
def test_multi_trade_invariant(capital, n_trades, price_changes):
    """Çok sayıda trade sonrası invariant bozulmamalı."""
    e = make_engine(capital)
    base_price = 1_000.0
    for i in range(min(n_trades, len(price_changes))):
        sym = f"SYM{i}/USDT"
        notional = e.available_cash * 0.1
        assume(notional > 10)
        qty = notional / base_price
        ok = e.open_position(sym, f"ord-{i}", base_price, qty, notional)
        if not ok:
            continue
        exit_price = base_price * price_changes[i]
        e.close_position(sym, f"close-{i}", exit_price, qty)
        assert _invariant_ok(e)
        assert e._cash >= 0.0
