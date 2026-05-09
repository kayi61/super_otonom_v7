"""
Cross-Module Invariant Testi
============================
Test: RiskManager._peak_equity ile CapitalEngine.nav zamanla kopuyor mu?

Senaryo:
  1. onto=None olarak başlatılır (RiskOntology bağlı değil)
  2. NAV yükselir → BotEngine._peak_equity güncellenir
  3. Ama RiskManager._peak_equity güncellenmez (update_peak() çağrılmıyor)
  4. NAV düşer → drawdown hesabı yanlış yapılır
  5. Emergency stop gerekirken tetiklenmez

Beklenen: TEST FAIL → bug gerçek
Düzeltme sonrası: TEST PASS
"""

import sys, os, types, logging
logging.disable(logging.CRITICAL)

# ── Ortam hazırlığı ──────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, '/mnt/user-data/uploads')

sys.modules.setdefault("super_otonom", types.ModuleType("super_otonom"))
cfg = types.ModuleType("super_otonom.config")
cfg.RISK = {
    "max_daily_loss_pct":       0.03,
    "max_weekly_loss_pct":      0.10,
    "max_total_drawdown":       0.15,   # %15 drawdown → emergency
    "max_exposure_pct":         0.95,
    "var_confidence":           0.95,
    "trailing_stop_pct":        0.02,
    "exposure_breach_emergency": False,
    "max_notional_per_order":   50000.0,
    "max_spread_pct":           0.005,
    "min_ob_depth":             1000.0,
}
sys.modules["super_otonom.config"] = cfg

import numpy as np
sys.modules.setdefault("numpy", np)

from capital_engine import CapitalEngine
from risk_manager   import RiskManager

# ── Sayaçlar ─────────────────────────────────────────────────────────────────
PASS = 0
FAIL = 0
FAILURES = []

def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ✓ {label}")
    else:
        FAIL += 1
        msg = f"  ✗ {label}" + (f" | {detail}" if detail else "")
        FAILURES.append(msg)
        print(msg)

# ── Fabrikalar ────────────────────────────────────────────────────────────────
import tempfile

def make_ce(cap=10000.0):
    t = tempfile.mkdtemp()
    return CapitalEngine(
        cap,
        journal_file=f"{t}/j.jsonl",
        reserve_pct=0.0,
        max_position_pct=1.0,
    )

def make_rm(cap=10000.0):
    return RiskManager(initial_capital=cap)

# ════════════════════════════════════════════════════════════════════════════
# TEST 1: onto=None durumunda peak_equity desynk
# ════════════════════════════════════════════════════════════════════════════
print("\n── TEST 1: RiskManager._peak_equity desynk (onto=None) ──")

ce = make_ce(10000.0)
rm = make_rm(10000.0)
# onto BAĞLANMIYOR — kritik nokta

# Adım 1: pozisyon aç, NAV yükselsin
oid = "test_order_1"
ce.open_position("BTC/USDT", oid, 50000.0, 0.1, 5000.0)
ce.update_unrealized({"BTC/USDT": 55000.0})   # +500 kar

nav_peak = ce.nav  # ~10500
check(
    "T1.1 nav_peak doğru hesaplandı",
    nav_peak > 10000.0,
    f"nav_peak={nav_peak:.2f}",
)

# Adım 2: RiskManager'a peak bildiriliyor mu?
# BotEngine'de update_peak() çağrılmıyor — simüle ediyoruz
rm_peak_before = rm._peak_equity
check(
    "T1.2 rm._peak_equity hala initial (güncellenmedi)",
    rm._peak_equity == 10000.0,
    f"rm._peak_equity={rm._peak_equity:.2f} (beklenen=10000.0)",
)

# Adım 3: NAV sert düşsün — %20 drawdown
ce.update_unrealized({"BTC/USDT": 35000.0})   # büyük zarar
nav_now = ce.nav
real_dd = (nav_peak - nav_now) / nav_peak

