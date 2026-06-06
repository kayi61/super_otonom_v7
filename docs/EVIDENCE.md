# super_otonom — Sistem kanıt paketi

> **TEK GERÇEK KAYNAK (single source of truth).**
> Bu belgedeki **her rakam**, yanındaki komutla yeniden üretilebilir. Tahmin, yuvarlama
> ile şişirme veya elle yazılmış sayı **yoktur**. Bir rakam komutla doğrulanamıyorsa bu
> belgede yer almaz. Eski sürümlerdeki uydurma/şişirilmiş rakamlar aşağıda açıkça
> **düzeltilmiştir** — gizlenmemiştir.
>
> **Son doğrulama:** 2026-06-06
> **Ortam:** test sayıları → yerel (pytest 9.0.3, Python 3.12.10, Windows 10);
> coverage → CI (ubuntu-latest, Python 3.10 & 3.12).

---

## 0) ⚠️ ÖNCEKİ SÜRÜMDEKİ SAHTE RAKAMLARIN DÜZELTMESİ

Bu belgenin eski hâli güvenilmez rakamlar içeriyordu. Denetçi güvenini korumak için
hepsi burada açıkça düzeltilir:

| Eski iddia | Gerçek | Sebep |
|-----------|--------|-------|
| Toplam test **"53,218+"** | **6528** | 53k rakamı, sonradan **silinen** ağır-parametrik sweep suite'lerini sayıyordu. |
| Coverage **"Yüksek, eşik CI ile kilitli"** (muğlak) | **%89.70** | Gerçek ölçülmüş değer; muğlak ifade yerine somut sayı + komut. |
| Dolaşan üç çelişkili sayı (~53k / 1129 / ~6.5k) | Tek tablo (bkz. §1) | Üç sayı üç farklı şeyi ölçüyordu; artık tek kaynak var. |

### Silinen sweep testleri (gizlenmeyen coverage etkisi)
Şu dosyalar commit **`4af84a1`** ("fix(ci): deploy_env_check on GHA, ruff sweep cleanup")
ile **silindi** ve artık diskte yok:

- `tests/test_sweep_45k_to_50k.py`
- `tests/test_sweep_ext_4500.py`
- `tests/test_sweep_matrix_500.py`

Bu sweep'ler ~46.000 parametrik vaka üretiyordu; silinince toplam test ~53k → **6528**'e
düştü. **Dürüst not:** Bu sweep'ler çoğunlukla aynı kod yollarını binlerce parametreyle
tekrar geziyordu; sildikten sonra gerçek **kod** coverage'ı anlamlı düşmedi (coverage satır
bazlıdır, parametre tekrarı yeni satır kapsamaz). Asıl yanıltıcı olan, silinmiş testleri
hâlâ "53,218+ test" diye saymaktı — bu düzeltildi.

> `pyproject.toml`'daki bu silinmiş dosyalara ait **ölü `per-file-ignores` referansları
> (eski satır 102-104) bu çalışmada temizlendi.**

---

## 1) Test sayıları — ölçülmüş, yeniden üretilebilir

| Metrik | Değer | Yeniden üretim komutu |
|--------|-------|------------------------|
| Toplam toplanan test | **6528** | `python -m pytest tests/ --collect-only -q 2>&1 \| grep -E ': [0-9]+$' \| awk -F': ' '{s+=$2} END{print s}'` |
| Test dosyası sayısı | **216** | yukarıdaki komut, `END{print NR}` |
| Risk engine testleri (`tests/risk/`) | **1129** | `python -m pytest tests/risk/ --collect-only -q 2>&1 \| grep -E ': [0-9]+$' \| awk -F': ' '{s+=$2} END{print s}'` |
| Fail eden test | **0** | CI `pytest-full` job, run `27060751037`, `conclusion=success` |
| Python sürümleri (CI matrisi) | 3.10, 3.12 | `.github/workflows/ci.yml` |

> Not: Komut **`python -m pytest`** ile çalıştırılmalı (çıplak `pytest` bu projede pythonpath
> nedeniyle boş dönebilir) ve `2>&1` şarttır. Bu pytest sürümü `--collect-only -q` ile
> dosya-başına `path: N` satırı basar, tek "N collected" özeti vermez; sayım dosya-başı
> değerlerin toplamıdır (yukarıdaki awk). Doğrulandı: 2026-06-06, çıktı = 6528 / 1129.

---

## 2) Coverage — gerçek yüzde, yuvarlamasız

| Metrik | Değer |
|--------|-------|
| **Gerçek toplam coverage** | **%89.70** (yuvarlanmadan) |
| Statements / Miss | 23624 / 2064 |
| Branch / partial | 7426 / 799 |
| CI eşiği | `--cov-fail-under=90` |

