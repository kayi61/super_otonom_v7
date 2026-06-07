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
