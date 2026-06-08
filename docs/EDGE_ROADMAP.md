# Edge Yol Haritası v2 — EV-Optimal, Exact-Spec Çalışma Promptları

> **Dürüst çerçeve:** "En iyi roadmap" = edge bulma OLASILIĞINI ve **kendini-kandırmama**yı
> maksimize eden; başarıyı GARANTİ ETMEYEN. Prompt kalitesi başarıyı garanti etmez (problem
> zor) — ama kötü roadmap kesin başarısızlık, bu = en yüksek şans. Sıra **beklenen-değere**
> göre: P(edge bulma) × (edge büyüklüğü) × (bizim uygulayabilirliğimiz). Her EP kendi
> sınavından geçer ya da ÖLDÜRÜLÜR. %80 hiçbir yerde vaat edilmez.

## CROSS-CUTTING DİSİPLİN (HER EP'ye uygulanır — pazarlık yok)
1. **Mekanizma zorunlu:** "neden edge var, karşıda kim ödüyor, neden arbitrajlanmamış, decay?"
   cevabı yoksa test etme.
2. **Ön-kayıt:** test ÖNCESİ hipotez + tam yöntem `EDGE_LOG.md`'ye (şablon EP-0'da). Sonradan kıvırma yok.
3. **NULL-KONTROL (kritik):** her yöntem ÖNCE rastgele/karıştırılmış veride koşulur → **edge ÇIKMAMALI.**
   Gürültüde edge çıkıyorsa harness sızdırıyor → önce onu düzelt. (Çoğu sahte "edge" buradan yakalanır.)
4. **Out-of-sample kutsal:** CPCV (purged) + Deflated Sharpe (çok-deneme düzeltmesi).
5. **Gerçekçi maliyet + kapasite:** maker/taker + slippage(hacim-bağlı) + funding + borrow + market-impact.
6. **Robustluk:** parametre ARALIĞI + rejim + sembol + alt-dönem. Tek değer çalışıyorsa = fluke.
7. **Rejim-koşullu test:** edge sadece belirli rejimde mi (vol/trend)? Koşullu edge gerçek olabilir;
   ama her koşul örneklemi düşürür → Deflated Sharpe sıkı.
8. **KILL > kabul:** işin %95'i RED sebebi aramaktır.

---

# FAZ 0 — TEMEL (zorunlu; bitmeden hiçbir sonuca güvenme)

## EP-0 — Sınav altyapısı + null-kalibrasyon
- **Amaç:** Kandırılamaz, kalibre edilmiş bir sınav.
- **Exact yöntem:** `edge_validate`'e ekle:
  - **CPCV** (López de Prado, purged+embargo k-fold) — sızıntısız out-of-sample.
  - **Deflated Sharpe Ratio** (denenen hipotez sayısını argüman al → şişmeyi düzelt).
  - **Maliyet modeli:** taker 5bps + slippage = f(emir/ADV), funding tahakkuku, borrow.
  - **Kapasite tahmini:** emrin fiyatı kaç bps iteceği (order-book derinliği / ADV %).
  - **3'lü split:** train(%60)/validation(%20)/**test(%20, mühürlü)**.
  - **`EDGE_LOG.md` şablonu:** [tarih, hipotez, mekanizma, yöntem, ön-kayıt-tarihi, sonuç, verdikt].
- **NULL-KALİBRASYON:** rastgele sinyalde → "NO_EDGE", sentetik-gömülü-edge'de → "VALIDATED".
  İkisi de doğruysa harness güvenilir.
- **Geçme:** iki kalibrasyon da doğru. **Prior:** kesin (altyapı, edge değil).
- **Çıktı:** sertleştirilmiş harness + günlük. **Olmadan aşağısı geçersiz.**

---

# FAZ 1 — EN YÜKSEK BEKLENEN-DEĞER (iki paralel bahis: bir "tavan", bir "taban")

## EP-1 — Cross-sectional momentum *(BAŞLANGIÇ — en yüksek tavan + akademik kanıt)*
- **Mekanizma:** Göreceli güç kısa-orta vadede kalıcıdır (bilgi yayılım gecikmesi + sürü). Mutlak
  yön DEĞİL — kazananı kaybedene karşı. Karşı taraf = geç tepki veren retail.
- **Exact yöntem:** 20-30 likit alt (BTC hariç tutulabilir). Her rebalance'ta geçmiş **{7,14,30,60,90}
  gün** getiriye göre sırala → üst %20 LONG, alt %20 SHORT, **dolar-nötr + beta-nötr.** Rebalance
  {günlük, 3-gün, haftalık}. Fee+slip dahil. **Piyasadan arındırılmış** (boğa/ayıdan bağımsız).
