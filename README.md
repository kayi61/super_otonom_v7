# super_otonom v7

Hibrit AI + Teknik Analiz + Korelasyon + Sentiment + OMEGA kalite/rejim katmanı.

**Operasyon ve izleme (Faz 3–4):** [docs/RUNBOOK.md](docs/RUNBOOK.md)  
Örnek ortam şablonu: `.env.example` → kopyalayıp `.env` oluşturun (`.env`’i asla commitlemeyin).

## Kurulum

```bash
pip install -e ".[dev]"
```

(Alternatif: `pip install -r requirements.txt` — projede varsa)

## Çalıştırma

```bash
# Paper / sim — varsayılan; DRY_RUN=true iken daima simülasyon
python -m super_otonom.main_loop

# Canlı (bilinçli onay) — LIVE_CONFIRM=YES zorunlu
PAPER_MODE=false LIVE_CONFIRM=YES python -m super_otonom.main_loop
```

`health.log` (kokpit): `Get-Content -Path logs\health.log -Wait -Tail 50` (Windows) veya `tail -f logs/health.log`. Ayrıntı runbook’ta.

## Ortam Değişkenleri (özet)

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `DRY_RUN` | kapalı | `true` iken daima simülasyon (gerçek emir yok) |
| `PAPER_MODE` | `true` | Gerçek emir yok (DRY yokken) |
| `LIVE_CONFIRM` | `` | Canlı mod için `YES` gerekli |
| `SIGNAL_QUALITY_MIN` | `40` | Ham kalite barajı; OMEGA `Qadj` altındaki BUY reddedilir |
| `ML_SERVICE_ENABLED` | `false` | Dış ML (Neural link) |
| `INITIAL_CAPITAL` | `1000` | Başlangıç sermayesi (USDT) |
| `POLL_INTERVAL_SEC` | `30` | Tick aralığı (saniye) |
| `ENTRY_MIN_CONFIDENCE` | `0.55` | Minimum AI güven eşiği |
| `SENTIMENT_BEARISH_THRESHOLD` | `0.3` | BUY veto altında eşik |
| `SENTIMENT_BULLISH_THRESHOLD` | `0.7` | SELL veto üstünde eşik |
| `FEAR_GREED_API_URL` | `` | Fear & Greed API endpoint |
| `METRICS_PORT` | `8000` | Prometheus HTTP portu |
| `CANDLE_LIMIT_4H` | `50` | 4H MTF için mum sayısı |

Tüm anahtarlar: `super_otonom/config.py`.

## Mimari

```
main_loop.py          ← Ana döngü (async, SIGTERM temiz kapanış)
├── exchange_async.py ← ccxt async + CircuitBreaker
├── analyzer.py       ← MTF analiz (1H + 4H), Hurst regime filtresi
├── bot_engine.py     ← Tick motoru, Sentiment veto, Korelasyon çarpanı
│   ├── ai_layer.py       ← LSTM model veya fallback
│   ├── risk_manager.py   ← Dinamik VaR + drawdown + volatility spike
│   ├── position_sizer.py ← Kelly + 3 katman güvenlik (zaman/imbalance/fractional)
│   ├── sentiment_layer.py← Fear & Greed / CryptoPanic filtresi
│   ├── correlation_manager.py ← Portföy korelasyon risk çarpanı
│   └── metrics_exporter.py   ← Prometheus + Grafana
└── wfa_manager.py    ← Walk-Forward Analysis (backtesting)
```
