# super_otonom Operasyon Runbook v1.0

## Çalıştırma sözleşmesi — canlı açma sırası

Tek komut (kapılar + ortam özeti): `scripts/fastrun_go_live.ps1` veya `scripts/fastrun_go_live.cmd`.

### Golden path (Faz 1 — her oturumda)

1. **Repo kökü:** terminali proje kökünde açın (`fatal: not a git repository` ve script bulunamadı hataları buradan çıkar). **PowerShell:** `Set-Location -LiteralPath 'C:\Users\...\super_otonom_v7'` (`cd /d` yalnızca CMD içindir). **CMD:** `cd /d "C:\Users\...\super_otonom_v7"`.
2. **`git pull`** — uzaktaki `main` ile senkron (merge çakışması varsa önce çözün).
3. **`scripts\fastrun_go_live.cmd`** — lint/smoke/deploy_env_check zinciri yeşil olmadan bot başlatmayın.
4. **`python -m super_otonom.main_loop`** — yalnızca üstteki kapılar yeşil ve ortam matrisi (DRY_RUN / PAPER_MODE / LIVE_CONFIRM) uygunsa.
5. **CI/CD paralelliği:** zorunlu check listesi ve otomasyon için `.github/REQUIRED_CHECKS.md`; koruma API/UI için `scripts\fastrun_faz1.cmd`. Dependabot PR’larında önce `main` ile güncel dal, CI yeşil olunca **sırayla** merge (CLI: `gh pr list --author app/dependabot`, sonra `gh pr merge <no>`).

### Faz 3 — Vault ve sırlar (sıra ve adres)

**3.1 — Host port (doğrulama)**  
`docker-compose.yml` içinde **Vault** servisi **`127.0.0.1:8200:8200`** ile host’a bağlı; health check `127.0.0.1:8200`. Konteyner içi `VAULT_ADDR=http://127.0.0.1:8200`. **Host’tan** seed / `main_loop` çalıştırırken: `http://127.0.0.1:8200` (veya `vault_bridge` ile fallback); yalnızca `http://vault:8200` bırakıp hosttan çalıştırmayın — bağlantı reddi oluşur.

**Mühürlü Vault:** Konteyner yeniden başlatılınca Vault **sealed** kalabilir → HTTP **503**. `data\local\vault_init.json` varsa **`scripts\vault_unseal.ps1`** ile açın; **`setup_telegram_alerts`** ve **`fastrun_observability`** zinciri başta bunu dener.

**3.2 — Seed sırası (zorunlu disiplin)**  
1. **`scripts\vault_seed.cmd`** — Vault KV’ye borsa / gerekli sırları yazar (`vault_seed_host.ps1`).  
2. **`scripts\env_harden_secrets.cmd`** — `.env` içindeki hassas alanları sıkılaştırır; **mutlaka seed’den sonra**; ters sıra “seed sonra env_hard sıçrama” ve eksik anahtar hataları üretir.  
3. Anahtar yokken geçici: **`data\local\telegram.env`** veya yerel `.env` (asla commit yok).

**3.3 — Canlı: SECRETS_VAULT_ONLY**  
Canlı profile geçmeden önce: **`SECRETS_VAULT_ONLY=true`**, yalnızca **AppRole** (`VAULT_ROLE_ID`, `VAULT_SECRET_ID`) veya kısa ömürlü `VAULT_TOKEN`; **`.env`’de düz `BINANCE_API_KEY` / `BINANCE_SECRET` olmamalı** — `deploy_env_check` ve RUNBOOK canlı matrisi ile uyumlu.  
**Sir denetimi (PROMPT 2):** `scripts\fastrun_secrets_audit.cmd` → kanıt `docs\SECRETS_AUDIT_LAST.md` (sır değerleri dosyada yok).

### Faz 4 — Veri tazeliği ve zaman mantığı (mum / TF uyumu)

**4.1 — Ortak kaynak (`super_otonom/data_freshness.py`)**  
- **`stale_threshold_sec()`** → `main_loop` **STALE_DATA** eşiği (`TIMEFRAME` / `EXCHANGE_TIMEFRAME` + `STALE_DATA_TIMEFRAME_BUFFER_SEC`).  
- **`max_candle_age_ms()`** → `position_sizer` **ZAMAN_KAYMASI** (isteğe `POSITION_SIZER_MAX_DATA_AGE_MS`; yoksa `stale_threshold_sec` ile aynı cap).  
**TF değişince** yalnız bu modül + ilgili env’leri güncelleyin; iki alarm ayrı eşikle spam üretmez.

