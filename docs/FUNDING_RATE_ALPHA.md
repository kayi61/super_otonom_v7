# Funding Rate Alpha (PROMPT-3.1)

`super_otonom/signals/funding_rate_alpha.py` — derinlemesine funding analizi;
`derivatives_intel` (Faz 18) `funding_rate` girdisini zenginleştirir.

## Metrikler

### 1. Funding history (8h aralık)
- `funding_stats(history)` → 30g ortalama, std, **z-score**, örnek sayısı.
- **Aşırılık sınıflandırma** (`classify_extremity`):
  - funding > **+0.05%** → `overcrowded_long` (aşırı long kalabalığı → short fırsatı)
  - funding < **−0.03%** → `overcrowded_short` (aşırı short → long squeeze olasılığı)

### 2. Cross-exchange (`cross_exchange_analysis`)
- Binance vs Bybit vs OKX funding farkı (`max_spread`).
- Arbitraj fırsatı tespiti (`arb_opportunity`, eşik vars. 0.03%).
- Yakınsama/uzaklaşma trendi (`converging` / `diverging` / `flat`, `prev_spread` ile).

### 3. Predicted funding (`predict_next_funding`)
- Order book imbalance (−1..1) → bir sonraki funding tahmini.
- Opsiyonel `premium_pct` (mark−index)/index ile yakınsama.

### 4. Cumulative funding (`cumulative_funding`)
- 7/30 günlük kümülatif funding cost.
- Long/short taşıma maliyeti (carry): pozitif funding → long maliyeti.

## Faz 18 entegrasyonu

`derivatives_intel.analyze_derivatives_intel`, `derivatives_data` içinde funding
alanları varsa derinlemesine analizi otomatik çalıştırır ve çıktıya
`derivatives.funding_analysis` ekler:

```python
data = {
    "funding_rate": 0.0010,
    "funding_history": [...],                 # 8h ondalık liste
    "cross_exchange_funding": {"binance": 0.0002, "bybit": 0.0008, "okx": 0.0003},
    "order_book_imbalance": 0.4,              # -1..1
    "funding_premium_pct": 0.0005,            # opsiyonel
    "position_notional": 1_000_000,           # carry maliyeti için
    "prev_funding_cross_spread": 0.0003,      # opsiyonel trend
}
out = analyze_derivatives_intel("BTC/USDT", data, analysis)
# out["derivatives"]["funding_analysis"] → tüm metrikler
```

**Karar kuralı:** `abs(z_score) > 2.5` → **`trade_permission: BLOCK`**.

Geriye uyumluluk: `funding_history`/`cross_exchange_funding` yoksa Faz 18 davranışı
değişmez (`funding_analysis` eklenmez).

## Sinyal yorumu

| Durum | alpha_bias | Anlam |
|-------|-----------|-------|
| `overcrowded_long` (yüksek + funding) | < 0 | Kontraryan short fırsatı |
| `overcrowded_short` (negatif funding) | > 0 | Long squeeze (bullish) |
| `abs(z) > 2.5` | — | BLOCK (aşırı funding rejimi) |

Tüm fonksiyonlar saftır; testler ağsız (`tests/test_funding_rate_alpha_p31.py`).
