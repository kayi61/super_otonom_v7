# super_otonom — Service Level Objectives (Faz 5)

**Hedef olgunluk:** güven skoru **+9.9 üstü** ile uyumlu, **ölçülebilir** hizmet hedefleri.  
Bu belge **ürün SLA’sı değildir**; ekip içi SLO ve üretim öncesi hedefleme içindir. Müşteriye taahhüt öncesi hukuk ve iş birimi onayı gerekir.

---

## 1) Service Level Objectives tanımları

| SLO kimliği | Tanım | Ölçüm penceresi |
|-------------|--------|------------------|
| SLO-Availability | Bot kontrol düzleminin ve kritik uçların ulaşılabilirliği | Aylık takvim |
| SLO-Latency | Borsa / iç işlem yolu gecikme bütçeleri | P95 / P99, rolling 7 gün |
| SLO-Errors | İşlem ve API hata oranı üst sınırı | Rolling 24 saat / 7 gün |
| SLO-Recovery | Olay sonrası normale dönüş süresi | Olay bazlı |

**SLI (gösterge) örnekleri:** süreç çalışıyor mu, `health.log` güncelleniyor mu, Prometheus varsa metrik kaybı, borsa HTTP hata oranı, circuit breaker açılma sıklığı, kullanıcıya yansıyan başarısız emir oranı (tanımlıysa).

---

## 2) Uptime hedefi

| Hedef | Değer | Not |
|-------|--------|-----|
| Kontrol düzlemi hedefi | **%99.9** aylık | Yaklaşık **43 dakika** / ay planlı dışı kesinti bütçesi (teorik üst sınır) |

**Kapsam önerisi (netleştirin):**

- Dahil: `main_loop` süreci ayakta, log yazımı, kritik konfig okunabilir.  
- Hariç veya ayrı SLO: üçüncü taraf borsa kesintisi, internet servis sağlayıcı, müşteri API kotası dışı olaylar (ayırt edici etiketle raporlanır).

---

## 3) Latency hedefleri

Aşağıdakiler **hedef bütçe**dir; piyasa ve ağ koşullarına göre kalibre edilmelidir.

| Yol | Hedef (P95) | Hedef (P99) | Not |
|-----|-------------|-------------|-----|
| OHLCV / order book çekimi (tek sembol) | &lt; 3 s | &lt; 8 s | Rate-limit ve CB etkisi ayrı izlenir |
| Tick işleme (analiz + `engine.tick` dahil) | &lt; 5 s | &lt; 15 s | CPU ve kuyruk derinliği ile ilişkili |
| Dış ML çağrısı (açıksa) | `ML_SERVICE_TIMEOUT` içinde | Aynı + marj | Timeout’ta fallback yolu runbook’ta |

**Ölçüm:** Uygulama logları, Prometheus histogramları (varsa), APM veya dağıtık trace (ileride).

---

## 4) Hata oranı hedefleri

| Gösterge | Hedef | Açıklama |
|----------|--------|----------|
| Kritik işlem hatası (unhandled exception / process crash) | **0** hedef; pratikte nadiren | Her olay incident |
| Borsa API 4xx/5xx (normalize edilmiş) | &lt; **%1** istek (rolling 24s) uyarı; &lt; **%0.1** hedef (stabil ortam) | 429 ayrı etiket |
| Circuit breaker açılma | Sürekli açık kalma **yok** | Recovery döngüsü izlenir |
| Sinyal reddi (LOW_QUALITY vb.) | İş kuralı; “hata” değil | Ancak ani %100 reddiye kök neden analizi |

---

## 5) Recovery time hedefleri