**4.2 — Redis (`super_otonom/redis_bridge.py`)**  
- **`redis_kline_max_age_ms()`** aynı dosyadan: `updated_at` yaşı için üst sınır (varsayılan `REDIS_KLINE_TIMEFRAME=5m` + buffer; ince ayar **`REDIS_KLINE_MAX_AGE_MS`**).  
- Bozuk / çok eski anahtarlar: **`RedisBridge.clear_stale_kline_keys()`** (ops / deploy öncesi).  
- **Go köprüsü (`go_service`, `go_redis_bridge`):** her `SET` **`REDIS_KLINE_TTL_SECONDS`** (varsayılan **900**) ile TTL — yazım kesilince anahtarlar kendiliğinden düşer; `go_service` **`:history`** listesine de aynı TTL (`EXPIRE`).  
- Anahtar soneki: **`REDIS_KLINE_KEY_SUFFIX`** (varsayılan `kline_5m`; Go ve Python aynı env’i okur).

### Faz 5 — Mutabakat ve paper log gürültüsü

**5.1 — DRY_RUN + read-only / imzalı istek**  
- **`RECON_SIM_SKIP_SIGNED_FETCH=1`** + `DRY_RUN=true` + `PAPER_MODE=true` → mutabakat **borsadan bakiye/pozisyon çekmez** (apiKey / `-2008` gürültüsü yok); yerel `NAV` kullanılır. Özet recon satırı **INFO**; uyarılar **DEBUG** (hard block hariç).  
- Gerçek bakiye okumak için: **`RECON_FETCH_BALANCE_IN_SIM=1`** + **`BINANCE_SIGN_REQUESTS_IN_DRY_RUN=1`** + Vault’tan geçerli (tercihen **read-only**) anahtar — bu durumda `RECON_SIM_SKIP_SIGNED_FETCH` kapalı olmalı.

**5.2 — `pending_orders.json`**  
Bot **kapalıyken** gereksiz / eski dosyayı silin (`data/pending_orders.json`).  
Çalışırken: **`RECON_AUTO_FAIL_SKIPPED_PENDING=true`** (sim/paper) → recovery **SKIPPED** olan satırlar **iptal** edilir; dosya boşalınca **otomatik silinir**. Varsayılan `false` — bilinçli açın.

### Faz 6 — Gözlemlenebilirlik ve uyarılar

**6.1 — Stack + drill (PROMPT 3):** `scripts\fastrun_observability.cmd` → stack + **`python -m super_otonom.observability_drill`** (kasitli test alert → Telegram **HTTP 200** sart; yalnizca stack ayakta yetmez). Kanit: **`docs/OBSERVABILITY_DRILL.md`**. Grafana: `http://127.0.0.1:3000/d/super-otonom-ops`. Telegram: `data\local\telegram.env` veya Vault. Alertmanager → **`ALERTMANAGER_WEBHOOK_URL`** (varsayilan `http://alert_telegram:8081/alert`). Stack zaten ayaktaysa: `python -m super_otonom.observability_drill` veya `fastrun_observability.ps1 -SkipStack`.

**6.2 — Webhook / DNS:** Bot içi doğrudan Slack vb. için **`ALERT_WEBHOOK_URL`** kullanın. **`WEBHOOK_URL=http://alert_telegram:8081/alert`** yalnızca Alertmanager içindir; bot (`AlertManager`) bu köprü adresini otomatik yok sayar — host üzerinde **`getaddrinfo failed`** gürültüsü oluşmaz. Paper/sim’de ek kanal istemiyorsanız `ALERT_WEBHOOK_URL` boş bırakın; uyarılar Prometheus → Alertmanager → Telegram (veya yalnızca metrik/Grafana).

### Faz 7 — Yedek ve süreklilik

