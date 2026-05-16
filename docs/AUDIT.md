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

---

## 4) Çeyrek AUDIT turu (salt okuma) — **2026-Q2** · PROMPT 8.2

**Tur tarihi:** 2026-05-16 · **Kapsam:** `AUDIT.md` §1–§2 maddeleri; kod değişikliği yapılmadı, kanıt yerel repo + GitHub CLI ile kontrol edildi.

### 4.1 Özet tablo

| Ref | Konu | Durum | Kısa kanıt |
|-----|------|-------|------------|
| 1.1 | Ana dal CI yeşil | **OK** | `main` son başarılı CI: PR #7 merge sonrası yeşil koşu (`gh run list --branch main --workflow CI`). |
| 1.1 | `docs/EVIDENCE.md` güncelliği | **BORÇ** | §2’deki test sayısı / coverage sabit; CI coverage omit ve iş akışı evrimi ile rakamlar yeniden üretilmeden tam kanıt sayılmamalı. |
| 1.1 | Sürüm uyumu | **OK** | `super_otonom.__version__`, `pyproject.toml`, `GENERAL["version"]` → **7.0.0**. |
| 1.1 | `.env` repoda yok | **OK** | `git ls-files` ile `.env` izlenmiyor; `.gitignore` kapsıyor. |
| 1.1 | `.env.example` güncel mi | **KISMİ** | `.env.example` ve `.env.template` birlikte izleniyor; çift kaynak sapması riski — çeyrekte hizalama (bkz. aksiyon). |
| 1.2 | Canlı / sim matrisi dokümante | **OK** | `RUNBOOK.md` ortam matrisi + şablon dosyaları. |
| 1.2 | Risk parametreleri üretim gözden geçirme | **İNSAN** | `RISK` / env üretim öncesi iş listesi; otomatik doğrulanamaz. |
| 1.2 | Yedek / geri yükleme | **OK** | `docs/DR_BCP.md`, `scripts/backup_daily.*`, görev zamanlayıcı (kurulum yerelde yapıldıysa). |
| 1.3 | RUNBOOK acil durum | **OK** | `docs/RUNBOOK.md` (Faz 3–7). |
| 1.3 | `docs/SLO.md` ihlal prosedürü + rol | **BORÇ** | Prosedür §6 mevcut; **ihlal sahibi rol/ad** org içinde atanmamış — tek satır sahiplik gerekir. |
| 1.4 | Log politikası | **KISMİ** | `logs/` gitignore; merkezi toplama tanımı yok — tek makine varsayımı. |
| 1.4 | Prometheus / alarmlar | **OK** | `.github/workflows/ci.yml`, `docker/prometheus/alerts.yml`, Grafana provisioning (Faz 6). |
| 2.1 | Sırlar repoda düz metin | **OK** (git) | İzlenen dosyalarda `.env` yok; yerelde `data/local/*` kullanıcı disiplini. |
| 2.1 | Rotasyon politikası | **BORÇ** | Yazılı sıklık/onay akışı yok — kısa runbook özeti önerilir. |
| 2.2 | Tekrarlanabilir kurulum | **OK** | `pyproject.toml` + `pip install -e ".[dev]"`. |
| 2.2 | CVE / Dependabot | **OK** | `.github/dependabot.yml`; CI `dependency-security`; `scripts/fastrun_security.ps1`. |
| 2.3–2.6 | Ağ, canlı emir, GDPR, güvenlik olayı | **KISMİ / İNSAN** | Kod/runbook ile uyumlu; kurumsal VPN/MFA/KVKK kanıtı org düzeyinde. |

### 4.2 Süreç borcu — aksiyon listesi

1. **`docs/EVIDENCE.md` §2 güncelle:** CI ile uyumlu pytest+coverage özetini yeniden üret; tabloya tarih/not ekle.  
2. **`.env.example` / `.env.template`:** Tek “canonical” şablon veya senkron prosedür tanımla (çeyrek kontrol).  
3. **SLO ihlal sahibi:** `docs/SLO.md` §6 için atanmış kişi/rolü belgeye yaz.  
4. **Rotasyon:** API / Telegram / Vault sırları için kısa rotasyon & onay özeti (`RUNBOOK` veya `DR_BCP`).  
5. **Log sürdürülebilirliği:** Disk retention veya merkezi log hedefi için tek paragraflık politika.  
6. **KVKK/GDPR:** Kişisel veri var/yok beyanı tek satır güncelle (`AUDIT` veya `EVIDENCE`).

**Sonraki tur:** 2026-Q3 — bu bölümü arşivleyin veya `docs/AUDIT_HISTORY.md` ile tarihçe tutun.
