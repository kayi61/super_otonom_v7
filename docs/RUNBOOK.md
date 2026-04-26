# super_otonom — Faz 3–4: Gözlem, güven, runbook

Bu belge, botu **güvenle izlemek**, **doğrulamak** ve **canlıya geçerken** kontrol listesini kullanmak içindir. **Hedef:** operasyonel güven **+9.9** üzeri. **Faz 5** kanıt / SLO / denetim: `docs/EVIDENCE.md`, `docs/SLO.md`, `docs/AUDIT.md`.

---

## 1) Önkoşul

- Python ≥ 3.10, proje kökünde: `pip install -e ".[dev]"`
- Borsa anahtarları: yalnız **testnet** veya **küçük bakiye** ile canlı dene; `.env` asla commitleme

### Faz 2 (sürekli entegrasyon)

- CI’da **lint (Ruff)** + **hızlı test (pytest; ağır sweep’ler hariç)** yeşil — aksi halde bu runbook yalnızca “hedef davranış”tır, kod garantisi değildir
- Kapsam: `pytest` + `--cov=super_otonom` + coverage **`--cov-fail-under=80`** (güncel eşik ve komut: `.github/workflows/ci.yml`)

---

## 2) Hızlı başlangıç (iki terminal)

**Terminal A — motor**

```bash
python -m super_otonom.main_loop
```

(Alternatif: `super-otonom` — `pyproject.toml` içindeki entrypoint)

**Terminal B — sağlık dosyası (sürekli)**

Windows (PowerShell):

```powershell
Get-Content -Path logs\health.log -Wait -Tail 50
```

Linux / macOS:

```bash
tail -f logs/health.log
```

Beklenti: Her analiz+tick adımında `health.log`’a yeni satırlar (eşzamanlılık, borsa gecikmesi ve hata durumunda seyrekleşebilir).

---

## Faz 3-4 — İzleme turu, health ve operasyon

Bu bölüm, üretim benzeri izleme ve müdahale için tek kaynak prosedürlerdir.

### İzleme turu (adım adım, en az 8 adım)

1. **Önkoşul:** CI yeşil; `.env` güncel; repoda `.env.example` ile uyumlu anahtarlar (canlı anahtar asla commit yok).
2. **Süreç canlı mı:** İşletim sisteminde `python -m super_otonom.main_loop` (veya eşdeğer entrypoint) tek örnek mi; çakışan eski process yok.
3. **Terminal (ana process):** Açılışta `Bot baslatildi`, risk özeti, DRY_RUN / paper / live kilidi mesajları; Windows’ta sinyal notu beklenir.
4. **`logs/health.log` akışı:** `tail -f` veya PowerShell `Get-Content -Wait` ile satırların tick/döngü ile güncellendiğini doğrula (donma yok).
5. **Tick satırı anlamı:** `[OK]` vs `[HALT]`, `Qraw` / `Qadj` / `effective_qmin`, `Scale`, `PnL`, `Lim`, OMEGA kısa metin — aşağıdaki tablo ile eşleştir.
6. **Döngü sonu:** Terminalde `DURUM |` + `format_durum_line` özeti: `eq`, `pnl`, `emerg`, fuse / rate-limit sayaçları.
7. **Dış ML:** `ML_SERVICE_ENABLED` kapalıysa logda `no_external_ml` beklentisi; açıksa gecikme ve timeout davranışını gözle.
8. **Güvenlik durumu:** `EMERGENCY_STOP`, `kill_switch`, 429 fırtınası veya sürekli `LOW_QUALITY_REJECT` — beklenen aralıkta mı, yoksa müdahale mi gerekiyor?
9. **Süreklilik:** En az bir oturumda log dosya boyutu / son değişiklik zamanı ile “yazım devam ediyor” teyidi (opsiyonel: arşiv rotasyonu yoksa `health.log` büyümesi normal).

### Health check prosedürü

