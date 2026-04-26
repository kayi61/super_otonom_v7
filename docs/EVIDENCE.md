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

## 2) Test sonuçları özeti

Aşağıdaki rakamlar **onaylı kanıt paketi** için referans tabandır (CI ile aynı kapsam: ağır sweep testleri hariç).

| Metrik | Değer |
|--------|--------|
| Toplam test sayısı | **1058** |
| Paket altı satır kapsamı (`super_otonom`) | **%99.48** |
| Python sürümleri (CI matrisi) | 3.10, 3.12 |

**Yerelde yeniden üretim (sweep’ler hariç):**

```bash
pip install -e ".[dev]"
pytest tests/ -q \
  --ignore=tests/test_sweep_45k_to_50k.py \
  --ignore=tests/test_sweep_ext_4500.py \
  --ignore=tests/test_sweep_matrix_500.py \
  --cov=super_otonom --cov-report=term-missing
```

> Not: Tam parametre tarama testleri (`test_sweep_*`) bilinçli olarak CI dışı bırakılabilir; tam matris için `pytest tests/` kullanın.

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
