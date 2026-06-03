# Open Interest & Liquidation Map (PROMPT-3.2)

`super_otonom/signals/liquidation_intelligence.py` — türev piyasa derinlik analizi;
`derivatives_intel` (Faz 18) `open_interest` / `liquidation_levels` /
`long_short_ratio` alanlarını zenginleştirir.

## 1. Open Interest analizi

`classify_oi_regime(oi_change, price_change)` — OI × fiyat yönü:

| OI | Fiyat | Rejim | Yorum |
|----|-------|-------|-------|
| ↑ | ↑ | `trend_strengthening` | New money in (bullish) |
| ↑ | ↓ | `short_buildup` | Squeeze riski |
| ↓ | ↓ | `long_capitulation` | — |
| ↓ | ↑ | `short_covering` | Sürdürülebilir değil |

- `analyze_oi(...)` → `OiRegime` (+ `squeeze_risk`, `is_bullish`).
- `velocities_from_history([(ts,oi)...])` → 1h/4h/24h yüzde değişim.

## 2. Liquidation haritası

`analyze_liquidation_map(levels, ref_price)` → `LiquidationMap`:
- **$100M+ cluster** tespiti (`LIQ_CLUSTER_MIN_USD`).
- **Magnet effect**: `%5` içindeki en yakın büyük cluster → `magnet_target`.
- **Cascade risk** (0..1): `%2` içindeki toplam liquidation yoğunluğu.

Coinglass/CoinAnk benzeri level formatı `parse_liquidation_levels` ile normalize edilir.

## 3. Long/Short derinlemesine

`analyze_long_short(top_trader_ratio, global_ratio, long_pct)` → `LongShortAnalysis`:
- Top trader (whale) vs global (retail) L/S.
- **Crowded trade**: tek tarafa `> %70` yığılma (`is_crowded`, `crowded_side`).
- **Retail-whale divergence**: top trader vs global ters yön.

## 4. Basis & Contango/Backwardation

`analyze_basis(spot, perp_price, quarterly_price)` → `BasisAnalysis`:
- Futures premium/discount (`basis_pct`).
- Vade yapısı: `contango` (futures > spot) / `backwardation` / `flat`.
- Quarterly vs perp **term spread** + **basis trade fırsatı**.

## Faz 18 entegrasyonu

`derivatives_intel.analyze_derivatives_intel`, `derivatives_data` içinde ilgili
alanlar varsa derinlik analizini otomatik çalıştırır ve çıktıya
`derivatives.market_structure` ekler:

```python
data = {
    "open_interest": 1_050_000, "open_interest_prev": 1_000_000,  # +5%
    "price_change_pct": -0.02,                                     # OI↑+P↓ → short_buildup
    "oi_history": [[ts, oi], ...],                                 # opsiyonel velocity
    "liquidation_levels": [{"price": 101.5, "notional_usd": 150e6, "side": "short"}],
    "top_trader_ls_ratio": 3.0, "global_ls_ratio": 0.8,           # divergence
    "spot_price": 100.0, "perp_price": 100.5, "quarterly_price": 102.0,
}
out = analyze_derivatives_intel("BTC/USDT", data, analysis)
# out["derivatives"]["market_structure"] → tüm metrikler
```

- Cascade riski + crowded yığılma toplam `risk_score`'a yansır.
- Kontraryan `alpha_bias` (squeeze/crowded → tersine) Faz 18 alpha'sına eklenir.
- Geriye uyumluluk: ilgili alanlar yoksa `market_structure` eklenmez, davranış değişmez.

Tüm fonksiyonlar saftır; testler ağsız (`tests/test_liquidation_intelligence_p32.py`).