| # | Kontrol | Geçer kriter |
|---|---------|----------------|
| H1 | `ensure_health_file_logger` çalıştı mı? | İlk tick öncesi `logs/` oluşur; `health.log` yazılabilir. |
| H2 | Logger tekilliği | Aynı process içinde çift `FileHandler` yok (modül `_HEALTH_FILE_SETUP` ile korunur). |
| H3 | Encoding | Satırlar UTF-8; Türkçe / sembol bozulmuyor. |
| H4 | Seviye | Kokpit satırları INFO; beklenmeyen ERROR root’ta araştırılır. |
| H5 | Flush | Her tick sonrası dosya handler flush (yüksek frekansta diskte güncel görünür). |
| H6 | Acil durum etiketi | `emergency_stop` veya `decision_context.emergency_code` varsa satırda `[HALT]` ve açıklama. |

**Hızlı komut (dosya var mı, son satırlar):**

```bash
# Linux / macOS
test -f logs/health.log && tail -n 5 logs/health.log
```

```powershell
# Windows (PowerShell)
if (Test-Path logs\health.log) { Get-Content logs\health.log -Tail 5 }
```

### Log kontrol adımları

1. Proje kökünden `logs/health.log` yolunu aç (veya `GENERAL["log_dir"]` özelleştiyse o dizin).
2. Zaman damgası formatı: `YYYY-MM-DD HH:MM:SS | <mesaj>` (`health_summary` formatter).
3. Her parite tick’inde `log_tick_health` ile bir satır; sembol ve `tick_id` izlenebilir olmalı.
4. Terminaldeki `DURUM |` satırı ile `health.log` aynı oturumda tutarlı equity / emergency bilgisi vermeli (farklı kanallar, aynı motor).
5. Hata ayıklamada: önce terminal (traceback), sonra `health.log` (iş mantığı özeti), gerekirse genel uygulama logları.
6. Olay sonrası: ilgili zaman aralığını kopyala / arşivle; `.env` ve borsa limitini birlikte incele.

### Canlı sistem doğrulama checklist

Aşağıdakiler **bilinçli canlı** veya testnet denemesi öncesi işaretlensin:

- [ ] `LIVE_CONFIRM=YES` ve `PAPER_MODE=false` yalnız kasıtlı olarak set; küçük sermaye veya testnet.
- [ ] `DRY_RUN` durumu biliniyor; paper/live karışıklığı yok.
- [ ] `health.log` canlı oturumda akıyor; `[HALT]` yoksa veya bilinen nedenle sınırlı.
- [ ] İlk emirlerden sonra slipaj / `EYLEM` logları beklenen aralıkta.
- [ ] Rate-limit / circuit breaker logları anormal değil.
- [ ] `Ctrl+C` veya SIGTERM (Linux) ile temiz kapanış denendi; zombie process yok.
- [ ] Operatör: kurtarma ve iletişim adımları bu runbook’ta okunmuş.

### İzleme altyapısı doğrulaması (`health_summary.py`, `logs/health.log`)

| Bileşen | Rol | Doğrulama |
|---------|-----|-----------|
| `ensure_health_file_logger(log_dir)` | `logs/health.log` için tekil `FileHandler`; `log_health` logger | Kod: `super_otonom/health_summary.py`. Çağrı: `main_loop` açılışında `GENERAL["log_dir"]` ile. |
| `log_tick_health` / `format_tick_health` | Tick başına kokpit satırı (kalite, OMEGA özeti, limitleyiciler) | Her `engine.tick` sonrası `main_loop` içinde. |
| `format_durum_line` | Döngü sonu equity / fuse / emergency özeti | Terminal `DURUM` logunda. |
| Otomatik testler | Regresyon | `pytest tests/test_health_summary.py tests/test_health_summary_more.py` ve `tests/test_main_loop_helpers.py` (health logger kurulumu). |

**Manuel duman testi:** Motoru kısa süre çalıştır → `logs/health.log` oluşuyor ve son satırlar zaman damgalı büyüyor → Ctrl+C ile durdur → dosya tutarlı kapanıyor.

