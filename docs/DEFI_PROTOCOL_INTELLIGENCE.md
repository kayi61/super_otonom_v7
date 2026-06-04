# DeFi Protocol Intelligence (PROMPT-2.2)

`super_otonom/signals/defi_protocol_intelligence.py` — DeFi protokol verilerini
izler; `alternative_data_engine` (Faz 27) adoption bölümünü zenginleştirir.

Kaynak: **DeFiLlama** API (ücretsiz, key gereksiz; injectable `http_get`). Analiz
fonksiyonları saftır; testler ağsız (`tests/test_defi_protocol_intelligence_p22.py`).

## 1. TVL (`analyze_tvl`)
- Protokol/chain TVL değişimi; `chain_tvl_flows` → akışın yoğunlaştığı chain.
- **TVL/FDV** oranı < 0.10 → `overvalued`.
- Ani TVL düşüşü ≤ **-%15** → `exploit_alert` (bank run / exploit), risk ↑.

## 2. DEX Volume & Liquidity (`analyze_dex`)
- Uniswap/Raydium/Jupiter volume; **$1M+ swap** sayısı → `whale_activity`.
- `large_swaps` net yönü (buy/sell) → bias (price impact öncesi sinyal).
- Pool depth düşüşü → likidite çekilme riski; yeni pool → token launch göstergesi.

## 3. Lending/Borrowing (`analyze_lending`)
- Borrow rate spike (≥ +%50) → kaldıraç artışı / volatilite.
- Utilization > **%80** → borrowing talep patlaması.
- Stablecoin borrow spike → piyasa stresi.
- `liquidation_proximity` → `cascade_risk` (toplu liquidation yaklaşıyor).

## 4. Bridge Flow (`analyze_bridge`)
- `bridge_flows` → hangi chain'e para akıyor (`dominant_inflow_chain`).
- `bridge_exploit_history` → exploit risk skoru (bias'ı düşürür).

## Birleşik sinyal (`analyze_defi` → `DefiSignal`)
- **Chain rotation**: TVL + bridge akışı aynı chain'e işaret ediyorsa → o chain'e alpha.
- `adoption_score`, `alpha_bias`, `risk_score`, `cascade_risk`, `volatility_expectation`,
  `exploit_alert`. Exploit alert → risk dominant, alpha negatif.
- `analyze_defi_data(dict)` köprüsü (`defi` alt dict veya düz `tvl`/`dex`/`lending`/`bridge`).
- `parse_defillama_protocol` / `parse_defillama_chains` + mock'lanabilir `DefiCollector`.

## Faz 27 entegrasyonu (`alternative_data_engine`)
`defi` verisi varsa: DeFi `adoption_score` mevcut adoption ile harmanlanır,
`risk_score` risk ile `max()`, `alpha_score` `defi_alpha_bias` ile ayarlanır;
`alternative_data.defi` bloğu eklenir. DeFi `defi_alpha_bias` alpha'ya eklenir
(`+0.10`), `defi_risk_score` risk ile `max()` alınır. onchain/options/unlock/developer
katmanlarıyla birlikte çalışır. Veri yoksa `defi` bloğu eklenmez, davranış değişmez;
hata Faz 27'yi asla bozmaz.
