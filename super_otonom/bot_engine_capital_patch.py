"""
BotEngine ↔ CapitalEngine entegrasyon rehberi
─────────────────────────────────────────────────────────────────────────────
Bu dosya doğrudan çalıştırılmaz; bot_engine.py'ye uygulanacak diff/patch'i
gösterir. Her bölümün altında açıklama var.

Uygulama sırası:
  1. capital_engine.py → super_otonom/ altına koy
  2. bot_engine.py'de aşağıdaki 4 bölümü güncelle
  3. Testleri çalıştır: pytest tests/ -n auto
"""

# ═══════════════════════════════════════════════════════════════════════════════
# BÖLÜM 1 — Import ekle (bot_engine.py başına)
# ═══════════════════════════════════════════════════════════════════════════════

# Şu satırların bulunduğu yere ekle:
# from super_otonom.trade_logger import TradeLogger  (varsa)
#
# EKLE:
# from super_otonom.capital_engine import CapitalEngine

IMPORT_PATCH = """
from super_otonom.capital_engine import CapitalEngine
"""


# ═══════════════════════════════════════════════════════════════════════════════
# BÖLÜM 2 — BotEngine.__init__() içinde capital engine başlatma
# ═══════════════════════════════════════════════════════════════════════════════
#
# MEVCUT (satır ~255):
#   self.equity       = float(capital)
#   self.free_capital = float(capital)
#   self._peak_equity = float(capital)
#
# YENİ — bu üç satırın ALTINA ekle:
#   self.capital = CapitalEngine(capital)
#
# Geriye dönük uyumluluk için equity/free_capital property'leri
# CapitalEngine içinde zaten tanımlı; BotEngine'deki ham değişkenler
# korunabilir veya kaldırılabilir. Güvenli geçiş için önce koru.

INIT_PATCH = """
# v9 — CapitalEngine entegrasyonu
self.capital = CapitalEngine(
    initial_capital=capital,
    max_position_pct=RISK.get("max_position_pct", 0.95),
    reserve_pct=RISK.get("capital_reserve_pct", 0.05),
)
"""


# ═══════════════════════════════════════════════════════════════════════════════
# BÖLÜM 3 — _handle_entry() içinde pozisyon açılışı
# ═══════════════════════════════════════════════════════════════════════════════
#
# MEVCUT (satır ~632-639):
#   self.open_positions[symbol] = {
#       "entry": fill_price, "qty": qty, "size": size, ...
#   }
#   self.free_capital -= size
#
# YENİ — open_positions kaydından SONRA CapitalEngine'i güncelle:

ENTRY_PATCH = """
# CapitalEngine ledger güncellemesi
fee = float(analysis.get("fee", 0.0))          # exchange fee varsa analysis'e ekle
self.capital.open_position(
    symbol=symbol,
    order_id=str(action.get("order_id", f"{symbol}_{int(time.time()*1000)}")),
    entry_price=fill_price,
    qty=qty,
    notional=size,
    fee=fee,
)
# Geriye dönük uyumluluk — eski free_capital değişkenini senkronize et
self.free_capital = self.capital.available_cash
self.equity       = self.capital.nav
"""


# ═══════════════════════════════════════════════════════════════════════════════
# BÖLÜM 4 — _close() içinde pozisyon kapanışı
# ═══════════════════════════════════════════════════════════════════════════════
#
# MEVCUT (satır ~731-733):
#   pnl = (exit_px - entry) * filled_qty
#   self.equity       += pnl
#   self.free_capital  = max(0.0, self.free_capital + size + pnl)   ← daha önce fix edildi
#
# YENİ — bu üç satırı REPLACE et:

CLOSE_PATCH = """
# CapitalEngine ledger güncellemesi — çift kayıt
fee = float(analysis.get("fee", 0.0))
pnl = self.capital.close_position(
    symbol=symbol,
    order_id=pos.get("order_id", f"{symbol}_close_{int(time.time()*1000)}"),
    exit_price=exit_px,
    filled_qty=filled_qty,
    fee=fee,
)
if pnl is None:
    # Pozisyon ledger'da bulunamadı — fallback hesap
    pnl = (exit_px - entry) * filled_qty
    log.warning("CapitalEngine: pozisyon bulunamadı, fallback pnl=%.4f", pnl)

# Geriye dönük uyumluluk
self.equity       = self.capital.nav
self.free_capital = self.capital.available_cash
"""


# ═══════════════════════════════════════════════════════════════════════════════
# BÖLÜM 5 — tick() içinde unrealized güncelleme
# ═══════════════════════════════════════════════════════════════════════════════
#
# tick() başında (satır ~442, price hesaplandıktan sonra) ekle:

TICK_PATCH = """
# Unrealized PnL güncelle (tüm açık pozisyonlar için)
if self.open_positions:
    prices = {sym: float(candles[-1]["close"]) if sym == symbol
              else float(self.open_positions[sym].get("entry", 0))
              for sym in self.open_positions}
    self.capital.update_unrealized(prices)
    self.equity = self.capital.nav
"""


# ═══════════════════════════════════════════════════════════════════════════════
# BÖLÜM 6 — status() içinde capital snapshot ekle
# ═══════════════════════════════════════════════════════════════════════════════
#
# status() return dict'ine ekle:

STATUS_PATCH = """
"capital": self.capital.snapshot(),
"""


# ═══════════════════════════════════════════════════════════════════════════════
# BÖLÜM 7 — _save_state() / _load_state() güncellemesi
# ═══════════════════════════════════════════════════════════════════════════════
#
# _save_state() state dict'ine ekle:
#   "capital_engine": self.capital.to_dict(),
#
# _load_state() içinde yükle:
#   if "capital_engine" in state:
#       self.capital = CapitalEngine.from_dict(state["capital_engine"])

PERSISTENCE_PATCH = """
# _save_state() içine:
state["capital_engine"] = self.capital.to_dict()

# _load_state() içine (state yüklendikten sonra):
if "capital_engine" in state:
    self.capital = CapitalEngine.from_dict(
        state["capital_engine"],
        max_position_pct=RISK.get("max_position_pct", 0.95),
        reserve_pct=RISK.get("capital_reserve_pct", 0.05),
    )
    self.equity       = self.capital.nav
    self.free_capital = self.capital.available_cash
"""

# ═══════════════════════════════════════════════════════════════════════════════
# Uygulama tamamlandığında kontrol listesi:
# ─────────────────────────────────────────────────────────────────────────────
# [ ] capital_engine.py → super_otonom/ klasörüne kopyalandı
# [ ] bot_engine.py'ye 7 bölüm uygulandı
# [ ] pytest tests/ -n auto → yeşil
# [ ] data/capital_journal.jsonl oluştu ve trade kayıtları görünüyor
# [ ] engine.status()["capital"] snapshot dönüyor
# [ ] engine.capital.snapshot()["nav"] == engine.equity
# ═══════════════════════════════════════════════════════════════════════════════