**Otomatik doğrulama (CI / lokal):**

```bash
pytest tests/test_health_summary.py tests/test_health_summary_more.py tests/test_main_loop_helpers.py -q
```

### Gözlem sistemi — `health.log` izleme ve metrik

| Kanal | Amaç | Operasyon notu |
|-------|------|----------------|
| `logs/health.log` | Tick bazlı kokpit (`log_tick_health`) | §2 ve “Log kontrol adımları”; `GENERAL["log_dir"]` özelse yol ona göre. |
| Ana terminal | `DURUM \|`, `AI KARAR \|`, `EYLEM \|`, circuit breaker uyarıları | Gerçek zamanlı triage önce burada. |
| Prometheus | `MetricsExporter` HTTP `/metrics` | `METRICS_PORT` (varsayılan **8000**), `METRICS_NAMESPACE` (`config.METRICS`). |

**`health.log` izleme adımları (özet):**

1. Motor çalışırken dosyanın son mtime’ının güncellendiğini doğrula.
2. Her parite için tick satırında sembol ve `tick_id` olduğunu kontrol et.
3. `[HALT]` görürsen aynı zaman diliminde terminalde `emergency` / `DURUM` ile çapraz doğrula.
4. OMEGA / kalite alanları (`Qraw`, `Qadj`, `effective_qmin`) beklenen rejimle uyumlu mu bak.
5. Sorun gidermede dosyayı arşivle; rotasyon yoksa boyut büyümesi normal.

**Metrik toplama doğrulama:**

- **Kaynak:** `BotEngine` içinde `MetricsExporter` (`super_otonom/metrics_exporter.py`); durum güncellemesi ve işlem yolunda `record_slippage` / `record_trade` çağrıları.
- **Bağımlılık:** `prometheus_client` yoksa exporter **no-op** (motor çalışmaya devam eder); kurulum: `pip install prometheus-client` (projede zaten bağımlılık).
- **`METRICS_PORT=0`:** HTTP sunucusu başlatılmaz (test / güvenlik); metrikler yalnızca bellek içi veya devre dışı kalır — üretimde genelde &gt;0 port kullan.

**Prometheus / `metrics_exporter` kontrolü:**

1. `prometheus_client` kurulu mu: `python -c "import prometheus_client"` (hata yok).
2. Varsayılan port çakışması yok: `METRICS_PORT` (ör. 8000) boş.
3. Motor açıkken: `curl -sS http://127.0.0.1:<METRICS_PORT>/metrics | head` (Windows’ta `Invoke-WebRequest`) — `bot_*` veya `METRICS_NAMESPACE` önekli seriler görünmeli (prometheus_client kurulu ve port≠0 ise).
4. Slipaj / rejim / circuit breaker göstergeleri: exporter dokümantasyonu ve `metrics_exporter.py` içindeki Gauge tanımları.
5. Regresyon: `pytest tests/test_metrics_exporter.py -q` (isteğe bağlı: `tests/test_metrics_and_ml_boost.py`).

### Güven katmanı — doğrulama prosedürleri

Bu alt bölüm §4 tablosunu **operasyonel kontrol** ile tamamlar.

#### AI confidence bridge

| Kontrol | Nerede | Not |
|---------|--------|-----|
| Giriş güven eşiği | `RISK["entry_min_confidence"]`, env `ENTRY_MIN_CONFIDENCE` | `ai_layer._entry_conf_floor()` ile uyumlu taban. |
| Model / fallback | `AILayer.validate_signal` | Terminalde `AI KARAR \| ... guven=...`; LSTM kapalıysa fallback yolu runbook §3 ile uyumlu. |
| Kalite × güven | `effective_qmin`, `Qadj` | BUY için hem kalite hem AI güven zinciri; düşük güvende HOLD beklenir. |

**Doğrulama:** Paper/DRY oturumunda loglarda `guven` değerlerinin 0.45–0.95 bandında ve gerekçe string’inin boş olmadığını örnekleyin.

#### Sentiment katmanı

