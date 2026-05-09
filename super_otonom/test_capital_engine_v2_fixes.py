"""
test_capital_engine_v2_fixes.py
─────────────────────────────────────────────────────────────────────────────
4 bug fix için kapsamlı testler:

  FIX-1: deposit/withdrawal invariant (_net_deposits tracker)
  FIX-2: _reserved_margin serileştirme (to_dict/from_dict)
  FIX-3: Partial fill muhasebesi (orantılı notional)
  FIX-4: update_unrealized float drift önlemi
"""
from __future__ import annotations
import os, sys, tempfile, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from capital_engine import CapitalEngine

_TOLERANCE = 0.01


def make_engine(capital=10_000.0):
    return CapitalEngine(
        initial_capital=capital,
        journal_file="/tmp/test_ce_v2.jsonl",
        reserve_pct=0.0,   # testlerde rezerv 0 — hesap basitleşsin
        max_position_pct=1.0,
    )


def invariant_ok(e: CapitalEngine) -> bool:
    expected = (
        e.initial_capital
        + e._net_deposits
        + e._realized_pnl
        + e._unrealized_pnl
        - e._fees_paid
    )
    return abs(e.nav - expected) <= _TOLERANCE


# ══════════════════════════════════════════════════════════════════════════════
# FIX-1: Deposit / Withdrawal invariant
# ══════════════════════════════════════════════════════════════════════════════

class TestDepositWithdrawalInvariant:

    def test_deposit_invariant_holds(self):
        e = make_engine(10_000)
        e.deposit(2_000)
        assert invariant_ok(e), f"nav={e.nav} net_dep={e._net_deposits}"

    def test_withdrawal_invariant_holds(self):
        e = make_engine(10_000)
        e.withdrawal(1_000)
        assert invariant_ok(e)

    def test_multiple_deposits_invariant(self):
        e = make_engine(10_000)
        for amount in [500, 1_000, 2_500]:
            e.deposit(amount)
        assert invariant_ok(e)
        assert e._net_deposits == pytest.approx(4_000.0)

    def test_deposit_then_withdrawal_invariant(self):
        e = make_engine(10_000)
        e.deposit(3_000)
        e.withdrawal(1_000)
        assert invariant_ok(e)
        assert e._net_deposits == pytest.approx(2_000.0)

    def test_deposit_increases_nav(self):
        e = make_engine(10_000)
        e.deposit(5_000)
        assert e.nav == pytest.approx(15_000.0)

    def test_withdrawal_decreases_nav(self):
        e = make_engine(10_000)
        e.withdrawal(2_000)
        assert e.nav == pytest.approx(8_000.0)

    def test_invariant_after_trade_and_deposit(self):
        """Trade + deposit kombinasyonu invariantı bozmamalı."""
        e = make_engine(10_000)
        e.open_position("BTC/USDT", "ord-1", 50_000, 0.1, 5_000)
        e.deposit(2_000)
        assert invariant_ok(e)
        e.close_position("BTC/USDT", "ord-2", 52_000, 0.1)
        assert invariant_ok(e)

    def test_net_deposits_in_snapshot(self):
        e = make_engine(10_000)
        e.deposit(1_500)
        snap = e.snapshot()
        assert "net_deposits" in snap
        assert snap["net_deposits"] == pytest.approx(1_500.0)

    def test_net_deposits_in_to_dict(self):
        e = make_engine(10_000)
        e.deposit(1_000)
        d = e.to_dict()
        assert "net_deposits" in d
        assert d["net_deposits"] == pytest.approx(1_000.0)


# ══════════════════════════════════════════════════════════════════════════════
# FIX-2: _reserved_margin serileştirme
# ══════════════════════════════════════════════════════════════════════════════

class TestReservedMarginSerialization:

    def test_reserved_margin_in_to_dict(self):
        e = make_engine(10_000)
        e.reserve_margin("ord-1", 3_000)
        d = e.to_dict()
        assert "reserved_margin" in d
        assert d["reserved_margin"] == pytest.approx(3_000.0)

    def test_reserved_margin_restored_from_dict(self):
        e1 = make_engine(10_000)
        e1.reserve_margin("ord-1", 2_500)
        d = e1.to_dict()
        e2 = CapitalEngine.from_dict(d, journal_file="/tmp/test_ce_v2_load.jsonl")
        assert e2._reserved_margin == pytest.approx(2_500.0)

    def test_reserved_margin_zero_without_reservation(self):
        e = make_engine(10_000)
        d = e.to_dict()
        assert d["reserved_margin"] == pytest.approx(0.0)

    def test_available_cash_correct_after_load(self):
        """Restart sonrası available_cash rezervi yansıtmalı."""
        e1 = make_engine(10_000)
        e1.reserve_margin("ord-1", 4_000)
        before = e1.available_cash

        d = e1.to_dict()
        e2 = CapitalEngine.from_dict(d, journal_file="/tmp/test_ce_v2_load2.jsonl")
        assert e2.available_cash == pytest.approx(before)

    def test_no_double_spend_after_restart(self):
        """
        Restart öncesi 8000 rezerv → available_cash = 2000.
        Restart sonrası da aynı olmalı — 10000'e dönmemeli.
        """
        e1 = make_engine(10_000)
        e1.reserve_margin("ord-1", 8_000)
        assert e1.available_cash == pytest.approx(2_000.0)

        d = e1.to_dict()
        e2 = CapitalEngine.from_dict(d, journal_file="/tmp/test_ce_v2_load3.jsonl")
        assert e2.available_cash == pytest.approx(2_000.0)   # çift harcama yok

    def test_net_deposits_restored(self):
        e1 = make_engine(10_000)
        e1.deposit(3_000)
        d = e1.to_dict()
        e2 = CapitalEngine.from_dict(d, journal_file="/tmp/test_ce_v2_load4.jsonl")
        assert e2._net_deposits == pytest.approx(3_000.0)
        assert invariant_ok(e2)