- **Null-kontrol:** sembol etiketlerini karıştır → edge sıfırlanmalı.
- **Geçme:** market-nötr net **Sharpe > 1.0**, **Deflated Sharpe p<0.05**, parametre aralığında
  stabil (tek lookback'e bağlı değil), hold-out + alt-dönem robust, kapasite makul.
- **KILL:** sadece boğada çalışıyor / nötr Sharpe < 0.5 / tek parametreye duyarlı / null sızdırıyor.
- **Prior:** ORTA-YÜKSEK. **İlk gerçek hipotez bu olmalı** (en yüksek EV).

## EP-2 — Funding/basis carry (delta-nötr) *(TABAN — mekanik, en olası-gerçek)*
- **Mekanizma:** Kaldıraçlı boğa funding/prim ÖDEMEK zorunda; sen market-nötr (long-spot+short-perp)
  durup hasat edersin. Karşı taraf = sabırsız kaldıraçlı long.
- **Exact yöntem:** Seçici — yalnız pozitif-funding majör; negatif-funding'de çık. İki-bacak fee +
  rebalance + **short bacak likidasyon marjı** modellenir. **Net APR** (brut değil) ölç. Basis
  versiyonu: future-spot primi ayrı (funding ile çift-sayım yok).
- **Geçme:** net (maliyet+likidasyon-tampon sonrası) **≥ %8/yıl**, çok-sembol/dönem, t anlamlı.
- **KILL:** net < risksiz USD (~%4-5) / likidasyon riski getiriyi yutuyor.
- **Prior:** ORTA (gerçek ama mütevazı tavan ~%3-8/yıl net). **Floor stratejisi.**

> Faz 1 mantığı: EP-1 yüksek-tavan şansı (Sharpe>1 olabilir), EP-2 düşük-tavan ama yüksek-kesinlik
> floor. İkisini paralel test → ya gerçek bir faktör (EP-1) ya da mütevazı carry (EP-2) ya da hiçbiri.

---

# FAZ 2 — FAKTÖR GENİŞLETME + ENSEMBLE

## EP-3 — Cross-sectional carry/value (funding-faktörü)
- **Mekanizma:** Yüksek-funding altları short, negatif-funding'i long — yön değil, **göreceli carry.**
- **Yöntem:** EP-1 iskeleti, sıralama metriği = funding (ve/veya basis). **Prior:** ORTA.

## EP-4 — Çok-faktör ensemble (momentum + carry, düşük korelasyon)
- **Mekanizma:** Tek faktör kırılgan; **korelasyonsuz faktörler birleşince** Sharpe artar, drawdown düşer.
  (Gerçek sistematik fonların yaptığı budur — tek sinyal değil.)
- **Yöntem:** EP-1,2,3'ten geçenlerin korelasyon matrisi → risk-parity ağırlık → birleşik nötr portföy.
- **Geçme:** birleşik Sharpe > bileşenlerin en iyisi + drawdown düşüyor. **Prior:** sentez (geçenler varsa).

---

# FAZ 3 — EVENT-DRIVEN (test edilebilir nişler; yalnız Faz 1-2 umut verdiyse)

## EP-5 — Yeni-listeleme paterni · EP-6 — Token-unlock öncesi baskı · EP-7 — Koşullu funding (confluence)
- **Mekanizma/yöntem/KILL:** event-çevresi getiri dağılımı + paternin dönemler-arası kalıcılığı;
  her ek koşul örneklemi düşürür → Deflated Sharpe sıkı. **Prior:** DÜŞÜK-ORTA.

---

# FAZ 4 — ZOR / DÜŞÜK PRIOR (yalnız üsttekiler tükendiyse)

## EP-8 — Stat-arb / pairs (kointegrasyon, market-nötr) · EP-9 — On-chain (ÜCRETLİ veri kapısı)
- **KILL:** çift decohere / on-chain rijit testte zayıf. **Prior:** DÜŞÜK.

---

# FAZ 5 — SENTEZ & KONUŞLANDIRMA (yalnız hayatta-kalan varsa)

## EP-10 — Canlı testnet ileri-doğrulama (≥1-3 ay)
- **Geçme:** canlı ≥ backtest'in %50'si + tracking-error makul + alpha-decay yok. **KILL:** canlı
  çöküyor → backtest'te gizli sızıntı. Çoğu burada ölür (normal).

## EP-11 — Risk/sizing (P-7) + mikro gerçek sermaye
- **Yöntem:** fractional Kelly / vol-target + mevcut risk motoru (kill-switch, drawdown). **EN KÜÇÜK**
  miktar → canlı vs beklenti → sadece tutarsa ölçekle. **KILL:** mikro-canlı saparsa DUR.

---

## TOPLU KARAR KAPILARI (ön-taahhüt — duygusal değil)
- EP-0 bitmeden hiçbir edge sonucuna güvenme.
- **Faz 1'de (EP-1 + EP-2) ikisi de geçmezse + EP-3,4 da → ~3-4 yüksek-EV deneme başarısız → dürüstçe
  "bu setup'ta sağlam edge yok", DUR/pivot.** Alt-fazlara aylar gömme.
- Bir şey geçse bile **mütevazı** (net birkaç-çift hane %/yıl, market-nötr). **%80 fantezi — vaat YOK.**

## NEDEN BU SIRA "EN İYİ" (dürüst gerekçe)
- **EP-0 önce:** sağlam sınav olmadan her sonuç gürültü; null-kontrol sahte-edge'i baştan yakalar.
- **EP-1 (cross-sectional momentum) ilk:** kripto'da akademik olarak **en güçlü dokümante faktör** +
  market-nötr (rejimden bağımsız) + en yüksek tavan = en yüksek EV.
- **EP-2 paralel:** mekanik/kesin-gerçek bir **floor** verir (ya küçük carry bulursun ya da hiçbiri).
- **Ensemble (EP-4):** gerçek fonların tutarlılık sırrı — korelasyonsuz faktör birleşimi.
- **Event/stat-arb/on-chain sonra:** düşük prior + veri/operasyon engeli; ancak yüksek-EV'liler
  tükenirse.
- **Testnet + mikro sermaye en son:** backtest yalan söyleyebilir; gerçek para sadece her şey geçince.

> Sahte umut yok. Bu sıra **şansı maksimize eden** sıradır — garanti değil. En olası sonuç hâlâ
> "mütevazı bir şey ya da hiçbiri." Ama yapılırsa, **doğru ve kendini-kandırmadan** yapılır.
