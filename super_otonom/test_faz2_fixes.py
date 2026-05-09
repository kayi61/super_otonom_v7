"""
test_faz2_fixes.py
─────────────────────────────────────────────────────────────────────────────
Faz 2 (RiskOntology + RiskManager) 6 bug fix testleri:

  FIX-1: Çift state — record_pnl onto'ya da iletiliyor
  FIX-2: check_dynamic_risk yanlış payda (initial_capital → current_equity)
  FIX-4: VaR min_history 20 → 100
  FIX-5: sod_nav tick gecikmesi — nav önce güncelleniyor
  FIX-6: onto=None sessiz fallback → WARNING log
"""
from __future__ import annotations
import logging, sys, os, time
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Minimal stub — gerçek modüller olmadan test
import types

# Config stub
cfg = types.ModuleType("super_otonom.config")
cfg.RISK = {
    "max_daily_loss_pct":   0.03,
    "max_weekly_loss_pct":  0.10,
    "max_total_drawdown":   0.15,
    "max_exposure_pct":     0.95,
    "var_confidence":       0.95,
    "trailing_stop_pct":    0.02,
    "exposure_breach_emergency": False,
}
sys.modules["super_otonom"] = types.ModuleType("super_otonom")
sys.modules["super_otonom.config"] = cfg

import numpy as np
from risk_ontology import RiskOntology
from risk_manager  import RiskManager


# ── Yardımcılar ───────────────────────────────────────────────────────────────

def make_onto(nav=10_000.0):
    return RiskOntology(initial_nav=nav)

def make_rm(capital=10_000.0):
    return RiskManager(initial_capital=capital)

def make_rm_with_onto(capital=10_000.0):
    rm   = make_rm(capital)
    onto = make_onto(capital)
    rm.set_ontology(onto)
    return rm, onto


# ══════════════════════════════════════════════════════════════════════════════
# FIX-5: sod_nav tick gecikmesi
# ══════════════════════════════════════════════════════════════════════════════

class TestSodNavTiming:

    def test_sod_nav_uses_current_nav_on_reset(self):
        """
        Gün sıfırlandığında sod_nav güncel nav'ı almalı, bir tick öncekini değil.
        """
        onto = make_onto(10_000)
        # nav'ı 11000'e taşı
        onto.update(nav=11_000)
        # Gün sıfırını simüle et — _day_start'ı geçmişe çek
        onto._day_start = time.time() - 90_000
        onto.update(nav=11_000)
        # sod_nav 11000 olmalı, 10000 değil
        assert onto.sod_nav == pytest.approx(11_000.0)

    def test_daily_loss_pct_zero_at_start_of_day(self):
        """Gün başında daily_loss_pct sıfır olmalı."""
        onto = make_onto(10_000)
        onto.update(nav=10_000)
        assert onto.daily_loss_pct == pytest.approx(0.0)

    def test_daily_loss_pct_correct_after_loss(self):
        """10000 → 9500: daily_loss_pct = %5."""
        onto = make_onto(10_000)
        onto.update(nav=10_000)
        onto.update(nav=9_500)
        assert onto.daily_loss_pct == pytest.approx(0.05, abs=0.001)

    def test_nav_updated_before_sod_reset(self):
        """
        FIX-5 doğrulama: sod_nav = self.nav çağrısı
        self.nav = float(nav) SONRASINDA olmalı.
        """
        onto = make_onto(10_000)
        onto.update(nav=12_000)  # nav = 12000
        onto._day_start = time.time() - 90_000
        onto.update(nav=12_500)  # gün sıfırlanıyor — sod_nav 12500 olmalı
        assert onto.sod_nav == pytest.approx(12_500.0)


# ══════════════════════════════════════════════════════════════════════════════
# FIX-4: VaR minimum history
# ══════════════════════════════════════════════════════════════════════════════

