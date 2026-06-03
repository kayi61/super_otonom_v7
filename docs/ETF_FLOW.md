# Bitcoin/Ethereum ETF Flow Tracker (PROMPT-7.1)

`super_otonom/signals/etf_flow_intelligence.py` — kripto spot ETF akışlarını
takip eder; `smart_money_tracker` (Faz 17) `etf_net_flow_usd` alanını besler.

Kaynak: **SoSoValue API** / **farside.co** (enjekte edilebilir `http_get`).

## İzlenen ETF'ler

| Asset | Ticker'lar |
|-------|-----------|
| BTC | GBTC, IBIT, FBTC, ARKB, BITB, BTCO, EZBC, BRRR, HODL, BTCW |
| ETH | ETHA, FETH, ETHW, CETH, ETHV, EZET, QETH, ETHE, ETH |
| Grayscale (legacy) | GBTC, ETHE — yüksek ücret → outflow eğilimi |

## Metrikler

1. **BTC/ETH Spot ETF**: günlük net flow (ETF bazında), toplam AUM, GBTC outflow
   vs IBIT inflow dinamiği.
2. **Kurumsal pozisyon**: Grayscale premium/discount, CME futures OI (proxy), 13F.

## Sinyal kuralları

| Kural | Sinyal | alpha_bias |
|-------|--------|-----------|
| 5+ gün üst üste net inflow | `strong_institutional_demand` | + |
| GBTC outflow + diğerleri inflow | `rotation` | 0 (nötr) |
| Tüm ETF'lerde outflow | `institutional_selling` | − |
| ETF volume ≥ 2x ortalama | `volume_spike` | — |
| Grayscale discount (< −5%) | — | hafif + (birikim) |

## Faz 17 köprüsü

```
etf_net_flow_usd = Σ(per-ETF net flow)   # pozitif = inflow (bullish)
```
Faz 17 `_institutional_vc_score` `tanh(v/5e6)` ile değerlendirir.

```python
from super_otonom.signals.etf_flow_intelligence import EtfFlowTracker, run_etf_flow_phase
from super_otonom.monitoring.alert_manager import AlertManager

tracker = EtfFlowTracker(alert_manager=AlertManager())
if tracker.should_update():  # günlük döngü
    out = run_etf_flow_phase("BTC/USDT", tracker, analysis,
                             asset="BTC", daily_net_flow_history=[...])
    # out: {alpha_score, risk_score, trade_permission, phase: "17", ...}
```

## Ortam değişkenleri

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `SOSOVALUE_API_URL` / `SOSOVALUE_API_KEY` | — | SoSoValue ETF flow |
| `FARSIDE_API_URL` | — | farside.co flow tablosu |
| `ETF_INFLOW_STREAK_DAYS` | `5` | Güçlü talep için ardışık inflow günü |
| `ETF_VOLUME_SPIKE_MULT` | `2` | Volume spike çarpanı |
| `ETF_UPDATE_INTERVAL_SEC` | `3600` | Güncelleme aralığı (1 saat) |

Kaynak yoksa sessizce boş döner. Tüm parser/analiz fonksiyonları saftır; testler
ağsız (`tests/test_etf_flow_intelligence_p71.py`).