- **Bileşen:** `BotEngine.sentiment_layer` (`SentimentLayer`); korelasyon çarpanı `correlation_mgr` ile birlikte karar bağlamına girer.
- **Log imzası:** `V6 DURUM \| <symbol> \| sentiment=... \| corr_mult=...` (`main_loop`).
- **Doğrulama:** En az bir döngüde sentiment `N/A`/`UNKNOWN` dışına çıkıyorsa veya `corr_mult < 1.0` ise değerlerin piyasa haber akışıyla makul olduğunu kontrol edin; beklenmeyen sürekli baskıda sentiment kaynağını ve mock modunu gözden geçirin.

#### Risk manager limitleri

Aşağıdakiler `super_otonom/config.py` içindeki `RISK` ve ilgili env ile yönetilir; değişiklik sonrası oturumu yeniden başlatın.

| Alan | Örnek anahtar | Sağlık / log |
|------|----------------|--------------|
| Pozisyon üst sınırı | `max_position_pct`, `max_open_positions` | `DURUM` / `format_durum_line` exposure |
| Zarar durdurma | `stop_loss_pct`, `trailing_stop_pct`, `take_profit_pct` | `EYLEM`, pozisyon kapanışları |
| Günlük kayıp / acil | `max_daily_loss_pct`, emergency | `emerg=`, `[HALT]` |
| Sinyal kalitesi tabanı | `signal_quality_min` (+ OMEGA sıkılaşması) | `effective_qmin`, `LOW_QUALITY_REJECT` |
| Emir hızı | `max_orders_per_min` (GENERAL) | hard_limits `orders_in_window` / `order_limit` |

**Doğrulama:** `health.log` satırındaki `Lim: oin/olim` ile terminal `Fuses` satırının tutarlı olduğunu bir döngüde teyit edin.

#### Circuit breaker testi

- **Kod:** `super_otonom/exchange_async.py` — sembol başına `CircuitBreaker`; eşik ve iyileşme süresi `main_loop` içinde `CB_FAILURE_THRESHOLD`, `CB_RECOVERY_TIME` env ile `AsyncExchangeHandler`’a verilir.
- **Beklenen loglar:** `CircuitBreaker: N art arda hata — devre AÇILDI`, `recovery süresi doldu — HALF-OPEN`, `başarılı çağrı — devre KAPATILDI`.
- **Metrik:** Prometheus açıksa `circuit_breaker_open` (sembol etiketli) `metrics_exporter` üzerinden izlenebilir.

**Operasyonel test (dikkatli):** Yalnız testnet veya kontrollü ortamda, bilinen geçici API hatası veya firewall kesintisinde logların panic yerine devre mesajı ürettiğini doğrulayın; ardından bağlantıyı onarın ve HALF-OPEN → CLOSED dönüşünü gözlemleyin. Canlıda kasıtlı hata üretmeyin.

### Operasyonel prosedürler

#### Sistem başlatma

1. Sanal ortam / bağımlılıklar: `pip install -e ".[dev]"` (veya dağıtım imajı eşdeğeri).
2. `.env` doğrula: borsa, `PAPER_MODE`, `DRY_RUN`, `LIVE_CONFIRM`, risk ve kalite eşikleri.
3. Proje kökünden tek terminal: `python -m super_otonom.main_loop` (veya `super-otonom`).
4. İkinci terminalde `health.log` takibi (bkz. §2).
5. İlk 1–3 döngüde terminal + `health.log` uyumunu teyit et.

#### Sistem durdurma

1. **Tercih:** Ön plandaki süreçte `Ctrl+C` (Windows/Linux etkileşimli terminal).
2. **Linux / arka plan:** süreçe `SIGTERM` gönder; gerekirse `SIGKILL` (son çare).
3. **Windows:** Görev Yöneticisi veya `Stop-Process` yalnız motor durmuyorsa.
4. Son kontrol: son `health.log` satırı zamanı; borsada bekleyen emir / açık pozisyon operasyon politikasına göre incelenir (bot dışı).