class TestVaRMinHistory:

    def test_var_zero_below_100_samples(self):
        """99 örnekle VaR sıfır dönmeli."""
        onto = make_onto(10_000)
        for i in range(99):
            onto.update(nav=10_000, realized_pnl_delta=float(-i))
        assert onto.var_1d == 0.0

    def test_var_nonzero_at_100_samples(self):
        """100 örnekle VaR hesaplanmalı."""
        onto = make_onto(10_000)
        for i in range(1, 101):   # 1'den başla — delta=0 atlanıyor
            onto.update(nav=10_000, realized_pnl_delta=float(-i * 10))
        assert onto.var_1d != 0.0

    def test_var_value_reasonable(self):
        """200 örnekle VaR makul bir negatif değer olmalı."""
        onto = make_onto(10_000)
        losses = [-abs(x) for x in range(1, 201)]
        for l in losses:
            onto.update(nav=10_000, realized_pnl_delta=l)
        # VaR negatif olmalı (kayıp senaryosu)
        assert onto.var_1d < 0


# ══════════════════════════════════════════════════════════════════════════════
# FIX-2: check_dynamic_risk payda
# ══════════════════════════════════════════════════════════════════════════════

class TestDynamicRiskDenominator:

    def test_dynamic_risk_uses_current_equity(self):
        """
        initial_capital=10000, current_equity=20000 (büyük kâr sonrası).
        daily_loss=500.
        initial_capital bazlı: 500/10000 = %5 → limit aşıldı (yanlış)
        current_equity bazlı: 500/20000 = %2.5 → limit aşılmadı (doğru)
        """
        rm = make_rm(10_000)
        rm.daily_loss = 500.0
        # vol=0.02 → dynamic_limit = clamp(0.04, 0.02, 0.05) = 0.04 (%4)
        # current_equity=20000 → daily_pct = 500/20000 = 0.025 < 0.04 → geçmeli
        result = rm.check_dynamic_risk(current_equity=20_000, market_volatility=0.02)
        assert result is True

    def test_dynamic_risk_blocks_correctly(self):
        """
        current_equity=10000, daily_loss=500, vol=0.02 → limit=%4
        500/10000 = %5 > %4 → bloklanmalı
        """
        rm = make_rm(10_000)
        rm.daily_loss = 500.0
        result = rm.check_dynamic_risk(current_equity=10_000, market_volatility=0.02)
        assert result is False

    def test_dynamic_limit_clamp_low(self):
        """vol=0.001 → limit clamp → %2 minimum."""
        rm = make_rm(10_000)
        rm.daily_loss = 150.0  # %1.5 < %2 → geçmeli
        result = rm.check_dynamic_risk(current_equity=10_000, market_volatility=0.001)
        assert result is True

    def test_dynamic_limit_clamp_high(self):
        """vol=0.10 → limit clamp → %5 maximum."""
        rm = make_rm(10_000)
        rm.daily_loss = 400.0  # %4 < %5 → geçmeli
        result = rm.check_dynamic_risk(current_equity=10_000, market_volatility=0.10)
        assert result is True


# ══════════════════════════════════════════════════════════════════════════════
# FIX-1: Çift state — record_pnl onto senkronizasyonu
# ══════════════════════════════════════════════════════════════════════════════

class TestDoubleStateFix:

    def test_record_pnl_feeds_onto_pnl_history(self):
        """record_pnl çağrıldığında onto._pnl_history de dolmalı."""
        rm, onto = make_rm_with_onto(10_000)
        rm.record_pnl(-100.0)
        assert len(onto._pnl_history) == 1
        assert onto._pnl_history[0] == pytest.approx(-100.0)

    def test_record_pnl_without_onto_no_crash(self):
        """onto yoksa record_pnl hata vermemeli."""
        rm = make_rm(10_000)
        rm.record_pnl(-50.0)
        assert rm.daily_loss == pytest.approx(50.0)

    def test_var_updated_via_record_pnl(self):
        """100+ pnl kaydından sonra onto.var_1d güncellenmeli."""
        rm, onto = make_rm_with_onto(10_000)
        for i in range(100):
            rm.record_pnl(float(-i * 10))
        assert onto.var_1d != 0.0

    def test_onto_pnl_history_capped_at_500(self):
        """onto._pnl_history 500'ü aşmamalı."""
        rm, onto = make_rm_with_onto(10_000)
        for i in range(600):
            rm.record_pnl(float(-i))
        assert len(onto._pnl_history) <= 500


