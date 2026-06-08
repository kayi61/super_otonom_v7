# Edge Araştırma Programı — Kapsamlı Master Plan (Aylar)

> **Bu belge tek doğruluk kaynağıdır.** Her hipotez + sonuç buraya işlenir. Amaç:
> kendimizi kandırmadan, fee-sonrası, out-of-sample, **gerçek ve tekrarlanabilir** bir
> edge aramak. Bulursak uygularız; bulamazsak dürüstçe "yok" deriz — para kaybetmeden.

## 0) DÜRÜST HEDEF KALİBRASYONU (önce bunu oku)
- **ULAŞILAMAZ:** "piyasayı domine etmek." Solo + retail-API + Python ile imkânsız.
  Domination = sermaye + hız (co-location) + özel veri + ekip. Bizde yok.
- **NEREDE YARIŞAMAYIZ:** HFT, latency-arb, market-making (majörlerde), saf hız.
- **NEREDE YARIŞABİLİRİZ (yapısal avantajlarımız):** sabır (kariyer riski yok),
  küçük/niş kapasite (büyük fonlara değmeyecek köşeler), market-nötr taşıma, uzun ufuk.
- **GERÇEK HEDEF:** fee+slippage sonrası, out-of-sample VE canlı testnette pozitif
  risk-ayarlı getiri veren, kapasitesi mütevazı **tek sağlam edge.** Bu zaten nadirdir.
- **BAŞARI TANIMI:** Faz 4 (canlı testnet) sonrası backtest'e yakın performans +
  Deflated Sharpe anlamlı + B&H'a karşı risk-ayarlı üstünlük. Bundan azı "kazanan değil".

## 1) ARAŞTIRMA ALTYAPISI (laboratuvar) — Faz 0
**Veri katmanı:**
- Çok-TF, çok-sembol OHLCV (sayfalamalı, mevcut `edge_validate`/`fetch_range`).
- Funding, Open Interest, basis (spot-perp); ileride L2 order-book, on-chain (ücretli).
- Veri kalitesi: point-in-time, survivorship (delist olmuş coinler), look-ahead YASAK.

**Backtest motoru:**
- Olay-temelli, gerçekçi maliyet: maker/taker ayrı, **slippage modeli** (hacim-bağımlı),
  funding tahakkuku, **kapasite/likidite sınırı** (emrin piyasayı kaç bps iteceği).

**Validasyon çerçevesi (overfit-katili):**
- 3'lü ayrım: **train / validation / test** (test setine ASLA dokunma).
- **Walk-forward** + **CPCV** (Combinatorial Purged Cross-Validation, López de Prado).
- **Deflated Sharpe Ratio** (çok deneme yapınca şişen Sharpe'ı düzeltir).
- **Multiple-testing kontrolü** (N hipotez → Bonferroni / FDR).
- Reproducibility: sabit seed, versiyonlu veri.

**Araştırma günlüğü:** her hipotez ÖN-KAYITLI (test öncesi yazılır) + sonuç (PASS/FAIL/why).
p-hacking (geçeni bulana kadar deneme) yasak; günlük bunu görünür kılar.

## 2) AVLANMA SAHALARI (edge'in bizim için olası olduğu yerler)
Solo taban-oranına göre sıralı:
- **A. Market-nötr / carry:** seçici funding hasadı, cash-and-carry basis, cross-exchange
  funding spreadi. (Düşük rekabet, yapısal yield.)
- **B. Cross-sectional:** altlar arası relative-strength momentum; dispersiyon mean-reversion.
  (Akademik olarak en sağlam kripto faktörü.)
- **C. Olay-temelli:** yeni listeleme, token unlock, koşullu funding ekstremi, index rebalance.
- **D. Mikroyapı (zor):** order-book imbalance — L2 veri + düşük latency ister.
- **E. Stat-arb:** kointegre çiftler (pairs).
- **YASAK (kanıtlandı ölü):** majörlerde naive yönlü TA (Donchian/EMA/momentum hold-out'ta çöktü).

## 3) ARAŞTIRMA DÖNGÜSÜ (her hipotez için)
1. **Ekonomik gerekçe:** edge neden VAR? karşı tarafta kim, neden ödüyor, neden
   arbitrajlanmamış, decay riski ne? (Gerekçesi olmayan fikir test edilmez.)
2. Hipotez + testi **ön-kaydet** (günlüğe).
3. Feature engineering (point-in-time, sızıntı yok).
4. In-sample keşif → validation.
5. CPCV / walk-forward **out-of-sample.**
6. **Deflated Sharpe + multiple-testing** düzeltmesi.
7. Maliyet + kapasite stresi.
8. Robustluk: parametre stabilitesi, rejim, sembol, alt-dönem.
9. **KILL ya da PROMOTE** (duygusal bağlanma yok).

## 4) İLERİ DOĞRULAMA (canlı testnet)
Hayatta kalanlar → **≥1-3 ay canlı testnet** (gerçek execution/slippage/latency).
Canlı vs backtest tracking-error + **alpha-decay** izle. Çoğu strateji burada ölür — normal.

## 5) PORTFÖY & RİSK (P-7, altyapı hazır)
Sağ kalan edge'ler → düşük-korelasyon kombinasyonu, sizing (fractional Kelly / vol-target),
drawdown kill-switch, exposure limitleri. **Edge olsa bile kötü sizing hesabı bitirir** —
mevcut risk motoru burada korur.

## 6) SERMAYE KONUŞLANDIRMA
Her şey geçtiyse: **en küçük gerçek miktar** → canlı vs beklenti izle → **sadece tutarsa**
kademeli ölçekle. Sıkı drawdown durdurma.

## 7) İZLEME & YAŞAM DÖNGÜSÜ
Edge aşınır. Sürekli izle, periyodik yeniden-doğrula, çalışmayı bırakınca emekliye ayır.
Araştırma asla durmaz (bir edge bulmak = sonu değil, başlangıcı).

## 8) ZAMAN ÇİZELGESİ & KİLOMETRE TAŞLARI
| Ay | İş |
|----|-----|
| 1-2 | Faz 0: CPCV + Deflated Sharpe + maliyet/kapasite modeli + funding/OI/cross-sectional veri hatları |
| 2-5 | Hipotez döngüsü: Kademe A → B → C (ayda ~2-4 hipotez, tam rijit) |
| 5-8 | Sağ kalanları canlı testnette ileri-test |
| 8+ | Bir şey sağ kalırsa mikro sermaye |

## 9) KILL KRİTERLERİ & ACI OLASILIKLAR (ön-taahhüt)
- Bir hipotez Faz 3'ü geçemezse → at.
- Faz 4'te canlı, backtest'in <%50'siyse → at.
- **~6 ay Kademe A+B'de hiçbir şey sağ kalmazsa → dürüstçe "bu setup'ta edge yok", dur/pivot.**
- **Dürüst olasılık:** mütevazı gerçek edge bulma ~%20-30; büyük/dayanıklı <%5; domination ~0.
  En olası sonuç: küçük market-nötr yield ya da hiçbir şey. Buna baştan razıyız.

## 10) NEREDEN BAŞLIYORUZ
1. Faz 0 eksikleri: CPCV + Deflated Sharpe + gerçekçi maliyet/slippage + araştırma günlüğü.
2. İlk hipotez: **Kademe B — cross-sectional momentum** (yönlü-olmayan, akademik olarak en
   sağlam, en yüksek taban-oran). Ekonomik gerekçesi yazılır, sınavdan geçirilir.

> Her satırı kanıtla doğrulanacak. Sahte yok. Sonuç acı çıkarsa acı haliyle buraya yazılır.
