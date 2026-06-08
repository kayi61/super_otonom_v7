# Edge Yol Haritası — Öncelik Sıralı Çalışma Promptları

> **Kullanım:** Her prompt'u sırayla bir iş-emri olarak ver. Her biri kendi sınavından
> (CPCV + Deflated Sharpe + maliyet + hold-out + canlı) geçmek zorunda. Geçmeyen → AT.
> **Sahte yok.** Her prompt'un dürüst priori + KILL kriteri var. "Kazandı" demek için
> tüm kapıları geçmesi şart. p-hacking (geçeni bulana kadar deneme) YASAK.

## META KURALLAR (hepsini yönetir — her prompt'a uygulanır)
- **Mekanizma zorunlu:** "neden edge var, karşı tarafta kim ödüyor, neden arbitrajlanmamış,
  decay riski ne?" cevabı yoksa → test etme.
- **Önce ön-kayıt:** test öncesi hipotez + yöntem `EDGE_LOG.md`'ye yazılır (sonradan kıvırma yok).
- **Out-of-sample kutsal:** test seti hiç görülmez; sonuç orada açıklanır.
- **Multiple-testing:** N hipotez denenince Deflated Sharpe / FDR uygulanır.
- **Maliyet gerçekçi:** maker/taker + slippage + funding + borrow + kapasite.
- **Robustluk:** parametre aralığı + rejim + sembol + alt-dönem. Tek değer çalışıyorsa = fluke.
- **KILL > kabul:** işin %95'i red sebebi aramaktır. Duygusal bağlanma yok.

---

# ÖNCELİK 0 — TEMEL (bunsuz her test güvenilmez; İLK bu)

## EP-0 — Validasyon sınavını sertleştir (overfit-katili altyapı)
- **Amaç:** Her stratejinin geçeceği rijit, kandırılamaz sınav.
- **Yöntem:** Mevcut `edge_validate`'e ekle: (1) **CPCV** (combinatorial purged cross-validation,
  López de Prado), (2) **Deflated Sharpe Ratio** (çok deneme düzeltmesi), (3) gerçekçi
  **maliyet/slippage/kapasite** modeli, (4) train/validation/test 3'lü ayrım, (5) `EDGE_LOG.md`
  araştırma günlüğü iskeleti.
- **Geçme:** sentetik bilinen-edge'de PASS, bilinen-no-edge'de FAIL verir (kalibrasyon kanıtı).
- **Prior:** kesin yapılabilir (altyapı işi, edge değil).
- **Çıktı:** sertleştirilmiş harness + günlük. **Bu olmadan aşağıdaki hiçbir sonuca güvenme.**

---

# ÖNCELİK 1 — MARKET-NÖTR / CARRY (retail için EN YÜKSEK taban-oran)

## EP-1 — Seçici funding hasadı (delta-nötr carry)
- **Mekanizma:** Kaldıraçlı long talebi short'u aşınca perp long'lar funding ÖDEMEK zorunda;
  sen long-spot + short-perp ile market-nötr durup funding'i HASAT edersin. Karşı taraf =
  sabırsız kaldıraçlı longlar.
- **Yöntem:** Yalnız pozitif-funding majörlerde gir; negatif-funding'de çık. Rebalance + iki-bacak
  maliyeti + **short bacak likidasyon riski** modellenir. Net APR ölç (brut değil).
- **Geçme:** net (maliyet+risk sonrası) ≥ %8/yıl, çok-sembol, çok-dönem; t anlamlı.
- **KILL:** net < risksiz USD (~%4-5) ya da likidasyon riski getiriyi yutuyor.
- **Prior:** ORTA (gerçek ama mütevazı; ~%3-6/yıl net çıkabilir). **En somut ilk aday.**

## EP-2 — Cash-and-carry basis hasadı
- **Mekanizma:** Boğada perp/futures spot'a prim yapar (contango); long-spot + short-future ile
  primi vade boyu hasat. Karşı taraf = primi ödeyen kaldıraçlı boğa.
- **Yöntem:** Basis (future-spot) ölç; eşik üstünde gir, yakınsayınca çık. Funding ile ilişkisini
  ayrıştır (çift-sayım yok).
- **Geçme/KILL:** EP-1 ile aynı çıta. **Prior:** ORTA.

## EP-3 — Cross-exchange funding/fiyat dislokasyonu (çok-borsa fizibilse)
- **Mekanizma:** Borsalar arası funding/fiyat farkları (segmentasyon). İki borsada zıt bacak.
- **Yöntem:** İki borsa API + transfer/latency maliyeti modellenir.
- **KILL:** transfer/withdraw maliyeti farkı yutuyor (genelde yutar). **Prior:** DÜŞÜK-ORTA
  (operasyonel ağır). Sadece EP-1/2 sonuç verirse.

---

# ÖNCELİK 2 — CROSS-SECTIONAL (akademik olarak en sağlam faktör)

## EP-4 — Cross-sectional momentum (market-nötr)
- **Mekanizma:** Kazananlar kısa-orta vadede kazanmaya, kaybedenler kaybetmeye devam eder
  (sürü + bilgi yayılım gecikmesi). Mutlak yön değil, **göreceli güç.**
- **Yöntem:** 15-30 likit alt; geçmiş N-period getiriye göre sırala; üst %20 LONG, alt %20 SHORT
  (dolar-nötr). Periyodik rebalance. Mutlak piyasadan arındırılmış → boğa/ayıdan bağımsız test.
