# Options Flow Intelligence (PROMPT-3.3)

`super_otonom/signals/options_flow_intelligence.py` — Deribit tabanlı options
akış analizi; `alternative_data_engine` (Faz 27) options bölümünü zenginleştirir.

Birincil kaynak: **Deribit public API** (anahtar gerekmez).

## 1. Options flow / PCR

`analyze_pcr(put_volume, call_volume, pcr, pcr_history)` → `PcrSignal`:

| PCR | Sentiment | Kontraryan bias |
|-----|-----------|-----------------|
| > 1.2 | `fear` (korku, olası dip) | + (bullish) |
| < 0.5 | `greed` (aşırı güven, olası tepe) | − (bearish) |
| arası | `neutral` | 0 |

PCR trendi (`rising`/`falling`/`flat`) history'den hesaplanır.

## 2. Whale options

`detect_whale_options(trades, current_volume, avg_volume)` → `WhaleOptionsSignal`:
- **$1M+** tek trade.
- **Unusual activity**: volume ≥ 3x ortalama.
- **Yön**: büyük call alımı / put satışı → `bullish`; büyük put alımı / call satışı → `bearish`.

## 3. Max Pain

`compute_max_pain(chain)` — option holder toplam ödemesini minimize eden strike.
`analyze_max_pain(chain, spot, hours_to_expiry)` → `MaxPainAnalysis`:
- `max_pain_price`, spot uzaklığı.
- **Pull strength**: expiry yaklaşınca artar (fiyat max pain'e çekilir).
- **Gamma squeeze risk**: expiry'ye < 24h kala yükselir.

## 4. Implied Volatility

`analyze_iv(put_iv, call_iv, short_iv, long_iv, realized_vol, hours_to_expiry)` → `IvAnalysis`:
- **IV skew**: `put_iv − call_iv` (pozitif = downside korku).
- **Term structure**: `backwardation` (kısa>uzun, stres) / `contango` / `flat`.
- **Vol risk premium**: `implied − realized` (pozitif = pahalı opsiyon).
- **IV crush risk**: yüksek IV + yakın expiry → expiry sonrası vol düşüşü.

## Faz 27 entegrasyonu

`alternative_data_engine.analyze_alternative_data`, `options_flow` altında ilgili
alanlar varsa derinlik analizini çalıştırır ve çıktıya
`alternative_data.options_flow_deep` ekler:

```python
data = {"options_flow": {
    "put_volume": 150, "call_volume": 100, "pcr_history": [1.0, 1.3, 1.5],
    "whale_trades": [{"option_type": "call", "side": "buy", "notional_usd": 2e6}],
    "current_volume": 300, "avg_volume": 80,
    "option_chain": [{"strike": 50000, "call_oi": 300, "put_oi": 300}],
    "spot": 49000, "hours_to_expiry": 12,
    "put_iv": 80, "call_iv": 60, "short_iv": 85, "long_iv": 70, "realized_vol": 55,
}}
out = analyze_alternative_data("BTC/USDT", data, analysis)
# out["alternative_data"]["options_flow_deep"] → tüm metrikler
```

- Gamma squeeze + IV crush + unusual activity → `risk_score`.
- Kontraryan `alpha_bias` (PCR fear/greed + whale yönü) Faz 27 alpha'sına eklenir.
- Geriye uyumluluk: ilgili alanlar yoksa `options_flow_deep` eklenmez, davranış değişmez.
  Eski tek `put_call_ratio` alanı da yakalanır.

## Deribit collector

```python
from super_otonom.signals.options_flow_intelligence import OptionsFlowCollector
col = OptionsFlowCollector()                      # DERIBIT_API_URL (public)
contracts = col.fetch_contracts("BTC")            # get_book_summary_by_currency
pcr = OptionsFlowCollector.aggregate_pcr(contracts)
```

Tüm analiz fonksiyonları saftır; testler ağsız (`tests/test_options_flow_intelligence_p33.py`).
