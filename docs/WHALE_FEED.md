# Whale Wallet Tracker (PROMPT-1.1)

`super_otonom/signals/whale_feed_collector.py` — gerçek zamanlı whale transfer
takibi; `smart_money_tracker` (Faz 17) için on-chain feed sağlar.

## Mimari

```
Whale Alert / Etherscan / Blockchain.com
        │  (urllib + enjekte edilebilir http_get)
        ▼
  parse_*()  →  WhaleTransfer[]  (≥ $500K filtre + borsa-yönü sınıflandırma)
        │
        ├─ to_smart_money_data() → {whale_transfers, exchange_netflow_usd}
        │        ▼  analyze_smart_money (Faz 17)
        │   alpha_score / risk_score / trade_permission
        └─ detect_alerts() → WhaleAlert[] → AlertManager.system() (Telegram)
```

## Borsa-yönü sınıflandırma

| direction | Anlam | Faz 17 etkisi |
|-----------|-------|---------------|
| `to_exchange` | Borsaya giriş (deposit) | Satış baskısı (bearish) |
| `from_exchange` | Borsadan çıkış (withdrawal) | Birikim (bullish) |
| `cold_storage` | Soğuk cüzdana | Güçlü birikim (bullish) |
| `internal` | Borsa-içi / etiketsiz | Nötr |

Öncelik: yerel `data/whale_wallets.json` etiketi > API `owner_type`.

## Net exchange flow

```
exchange_netflow_usd = Σ(to_exchange) − Σ(from_exchange + cold_storage)
```
Pozitif = net giriş = satış baskısı (Faz 17 `_exchange_netflow_bias` ile uyumlu).

## Alert kuralları

| kind | Tetik | Severity |
|------|-------|----------|
| `LARGE_TRANSFER` | Tek transfer ≥ $10M | CRITICAL |
| `TREND` | 1 saatte ≥ 3 aynı yön transfer | WARNING |
| `SELL_PRESSURE` | Net borsa girişi ≥ $10M | WARNING |

`AlertManager` verilirse `system("WHALE_<kind>", message, severity)` ile Telegram'a gider.

## Kullanım

```python
from super_otonom.signals.whale_feed_collector import WhaleFeedCollector, run_whale_phase
from super_otonom.monitoring.alert_manager import AlertManager

collector = WhaleFeedCollector(alert_manager=AlertManager())

# 5 dakikalık döngü
if collector.should_update():
    out = run_whale_phase("ETH/USDT", collector, analysis,
                          eth_price_usd=3000.0, btc_price_usd=60000.0)
    # out: {alpha_score, risk_score, trade_permission, phase: "17", ...}
```

## Ortam değişkenleri

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `WHALE_ALERT_API_KEY` / `WHALE_ALERT_API_URL` | — / whale-alert.io | Whale Alert |
| `ETHERSCAN_API_KEY` / `ETHERSCAN_API_URL` | — | Token transfer event'leri |
| `BLOCKCHAIN_BTC_API_URL` | — | Büyük BTC transfer'leri |
| `WHALE_MIN_USD` | `500000` | Minimum transfer eşiği |
| `WHALE_LARGE_ALERT_USD` | `10000000` | Büyük transfer alarm eşiği |
| `WHALE_UPDATE_INTERVAL_SEC` | `300` | Güncelleme aralığı (5 dk) |

API anahtarı yoksa ilgili kaynak sessizce boş döner — bot çökmeden çalışmaya devam eder.
Tüm parser'lar saf fonksiyondur; testler ağsız (`tests/test_whale_feed_collector_p11.py`).
