# Edge Validasyon Protokolü (P-1 — "önce doğrulayarak kur")

> Amaç: bir stratejinin GERÇEK edge'i olup olmadığını, **kendimizi in-sample sayılarla
> kandırmadan** ölçmek. Kurulacak HER strateji bu sınavdan geçmek zorunda.

## Sınav (`scripts/edge_validate.py`)
Çok sembol + uzun geçmiş + tüm rejimler üzerinde stratejiyi çalıştırır, **tüm işlemleri
havuzlar**, fee/slippage sonrası ölçer:
- işlem sayısı, ortalama işlem %, **t-istatistiği** (mean/std·√n) → anlamlılık
- kazanma oranı, sembol-başı bileşik getiri, **buy&hold kıyası**

## Geçme kriteri (sıkı — pazarlık yok)
| Verdikt | Koşul |
|---------|-------|
| `INSUFFICIENT` | işlem < 30 (istatistik için yetersiz) |
| `NO_EDGE` | ortalama işlem ≤ 0 (negatif/sıfır beklenti) |
| `NOT_SIGNIFICANT` | pozitif ama **t < 2.0** (şansa bağlanabilir) |
| `WEAK` | t ≥ 2 ama **buy&hold'u geçemiyor** |
| `VALIDATED-tentative` | **t ≥ 2 + pozitif + buy&hold üstü** |

`VALIDATED-tentative` bile "kesin kazanan" demek DEĞİL — sadece "sınavı geçti, canlı
testnet doğrulamasına aday." Gerçek para yalnızca uzun canlı testnet + risk validasyonu (P-7)
sonrası.

## Mevcut stratejinin taban sonucu (2023-01..2024-12, 4 sembol, 4h, fee 10bps)
```
HAVUZ: 151 işlem | ort.işlem +2.4% | t-stat 1.70 | kazanma 0.40
Strateji ort +84.6%  vs  Buy&Hold +614%
VERDİKT: NOT_SIGNIFICANT (t=1.70 < 2.0) + buy&hold'un 7× altında
```
**Yani mevcut sistem sınavı GEÇEMİYOR.** (Hurst fix öncesi negatif edge'di; fix sonrası
pozitif ama anlamsız + B&H-altı.)

## R&D protokolü (sıradaki — disiplinli, overfit'siz)
1. Yeni bir sinyal fikri tasarla (hipotez net).
2. `edge_validate.py`'ye sinyal fonksiyonu olarak tak.
3. Sınavı çalıştır. `VALIDATED-tentative` değilse → **at, bir sonrakine geç.** Ayar çekip
   in-sample'a uydurma (overfit yasak).
4. Geçenleri ayrı/yeni dönem + sembollerde tekrar doğrula (hold-out).
5. Hayatta kalan → canlı testnet ≥30 gün → P-7 risk validasyonu → ancak sonra gerçek para.

> Acı gerçek: çoğu fikir sınavı geçmez. Bu normal. Sınav, para kaybetmeni önler.

## R&D İterasyon 1-2 — baseline sinyaller (kanonik, ön-kayıtlı)

`--signal {analyzer,momentum,donchian,ema_cross}` ile aynı sınav. **Önemli metodoloji:**
boğa-yanlı pencere zamanlama stratejisine haksızdır → **tam döngü** (ayı dahil) test edilmeli.

**Boğa-yanlı (2023-01..2024-12):** hepsi B&H-altı (azgın boğada long/flat "hep long"u geçemez).

**TAM DÖNGÜ (2022-01..2024-12, 2022 ayısı dahil, 4 sembol, 4h, fee 10bps):**
| Sinyal | İşlem | t-stat | Strateji ort | Buy&Hold | Verdikt |
|--------|-------|--------|--------------|----------|---------|
| **donchian (20)** | 258 | **2.10** | **+139.8%** | +56.8% | ✅ VALIDATED-tentative |
| **ema_cross (12/26)** | 413 | **2.03** | **+141.1%** | +56.8% | ✅ VALIDATED-tentative |
| momentum (30) | 996 | 1.08 | +30.5% | +56.8% | NOT_SIGNIFICANT |
| analyzer (mevcut bot) | 151 | 1.70 | (boğa: +84.6%) | — | NOT_SIGNIFICANT |

### Bulgu
**Doğrulanabilir edge basit trend sinyallerinde** (Donchian/EMA cross): tam döngüde B&H'ı
~2.5× yeniyor + istatistiksel anlamlı. Sebep: 2022 ayısından kaçıp sermaye koruyor.
**Mevcut karmaşık bot bunların altında** — karmaşıklık edge çıkardı.

### Uyarılar (abartma)
- 4 sinyalden 2'si geçti (kanonik sinyaller, hafif multiple-comparison).
- **Hold-out gerekli:** seçimde kullanılmayan dönem/sembol + parametre robustluğu (N taraması).
- t≈2.1 çıtanın hemen üstü; canlı testnet execution doğrulaması şart.

### Sıradaki (sorumlu)
1. Donchian/EMA cross'u hold-out dönem + farklı sembollerde + parametre-robustluk ile doğrula.
2. Hayatta kalırsa: botun karar çekirdeğini bu basit doğrulanmış sinyalle değiştir (over-engineered katmanları emekliye ayır — P-2 ile örtüşür).
3. Canlı testnet ≥30 gün → P-7 risk validasyonu → ancak sonra gerçek para.

## R&D İterasyon 3 — HOLD-OUT: aday ÇÖKTÜ (overfit/fluke)

Donchian "VALIDATED-tentative"yi acımasızca test ettik:

| Test | t-stat | Strateji vs B&H | Sonuç |
|------|--------|------------------|-------|
| Seçim seti (2022-24, BTC/ETH/SOL/BNB, N=20) | 2.10 | +140% vs +57% | geçmişti |
| **Parametre taraması** (N=10..55) | sadece N=15,20 ≥2 | — | ⚠️ kırılgan (6'da 2) |
| **Hold-out dönem (2021)** | **1.11** | +157% vs +454% | ❌ ÇÖKTÜ |
| **Hold-out semboller (XRP/ADA/DOGE/LTC)** | **1.49** | +78% vs +66% | ❌ ÇÖKTÜ |

**Hüküm:** seçim setindeki "edge" hold-out'ta (farklı dönem + farklı semboller) t<2'ye
çöküyor + parametreye duyarlı = **klasik overfit/fluke.** Genellenebilir edge YOK.

### P-1 nihai durum (bu seans)
Test edilenler — mevcut bot, momentum, donchian, ema_cross — **hiçbiri hold-out'ta
istatistiksel anlamlı + B&H-üstü değil.** Sağlam edge bulunamadı.

> Disiplin başarısı: harness + hold-out bir yanlış-pozitifi yakaladı; bu olmadan Donchian
> "doğrulandı" deyip deploy edilir, para kaybedilirdi. **Sınavın değeri budur.**

### Dürüst seçenekler
1. Daha fazla R&D (yeni feature/sinyal/rejim-koşullu/farklı TF) — aylar, **düşük başarı oranı**
   (basit klasikler bile geçemedi; bu, kolay edge olmadığının güçlü kanıtı).
2. Kabul: kolay/sağlam edge yok → zamanlama yerine pasif (B&H/DCA) kanıta dayalı seçim.

Her yeni fikir yine bu harness + hold-out'tan geçmek zorunda. Cherry-pick (geçeni bulana
kadar sinyal denemek) = p-hacking, yasak.