# ══════════════════════════════════════════════════════════════════════════════
# FIX-6: onto=None sessiz fallback → WARNING
# ══════════════════════════════════════════════════════════════════════════════

class TestOntoNoneWarning:

    def test_warn_if_onto_missing_logs_warning(self, caplog):
        """onto=None iken check_risk WARNING log üretmeli."""
        rm = make_rm(10_000)
        with caplog.at_level(logging.WARNING, logger="super_otonom.risk"):
            rm._warn_if_onto_missing()
        assert any("onto=None" in r.message for r in caplog.records)

    def test_no_warning_when_onto_set(self, caplog):
        """onto bağlıyken WARNING üretmemeli."""
        rm, onto = make_rm_with_onto(10_000)
        with caplog.at_level(logging.WARNING, logger="super_otonom.risk"):
            rm._warn_if_onto_missing()
        assert not any("onto=None" in r.message for r in caplog.records)

    def test_set_ontology_logs_info(self, caplog):
        """set_ontology() INFO log üretmeli."""
        rm   = make_rm(10_000)
        onto = make_onto(10_000)
        with caplog.at_level(logging.INFO, logger="super_otonom.risk"):
            rm.set_ontology(onto)
        assert any("baglandi" in r.message for r in caplog.records)


# ══════════════════════════════════════════════════════════════════════════════
# RiskOntology genel doğruluk
# ══════════════════════════════════════════════════════════════════════════════

class TestRiskOntologyGeneral:

    def test_daily_loss_pct_never_negative(self):
        """NAV artarsa daily_loss_pct sıfır kalmalı (negatife düşmemeli)."""
        onto = make_onto(10_000)
        onto.update(nav=10_000)
        onto.update(nav=11_000)   # kâr — kayıp yok
        assert onto.daily_loss_pct == pytest.approx(0.0)

    def test_peak_nav_monotonically_increases(self):
        """peak_nav hiç azalmamalı."""
        onto = make_onto(10_000)
        navs = [10_000, 11_000, 10_500, 12_000, 9_000]
        for n in navs:
            onto.update(nav=n)
        assert onto.peak_nav == pytest.approx(12_000.0)

    def test_intraday_dd_correct(self):
        """peak=12000, nav=9000 → dd = (12000-9000)/12000 = %25."""
        onto = make_onto(10_000)
        onto.update(nav=12_000)
        onto.update(nav=9_000)
        assert onto.intraday_dd_pct == pytest.approx(0.25, abs=0.001)

    def test_is_daily_limit_breached(self):
        """daily_loss_pct >= dynamic_daily_limit → True."""
        onto = make_onto(10_000)
        onto.update(nav=10_000)
        onto.dynamic_daily_limit = 0.03
        onto.update(nav=9_600)   # %4 kayıp > %3 limit
        assert onto.is_daily_limit_breached() is True

    def test_is_drawdown_breached(self):
        """dd >= 0.15 → True."""
        onto = make_onto(10_000)
        onto.update(nav=10_000)
        onto.update(nav=8_400)   # %16 dd
        assert onto.is_drawdown_breached(max_dd=0.15) is True

    def test_snapshot_keys(self):
        onto = make_onto(10_000)
        snap = onto.snapshot()
        for key in ["nav", "sod_nav", "peak_nav", "intraday_dd_pct",
                    "daily_loss_pct", "weekly_loss_pct", "var_1d",
                    "gross_exp", "net_exp", "exp_pct"]:
            assert key in snap

    def test_round_trip(self):
        """to_dict / from_dict round-trip."""
        onto = make_onto(10_000)
        onto.update(nav=10_500)
        d    = onto.to_dict()
        onto2 = RiskOntology.from_dict(d)
        assert onto2.nav      == pytest.approx(onto.nav)
        assert onto2.sod_nav  == pytest.approx(onto.sod_nav)
        assert onto2.peak_nav == pytest.approx(onto.peak_nav)
