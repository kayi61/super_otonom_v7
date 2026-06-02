# VC & Fund Wallet Tracker (PROMPT-1.3)

`super_otonom/signals/vc_fund_tracker.py` — bilinen VC/fund cüzdanlarının token
hareketlerini izler; `smart_money_tracker` (Faz 17) `vc_net_flow_usd` alanını besler.

## İzlenen kuruluşlar (`data/vc_fund_wallets.json`)

| Tür | Kuruluşlar |
|-----|-----------|
| VC | a16z Crypto, Paradigm, Polychain, Pantera |
| Fund | Jump Trading, Wintermute, Alameda, Galaxy Digital, Grayscale |
| Venue (sınıflandırma) | Uniswap/1inch (dex), Binance/Coinbase/Bybit (cex) |

Adresler Etherscan / Arkham Intelligence public label'larından derlenmiştir
(append-only; periyodik doğrulama önerilir).

## Mimari

```
Etherscan tokentx  (enjekte edilebilir http_get)
        ▼
  parse_vc_transfers() → VcTransfer[]  (yalnızca VC/fund içeren transferler)
        ▼
  analyze() → VcFundSignal (vc_net_flow_usd, alpha/risk tokens, conviction)
        │
        ├─ to_smart_money_data() → {vc_net_flow_usd, ...}
        │        ▼  analyze_smart_money (Faz 17) → alpha/risk/trade_permission
        └─ detect_alerts() → AlertManager.system() (Telegram)
```

## Transfer sınıflandırma

| direction | Anlam | Net akış |
|-----------|-------|----------|
| `acquire` | VC/fund ALICI | + (birikim) |
| `distribute_dex` | VC/fund → DEX | − (satış) |
| `distribute_cex` | VC/fund → CEX | − (satış) |
| `distribute` | VC/fund → diğer | − |

```
vc_net_flow_usd = Σ(acquire) − Σ(distribute)
```
Pozitif = VC birikimi (bullish). Faz 17 `_institutional_vc_score` ile değerlendirilir.

## Sinyal kuralları

| Kural | Sinyal |
|-------|--------|
| VC bir token biriktiriyor (≥ $100K) | EARLY_ALPHA |
| VC toplu satış (≥ $5M) | VC_BULK_SELL (risk) |
| ≥ 2 farklı VC aynı token'a giriyor | CONVICTION |
| Token unlock sonrası dağıtım (≤ 3 gün) | POST_UNLOCK_DUMP (risk) |

## Token unlock takibi

`update(unlock_events={token: unlock_ts_ms})` verilirse, unlock tarihinden sonraki
`VC_UNLOCK_WINDOW_SEC` (vars. 3 gün) içindeki dağıtım transferleri `is_post_unlock=True`
ile işaretlenir → POST_UNLOCK_DUMP alarmı.

## Kullanım

```python
from super_otonom.signals.vc_fund_tracker import VcFundTracker, run_vc_fund_phase
from super_otonom.monitoring.alert_manager import AlertManager

tracker = VcFundTracker(alert_manager=AlertManager())
if tracker.should_update():  # 5 dakikalık döngü
    out = run_vc_fund_phase("ETH/USDT", tracker, analysis,
                            price_usd=3000.0, unlock_events={"ARB": 1_700_000_000_000})
    # out: {alpha_score, risk_score, trade_permission, phase: "17", ...}
```

## Ortam değişkenleri

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `ETHERSCAN_API_KEY` / `ETHERSCAN_API_URL` | — | Token transfer event'leri |
| `VC_MIN_USD` | `100000` | Early-alpha birikim eşiği |
| `VC_BULK_SELL_USD` | `5000000` | Toplu satış risk eşiği |
| `VC_CONVICTION_MIN` | `2` | Conviction için minimum farklı VC sayısı |
| `VC_UNLOCK_WINDOW_SEC` | `259200` | Unlock sonrası izleme penceresi (3 gün) |
| `VC_UPDATE_INTERVAL_SEC` | `300` | Güncelleme aralığı (5 dk) |

API anahtarı yoksa kaynak sessizce boş döner. Tüm parser'lar saf fonksiyondur;
testler ağsız (`tests/test_vc_fund_tracker_p13.py`).