- **Geçme:** market-nötr net Sharpe > 1, Deflated Sharpe anlamlı, hold-out + alt-dönem robust.
- **KILL:** sadece boğada çalışıyor / nötr Sharpe < 0.5 / parametreye duyarlı.
- **Prior:** ORTA-YÜKSEK (akademik literatürde kripto'da en güçlü faktör). **Test etmeye en değer.**

## EP-5 — Cross-sectional carry/value
- **Mekanizma:** Yüksek-funding altları short, düşük/negatif-funding'i long (carry faktörü).
- **Yöntem:** EP-4 iskeleti, sıralama metriği = funding. **Prior:** ORTA.

---

# ÖNCELİK 3 — EVENT-DRIVEN (test edilebilir nişler)

## EP-6 — Yeni-listeleme paterni
- **Mekanizma:** Listeleme anı dikkat + likidite şoku → tekrar eden pump/dump paterni.
- **Yöntem:** Tarihsel Binance listelemeleri; listeleme sonrası saatlik getiri dağılımı + paternin
  istatistiksel kalıcılığı. **KILL:** patern dönemler arası tutmuyor. **Prior:** DÜŞÜK-ORTA.

## EP-7 — Token-unlock öncesi baskı
- **Mekanizma:** Büyük unlock öncesi bilinen arz baskısı → öngörülebilir zayıflık.
- **Yöntem:** Unlock takvimi + event-çevresi getiri çalışması. **KILL:** etki zaten fiyatlanmış.
  **Prior:** DÜŞÜK-ORTA.

## EP-8 — Koşullu funding ekstremi (naive DEĞİL)
- **Mekanizma:** Funding tek başına yön vermiyor (kanıtlandı), ama **confluence** (ekstrem funding
  + OI sıçraması + likidite boşluğu) koşullu bir edge olabilir.
- **Yöntem:** Çok-koşullu filtre; ama her ek koşul overfit riski → Deflated Sharpe sıkı.
  **KILL:** koşul sayısı arttıkça örneklem düşer, anlamlılık kaybolur. **Prior:** DÜŞÜK.

---

# ÖNCELİK 4 — ZOR / DÜŞÜK PRIOR (yalnız üsttekiler tükenirse)

## EP-9 — Statistical arbitrage / pairs (kointegrasyon)
- **Mekanizma:** Kointegre iki varlığın spread'i ortalamaya döner; ayrıldığında bahse gir.
- **Yöntem:** Kointegrasyon testi + spread z-score + market-nötr. **KILL:** çift decohere oluyor /
  in-sample kointegrasyon out-of-sample bozuluyor. **Prior:** ORTA-DÜŞÜK (kalabalık).

## EP-10 — On-chain sinyaller (ücretli veri kapısı)
- **Mekanizma:** Exchange giriş/çıkış, stablecoin akışı, smart-money — yapısal akış bilgisi.
- **Yöntem:** Glassnode/CryptoQuant API (ÜCRETLİ — önce veri kararı). Sinyal → forward getiri
  çalışması. **KILL:** rijit testte zayıf (genelde öyle çıkar). **Prior:** DÜŞÜK + maliyet engeli.

---

# ÖNCELİK 5 — SENTEZ & KONUŞLANDIRMA (yalnız hayatta-kalan varsa)

## EP-11 — Portföy: korelasyonsuz edge'leri birleştir
- **Mekanizma:** Tek edge kırılgan; 2-5 **düşük korelasyonlu** edge = pürüzsüz, sağlam.
- **Yöntem:** Hayatta kalanların korelasyon matrisi + risk-parity/eşit-risk ağırlık.
- **KILL:** tüm edge'ler aynı rejimde ölüyorsa (gizli korelasyon). **Prior:** sentez işi.

## EP-12 — Canlı testnet ileri-doğrulama
- **Amaç:** Backtest ≠ canlı. Hayatta kalan portföyü **≥1-3 ay testnette** çalıştır.
- **Geçme:** canlı performans backtest'in ≥%50'si + tracking-error makul + alpha-decay yok.
- **KILL:** canlı çöküyor → backtest'te gizli sızıntı vardı. **Prior:** çoğu burada ölür (normal).

## EP-13 — Risk/sizing + mikro gerçek sermaye (P-7)
- **Yöntem:** Fractional Kelly / vol-target sizing + mevcut risk motoru (kill-switch, drawdown).
  **EN KÜÇÜK** gerçek miktar → canlı vs beklenti izle → sadece tutarsa ölçekle.
- **KILL:** mikro-canlı beklentiden saparsa → DUR. **Prior:** sadece her şey geçtiyse.

---

## TOPLU KARAR KAPILARI (ön-taahhüt)
- EP-0 bitmeden hiçbir edge sonucuna güvenme.
- ÖNCELİK 1-2'de (EP-1,2,4) **3-4 ciddi deneme de geçmezse → dürüstçe "bu setup'ta edge yok",
  dur ya da pivot.** Boşuna ÖNCELİK 3-4'e aylar gömme.
- Bir şey geçse bile **mütevazı** (net birkaç-çift hane %/yıl); **%80 hedefi hiçbir aşamada
  vaat EDİLMEZ** — o fantezidir.

## DÜRÜST ÖZET
Bu sıralama **şansı maksimize eder, garanti vermez.** En yüksek-prior yollar (carry, cross-sectional)
önce. Her adım bir red makinesi; geçen nadirdir. Edge bulunursa küçük + gerçek olur — ve o bile
nadir bir başarıdır. Sahte umut yok; sadece disiplinli, sıralı, kanıt-temelli arama.
