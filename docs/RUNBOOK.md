# super_otonom — Faz 3–4: Gözlem, güven, runbook

Bu belge, botu **güvenle izlemek**, **doğrulamak** ve **canlıya geçerken** kontrol listesini kullanmak içindir. Faz 5 (kanıt paketi, SLO imzası, dış inceleme) ayrı belgede genişletilir.

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
- En az bir tam izleme turu (checklist 5 maddesi elle işaretlenebilir)
- Canlı denenecekse: yukarıdaki B adımı **kasıtlı** ve loglu

Faz 5 (9+ puan) için: metrik bütçeleri, denetim izi, imzalanmış SLO, isteğe bağlı dış review — ayrı çalışma.

---

## 9) İlgili dosyalar

| Dosya | Rol |
|-------|-----|
| `super_otonom/main_loop.py` | Ana döngü, health yazımı |
| `super_otonom/health_summary.py` | `health.log` formatı |
| `super_otonom/config.py` | Tüm `os.getenv` anahtarları |
| `super_otonom/bot_engine.py` | Kalite, OMEGA, dış ML birleşimi |
| `.github/workflows/ci.yml` | Kalite kapısı |

Sürüm: uygulama sürümü `super_otonom.__version__` (tek kaynak) → `GENERAL["version"]` ve `pyproject.toml` [project] version ile aynı tutulur.
