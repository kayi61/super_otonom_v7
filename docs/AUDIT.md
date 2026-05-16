# super_otonom — Denetim ve güvenlik (Faz 5)

**Hedef olgunluk:** **+9.9 üstü** güven skoru ile uyumlu, tekrarlanabilir kontroller.  
Bu liste **yasal denetim yerine geçmez**; iç ve dış denetime hazırlık içindir.

**9 bant özeti ve öncelikli 3 PR:** `docs/P09_BANDS.md` — yerel kapılar: `scripts/fastrun_p09.ps1`

---

## 1) Denetim kontrol listesi

Aşağıdaki maddeler periyodik (ör. çeyrek) veya sürüm öncesi işaretlenebilir.

### 1.1 Süreç ve kaynak

- [ ] Ana dalda son CI koşusu **yeşil** (lint + pytest + coverage eşiği).  
- [ ] `docs/EVIDENCE.md` içindeki test/kapsam özeti güncel mi (veya otomatik rapor bağlantısı var mı)?  
- [ ] `super_otonom.__version__` ile `pyproject.toml` / `GENERAL["version"]` uyumlu mu?  
- [ ] `.env` ve gerçek anahtarlar repoda **yok**; `.env.example` güncel mi?

### 1.2 Yapılandırma ve dağıtım

- [ ] Canlı / testnet ayrımı dokümante; `LIVE_CONFIRM`, `PAPER_MODE`, `DRY_RUN` anlaşılmış.  
- [ ] Risk parametreleri (`RISK`, `GENERAL`) üretim için gözden geçirildi.  
- [ ] Yedekleme ve geri yükleme (durum dosyaları, loglar) tanımlı mı?

### 1.3 Olay müdahalesi

- [ ] `docs/RUNBOOK.md` acil durum ve kurtarma bölümleri okunmuş / eğitim verilmiş.  
- [ ] `docs/SLO.md` ihlal prosedürü atanmış role bağlı mı?

### 1.4 İzlenebilirlik

- [ ] `logs/health.log` veya merkezi log politikası tanımlı.  
- [ ] Prometheus kullanılıyorsa `/metrics` ve alarm kuralları (varsa) gözden geçirildi.

---

## 2) Güvenlik kontrol

### 2.1 Kimlik bilgileri ve sırlar

- [ ] API anahtarları yalnız gizli depoda veya güvenli env’de; repoda düz metin yok.  
- [ ] Eski / iptal anahtarlar devre dışı; rotasyon politikası biliniyor.  
- [ ] Üretim anahtarları testnet ile karışmıyor (etiket ve env ayrımı).

### 2.2 Bağımlılıklar ve tedarik zinciri

- [ ] `pip install -e ".[dev]"` veya kilit dosyası ile tekrarlanabilir kurulum.  
- [ ] Bilinen kritik CVE’ler için bağımlılık taraması (manuel veya `pip audit` / GH Dependabot) yapıldı mı?

#### 2.2.1 Otomatik (pip-audit + SBOM + SLA)

| Araç | Rol |
|------|-----|
| **Dependabot** | `.github/dependabot.yml` — haftalık pip / Actions / Docker PR |
| **pip-audit** | `requirements.txt` CVE taraması |
| **SBOM** | `artifacts/sbom.cyclonedx.json` (CycloneDX) |
| **SLA** | `config/dependency_security.json` — critical **7 gün**, high **30 gün** (CI: critical+high = fail) |

Yerel fastrun:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/fastrun_security.ps1
```

CI: workflow `Security` / job `dependency-security`.

### 2.3 Ağ ve erişim

- [ ] Bot çalışan host / konteyner için gereksiz portlar kapalı.  
- [ ] Borsa API erişimi IP kısıtına uygun; VPN veya sabit çıkış gereksinimi dokümante.  
- [ ] SSH veya uzaktan erişim çok faktörlü / güçlü parola politikası (kurumsal politika ile).

### 2.4 Uygulama davranışı

- [ ] Canlı emir yolu yalnız bilinçli konfig ile açılıyor (runbook ile uyumlu).  
- [ ] Rate-limit ve circuit breaker devrede; aşırı deneme saldırısı yüzeyi sınırlı.  
- [ ] Hata mesajları istemciye veya loga gereksiz iç sırlar sızdırmıyor.

### 2.5 Veri ve gizlilik

- [ ] Kişisel veri işlenmiyorsa dokümante; işleniyorsa KVKK/GDPR uyumu için ayrı kayıt.  
- [ ] Loglarda hesap numarası / ham token kesilmesi veya maskeleme politikası.

### 2.6 Olay müdahalesi (güvenlik)

- [ ] Şüpheli aktivitede anahtar iptali ve borsa paneli adımları runbook’ta.  
- [ ] Güvenlik olayı zaman çizgisi ve öğrenilen dersler kaydı (post-incident).

---

## 3) İlgili belgeler

- `docs/EVIDENCE.md` — kanıt paketi  
- `docs/SLO.md` — hizmet hedefleri ve ihlal prosedürü  
- `docs/RUNBOOK.md` — operasyon ve acil durum  
