# Makroekonomik Event Tracker (PROMPT-6.1)

`super_otonom/macro_event_intelligence.py` — kripto piyasayı etkileyen makro
olayları takip eder; `regime_detection_engine` (Faz 26) ve `meta_regime_orchestrator`
(A9) rejim çıkarımını makro ortamla zenginleştirir.

Kaynaklar: FRED (Federal Reserve, ücretsiz) / investing.com (injectable `http_get`).
Analiz fonksiyonları saftır; testler ağsız (`tests/test_macro_event_intelligence_p61.py`).

## 1. Ekonomik takvim (`analyze_economic_calendar`)
FED duruşu (dovish/hawkish), CPI/PPI surprise (actual − expected), FOMC sentiment,
yaklaşan büyük olay → bias + volatilite beklentisi. **CPI beklentiden yüksek →
hawkish/bearish + volatilite spike.**

## 2. Makro indikatörler (`analyze_macro_indicators`)
- **DXY** ↑ → crypto baskı (bias −); ↓ → destek (bias +).
- US 10Y yield ↑ → hafif risk-off.
- S&P/Nasdaq trendi.
- **VIX > 30 → risk-off** (bias −, risk ↑).

## 3. Likidite (`analyze_liquidity`)
- Fed balance sheet (QE genişleme → +, QT daralma → −).
- **M2** ↑ → bullish likidite.
- Reverse repo düşüşü → piyasaya likidite (+).
- Global net likidite (Fed + ECB + BOJ + PBOC).

## 4. Geopolitik (`analyze_geopolitical`)
Savaş/yaptırım keyword, kripto regülasyon (SEC/MiCA, severity), CBDC → geo risk.

## Sinyal mantığı (`analyze_macro` → `MacroSignal`)

| Kombinasyon | Ortam | regime_hint |
|-------------|-------|-------------|
| FED dovish + DXY↓ + M2↑ | `BULLISH` | `TRENDING` |
| FED hawkish + DXY↑ + VIX spike | `RISK_OFF` | `CRASH_RISK` |
| DXY↑ + SPX↓ / regülasyon | `BEARISH` | `RANGING` |
| nötr | `NEUTRAL` | `UNKNOWN` |

- `risk_off + risk ≥ 0.75` → `trade_permission = BLOCK`.
- `volatility_expectation` — CPI surprise / VIX / yaklaşan olaydan.
- `parse_fred_series` + mock'lanabilir `MacroCollector` (FRED_API_KEY).

## Entegrasyon (geriye uyumlu)

### `regime_detection_engine` (Faz 26)
`analysis` içinde makro veri varsa: phase26 `risk_score` makro riskle `max()`,
makro `BLOCK` → `trade_permission`, `macro` bloğu eklenir. Veri yoksa değişmez.

### `meta_regime_orchestrator` (A9)
**`omega_regime` yoksa/UNKNOWN** ve makro veri varsa: makro rejim ipucu
(`macro_regime_hint`) rejim olarak kullanılır (`regime_source = "macro_hint"`).
**Omega mevcutsa makro DEVREYE GİRMEZ** — kurallı tablo ve eski davranış aynen
korunur ("ölçüm olmadan ağırlık değiştirme yok" ilkesi bozulmaz). Hata → fallback
`UNKNOWN`, Faz asla bozulmaz.