**7.1 — Günlük yedek:** **`scripts\backup_daily.cmd`** veya **`scripts\backup_daily.ps1`** (`-DryRun`, `-RetentionDays`, `-ExcludeSecrets`, `-BackupRoot`). Görev zamanlayıcı: **`scripts\register_backup_task.ps1`** (çoğu sistemde yönetici PowerShell). Özet: `docs\DR_BCP.md`.

**7.2 — Docker volume riski:** **`docker compose down -v`** named volume’ları (Vault, Timescale, Redis, Prometheus, Grafana) siler; **`./data`** bind mount genelde kalır. Tablo ve felaket adımları: **`docs\DR_BCP.md`** (bölüm “Docker Compose”).

### Faz 9 — Strateji kanıtı ve küçük canlı tatbikat (ticari gerçekçilik)

**9.1 — Edge kanıtı (komisyon + slip, HOLD dağılımı)**  
- **Komut:** `python -m super_otonom.edge_evidence --source synthetic` (hızlı, ağ yok) veya `--source ccxt --symbol BTC/USDT --timeframe 5m --limit 800` (CCXT ile mum çeker).  
- **Özet:** Tam örnek geri test + isteğe bağlı **WFA test dilimleri** (`WFAManager`); `final_signal` histogramında HOLD/BUY/SELL sayıları. Çıktıdaki yorum: çoğu HOLD’un **beklenen düşük frekans** mı yoksa **sıkı filtre** sonucu mu olduğu bağlamda okunmalı; **“bot çalışıyor = para kazanıyor”** çıkarımı yapılmaz — net getiri ve işlem sayısı kanıt gerekir.  
- **Geri test parametreleri:** `--fee-bps` (taraf başına basis point), `--slip-min` / `--slip-max`, `--exec-seed` (tekrarlanabilir slip/fill). `super_otonom.backtester.run_backtest` → paper motorunda `paper_fee_bps_per_side` + `ExecutionSimulator` slip aralığı.  
- **Hızlı script:** `scripts\fastrun_phase9_strategy.cmd` — synthetic özet + `pytest tests/test_edge_evidence_fastrun.py`.

**9.2 — Canlı küçük nominal tatbikat (RUNBOOK checklist)**  
Aşağıdakiler **üretim yolunun teknik doğrulaması** içindir; sermaye riski operatördedir.

1. **Tek çift:** `.env` veya konfigürasyonda yalnızca bir işlem çifti (ör. `PAIRS` / tek sembol).  
2. **Küçük boyut:** `max_position_pct` / minimum notional ile **nihai küçük** yüzey; staging ile asla aynı boyutu kullanmayın.  
3. **`LIVE_CONFIRM=YES`:** Canlı profilde (`DRY_RUN=false`, `PAPER_MODE=false`) zorunlu kapı; önce `python -m super_otonom.deploy_env_check`.  
4. **Kill-switch / acil durdurma:** `GLOBAL_TRADE_DISABLE=1` ile bot sürecinden çıkmadan emir gönderimini doğrulayın (RUNBOOK “Golden path” ve smoke ile uyumlu).  
5. **İzleme:** İlk 15–30 dk log + `metrics` / Grafana; anomali halinde süreci durdurun ve matrisi **Aşama 2** (kuru/paper) geri alın.

### Ortam matrisi (sırayla)

| Aşama | `DRY_RUN` | `PAPER_MODE` | `LIVE_CONFIRM` | `BINANCE_TESTNET` | Emir |
|-------|-----------|--------------|----------------|-------------------|------|
| **0 — Yerel sim** | `true` | `true` | *(boş)* | `false` | Yok (simülatör) |
| **1 — Testnet tatbikat** | `true` veya `false` | `true` | *(boş)* | `true` | Testnet API; paper önerilir |
| **2 — Mainnet kuru çalışma** | `true` | `true` | *(boş)* | `false` | İmzalı istek yok / sim |
| **3 — Canlı spot** | `false` | `false` | **`YES`** | `false` | Gerçek limit emir |

Kurallar:

- `DRY_RUN=true` → daima simülasyon; `main_loop` gerçek emir göndermez.
- `PAPER_MODE=false` ve `DRY_RUN=false` → **canlı profil**; `LIVE_CONFIRM=YES` zorunlu (`main_loop` ve `deploy_env_check` aynı kapı).
- Üretimde API anahtarları yalnızca **Vault KV** (`SECRETS_VAULT_ONLY=true`); `.env` içinde `BINANCE_API_KEY` / `SECRET` olmamalı.
- `META_REGIME_MODE=advisory` + canlı → ölçüm ACK dosyası gerekir (aşağıdaki smoke).

