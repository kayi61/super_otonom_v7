# Reddit & Telegram Community Sentiment Scanner (PROMPT-4.2)

`super_otonom/signals/community_sentiment_scanner.py` — Reddit/Telegram toplulukları
+ Fear & Greed + Google Trends sinyallerini tarar; `social_signal` (Faz 16) ve
`sentiment_layer` analizlerini zenginleştirir.

Kaynaklar: Reddit/Telegram (enjekte edilebilir veri), **Alternative.me** F&G Index
(ücretsiz, key'siz), Google Trends (pytrends-tarzı seri). Analiz fonksiyonları
saftır; testler ağsız (`tests/test_community_sentiment_scanner_p42.py`).

## 1. Reddit (`analyze_reddit`)

r/cryptocurrency, r/bitcoin, r/ethereum, r/altcoin:

- **mention_spike** `[0,1]` — coin mention patlaması (`current/baseline`, tanh).
- **upvote_momentum** `[0,1]` — hızlı yükselen postlar.
- **comment_sentiment** `[-1,1]` — bullish/bearish keyword sayımı.
- **award_anomaly** `[0,1]` — award sayısı anomalisi.
- **heat** `[0,1]` — genel topluluk ısısı.

## 2. Telegram (`analyze_telegram`)

Büyük kripto grupları:

- **freq_spike** `[0,1]` — mesaj frekansı patlaması.
- **fomo_score** `[0,1]` — "pump"/"moon"/"buy now"/"lambo"/"100x" oranı.
- **fud_score** `[0,1]` — "scam"/"dump"/"rug"/"ponzi" oranı.
- **bot_ratio** `[0,1]` + **manipulation_risk** = `0.6×bot + 0.4×fomo` — yüksek bot
  oranı + FOMO → pump manipülasyonu şüphesi.

## 3. Fear & Greed (`analyze_fear_greed`)

| F&G | Sınıf | Sinyal | bias |
|-----|-------|--------|------|
| < 20 | `extreme_fear` | `contrarian_buy` | + |
| 20–40 | `fear` | neutral | hafif + |
| 40–60 | `neutral` | neutral | ~0 |
| 60–80 | `greed` | neutral | hafif − |
| > 80 | `extreme_greed` | `reduce_risk` | − |

- `trend_7d` / `trend_30d` = mevcut değer − geçmiş ortalama.
- **Extreme Fear (<20)** → contrarian **buy** sinyali (+bias).
- **Extreme Greed (>80)** → **risk azaltma** (−bias, risk_score ≥ 0.5).
- Parser: `parse_alternative_me` (`{"data":[{"value":"15",...}]}`, data[0] güncel).

## 4. Google Trends (`analyze_google_trends`)

- **spike** `[0,1]` — "bitcoin"/"crypto"/"buy bitcoin" arama ani yükselişi.
- **retail_fomo** — spike ≥ 0.6 → geç girişçi FOMO (contrarian negatif bias).
- **accumulation_zone** — düşük ilgi (`< 0.7×baseline`) + düşük fiyat → birikim (+bias).

## Birleşik sinyal (`analyze_community`)

`analyze_community(reddit=, telegram=, fear_greed=, trends=, whale_accumulation=)`
→ `CommunitySignal` (hepsi opsiyonel; hiçbiri yoksa `None`):

- `sentiment` `[-1,1]`, `alpha_bias` `[-1,1]`, `risk_score` `[0,1]`, `manipulation_risk`.
- **F&G + whale birikim birlikte** → `whale_accumulation > 0.5` ve fear/extreme_fear
  ise alpha'ya ek boost (güçlü contrarian buy).

`analyze_community_data(dict)` — düz dict köprüsü (`reddit`/`telegram`/`fear_greed`/
`google_trends`/`whale_accumulation`).

## Entegrasyon

### `social_signal` (Faz 16)
`social_data` içinde `community` alt dict (veya düz `reddit`/`telegram`/`fear_greed`/
`google_trends`) varsa: community `alpha_bias` Faz 16 alpha'sına eklenir (`+0.15×bias`),
`risk_score` risk ile `max()` alınır. **Geriye uyumlu**: veri yoksa `community` bloğu
eklenmez, davranış değişmez; hata Faz 16'yı bozmaz.

### `sentiment_layer`
`SentimentLayer.analyze_community_sentiment(community_data=None)` — scanner köprüsü.
`community_data` içinde F&G yoksa, katmanın kendi piyasa skoru (0..1) F&G değerine
(0..100) çevrilerek tohumlanır. Mevcut metodlar değişmez (geriye uyumlu).

```python
layer = SentimentLayer(mock_score=0.1)          # → F&G 10 (extreme fear)
sig = layer.analyze_community_sentiment()        # contrarian buy bias
```