# ══════════════════════════════════════════════════════════════════════════════
# FIX-3: Partial fill muhasebesi
# ══════════════════════════════════════════════════════════════════════════════

class TestPartialFillAccounting:

    def test_full_fill_closes_position(self):
        e = make_engine(10_000)
        e.open_position("BTC/USDT", "ord-1", 50_000, 0.1, 5_000)
        pnl = e.close_position("BTC/USDT", "ord-2", 52_000, 0.1)
        assert pnl == pytest.approx(200.0)
        assert "BTC/USDT" not in e._positions
        assert e._margin_used == pytest.approx(0.0)
        assert invariant_ok(e)

    def test_partial_fill_keeps_position(self):
        """Kısmi fill: pozisyon silinmemeli, qty güncellenmeli."""
        e = make_engine(10_000)
        e.open_position("BTC/USDT", "ord-1", 50_000, 0.1, 5_000)
        pnl = e.close_position("BTC/USDT", "ord-2", 52_000, 0.05)  # yarısı
        # Pozisyon hâlâ açık olmalı
        assert "BTC/USDT" in e._positions
        pos = e._positions["BTC/USDT"]
        assert pos.qty == pytest.approx(0.05)

    def test_partial_fill_pnl_correct(self):
        e = make_engine(10_000)
        e.open_position("BTC/USDT", "ord-1", 50_000, 0.1, 5_000)
        pnl = e.close_position("BTC/USDT", "ord-2", 52_000, 0.05)
        # pnl = (52000 - 50000) * 0.05 = 100
        assert pnl == pytest.approx(100.0)

    def test_partial_fill_notional_correct(self):
        """Sadece doldurulan kısım kadar notional serbest bırakılmalı."""
        e = make_engine(10_000)
        e.open_position("BTC/USDT", "ord-1", 50_000, 0.1, 5_000)
        initial_margin = e._margin_used  # 5000
        e.close_position("BTC/USDT", "ord-2", 52_000, 0.05)  # %50 fill
        # Margin_used 2500 azalmalı (5000 × 0.5)
        assert e._margin_used == pytest.approx(initial_margin * 0.5)

    def test_partial_fill_invariant(self):
        e = make_engine(10_000)
        e.open_position("BTC/USDT", "ord-1", 50_000, 0.1, 5_000)
        e.close_position("BTC/USDT", "ord-2", 52_000, 0.05)
        assert invariant_ok(e), f"nav={e.nav} net_dep={e._net_deposits}"

    def test_partial_then_full_close(self):
        """Kısmi kapanış + tam kapanış zinciri."""
        e = make_engine(10_000)
        e.open_position("BTC/USDT", "ord-1", 50_000, 0.1, 5_000)
        e.close_position("BTC/USDT", "ord-2", 51_000, 0.04)  # %40
        assert invariant_ok(e)
        e.close_position("BTC/USDT", "ord-3", 52_000, 0.06)  # kalan %60
        assert "BTC/USDT" not in e._positions
        assert e._margin_used == pytest.approx(0.0)
        assert invariant_ok(e)

    def test_partial_fill_margin_never_negative(self):
        """margin_used asla negatife düşmemeli."""
        e = make_engine(10_000)
        e.open_position("BTC/USDT", "ord-1", 50_000, 0.1, 5_000)
        # filled_qty > pos.qty — overfill kenar durumu
        e.close_position("BTC/USDT", "ord-2", 52_000, 0.1)  # tam fill
        assert e._margin_used >= 0.0

    def test_cash_never_negative_on_loss(self):
        e = make_engine(10_000)
        e.open_position("BTC/USDT", "ord-1", 50_000, 0.1, 5_000)
        e.close_position("BTC/USDT", "ord-2", 0.0, 0.1)   # fiyat sıfır
        assert e._cash >= 0.0