### Binance API izinleri (canlı öncesi)

| İzin | Gerekli |
|------|---------|
| Okuma (Read) | Evet |
| Spot & Margin Trading | Evet (limit emir yolu) |
| Futures / Withdraw / Transfer | **Hayır** |
| IP kısıtı (whitelist) | Önerilir |
| Testnet anahtarı ≠ mainnet anahtarı | Zorunlu ayrım |

Vault yolu: `secret/trading/binance` → `api_key`, `api_secret` (KV seed: `scripts\vault_seed.cmd`; tam Vault/stack: `scripts\fastrun_vault.cmd`).

### Açma sırası (checklist)

```
[ ] 1. .env kopyala: cp .env.example .env  (veya .env.template) — commit etme
[ ] 1b. Vault (Faz 3): compose ile Vault ayakta; host `http://127.0.0.1:8200` — önce `scripts\vault_seed.cmd`, sonra `scripts\env_harden_secrets.cmd` (ters sıra kullanma)
[ ] 1c. Redis kline (Faz 4): `TIMEFRAME` / `data_freshness` ile uyum; suni stale → `REDIS_KLINE_MAX_AGE_MS` veya `RedisBridge.clear_stale_kline_keys()` (RUNBOOK Faz 4)
[ ] 1d. Mutabakat (Faz 5): sim/paper gürültüsü için `RECON_SIM_SKIP_SIGNED_FETCH=1`; `data/pending_orders.json` gereksizse bot kapalıyken sil; otomatik temizlik: `RECON_AUTO_FAIL_SKIPPED_PENDING=true` (RUNBOOK Faz 5)
[ ] 2. Aşama 0→1→2→3 matrisine göre bayrakları ayarla
[ ] 3. Zayıf şifre yok (POSTGRES_*, GRAFANA_*, TIMESCALE_* — deploy_env_check reddeder)
[ ] 4. fastrun_go_live (release_gate + fastrun + deploy_env_check)
[ ] 5. İsteğe bağlı: docker stack — scripts/fastrun_observability.ps1
[ ] 6. Canlı (Aşama 3): Vault erişimi + deploy_env_check yeşil
[ ] 7. İlk süreç: main_loop; 5–15 dk log/metrik smoke
[ ] 8. GLOBAL_TRADE_DISABLE=1 ile acil durdurma yolunu doğrula
```

### İlk smoke komutları

```powershell
# Windows — proje kökünde
powershell -ExecutionPolicy Bypass -File scripts/fastrun_go_live.ps1

# veya adım adım:
python -m super_otonom.release_gate
python -m pytest -m fastrun -q
python -m super_otonom.deploy_env_check
python scripts/print_resolved_risk.py --summary
```

```bash
# Linux / CI kutusu
python -m super_otonom.release_gate
python -m pytest -m fastrun -q --tb=short
python -m super_otonom.deploy_env_check
python scripts/print_resolved_risk.py --summary
```

Advisory canlı (`META_REGIME_MODE=advisory`):

```powershell
python -m super_otonom.meta_regime_orchestrator --message "A5 reviewed"
# veya: scripts/write_meta_advisory_ack.ps1
python -m super_otonom.deploy_env_check
```

Bot başlatma (profil onaylandıktan sonra):

```bash
# Sim / paper (varsayılan .env.example)
python -m super_otonom.main_loop

# Canlı — bilinçli; .env: DRY_RUN=false PAPER_MODE=false LIVE_CONFIRM=YES
python -m super_otonom.main_loop
```

Başarılı `deploy_env_check` → `data/reports/deploy_env_check_last_ok.json` (canlı tick kilidi: `DEPLOY_ENV_LOCK_AT_START`, bkz. `deploy_env_check` docstring).

### Hızlı doğrulama (çalışırken)

```bash
curl -s http://127.0.0.1:8000/metrics | findstr /i "bot_dependency_up bot_order_errors"
docker logs super_otonom_bot --tail 30
python -m super_otonom.deploy_env_check
```

---

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
