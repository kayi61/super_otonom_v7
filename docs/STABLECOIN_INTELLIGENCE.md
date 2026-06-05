# Stablecoin Dominance & Flow (PROMPT-6.2)

`super_otonom/signals/stablecoin_intelligence.py` — stablecoin piyasa dinamiklerini
izler; `macro_event_intelligence` (Faz 6.1) likidite/makro ortamını zenginleştirir
(`stablecoin_mint` → insider_fusion STRONG_BUY kuralını besler).

Kaynak: CoinGecko API (ücretsiz) + on-chain USDT/USDC transfer (injectable `http_get`).
Analiz fonksiyonları saftır; testler ağsız (`tests/test_stablecoin_intelligence_p62.py`).

## 1. Market cap (`analyze_market_cap`)
USDT/USDC/DAI/BUSD toplam mcap trendi. **Artış → yeni para girişi (BULLISH)**;
düşüş → para çıkışı (BEARISH).

## 2. Dominance (`analyze_dominance`)
Stablecoin dominance ↑ → **piyasa cash'e dönüyor (BEARISH)**; ↓ → cash'ten crypto'ya
geçiş (BULLISH). (Ters yön.)

## 3. Mint/Burn (`analyze_mint_burn`)
- **USDT büyük mint (>$200M)** → alım gücü artışı → `big_mint` (→ `stablecoin_mint`).
- USDT büyük burn → likidite çekilmesi.
- USDC mint → kurumsal para girişi (Circle/Coinbase).

## 4. Depeg (`analyze_depeg`)
- USDT/USDC peg sapması **>%0.5 → alarm**, risk ↑.
- Curve 3pool dengesizliği, swap volume spike → panik göstergesi.

## Birleşik sinyal (`analyze_stablecoin` → `StablecoinSignal`)
- `environment` (BULLISH/BEARISH/NEUTRAL/RISK_OFF), `bias` `[-1,1]`, `risk_score`,
  **`stablecoin_mint`** (büyük mint), `depeg_alarm`, `depeg_risk`.
- Depeg alarmı + yüksek risk → `RISK_OFF`.
- `analyze_stablecoin_data(dict)` köprüsü + `parse_coingecko_stablecoins` +
  mock'lanabilir `StablecoinCollector`.

## Faz 6.1 entegrasyonu (`macro_event_intelligence`)
`stablecoin` alt dict / düz anahtarlar (`mcap_change_pct`, `dominance_change_pct`,
`usdt_mint_usd`, `usdt_price`…) varsa:
- Stablecoin `bias` makro bias'a katılır (`0.82×macro + 0.18×stablecoin`).
- `MacroSignal.stablecoin_mint` + `.stablecoin` bloğu **exposed** → 10.1
  insider_fusion'ın `macro_signal.stablecoin_mint` STRONG_BUY kuralını besler.
- Stablecoin-only veri de macro sinyalini aktive eder. **Geriye uyumlu**: veri yoksa
  `stablecoin_mint=False`, stablecoin bloğu eklenmez, eski 6.1 davranışı korunur;
  hata makro'yu asla bozmaz.