#### Hata durumu prosedürü

1. **Sınıflandır:** (A) borsa / ağ, (B) rate-limit / kill-switch, (C) mantık / assertion, (D) disk / izin.
2. Motoru güvenli şekilde durdur (üstteki “Sistem durdurma”).
3. Logları koru: terminal çıktısı + `logs/health.log` + ilgili uygulama logları.
4. `.env` ve son deploy / config değişikliğini not et; CI son koşuyu kontrol et.
5. Tekrar başlatmadan önce kök nedeni giderildi mi karar ver; gerekirse `DRY_RUN=true` ile repro.

#### Kurtarma prosedürü

1. **Minimum güvenli mod:** `DRY_RUN=true` ve/veya `PAPER_MODE=true` ile ayağa kaldır; gerçek emir yok.
2. API anahtarı / IP / testnet anahtarı rotasyonu gerekiyorsa borsa panelinden yap.
3. `health.log` ve `DURUM` ile equity / emergency normale dönene kadar izle.
4. Canlıya dönüş: runbook “Aşamalı geçiş” ve “Canlı sistem doğrulama checklist” adımlarını sırayla uygula.
5. Olay raporu: tarih, süre, kök neden, alınan önlem (ekip için kısa not).

#### Acil durum prosedürü

Aşağıdakiler **eşzamanlı** veya **kritik risk** durumunda uygulanır (equity çöküşü, beklenmeyen çoklu gerçek emir, sürekli acil stop, borsa / anahtar ihlali şüphesi).

1. **Derhal durdur:** Ana süreçte `Ctrl+C` veya güvenli `SIGTERM`; gerekirse OS düzeyinde sonlandırma (son çare `SIGKILL` / Görev Yöneticisi).
2. **Emir ve pozisyon:** Borsa arayüzünde açık emirleri ve pozisyonları kontrol et; operasyon politikasına göre manuel kapama veya hedge (bot dışı karar).
3. **Kilitle:** API anahtarlarını borsada geçici devre dışı bırak veya IP kısıtla; anahtar sızıntısı şüphesinde **rotasyon**.
4. **Kanıt topla:** Terminal çıktısı, `logs/health.log`, son `.env` (secret’ları maskeleyerek), olay zamanı UTC.
5. **İletişim:** Ürün / risk sahibine özet; yasal veya müşteri etkisi varsa iç prosedür.
6. **Güvenli mod:** Kurtarma bölümüne göre `DRY_RUN=true` ve/veya `PAPER_MODE=true` ile yeniden ayağa kalk; canlıya dönüş yalnız kök neden giderildikten ve checklist tamamlandıktan sonra.
7. **Post-mortem:** Kısa rapor (zaman çizgisi, kök neden, önleyici aksiyon).

### Faz 3-4 tamamlandı işareti ve checklist

**Durum:** ✅ **Faz 3-4 runbook tamamlandı** — Hedef operasyonel güven / olgunluk **+9.8 üstü** için izleme, gözlem (health + metrik), güven katmanı doğrulamaları ve operasyonel prosedürler bu belgede birleştirildi.

Operatör / ekip aşağıdakileri işaretleyerek faz kapanışını kayda geçirebilir:

- [ ] **İzleme turu:** Bu bölümdeki 9 adımlı tur en az bir kez uygulandı ve not alındı.
- [ ] **Health:** H1–H6 tablosu geçerli bir oturumda doğrulandı.
- [ ] **Loglar:** Log kontrol adımları ve (varsa) canlı doğrulama checklist § üzerinden gözden geçirildi.
- [ ] **`health_summary`:** Yukarıdaki pytest komutu yeşil (veya CI eşdeğeri).
- [ ] **Metrik / Prometheus:** `/metrics` erişimi veya bilinçli no-op (`prometheus_client` / `METRICS_PORT`) dokümante edildi.
- [ ] **AI confidence bridge:** Örnek loglarda `AI KARAR` ve güven bandı makul.
- [ ] **Sentiment:** `V6 DURUM` satırları beklenen davranışla uyumlu (veya N/A bilinçli).
- [ ] **Risk limitleri:** `RISK` / env ile `health.log` ve `DURUM` tutarlı.
- [ ] **Circuit breaker:** Log veya metrik ile devre aç/kapa döngüsü anlaşıldı (tercihen testnet).
- [ ] **Operasyon:** Başlatma, durdurma, hata, kurtarma ve **acil durum** prosedürleri ekipte paylaşıldı.

