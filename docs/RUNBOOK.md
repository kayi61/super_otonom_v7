# super_otonom Operasyon Runbook v1.0

## Bot Durumu Kontrol

```bash
# Sağlık durumu
cat logs/health.log | tail -20

# Son trades
cat data/trades.log | tail -10

# Audit log
cat data/audit/audit_$(date +%Y-%m-%d).jsonl | tail -20

# Capital durumu
python3 -c "
import json
s = json.load(open('data/bot_state.json'))
c = s.get('capital_engine', {})
print(f'NAV: {c.get(\"cash\",0) + c.get(\"margin_used\",0):.2f}')
print(f'Cash: {c.get(\"cash\",0):.2f}')
print(f'Margin: {c.get(\"margin_used\",0):.2f}')
print(f'Realized PnL: {c.get(\"realized_pnl\",0):.4f}')
"
```

---

## Senaryo 1 — Bot çöktü, yeniden başlatma

```bash
# 1. Durumu kontrol et
cat logs/health.log | tail -5

# 2. PENDING emirleri kontrol et
cat data/pending_orders.json

# 3. Borsayı kontrol et — manuel olarak açık pozisyon var mı?
# Exchange web arayüzünden kontrol et

# 4. Botu yeniden başlat
python -m super_otonom.main_loop

# Bot başlarken otomatik:
# - ReconciliationEngine.startup_handshake() çalışır
# - PENDING emirler borsaya sorgulanır
# - NAV farkı %2 üzerindeyse uyarı, %10 üzerindeyse hard block
```

**Hard block durumunda:**
```bash
# data/recon/ klasörüne bak
ls data/recon/
cat data/recon/recon_*_startup.json | python3 -m json.tool

# Fark makul ise manuel override:
# bot_state.json'da capital_engine.cash değerini borsa bakiyesiyle hizala
# SONRA botu başlat
```

---

## Senaryo 2 — Emergency stop tetiklendi

```bash
# Sebebi bul
grep "EMERGENCY_STOP" logs/health.log | tail -5

# Audit log'a bak
grep "EMERGENCY" data/audit/audit_$(date +%Y-%m-%d).jsonl

# Yaygın sebepler:
# dynamic_daily_loss → günlük kayıp limiti aşıldı
# max_drawdown       → peak-to-trough drawdown aşıldı
# weekly_loss        → haftalık kayıp limiti aşıldı
# rate_limit_storm   → borsa 429 fırtınası
```

**Manuel reset (dikkatli!):**
```python
# Sadece sebebi anladıktan sonra:
engine.risk.reset_emergency()
```

---

## Senaryo 3 — Reconciliation farkı büyük

```bash
# Raporu gör
cat data/recon/recon_*_startup.json | python3 -m json.tool

# Fark nereden geliyor?
# 1. Kısmi fill — filled_qty != qty
# 2. Borsa fee tahmini hatalı
# 3. Bot çalışırken manuel işlem yapıldı

# Capital engine'i borsa ile hizala:
# bot_state.json → capital_engine.cash = borsa_bakiye - margin_used
```

---

## Senaryo 4 — Yüksek slippage / TCA anomalisi

```bash
# TCA log'a bak
grep "TCA" logs/health.log | tail -10

# Olası sebepler:
# - OB derinliği yetersiz (ob_depth düşük)
# - Volatilite çok yüksek
# - Emir boyutu çok büyük

# Çözüm:
# config.py → RISK["max_notional_per_order"] değerini düşür
# config.py → RISK["min_ob_depth"] değerini artır
```

---

## Senaryo 5 — Heartbeat timeout

```bash
grep "HEARTBEAT_TIMEOUT" logs/health.log | tail -5

# Exchange bağlantısı kesilmiş
# Circuit breaker açık olabilir
grep "CircuitBreaker" logs/health.log | tail -10

# Çözüm: botu yeniden başlat
# Adaptive throttle otomatik devreye girer
```

---

## Günlük Kontrol Listesi

```
[ ] logs/health.log → son 1 saatte EMERGENCY var mı?
[ ] data/audit/ → bugünkü trade sayısı beklenen aralıkta mı?
[ ] data/reconcile/ → dünkü reconcile raporu PASSED mı?
[ ] NAV bugün başlangıca göre makul mı?
[ ] Circuit breaker açık sembol var mı?
[ ] Webhook alarmları geldi mi?
```

---

## Kritik Dosyalar

| Dosya | Amaç |
|---|---|
| `data/bot_state.json` | Bot durumu — restart'ta buradan yüklenir |
| `data/capital_journal.jsonl` | Her ledger değişikliği — audit kaydı |
| `data/pending_orders.json` | In-flight emirler — restart recovery |
| `data/orders.jsonl` | Tüm emir geçmişi |
| `data/audit/` | Günlük audit logları |
| `data/recon/` | Reconciliation raporları |
| `logs/health.log` | Sistem sağlık logu |

---

## Acil İletişim

```
WEBHOOK_URL=https://hooks.slack.com/... → .env dosyasında tanımla
ALERT_LEVEL=WARNING                     → minimum alarm seviyesi
ALERT_COOLDOWN_SEC=300                  → aynı alarm 5 dk'da bir
HEARTBEAT_TIMEOUT_SEC=120               → 2 dk veri yoksa alarm
STALE_DATA_THRESHOLD_SEC=300            → 5 dk eski veri → tick atla
```