| Olay sınıfı | RTO (hedef) | RPO / veri | Not |
|-------------|-------------|------------|-----|
| Süreç çöküşü (tek host) | **&lt; 15 dk** yeniden başlatma | Durum dosyaları runbook | Otomatik restart politikası opsiyonel |
| Borsa geçici kesinti | Bağımlılık | N/A | CB + runbook; kullanıcıya şeffaflık |
| Yanlış canlı konfig | **&lt; 5 dk** kill-switch / durdurma | Manuel doğrulama | `DRY_RUN` / paper geri dönüş |
| Güvenlik olayı (anahtar sızıntısı) | **&lt; 1 saat** ilk müdahale | Anahtar rotasyonu | `AUDIT.md` + acil runbook |

**MTTR** (mean time to repair) aylık raporlanır; iyileştirme hedefi yıllık %10 düşüş örnek alınabilir.

---

## 6) SLO ihlal prosedürü

**Birincil ihlal sahibi:** Sistem operatoru (bot operasyonundan sorumlu kisi).  
**Yedek:** Teknik lider veya kurucu.

1. **Tespit:** İzleme (Prometheus, log, sağlık dosyası) eşiği aştı veya SLO tanımı ihlal edildi.  
2. **Sınıflandırma:** Kullanıcı etkisi (var/yok), finansal etki, süreklilik.  
3. **Müdahale:** `docs/RUNBOOK.md` acil / kurtarma bölümü; gerekirse süreç durdur ve güvenli mod.  
4. **İletişim:** Ekip içi ve (politikaysa) paydaş bildirimi; SLO ihlali kaydı açılır.  
5. **Kök neden:** 5-Why veya eşdeğeri; geçici çözüm vs kalıcı düzeltme ayrımı.  
6. **Eylem maddeleri:** Kod, konfig, kapasite veya runbook güncellemesi; sahibi ve tarih.  
7. **Eşik gözden gezimi:** Bu SLO belgesinde hedef veya ölçüm tanımı güncellenmiş mi?  
8. **Kapanış:** Incident raporu arşiv; tekrarlayan ihlalde üst yönetim / kalite incelemesi.

---

## 6.1) Log retention politikasi

| Log tipi | Konum | Saklama suresi | Sorumlu |
|----------|-------|----------------|---------|
| Bot islem loglari (`trades.log`) | `data/trades.log` | Suresiz (append-only) | Sistem operatoru |
| Audit loglari | `data/audit/*.jsonl` | Min 1 yil | Sistem operatoru |
| Health log | `logs/health.log` | 90 gun (rotation onerisi) | Sistem operatoru |
| Reconciliation | `data/recon/` | 90 gun | Sistem operatoru |
| Capital journal | `data/capital_journal.jsonl` | Suresiz | Sistem operatoru |
| Prometheus TSDB | Docker volume | 15 gun (varsayilan) | Sistem operatoru |

**Merkezi log:** Uretimde `logs/` ve `data/audit/` dosyalari merkezi log sistemine (Loki, ELK veya eşdeğeri) yonlendirilmelidir. Varsayilan: yalnizca yerel disk.

---

## 6.2) Secret rotation politikasi

| Secret tipi | Rotation sikligi | Sorumlu | Yontem |
|-------------|------------------|---------|--------|
| Borsa API anahtarlari | 90 gun veya sizdirma sonrasi hemen | Sistem operatoru | Vault KV guncelleme + `vault_seed` |
| Vault AppRole secret_id | 30 gun | Sistem operatoru | `vault_rotate` |
| Telegram bot token | Yalnizca sizdirmada | Sistem operatoru | BotFather + Vault |
| Postgres / TimescaleDB | 90 gun | Sistem operatoru | Docker secret + restart |

**Acil rotation:** API anahtari sizdirma suphe/tespitinde derhal: (1) borsadan iptal, (2) yeni anahtar uret, (3) Vault'a yaz, (4) bot restart.

---

## 7) İlgili belgeler

- `docs/EVIDENCE.md` — test ve CI kanıtı  
- `docs/RUNBOOK.md` — operasyon  
- `docs/AUDIT.md` — denetim kontrolleri  
