# super_otonom DR/BCP v1.1
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

## Docker Compose: hangi veri nerede? (PROMPT 7.2 — volume riski)

| Kaynak | Tip | Konum | `docker compose down` | `docker compose down -v` |
|--------|-----|--------|----------------------|---------------------------|
| Bot durum, audit, recon vb. | **Bind mount** | Repo içi `./data` → konteyner `/app/data` | **Kalır** (host dosyaları) | **Kalır** |
| Bot logları | Bind mount | `./logs` | Kalır | Kalır |
| Vault çalışma verisi | **Named volume** `vault_data` | Docker volume (ör. `super_otonom_v7_vault_data`) | Volume **kalır** | Volume **silinir** — KV ve mühür durumu gider |
| TimescaleDB | Named volume `timescale_data` | Docker volume | Kalır | **Silinir** — tüm DB gider |
| Redis AOF | Named volume `redis_data` | Docker volume | Kalır | **Silinir** |
| Prometheus TSDB | Named volume `prometheus_data` | Docker volume | Kalır | **Silinir** |
| Grafana | Named volume `grafana_data` | Docker volume | Kalır | **Silinir** |

**Özet:** `./data` ve `./logs` klasörlerini silmedikçe çoğu operasyonel dosya host’ta kalır. **`docker compose down -v`** ve **`docker volume prune`** yalnızca named volume’ları etkiler; **Vault / Timescale / Redis** sıfırlanır — üretimde komutu çalıştırmadan önce **yedek + DR özeti** doğrulanmalıdır.

**Vault mühürlü / 503:** Yerelde `data/local/vault_init.json` (unseal anahtarları + root token) yoksa veya kayıpsa Vault verisi geri gelse bile açılamayabilir — günlük yedeğe dahildir (`secrets/` altı, bakınız aşağı).

---

## Kritik Veri Yedekleme

### Otomatik (bot tarafından)
```
data/bot_state.json        → her trade sonrası güncellenir
data/capital_journal.jsonl → her ledger değişiminde append
data/pending_orders.json   → atomic write (tmp → rename)
data/orders.jsonl          → append-only
data/audit/                → günlük JSONL, append-only
data/reconcile/            → mutabakat çıktıları
```

### Günlük yedek (Windows — PROMPT 7.1)

Repo kökünden veya `scripts` klasöründen:

```bat
scripts\backup_daily.cmd
```

Önizleme (dosya yazmaz):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backup_daily.ps1 -DryRun
```

Harici disk örneği (`D:\Backups\super_otonom` önce oluşturun):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backup_daily.ps1 -BackupRoot "D:\Backups\super_otonom"
```

**Varsayılan hedef:** `data/backup/<yyyyMMdd-HHmmss>/` (repo içi; `.gitignore` ile commit dışı).

**İçerik:** Yukarıdaki kritik dosya/dizinler + `BACKUP_MANIFEST.txt` (UTC zaman, `git` HEAD, makine adı). Varsayılan olarak **`secrets/`** altında `vault_init.json`, `vault_admin_token.json`, `telegram.env` (varsa) — **şifre/token içerir**; yedeği şifreli ortamda saklayın. Sırları yedeklememek için:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backup_daily.ps1 -ExcludeSecrets
```

**Retention:** Varsayılan son **14** günden eski yedek klasörleri silinir (`-RetentionDays N` ile değişir).

### Windows Görev Zamanlayıcısı

Yönetici PowerShell:

```powershell
cd C:\tam\yol\super_otonom_v7
powershell -ExecutionPolicy Bypass -File .\scripts\register_backup_task.ps1
```

İsteğe bağlı harici kök:

```powershell
.\scripts\register_backup_task.ps1 -BackupRoot "D:\Backups\super_otonom" -StartTime "03:15"
```

Manuel kayıt (tek satır örnek):

```bat
schtasks /Create /TN "SuperOtonom_BackupDaily" /SC DAILY /ST 02:05 /RL LIMITED /F /TR "\"C:\tam\yol\super_otonom_v7\scripts\backup_daily.cmd\""
```

### Linux / cron (referans)

Windows dışı ortamda aynı dosya listesiyle `cp`/`rsync` yapın; `scripts/backup_daily.ps1` yerine eşdeğer kabuk betiği kullanın.

---

## Felaket Senaryoları

### Senaryo A — Sunucu tamamen çöktü

**Adımlar:**
1. Yeni sunucuya Python ortamını kur
2. Repo'yu clone et
3. `.env` dosyasını geri yükle (commitlenmez; yedek veya güvenli kasadan)
4. Son yedeği geri yükle (`YYYYMMDD-HHMMSS` klasöründen):
```powershell
Copy-Item .\backup\...\bot_state.json .\data\
Copy-Item .\backup\...\capital_journal.jsonl .\data\
Copy-Item .\backup\...\pending_orders.json .\data\
Copy-Item .\backup\...\secrets\vault_init.json .\data\local\   # varsa
```
5. Botu başlat — startup handshake otomatik çalışır
6. Reconciliation raporunu kontrol et

### Senaryo B — Borsa API değişti / key geçersiz

**Adımlar:**
1. Botu durdur (SIGINT)
2. Yeni API key al
3. `.env` veya Vault KV'yi güncelle
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

### Senaryo E — Yanlışlıkla `docker compose down -v`

**Etki:** Vault, Timescale, Redis, Prometheus, Grafana named volume’ları silinir. `./data` bind mount **korunur** ama DB ve KV içi veri gider.

**Adımlar:**
1. Panik yok — host `./data` + günlük yedekler duruyorsa operasyonel geri dönüş mümkün
2. `vault_init.json` yedeğinden Vault yeniden kurulum / unseal akışı (`scripts/vault_unseal.ps1`, `vault_seed`)
3. Timescale: şema migration / seed scriptleri ile yeniden oluşturma; kritik tablolar için ayrı DB dump (ileri seviye) önerilir

---

## İzleme ve Uyarı Sistemi

```
Alertmanager → WEBHOOK_URL / köprü → Telegram
Prometheus → bot:8000 (MetricsExporter)
Grafana → dashboard uid super-otonom-ops
```

Ayrıntı: `docs/RUNBOOK.md` Faz 6.

---

## İletişim Planı

| Durum | Aksiyon |
|---|---|
| Emergency stop | Webhook alarm → pozisyonları kontrol et |
| NAV farkı >%10 | Hard block → manuel müdahale zorunlu |
| Heartbeat timeout | Bot yeniden başlat |
| Flash crash | Bekle, piyasa sakinleşince reset |
| API key geçersiz | Yeni key → env/Vault güncelle → restart |

---

## Test Planı (Aylık)

```text
1. Bot'u durdur
2. bot_state.json'u yedekle, sil
3. Bot'u başlat — fresh recovery test et
4. Reconciliation raporunu kontrol et
5. bot_state.json'u geri yükle

Sonuç: RTO < 2 dakika hedefine ulaşıldı mı?
```

Ek: `backup_daily.ps1 -DryRun` ile yedek kapsamını doğrula.
