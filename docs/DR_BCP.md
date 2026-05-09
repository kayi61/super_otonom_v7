# super_otonom DR/BCP v1.0
## Felaket Kurtarma ve İş Sürekliliği Planı

---

## RTO / RPO Hedefleri

| Senaryo | RTO (geri dönüş süresi) | RPO (veri kaybı toleransı) |
|---|---|---|
| Bot çökmesi | < 2 dakika | 0 (tüm state diskten yüklenir) |
| Sunucu arızası | < 15 dakika | Son trade'e kadar |
| Borsa bağlantı kesintisi | Otomatik (circuit breaker) | 0 |
| Veri merkezi kaybı | < 1 saat | Son backup'a kadar |

---

## Kritik Veri Yedekleme

### Otomatik (bot tarafından)
```
data/bot_state.json        → her trade sonrası güncellenir
data/capital_journal.jsonl → her ledger değişiminde append
data/pending_orders.json   → atomic write (tmp → rename)
data/orders.jsonl          → append-only, kayıp yok
data/audit/                → günlük JSONL, append-only
```

### Manuel Yedek (günlük)
```bash
# Günlük yedek scripti — cron'a ekle
#!/bin/bash
DATE=$(date +%Y%m%d)
BACKUP_DIR="/backup/super_otonom/$DATE"
mkdir -p $BACKUP_DIR

cp data/bot_state.json        $BACKUP_DIR/
cp data/capital_journal.jsonl $BACKUP_DIR/
cp data/pending_orders.json   $BACKUP_DIR/
cp -r data/audit/             $BACKUP_DIR/audit/
cp -r data/recon/             $BACKUP_DIR/recon/

echo "Yedek tamamlandı: $BACKUP_DIR"
```

---

## Felaket Senaryoları

### Senaryo A — Sunucu tamamen çöktü

**Adımlar:**
1. Yeni sunucuya Python ortamını kur
2. Repo'yu clone et
3. `.env` dosyasını geri yükle (API keys)
4. Son yedeği geri yükle:
```bash
cp /backup/super_otonom/YYYYMMDD/bot_state.json data/
cp /backup/super_otonom/YYYYMMDD/capital_journal.jsonl data/
cp /backup/super_otonom/YYYYMMDD/pending_orders.json data/
```
5. Botu başlat — startup_handshake otomatik çalışır
6. Reconciliation raporunu kontrol et

### Senaryo B — Borsa API değişti / key geçersiz

**Adımlar:**
1. Botu durdur (SIGINT)
2. Yeni API key al
3. `.env` dosyasını güncelle
4. Exchange web arayüzünden açık pozisyonları kontrol et
5. `data/pending_orders.json`'u temizle (stale emirler)
6. Botu başlat

### Senaryo C — Büyük piyasa çöküşü (flash crash)

**Otomatik korumalar:**
- `max_total_drawdown` → emergency stop
- `volatility_spike` → işlem engeli
- `dynamic_daily_loss` → günlük limit

**Manuel müdahale:**
```bash
# Emergency stop aktifse tüm pozisyonlar zaten kapatıldı
# (emergency_liquidate otomatik çalıştı)
grep "EMERGENCY_LIQUIDATE" logs/health.log

# Manuel reset — sadece piyasa sakinleştikten sonra
python3 -c "
from super_otonom.bot_engine import BotEngine
import os
engine = BotEngine(capital=float(os.getenv('INITIAL_CAPITAL', '1000')))
engine.risk.reset_emergency()
print('Emergency reset tamamlandı')
"
```

### Senaryo D — Veri bozulması (bot_state.json corrupt)

**Adımlar:**
1. `data/bot_state.json`'u sil
2. `data/capital_journal.jsonl`'dan son NAV'ı hesapla:
```bash
python3 -c "
import json
entries = [json.loads(l) for l in open('data/capital_journal.jsonl')]
last = entries[-1]
print(f'Son NAV: {last[\"snap_nav\"]}')
print(f'Son event: {last[\"event\"]} | {last[\"ts\"]}')
"
```
3. `data/pending_orders.json`'u temizle
4. Botu başlat — fresh state ile, reconciliation farkı normal

---

## İzleme ve Uyarı Sistemi

```
AlertManager → WEBHOOK_URL (Slack/Discord)
    EMERGENCY       → anında, her tetiklemede
    NAV_DIFF        → %2+ fark, 5 dk cooldown
    CIRCUIT_BREAKER → açılışta, 5 dk cooldown
    HEARTBEAT       → 2 dk veri yoksa
    TCA_ANOMALY     → slippage 3x beklenenin üstünde

Prometheus → port 8000 (MetricsExporter)
    equity, free_capital, open_positions
    daily_loss_pct, drawdown_pct
    circuit_breaker durumu
```

---

## İletişim Planı

| Durum | Aksiyon |
|---|---|
| Emergency stop | Webhook alarm → pozisyonları kontrol et |
| NAV farkı >%10 | Hard block → manuel müdahale zorunlu |
| Heartbeat timeout | Bot yeniden başlat |
| Flash crash | Bekle, piyasa sakinleşince reset |
| API key geçersiz | Yeni key → env güncelle → restart |

---

## Test Planı (Aylık)

```bash
# DR testini çalıştır
# 1. Bot'u durdur
# 2. bot_state.json'u yedekle, sil
# 3. Bot'u başlat — fresh recovery test et
# 4. Reconciliation raporunu kontrol et
# 5. bot_state.json'u geri yükle

# Sonuç: RTO < 2 dakika hedefine ulaşıldı mı?
```