check(
    "T1.3 gerçek drawdown %15 üstünde",
    real_dd > 0.15,
    f"real_dd={real_dd*100:.1f}%",
)

# Adım 4: RiskManager drawdown'ı doğru görüyor mu?
# rm._peak_equity=10000 (eski), nav_now düşük
risk_result = rm.check_risk(
    current_equity=nav_now,
    open_exposure=ce._margin_used,
    current_vol=0.0,
)

# RiskManager'ın hesapladığı drawdown
if rm._peak_equity > 0:
    rm_dd = (rm._peak_equity - nav_now) / rm._peak_equity
else:
    rm_dd = 0.0

check(
    "T1.4 rm drawdown hesabı gerçek peak'e göre YANLIŞ",
    abs(rm_dd - real_dd) > 0.01,
    f"rm_dd={rm_dd*100:.1f}% real_dd={real_dd*100:.1f}% fark={abs(rm_dd-real_dd)*100:.1f}%",
)

# Adım 5: Emergency tetiklenmeli miydi?
check(
    "T1.5 emergency_stop tetiklenmeli (drawdown > %15)",
    not risk_result,  # False dönmeli
    f"risk_result={risk_result} (False bekleniyor)",
)

# ════════════════════════════════════════════════════════════════════════════
# TEST 2: onto=None, update_peak MANUEL çağrılsaydı doğru çalışır mıydı?
# ════════════════════════════════════════════════════════════════════════════
print("\n── TEST 2: update_peak() manuel çağrıldığında emergency doğru tetiklenir ──")

ce2 = make_ce(10000.0)
rm2 = make_rm(10000.0)

# Pozisyon aç
oid2 = "test_order_2"
ce2.open_position("ETH/USDT", oid2, 2000.0, 1.0, 2000.0)
ce2.update_unrealized({"ETH/USDT": 2400.0})  # +400 kar

nav_peak2 = ce2.nav
rm2.update_peak(nav_peak2)  # MANUEL çağrı — düzeltme simülasyonu

check(
    "T2.1 rm._peak_equity güncellendi",
    rm2._peak_equity == nav_peak2,
    f"rm._peak_equity={rm2._peak_equity:.2f} nav_peak={nav_peak2:.2f}",
)

# Sert düşüş — %15 üstünde drawdown için fiyatı yeterince düşür
# nav_peak2 ≈ 10400, %15 dd için nav < 10400*0.85 = 8840 gerekli
# entry=2000, qty=1 → unrealized = (price-2000)*1
# nav = cash(8000) + margin(2000) + unrealized
# nav < 8840 → unrealized < -1160 → price < 840
ce2.update_unrealized({"ETH/USDT": 700.0})   # büyük zarar, %15+ dd garantili
nav_now2 = ce2.nav
real_dd2 = (nav_peak2 - nav_now2) / nav_peak2

rm2.update_peak(nav_now2)  # peak düşmez, bu çağrı etkisiz (doğru davranış)

risk_result2 = rm2.check_risk(
    current_equity=nav_now2,
    open_exposure=ce2._margin_used,
    current_vol=0.0,
)

check(
    "T2.2 update_peak sonrası emergency doğru tetiklendi",
    not risk_result2,
    f"risk_result={risk_result2} real_dd={real_dd2*100:.1f}%",
)

check(
    "T2.3 emergency_reason doğru",
    rm2.emergency_reason == "max_drawdown",
    f"emergency_reason={rm2.emergency_reason}",
)

# ════════════════════════════════════════════════════════════════════════════
# TEST 3: Margin tutarlılığı — pozisyon kapandıktan sonra margin sıfır mu?
# ════════════════════════════════════════════════════════════════════════════
print("\n── TEST 3: Kapanış sonrası margin tutarlılığı ──")

ce3 = make_ce(10000.0)

oid3 = "test_order_3"
ce3.open_position("SOL/USDT", oid3, 100.0, 10.0, 1000.0)

check(
    "T3.1 açılış sonrası margin_used > 0",
    ce3._margin_used > 0,
    f"margin_used={ce3._margin_used:.2f}",
)