**Komut (CI ile birebir aynı):**
```bash
python -m pytest tests/ --cov=super_otonom --cov-report=term-missing --cov-fail-under=90
```
**Kaynak / kanıt:** CI run `27060751037`, commit `384fa72` (main'e `e0aaa94` olarak merge),
ubuntu-latest, Python 3.10 & 3.12, 2026-06-06.

### ⚠️ Dürüst uyarı 1 — %90 eşiği YUVARLAMAYLA geçiyor
Gerçek değer **%89.70**, yani **%90.0'ın ALTINDA**. CI yeşil yanıyor çünkü coverage.py
varsayılan olarak tam sayıya yuvarlar (precision=0): `89.70 → 90 ≥ 90 → geçer`. Karşılaştırma:
önceki commit **%89.49** ile `89`'a yuvarlanıp **kaldı** (kırmızı). Yani **"%90 coverage'a
ulaştık" demek yanlıştır** — ulaşılan değer %89.70'tir; eşik yuvarlama sınırında geçilir.

### ⚠️ Dürüst uyarı 2 — coverage TÜM kod tabanı üzerinde DEĞİL
%89.70, `[tool.coverage.run] omit` listesiyle **hariç tutulan 15 yol** dışındaki alt küme
üzerinde ölçülür. Hariç tutulanlar arasında **3 ürün modülü** vardır:
`signal_quality_scorer.py`, `correlation_manager.py`, `ml_client.py`. Ayrıca 8 CLI/ops/infra
modülü: alertmanager bridge, `risk_institutional_summary`, timescale ×2, vault ×3 ve
**`ws_manager.py`**. Bu omit listesi, gerçek sayıyı kod tabanının tamamına kıyasla **yukarı
çeker**. (Not: testnet WS host düzeltmesi `ws_manager.py` içindedir; bu dosya omit'te
olduğundan coverage'a yansımaz.)

### ⚠️ Dürüst uyarı 3 — küçük koşu-arası sapma
`tests/risk/test_var_properties_vr26.py` Hypothesis property testleri her koşuda farklı
örnekler ürettiğinden coverage ~±0.2% oynar. %89.70 tek bir koşunun değeridir; bant ~%89.5–89.7.

---

## 3) Kritik davranış testleri (ayrı doğrulama)

| Test dosyası | Kapsam | Durum |
|-------------|--------|-------|
| `tests/test_v8_architecture.py` | FORCE_ALL_CLOSE, karar hiyerarşisi | PASS |
| `tests/test_bot_engine_paper_trades.py` | Paper BUY/TP, trend follow | PASS |
| `tests/test_bot_main_coverage_ext.py` | Hard limit, live mode, recon | PASS |
| `tests/test_bot_engine_96.py` | OB merge, stub fallback, entry gates | PASS |
| `tests/test_ops_hardening_p4p5.py` | go-live gate, Vault auto-unseal, create_order | PASS |

Yeniden üretim: `pytest tests/test_v8_architecture.py tests/test_ops_hardening_p4p5.py -q`

---

## 4) CI/CD kanıtı

| Adım | Açıklama |
|------|-----------|
| Tetikleyiciler | `push` / `pull_request` — `main`, `master`, `develop` |
| Lint | `ruff check super_otonom tests` |
| Test | `pytest tests/` (`addopts = "-q"`; ayrı sweep ignore listesi YOK) |
| Coverage | `--cov=super_otonom --cov-fail-under=90` (omit listesi: `pyproject.toml`) |
| Eşzamanlılık | Aynı dalda önceki iş iptal (`concurrency`) |

**Kanıt zinciri:** Kod değişikliği → CI yeşil → merge. Her merge için GitHub Actions run
URL'si, commit SHA ve PR bağlantısı izlenebilir (örn. PR #133 → run `27060751037` → `e0aaa94`).

---

## 5) Tüm rakamları tek seferde yeniden üret (kopyala-çalıştır)

```bash
pip install -e ".[dev]"

# 1) Toplam test sayısı (beklenen: 6528)
python -m pytest tests/ --collect-only -q 2>&1 | grep -E ': [0-9]+$' | awk -F': ' '{s+=$2} END{print "TOPLAM TEST:", s}'

# 2) Risk testleri (beklenen: 1129)
python -m pytest tests/risk/ --collect-only -q 2>&1 | grep -E ': [0-9]+$' | awk -F': ' '{s+=$2} END{print "RISK TEST:", s}'

# 3) Gerçek coverage (beklenen: ~%89.70; eşik yuvarlamayla geçer)
python -m pytest tests/ --cov=super_otonom --cov-report=term-missing --cov-fail-under=90

# 4) Ortam
pytest --version ; python --version
```

---

## 6) İlgili belgeler

- `docs/RUNBOOK.md` — operasyon ve izleme
- `docs/SLO.md` — hizmet düzeyi hedefleri
- `docs/AUDIT.md` — denetim ve güvenlik kontrolleri
- `.github/workflows/ci.yml` — CI tanımı