# ══════════════════════════════════════════════════════════════════════════════
# FIX-4: Float drift — update_unrealized
# ══════════════════════════════════════════════════════════════════════════════

class TestUnrealizedFloatDrift:

    def test_unrealized_exact_after_many_ticks(self):
        """1000 tick sonrası _unrealized_pnl pozisyondan hesaplananla eşleşmeli."""
        e = make_engine(10_000)
        e.open_position("BTC/USDT", "ord-1", 50_000, 0.1, 5_000)

        prices = [50_000 + i * 10 for i in range(1000)]
        for p in prices:
            e.update_unrealized({"BTC/USDT": p})

        # Son fiyat: 50_000 + 999*10 = 59_990
        expected_unrealized = (59_990 - 50_000) * 0.1   # 999.0
        assert e._unrealized_pnl == pytest.approx(expected_unrealized, abs=_TOLERANCE)

    def test_unrealized_zero_after_all_closed(self):
        """Tüm pozisyonlar kapanınca _unrealized_pnl sıfır olmalı."""
        e = make_engine(10_000)
        e.open_position("BTC/USDT", "ord-1", 50_000, 0.1, 5_000)
        e.update_unrealized({"BTC/USDT": 55_000})
        assert e._unrealized_pnl != pytest.approx(0.0)
        e.close_position("BTC/USDT", "ord-2", 55_000, 0.1)
        assert e._unrealized_pnl == pytest.approx(0.0, abs=_TOLERANCE)

    def test_invariant_after_1000_ticks(self):
        e = make_engine(10_000)
        e.open_position("BTC/USDT", "ord-1", 50_000, 0.1, 5_000)
        for i in range(1000):
            e.update_unrealized({"BTC/USDT": 50_000 + i * 5})
        assert invariant_ok(e)

    def test_multi_position_unrealized_sum(self):
        """Çok pozisyonda unrealized toplam doğru hesaplanmalı."""
        e = make_engine(20_000)
        e.open_position("BTC/USDT", "ord-1", 50_000, 0.1, 5_000)
        e.open_position("ETH/USDT", "ord-2", 3_000, 1.0, 3_000)
        e.update_unrealized({"BTC/USDT": 52_000, "ETH/USDT": 3_200})
        # BTC unrealized = (52000-50000)*0.1 = 200
        # ETH unrealized = (3200-3000)*1.0  = 200
        assert e._unrealized_pnl == pytest.approx(400.0, abs=_TOLERANCE)
        assert invariant_ok(e)

    def test_unrealized_recalculated_from_positions(self):
        """
        FIX-4 doğrulaması: _unrealized_pnl delta birikimi değil,
        pozisyonların toplamı olmalı.
        """
        e = make_engine(10_000)
        e.open_position("BTC/USDT", "ord-1", 50_000, 0.1, 5_000)
        e.update_unrealized({"BTC/USDT": 55_000})
        pos_sum = sum(p.unrealized for p in e._positions.values())
        assert e._unrealized_pnl == pytest.approx(pos_sum, abs=1e-9)


# ══════════════════════════════════════════════════════════════════════════════
# Kombinasyon: tüm fix'ler birlikte
# ══════════════════════════════════════════════════════════════════════════════

class TestCombinedFixes:

    def test_full_scenario(self):
        """
        Gerçekçi senaryo:
        1. Başlat
        2. Deposit
        3. Pozisyon aç, rezerv tut
        4. 500 tick unrealized güncelle
        5. Kısmi fill
        6. Kalan kapat
        7. Withdrawal
        8. Restart (to_dict / from_dict)
        9. Tüm adımlarda invariant kontrol
        """
        e = make_engine(10_000)
        assert invariant_ok(e)

        e.deposit(2_000)
        assert invariant_ok(e)

        e.reserve_margin("ord-1", 5_000)
        e.open_position("BTC/USDT", "ord-1", 50_000, 0.1, 5_000)
        e.release_reservation("ord-1", 5_000)
        assert invariant_ok(e)

        for i in range(500):
            e.update_unrealized({"BTC/USDT": 50_000 + i * 2})
        assert invariant_ok(e)

        # Kısmi fill: %60
        e.close_position("BTC/USDT", "ord-2", 51_000, 0.06)
        assert invariant_ok(e)
        assert "BTC/USDT" in e._positions

        # Kalan kapat
        e.close_position("BTC/USDT", "ord-3", 52_000, 0.04)
        assert invariant_ok(e)
        assert "BTC/USDT" not in e._positions

        e.withdrawal(1_000)
        assert invariant_ok(e)

        # Restart
        d = e.to_dict()
        e2 = CapitalEngine.from_dict(d, journal_file="/tmp/test_ce_combined.jsonl")
        assert invariant_ok(e2)
        assert e2.nav == pytest.approx(e.nav, abs=_TOLERANCE)
        assert e2._net_deposits == pytest.approx(e._net_deposits)
        assert e2._reserved_margin == pytest.approx(e._reserved_margin)