ce3.close_position("SOL/USDT", "close_3", 110.0, 10.0)

check(
    "T3.2 kapanış sonrası margin_used == 0",
    abs(ce3._margin_used) < 0.01,
    f"margin_used={ce3._margin_used:.2f} (0 bekleniyor)",
)

check(
    "T3.3 kapanış sonrası pozisyon defterinde yok",
    "SOL/USDT" not in ce3._positions,
    f"positions={list(ce3._positions.keys())}",
)

check(
    "T3.4 invariant korunuyor",
    ce3._check_invariant(),
    f"nav={ce3.nav:.2f}",
)

# ════════════════════════════════════════════════════════════════════════════
# TEST 4: Senaryo zinciri — open→price_drop→close→re_open
# ════════════════════════════════════════════════════════════════════════════
print("\n── TEST 4: Senaryo zinciri cross-module ──")

ce4 = make_ce(10000.0)
rm4 = make_rm(10000.0)

# t0: pozisyon aç — küçük notional (günlük limiti zorlamayalım)
ce4.open_position("BTC/USDT", "o1", 50000.0, 0.01, 500.0)
rm4.update_peak(ce4.nav)

# t1: fiyat hafif düşer
ce4.update_unrealized({"BTC/USDT": 48000.0})
rm4.update_peak(ce4.nav)

# t2: kapat — küçük zarar (%2 altında kalmalı)
pnl = ce4.close_position("BTC/USDT", "c1", 48000.0, 0.01)
if pnl is not None:
    rm4.record_pnl(pnl)

check(
    "T4.1 kapanış sonrası zarar kaydedildi",
    rm4.daily_loss > 0,
    f"daily_loss={rm4.daily_loss:.2f}",
)

# t3: tekrar aç
ce4.open_position("BTC/USDT", "o2", 45000.0, 0.1, 4500.0)

check(
    "T4.2 ikinci açılış sonrası invariant korunuyor",
    ce4._check_invariant(),
    f"nav={ce4.nav:.2f}",
)

check(
    "T4.3 margin_used pozitif",
    ce4._margin_used > 0,
    f"margin_used={ce4._margin_used:.2f}",
)

# t4: CapitalEngine.nav ile risk check tutarlı mı?
risk_ok = rm4.check_risk(
    current_equity=ce4.nav,
    open_exposure=ce4._margin_used,
    current_vol=0.0,   # vol=0 → static limit kullanılır, %3 günlük kayıp
)

# NAV hala pozitif, drawdown küçük → risk geçmeli
check(
    "T4.4 düşük kayıp sonrası risk check geçiyor",
    risk_ok is True,
    f"risk_ok={risk_ok} nav={ce4.nav:.2f}",
)

# ════════════════════════════════════════════════════════════════════════════
# SONUÇ
# ════════════════════════════════════════════════════════════════════════════
total = PASS + FAIL
print(f"\n{'='*60}")
print(f"TOPLAM : {total}")
print(f"GEÇEN  : {PASS}")
print(f"FAIL   : {FAIL}")
print(f"{'='*60}")

if FAILURES:
    print(f"\nBAŞARISIZ {len(FAILURES)} TEST:")
    for f in FAILURES:
        print(f"  {f}")
    print(
        "\n⚠️  DÜZELTME ÖNERİSİ (T1/T2 için):\n"
        "  bot_engine.py → tick() içinde şunu ekle:\n"
        "    self.risk.update_peak(self.capital.nav)\n"
        "  Mevcut satır:\n"
        "    if self.equity > self._peak_equity:\n"
        "        self._peak_equity = self.equity\n"
        "  Sonrası:\n"
        "    if self.equity > self._peak_equity:\n"
        "        self._peak_equity = self.equity\n"
        "    self.risk.update_peak(self.capital.nav)  # ← EKLE\n"
    )
else:
    print("\n✓ TÜM TESTLER GEÇTİ")