---

## 3) Gözlemlenebilirlik: `health.log` satırı ne söylüyor?

Tipik parça (örnek, değerler piyasaya göre değişir):

```text
[OK] BUY | Qraw:60 Qadj:45 | effective_qmin:50 | Scale:... | PnL: ... | ... | ml=... | ext=... | [OMEGA-AI] TRENDING | ...
```

| Alan | Anlam |
|------|--------|
| **Qraw** | Ham sinyal kalite skoru (0–100) |
| **Qadj** | OMEGA rejim çarpanı sonrası skor; kötü rejimde `Qraw`’dan düşer → agresif olmayan filtre |
| **effective_qmin** | Ortam `SIGNAL_QUALITY_MIN` + RiskManager OMEGA sıkılaşması; **BUY** için eşik |
| **OMEGA satırı** (sonda) | Rejim etiketi: `TRENDING` / `RANGING` / `CRASH_RISK` ve çarpanlar; durgun piyasada `RANGING` vb. beklentisiyle karşılaştır |
| `ml=...` / `ext=...` | Dış ML kapalıysa `no_external_ml` beklentisi (`ML_SERVICE_ENABLED=false`) |

**Terminalde** (Ana process): DURUM satırları, `LOW_QUALITY_REJECT`, `ELITE-OMEGA`, acil durdurma mesajları.

---

## 4) Güven katmanı (kısa)

| Katman | Ne yapar? | Env / not |
|--------|-----------|------------|
| **DRY_RUN** | Açıkken daima simülasyon (paper) | `DRY_RUN=true` |
| **Paper** | Gerçek emir yok | `PAPER_MODE` (DRY yokken) |
| **Live kilidi** | Canlı açılmadan süreç çıkış | `LIVE_CONFIRM=YES` + `PAPER_MODE=false` |
| **Kalite barajı** | `Qadj` &lt; `effective_qmin` → BUY yok | `SIGNAL_QUALITY_MIN`, OMEGA sıkılaşması |
| **Rate-limit / fırtına** | Aşırı 429 → kill-switch tetik (loglama) | `kill_switch` / risk acil |
| **Circuit breaker** | Borsa hata serisi → sembol izolasyonu | `exchange_async` |

Detaylar ve tüm değişkenler: `super_otonom/config.py` + kökte `.env.example`.

---

## 5) Aşamalı geçiş (runbook akışı)

### A — İzleme (Faz 3)

1. `DRY_RUN=true` ve `ML_SERVICE_ENABLED=false` (istersen) ile sadece iç mantığı gör.
2. `health.log`’da en az 24 saat: rejim, Qraw/Qadj, `effective_qmin`, HOLD/BUY oranı, kırmızı mesaj yok.
3. `SIGNAL_QUALITY_MIN` ile seçiciliği onayla (ör. 50).

### B — Minör canlı (Faz 4’e geçiş)

1. `DRY_RUN=false`, **küçük** sermaye / testnet.
2. `LIVE_CONFIRM=YES`, `PAPER_MODE=false` (bilinçli onay).
3. İlk gün: terminal + `health.log` + (varsa) Prometheus: emir, slipaj, beklenmeyen `EMERGENCY_STOP` yok.

### C — ML / Neural link

1. `ML_SERVICE_ENABLED=true`, `ML_SERVICE_URL` ayarlanmış.
2. Gecikme ve hata: timeout’ta `no_external_ml` yolu — loglarda net olsun.

---

## 6) Hafif “iyi görünür” (SLO öncesi)

