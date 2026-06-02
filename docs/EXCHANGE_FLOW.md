# Exchange Flow Intelligence (PROMPT-1.2)

`super_otonom/signals/exchange_flow_intelligence.py` — borsa giriş/çıkış akışı,
rezerv değişimi ve stablecoin mint/burn takibi; `smart_money_tracker` (Faz 17)
`institutional_flow_usd` alanını gerçek veriyle besler.

## Mimari

```
CryptoQuant / Glassnode / Etherscan
        │  (urllib + enjekte edilebilir http_get)
        ▼
  parse_*()  →  ExchangeFlow[] / ReservePoint[] / StablecoinEvent[]
        ▼
  analyze() → FlowSignal (direction, strength, institutional_flow_usd, reasons)
        │
        ├─ to_smart_money_data() → {institutional_flow_usd, exchange_netflow_usd, ...}
        │        ▼  analyze_smart_money (Faz 17) → alpha/risk/trade_permission
        └─ detect_alerts() → AlertManager.system() (Telegram)
```

## İzlenen metrikler

| Metrik | Kaynak | Açıklama |
|--------|--------|----------|
| Net exchange flow | CryptoQuant | Σ(inflow − outflow); pozitif = net giriş (satış baskısı) |
| Exchange reserve (BTC/ETH/stable) | Glassnode | 7 günlük trend (`reserve_trend_7d`) |
| Stablecoin mint/burn | Etherscan | `from == 0x0` → mint; `to == 0x0` → burn |
| Borsa başına flow | CryptoQuant | Binance vs Coinbase vs Bybit (`per_exchange_netflow`) |

## Sinyal kuralları

| Kural | Yön |
|-------|-----|
| BTC exchange reserve 7g düşüş | BULLISH (birikim) |
| Stablecoin borsaya toplu giriş (≥ $100M) | BULLISH (alım hazırlığı) |
| BTC borsaya giriş (≥ $100M) + stablecoin çıkışı | BEARISH (satış) |
| USDT/USDC büyük mint (≥ $500M) | BULLISH (yeni likidite) |

## Faz 17 köprüsü

```
institutional_flow_usd = stablecoin_net_mint_usd − net_exchange_flow_usd
```
Pozitif = kurumsal birikim (bullish). Faz 17 `_institutional_vc_score` `tanh(v/5e6)`
ile değerlendirir.

## Kullanım

```python
from super_otonom.signals.exchange_flow_intelligence import (
    ExchangeFlowIntelligence, run_exchange_flow_phase,
)
from super_otonom.monitoring.alert_manager import AlertManager

engine = ExchangeFlowIntelligence(alert_manager=AlertManager())
if engine.should_update():  # 5 dakikalık döngü
    out = run_exchange_flow_phase("BTC/USDT", engine, analysis)
    # out: {alpha_score, risk_score, trade_permission, phase: "17", ...}
```

## Ortam değişkenleri

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `CRYPTOQUANT_API_KEY` / `CRYPTOQUANT_API_URL` | — | Exchange flow |
| `GLASSNODE_API_KEY` / `GLASSNODE_API_URL` | — | Exchange reserve balance |
| `ETHERSCAN_API_KEY` / `ETHERSCAN_API_URL` | — | USDT/USDC mint event'leri |
| `STABLE_MINT_ALERT_USD` | `500000000` | Büyük mint eşiği |
| `STABLE_INFLOW_ALERT_USD` | `100000000` | Stablecoin borsa giriş eşiği |
| `BTC_INFLOW_ALERT_USD` | `100000000` | BTC borsa giriş eşiği |
| `FLOW_UPDATE_INTERVAL_SEC` | `300` | Güncelleme aralığı (5 dk) |

API anahtarı yoksa ilgili kaynak sessizce boş döner. Tüm parser'lar saf fonksiyondur;
testler ağsız (`tests/test_exchange_flow_intelligence_p12.py`).
