"""
test_capital_engine_v3_fixes.py
─────────────────────────────────────────────────────────────────────────────
Yeni 5 fix için testler:
  FIX-A: open_position available_cash kontrolü (reserved dahil)
  FIX-B: record_fee sonrası invariant kontrolü
  FIX-C: available_cash reserve nav bazlı
  FIX-D: Journal 50MB rotation
  FIX-E: _margin_used negatif guard
"""
from __future__ import annotations
import os, sys, json, tempfile, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from capital_engine import CapitalEngine

_TOL = 0.01

def make_engine(capital=10_000.0, reserve_pct=0.0):
    return CapitalEngine(
        initial_capital=capital,
        journal_file="/tmp/test_ce_v3.jsonl",
        reserve_pct=reserve_pct,
        max_position_pct=1.0,
    )

def invariant_ok(e):
    expected = (e.initial_capital + e._net_deposits
                + e._realized_pnl + e._unrealized_pnl - e._fees_paid)
    return abs(e.nav - expected) <= _TOL


# ══════════════════════════════════════════════════════════════════════════════
# FIX-A: open_position available_cash kontrolü
# ══════════════════════════════════════════════════════════════════════════════

class TestOpenPositionReservedCheck:

    def test_overcommit_blocked_when_reserved(self):
        """
        cash=10000, reserved=8000, available=2000
        notional=3000 → geçmemeli (overcommit)
        """
        e = make_engine(10_000)
        e.reserve_margin("ord-0", 8_000)
        assert e.available_cash == pytest.approx(2_000.0)
        ok = e.open_position("BTC/USDT", "ord-1", 50_000, 0.06, 3_000)
        assert ok is False
        assert e._margin_used == pytest.approx(0.0)

    def test_open_allowed_within_available(self):
        """
        cash=10000, reserved=8000, available=2000
        notional=1500 → geçmeli
        """
        e = make_engine(10_000)
        e.reserve_margin("ord-0", 8_000)
        ok = e.open_position("BTC/USDT", "ord-1", 50_000, 0.03, 1_500)
        assert ok is True

    def test_no_reservation_uses_full_cash(self):
        """Rezerv yoksa tüm cash kullanılabilir."""
        e = make_engine(10_000)
        ok = e.open_position("BTC/USDT", "ord-1", 50_000, 0.1, 5_000)
        assert ok is True

    def test_open_position_fee_included_in_check(self):
        """Fee dahil kontrol yapılmalı."""
        e = make_engine(10_000)
        # notional=9950 + fee=100 = 10050 > available=10000 → blok
        ok = e.open_position("BTC/USDT", "ord-1", 50_000, 0.199, 9_950, fee=100)
        assert ok is False

    def test_invariant_after_open_with_reservation(self):
        e = make_engine(10_000)
        e.reserve_margin("ord-1", 3_000)
        e.open_position("BTC/USDT", "ord-1", 50_000, 0.1, 5_000)
        e.release_reservation("ord-1", 3_000)
        assert invariant_ok(e)


# ══════════════════════════════════════════════════════════════════════════════
# FIX-B: record_fee invariant kontrolü
# ══════════════════════════════════════════════════════════════════════════════

class TestRecordFeeInvariant:

    def test_invariant_holds_after_record_fee(self):
        e = make_engine(10_000)
        e.record_fee("BTC/USDT", "ord-1", 25.0, "swap fee")
        assert invariant_ok(e)

    def test_invariant_holds_after_multiple_fees(self):
        e = make_engine(10_000)
        for i in range(10):
            e.record_fee("BTC/USDT", f"ord-{i}", float(i * 5))
        assert invariant_ok(e)

    def test_record_fee_zero_ignored(self):
        """fee=0 durumunda _check_invariant çağrılmamalı — erken return."""
        e = make_engine(10_000)
        nav_before = e.nav
        e.record_fee("BTC/USDT", "ord-1", 0.0)
        assert e.nav == pytest.approx(nav_before)

    def test_record_fee_cash_never_negative(self):
        """Çok büyük fee cash'i negatife götürmemeli."""
        e = make_engine(1_000)
        e.record_fee("BTC/USDT", "ord-1", 2_000.0)
        assert e._cash >= 0.0


# ══════════════════════════════════════════════════════════════════════════════
# FIX-C: available_cash reserve nav bazlı
# ══════════════════════════════════════════════════════════════════════════════

class TestAvailableCashNavBased:

    def test_reserve_scales_with_nav_after_deposit(self):
        """
        reserve_pct=0.05
        initial=10000 → reserve=500 → available=9500
        deposit 5000 → nav=15000 → reserve=750 → available should decrease proportionally
        """
        e = CapitalEngine(
            initial_capital=10_000,
            journal_file="/tmp/test_ce_v3c.jsonl",
            reserve_pct=0.05,
            max_position_pct=1.0,
        )
        initial_available = e.available_cash
        assert initial_available == pytest.approx(9_500.0)  # 10000 - 500

        e.deposit(5_000)
        # nav=15000, reserve=15000*0.05=750, cash=15000, available=15000-750=14250
        assert e.available_cash == pytest.approx(14_250.0)

    def test_reserve_nav_based_no_deposit(self):
        """Deposit olmadan nav=initial → reserve aynı."""
        e = CapitalEngine(
            initial_capital=10_000,
            journal_file="/tmp/test_ce_v3c2.jsonl",
            reserve_pct=0.10,
        )
        # nav=10000, reserve=1000, available=9000
        assert e.available_cash == pytest.approx(9_000.0)

    def test_reserve_zero_pct(self):
        e = make_engine(10_000, reserve_pct=0.0)
        assert e.available_cash == pytest.approx(10_000.0)


