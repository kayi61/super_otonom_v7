# On-Chain Metrics Engine (PROMPT-2.1)

`super_otonom/signals/onchain_intelligence.py` — blockchain on-chain metriklerini
toplar/analiz eder; `alternative_data_engine` (Faz 27) adoption bölümünü zenginleştirir.

Kaynaklar: Blockchain.com / Etherscan / Glassnode / CoinMetrics Community
(enjekte edilebilir `http_get`).

## Metrikler

### 1. Ağ aktivitesi (`analyze_network_activity`)
- Active addresses, tx count/volume, new address hızı.
- Ortalama tx fee → **congestion** proxy.
- `activity_score` (0..1): sağlıklı adoption.

### 2. Holder analizi (`analyze_holders`)
- Supply distribution (top 10/100/1000), holder count değişimi.
- LTH (>1y) vs STH oranı.
- 30 günlük **accumulation / distribution** trendi.
- `concentration_risk`: yüksek top10 → risk.

### 3. Miner / Validator (`analyze_miner_metrics`)
- Miner outflow (BTC) → satış baskısı.
- Staking ratio değişimi (ETH/SOL), hash rate trend → `security_score`.

### 4. MVRV & Realized Price (`analyze_mvrv`)

| MVRV | Valuation | bias |
|------|-----------|------|
| > 3.5 | `overvalued` (satış riski) | − |
| < 1.0 | `undervalued` (birikim fırsatı) | + |
| arası | `fair_value` | 0 |

- MVRV = market_price / realized_price (verilmezse hesaplanır).
- `price_premium_pct` = (market − realized) / realized.

## Faz 27 entegrasyonu (adoption bölümü)

`alternative_data_engine.analyze_alternative_data`, `onchain` alt dict (veya düz
alt_data) içinde ilgili alanlar varsa derinlik analizini çalıştırır:

```python
data = {"onchain": {
    "active_addresses": 1e6, "tx_count": 8e5, "avg_tx_fee_usd": 2,
    "top10_pct": 0.4, "holder_count_change_pct": 0.03, "accumulation_trend_30d": 0.05,
    "miner_outflow_usd": 10e6, "hash_rate_change_pct": 0.05,
    "mvrv": 0.85, "market_price": 30000, "realized_price": 35000,
}}
out = analyze_alternative_data("BTC/USDT", data, analysis)
# out["alternative_data"]["onchain"] → tüm metrikler
```

- On-chain `adoption_score`, mevcut Faz 27 adoption skoruyla harmanlanır (0.55/0.45).
- MVRV overvalued + congestion + miner satış → `risk_score`.
- MVRV undervalued + accumulation → bullish `alpha_bias`.
- Geriye uyumluluk: ilgili alanlar yoksa `onchain` eklenmez, davranış değişmez.
  PROMPT-3.3 options analizi ile **birlikte** çalışır (ayrı çıktı anahtarları).

Tüm analiz fonksiyonları saftır; testler ağsız (`tests/test_onchain_intelligence_p21.py`).