Bunlar Faz 5 SLO değil; yalnız “doğru çalışıyor gibi” kontrol listesi:

- [ ] Açılışta `ensure_health_file_logger` sonrası motor log üretir
- [ ] Döngüde `health.log` büyür veya hata yok
- [ ] Kasıtlı düşük kalite senaryosunda `LOW_QUALITY_REJECT` veya HOLD davranışı
- [ ] Borsa kesintisinde devre açılır / log yazılır (panic yok)
- [ ] `Ctrl+C` / SIGTERM ile temiz kapanış (logda uyarı)

---

## 7) Kırmızı bayraklar (müdahale)

- Sürekli `EMERGENCY_STOP`, `emergency=...` veya equity çöküşü
- `health.log` donması + terminalde istisna fırtınası
- Beklenmeyen çok sayıda gerçek emir (paper sanılıyorken: `PAPER_MODE` / `DRY_RUN` tekrar kontrol)
- 429/lim serisi → `rate_limit` / `kill_switch` logları: önce borsa ve IP limitini doğrula

**İlk eylem:** process durdur, log arşivle, `.env` ve borsa limitini gözden geçir, CI yeşil mi bak.

---

## 8) Faz 3–4 “tamam” tanımı (bu repo için)

- Bu runbook + `.env.example` repoda, ekip aynı dili konuşuyor
- **Faz 3-4 — İzleme turu, health ve operasyon** bölümü: izleme turu, health tablosu, log adımları, gözlem (metrik/Prometheus), güven katmanı doğrulamaları, canlı checklist, operasyonel + **acil durum** prosedürleri ve **kapanış checklist** tek yerde
- En az bir tam izleme turu ve üst bölümdeki **Faz 3-4 tamamlandı checklist** maddeleri elle işaretlenebilir; ek olarak hafif liste §6
- Canlı denenecekse: §5-B ve **Canlı sistem doğrulama checklist** **kasıtlı** ve loglu uygulanır

**Kapanış işareti:** Üstteki **“Faz 3-4 tamamlandı işareti ve checklist”** bölümü bu fazın runbook tarafını resmi olarak işaretler.

**Faz 5:** Kanıt paketi ve kurumsal kalite özeti `docs/EVIDENCE.md`; hizmet hedefleri ve SLO ihlal prosedürü `docs/SLO.md`; denetim ve güvenlik kontrolleri `docs/AUDIT.md`.

---

## 9) İlgili dosyalar

| Dosya | Rol |
|-------|-----|
| `docs/EVIDENCE.md` | Sistem kanıt paketi, test/CI özeti, kurumsal kalite beyanı (Faz 5) |
| `docs/SLO.md` | SLO tanımları, uptime/latency/hata/kurtarma hedefleri, ihlal prosedürü (Faz 5) |
| `docs/AUDIT.md` | Denetim kontrol listesi, güvenlik kontrolleri (Faz 5) |
| `super_otonom/main_loop.py` | Ana döngü, health yazımı, `AI KARAR` / `V6 DURUM` logları |
| `super_otonom/health_summary.py` | `health.log` formatı, `ensure_health_file_logger`, tick/durum metni |
| `super_otonom/metrics_exporter.py` | Prometheus `/metrics`, slipaj / rejim / circuit breaker göstergeleri |
| `super_otonom/exchange_async.py` | `CircuitBreaker`, async borsa çağrıları |
| `super_otonom/bot_engine.py` | Kalite, OMEGA, ML, sentiment, risk, metrik entegrasyonu |
| `super_otonom/ai_layer.py` | AI doğrulama, güven / gerekçe |
| `super_otonom/config.py` | Tüm `os.getenv` anahtarları (`RISK`, `METRICS`, `GENERAL`, …) |
| `.github/workflows/ci.yml` | Kalite kapısı |

Sürüm: uygulama sürümü `super_otonom.__version__` (tek kaynak) → `GENERAL["version"]` ve `pyproject.toml` [project] version ile aynı tutulur.
