# super_otonom — Sistem kanıt paketi (Faz 5)

**Hedef olgunluk:** güven / kanıt skoru **+9.9 üstü** (iç değerlendirme).  
Bu belge, yazılımın **ölçülebilir kalite ve süreç kanıtlarını** tek yerde toplar.

---

## 1) Sistem kanıt paketi

| Bileşen | Kanıt türü | Konum / not |
|---------|------------|-------------|
| Kaynak kod | Versiyon kontümü, incelemeye açık geçmiş | Git repository |
| Otomatik test | Regresyon ve kapsam | `tests/`, `pytest` |
| Statik analiz | Stil ve hata önleme | Ruff (`ruff check super_otonom tests`) |
| Sürekli entegrasyon | Her PR/push’ta lint + test + coverage eşiği | `.github/workflows/ci.yml` |
| Çalışma doğrulama | Operasyonel runbook | `docs/RUNBOOK.md` |
| Hizmet hedefleri | Ölçüm ve ihlal prosedürü | `docs/SLO.md` |
| Denetim | Güvenlik ve uyum kontrol listesi | `docs/AUDIT.md` |

**Kanıt zinciri:** Kod değişikliği → CI yeşil → (üretimde) SLO gözlemi → olayda runbook + denetim kaydı.

---

## 2) Test sonuclari ozeti

Son dogrulama: **2026-06-05** (pytest 9.0.3, Python 3.12.10, Windows 10).

| Metrik | Deger |
|--------|--------|
| Toplam test sayisi (tam suite) | **53,218+** |
| Risk engine testleri (`tests/risk/`) | **1129** |
| Fail eden test sayisi | **0** (onceki 7 fail duzeltildi) |
| Python surumleri (CI matrisi) | 3.10, 3.12 |

**Kritik davranis testleri (ayri dogrulama):**

| Test dosyasi | Kapsam | Durum |
|-------------|--------|-------|
| `test_v8_architecture.py` | FORCE_ALL_CLOSE, karar hiyerarsisi | PASS |
| `test_bot_engine_paper_trades.py` | Paper BUY/TP, trend follow | PASS |
| `test_bot_main_coverage_ext.py` | Hard limit, live mode, recon | PASS |
| `test_bot_engine_96.py` | OB merge, stub fallback, entry gates | PASS |

**Yerelde yeniden uretim:**

```bash
pip install -e ".[dev]"
pytest tests/ -q --tb=short
```

> Not: Tam parametre tarama testleri (`test_sweep_*`) dahil. `_pytest_full.txt` dosyasi eski snapshot olabilir — her zaman canli `pytest` calistirin.

---

## 3) CI/CD kanıtı

| Adım | Açıklama |
|------|-----------|
| Tetikleyiciler | `push` / `pull_request` — `main`, `master`, `develop` |
| Lint | `ruff check super_otonom tests` |
| Test | `pytest tests/` (sweep ignore listesi ile hızlı profil) |
| Coverage | `--cov=super_otonom` + rapor; proje eşiği `ci.yml` içinde tanımlı |
| Eşzamanlılık | Aynı dalda önceki iş iptal (`concurrency`) |

**Kanıt olarak kullanım:** GitHub Actions run URL’si, yeşil commit SHA ve ilgili PR bağlantısı saklanır.

---

## 4) Kod kalitesi metrikleri

| Metrik | Kaynak | Hedef yönü |
|--------|--------|------------|
| Coverage (`super_otonom`) | `pytest-cov` | Yüksek, eşik CI ile kilitli |
| Lint temizliği | Ruff | Sıfır uyarı (CI) |
| Bağımlılık sabitleme | `pyproject.toml` / lock stratejisi | Tekrarlanabilir kurulum |
| Tek sürüm kaynağı | `super_otonom.__version__`, `GENERAL["version"]` | Sürüm sapması yok |
| Gözlemlenebilirlik | `health.log`, Prometheus (opsiyonel) | Runbook ile hizalı |

---

## 5) Kurumsal kalite belgesi

Bu bölüm, **kurumsal** veya **üst yönetim / uyum** tarafına yönelik kısa bir kalite beyanıdır.

1. **Süreç:** Yazılım değişiklikleri otomatik test ve lint kapısından geçer; ana dala birleşmeden önce CI yeşili esas alınır.  
2. **İzlenebilirlik:** Versiyon kontümü, runbook ve (üretimde) log/metrik izleri ile olaylar geriye dönük izlenebilir.  
3. **Risk:** Canlı işlem modları `.env` ve `config` ile kontrollüdür; `docs/RUNBOOK.md` ve `docs/SLO.md` operasyonel ve ölçülebilir sınırları tanımlar.  
4. **Denetim:** `docs/AUDIT.md` periyodik veya olay sonrası kontroller için kullanılabilir.  
5. **Sürekli iyileştirme:** SLO ihlalleri ve incident raporları aksiyon maddelerine bağlanır; eşikler yıllık veya sürüm bazında gözden geçirilir.

**Belge sahipliği:** Teknik liderlik + operasyon; onay tarihi ve sürüm notu ekip politikasına göre arşivlenir.

---

## 6) İlgili belgeler

- `docs/RUNBOOK.md` — operasyon ve izleme  
- `docs/SLO.md` — hizmet düzeyi hedefleri  
- `docs/AUDIT.md` — denetim ve güvenlik kontrolleri  
- `.github/workflows/ci.yml` — CI tanımı  
