# Twitter/X Crypto KOL Tracker (PROMPT-4.1)

`super_otonom/signals/kol_tracker.py` — kripto KOL (Key Opinion Leader)
aktivitesini takip eder; `social_signal` (Faz 16) sentiment/hype analizini KOL
konsensüsüyle zenginleştirir.

Kaynaklar: Twitter/X API v2 veya **Nitter** scraping alternatifi (enjekte
edilebilir `http_get`). Tüm analiz fonksiyonları saftır; testler ağsız
(`tests/test_kol_tracker_p41.py`).

## 1. KOL listesi + ağırlıklandırma

`KOL_REGISTRY` — handle → `KOL(handle, name, tier, accuracy)`.

| Tier | Tanım | Taban ağırlık | Örnek |
|------|-------|---------------|-------|
| 1 | market mover | 1.0 | CZ, Vitalik, Saylor, Elon Musk |
| 2 | crypto native | 0.7 | Cobie, Hsaka, CryptoCobain, GCR |
| 3 | analist | 0.5 | PlanB, Willy Woo, Benjamin Cowen |

- `KOL.weight = base_weight × (0.4 + 0.6 × accuracy)` — geçmiş doğruluk oranı
  ağırlığı düzeltir (Tier 1 her zaman Tier 3'ten ağır).
- `get_kol(handle)` handle'ı normalize eder (`@CZ_Binance`, `x.com/saylor` → `cz_binance`).
- Bilinmeyen handle → `resolve_kol()` Tier 3 / accuracy 0.5 varsayılanıyla geçici KOL üretir.

## 2. Tweet analizi (NLP)

- **Cashtag** (`parse_cashtags`): `$BTC`, `$eth` → `["BTC", "ETH"]` (tekilleştirilmiş).
- **Sentiment** (`analyze_sentiment`): kripto-native lexicon → score `[-1,1]` +
  label (`bullish`/`bearish`/`neutral`). Basit negasyon (`not bullish` → bearish).
- **Action** (`detect_action`): `buy`/`accumulate`/`long` → `BUY`,
  `sell`/`short`/`exit` → `SELL`. Karışık ifade → `None`. SELL muhafazakâr önceliklidir.
- **Engagement** (`engagement_weight`): `like + 2×retweet` → log ölçek `[0,1]`.
- `analyze_tweet(tweet)` → `TweetAnalysis` (tokens, sentiment, action, engagement,
  `kol_weight`, `influence = kol_weight × (0.5 + 0.5×engagement)`). Net action
  sentiment'i pekiştirir; `accuracy` alanı KOL doğruluğunu override eder.

## 3. KOL consensus (`compute_consensus`)

24h penceresinde token bazlı:

- `kol_count` — token'dan bahseden **farklı** KOL sayısı (KOL başına en yüksek
  influence'lı tweet alınır; tek KOL spam'i şişirmez).
- `weighted_sentiment` — influence ağırlıklı sentiment `[-1,1]`.
- `divergence` `[0,1]` — sentiment yayılımı (std) + bullish/bearish kamp dengesi.
  Yüksek divergence = **belirsizlik**.
- `label`: `bullish` / `bearish` / `divergent` (bullish↔bearish ayrışması) / `neutral`.

## 4. Timing sinyali (`backtest_kol_timing`)

KOL tweet sonrası fiyat tepkisi backtest'i (event: `sentiment`, `move_pct`,
opsiyonel `peak_pct`/`final_pct`/`lag_minutes`):

- `avg_move_pct` — tweet sonrası ortalama hareket.
- `avg_lag_minutes` — tweet ↔ tepe hareket gecikmesi.
- `hit_rate` — sentiment yönü ile hareket yönü uyumu.
- `buy_rumor_sell_news` — belirgin pump sonrası geri veriş (`peak ≥ %1.5`,
  `final < peak × 0.4`) bullish event'lerde baskınsa `True`.

## Birleşik sinyal (`analyze_kol`)

`analyze_kol(tweets, token, *, now_ms, window_hours=24, timing_events)` →
`KolSignal` (veya ilgili veri yoksa `None`):

- `alpha_bias` `[-1,1]` — weighted_sentiment × konviksiyon (KOL sayısı). Divergence
  ve "sell the news" alpha'yı kısar.
- `risk_score` `[0,1]` — bearish konsensüs / divergence / sell-the-news → risk.

## Faz 16 entegrasyonu (`social_signal`)

`analyze_social_signal`, `social_data` içinde KOL verisi varsa derinlik analizini
çalıştırır:

```python
data = {
    "sentiment_score": 0.5, "engagement_rate": 0.4,
    "kol": {
        "tweets": [
            {"handle": "cz_binance", "text": "accumulate $BTC", "likes": 5000, "retweets": 1000},
            {"handle": "saylor", "text": "buy $BTC forever", "likes": 8000, "retweets": 1500},
        ],
        "token": "BTC",            # opsiyonel; verilmezse symbol'den çözülür
        "window_hours": 24,        # opsiyonel
        "timing_events": [...],    # opsiyonel (backtest)
    },
}
out = analyze_social_signal("BTC/USDT", data, {})
# out["social"]["kol"] → consensus + timing + alpha/risk
```

- KOL `alpha_bias` Faz 16 alpha'sına eklenir (`+0.15 × bias`).
- KOL `risk_score`, Faz 16 risk'iyle `max()` alınır → yüksek bearish/divergence
  risk yükseltir (FOMO/PEAK BLOCK mantığıyla birleşir).
- Düz `kol_tweets` / `kol_token` anahtarları da desteklenir.
- **Geriye uyumluluk**: KOL verisi yoksa `kol` bloğu eklenmez, Faz 16 davranışı
  değişmez. KOL analizi hata verirse Faz 16 asla bozulmaz (sessiz fallback).