# ══════════════════════════════════════════════════════════════════════════════
# FIX-D: Journal rotation
# ══════════════════════════════════════════════════════════════════════════════

class TestJournalRotation:

    def test_journal_rotates_when_size_exceeded(self, tmp_path):
        """50MB limitini simulate et — küçük limit ile test."""
        import capital_engine as ce_mod
        original_limit = ce_mod._JOURNAL_MAX_BYTES
        ce_mod._JOURNAL_MAX_BYTES = 500  # 500 byte limit — test için küçük

        try:
            journal_file = str(tmp_path / "test_journal.jsonl")
            e = CapitalEngine(
                initial_capital=10_000,
                journal_file=journal_file,
                reserve_pct=0.0,
            )
            # Yeterince kayıt üret — 500 byte'ı geçmesi için
            for i in range(20):
                e.open_position(f"SYM{i}/USDT", f"ord-{i}", 100.0, 1.0, 100.0)
                e.close_position(f"SYM{i}/USDT", f"close-{i}", 105.0, 1.0)

            # .bak dosyası oluştu mu?
            bak_file = journal_file + ".bak"
            assert os.path.exists(bak_file), "Rotation yapılmadı — .bak oluşmadı"
        finally:
            ce_mod._JOURNAL_MAX_BYTES = original_limit

    def test_journal_continues_after_rotation(self, tmp_path):
        """Rotation sonrası yazma devam etmeli."""
        import capital_engine as ce_mod
        original_limit = ce_mod._JOURNAL_MAX_BYTES
        ce_mod._JOURNAL_MAX_BYTES = 200

        try:
            journal_file = str(tmp_path / "test_journal2.jsonl")
            e = CapitalEngine(10_000, journal_file=journal_file, reserve_pct=0.0)
            for i in range(10):
                e.deposit(100)
            # Yeni journal dosyası hâlâ yazılabilir olmalı
            assert os.path.exists(journal_file)
        finally:
            ce_mod._JOURNAL_MAX_BYTES = original_limit


# ══════════════════════════════════════════════════════════════════════════════
# FIX-E: _margin_used negatif guard
# ══════════════════════════════════════════════════════════════════════════════

class TestMarginUsedNeverNegative:

    def test_margin_never_negative_on_full_close(self):
        e = make_engine(10_000)
        e.open_position("BTC/USDT", "ord-1", 50_000, 0.1, 5_000)
        e.close_position("BTC/USDT", "ord-2", 50_000, 0.1)
        assert e._margin_used >= 0.0

    def test_margin_never_negative_on_loss(self):
        """Büyük zararda margin_used negatife düşmemeli."""
        e = make_engine(10_000)
        e.open_position("BTC/USDT", "ord-1", 50_000, 0.1, 5_000)
        e.close_position("BTC/USDT", "ord-2", 1.0, 0.1)  # neredeyse sıfır fiyat
        assert e._margin_used >= 0.0

    def test_margin_zero_after_all_closed(self):
        e = make_engine(20_000)
        e.open_position("BTC/USDT", "ord-1", 50_000, 0.1, 5_000)
        e.open_position("ETH/USDT", "ord-2", 3_000, 1.0, 3_000)
        e.close_position("BTC/USDT", "ord-3", 52_000, 0.1)
        e.close_position("ETH/USDT", "ord-4", 2_800, 1.0)
        assert e._margin_used == pytest.approx(0.0, abs=1e-8)

    def test_nav_not_affected_by_float_negative_margin(self):
        """_margin_used=0 guard nav'ı float kirlilikten korumalı."""
        e = make_engine(10_000)
        e.open_position("BTC/USDT", "ord-1", 50_000, 0.1, 5_000)
        e.close_position("BTC/USDT", "ord-2", 50_000, 0.1)
        # nav hesabında negatif margin_used olmamalı
        assert e.nav >= 0.0
        assert invariant_ok(e)


# ══════════════════════════════════════════════════════════════════════════════
# Kombinasyon testi
# ══════════════════════════════════════════════════════════════════════════════

class TestCombinedV3:

    def test_full_scenario_with_all_fixes(self):
        """Tüm 5 fix birlikte çalışıyor mu?"""
        e = CapitalEngine(
            initial_capital=10_000,
            journal_file="/tmp/test_ce_v3_combined.jsonl",
            reserve_pct=0.05,
            max_position_pct=1.0,
        )
        # FIX-C: nav bazlı reserve
        assert e.available_cash == pytest.approx(9_500.0)

        # Rezerv koy
        e.reserve_margin("ord-1", 3_000)
        assert e.available_cash == pytest.approx(6_500.0)

        # FIX-A: available_cash ile kontrol
        ok_big = e.open_position("BTC/USDT", "ord-2", 50_000, 0.2, 10_000)  # too big
        assert ok_big is False

        ok = e.open_position("BTC/USDT", "ord-1", 50_000, 0.1, 5_000)
        assert ok is True
        e.release_reservation("ord-1", 3_000)

        # FIX-B: record_fee invariant
        e.record_fee("BTC/USDT", "ord-1", 10.0)
        assert invariant_ok(e)

        # FIX-E: margin guard
        e.close_position("BTC/USDT", "ord-3", 52_000, 0.1)
        assert e._margin_used >= 0.0
        assert invariant_ok(e)
