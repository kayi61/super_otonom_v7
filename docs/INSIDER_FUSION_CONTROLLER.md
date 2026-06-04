# Insider Intelligence Fusion Controller (PROMPT-10.1)

`super_otonom/signals/insider_fusion_controller.py` — tüm insider intelligence
kaynaklarını tek `insider_conviction` (0-100) skoruna ve karara indirgeyen **son
karar katmanı**. `signal_fusion_engine` (Faz 36) ve `mm_whale_consensus_controller`
(Faz 75) ile entegre; BotEngine'e `analysis["insider_conviction"]` (+ phase76) olarak
iletilir. Saf/deterministik; testler ağsız.

## Girdi (decoupled — sinyallerin SONUÇLARI, dict/dataclass)
`whale_signal`, `onchain_signal`, `defi_signal`, `derivatives_signal`, `social_signal`,
`token_signal`, `macro_signal`, `etf_signal`, `exploit_alert`, `arb_signal` — hepsi
opsiyonel. Her sinyalden yön (`alpha_bias`/`action`/`environment`/`net_flow`…) ve
conviction (`conviction`/`confidence`) otomatik çıkarılır.

## Fusion mantığı (`analyze_insider_fusion`)
1. **Ağırlık + conviction**: her kategoriye yön (-1..1), conviction (0..1), ağırlık.
   Net yön = ağırlıklı (weight × conviction × direction) ortalaması.
2. **Çelişki**: whale bullish ama funding aşırı → `conflict`, net yön söndürülür → **WAIT**.
3. **Confluence**: 3+ bağımsız kaynak aynı yöne → conviction ↑.
4. **Override kuralları** (sırayla):
   - `exploit_alert` aktif → **HALT** (her şeyi ezer, conviction 100, perm HALT).
   - macro `RISK_OFF` + whale satış → **STRONG_SELL**.
   - whale birikim + stablecoin mint + ETF inflow → **STRONG_BUY**.
5. **Position sizing**: `conviction × kelly_fraction × risk_budget` (HALT/WAIT/NEUTRAL → 0).

Çıktı `InsiderFusionResult`: `insider_conviction` (0-100), `direction`, `decision`
(STRONG_BUY..HALT), `confluence_count`, `conflict`, `override_reason`,
`position_size_suggestion`, `trade_permission`, kaynak dökümü, gerekçeler.

## BotEngine'e iletim (`run_insider_fusion_phase`)
`run_insider_fusion_phase(analysis, signals=None)`:
- `signals` verilmezse `analysis` içindeki insider anahtarlarından toplanır.
- `analysis["insider_conviction"]` / `["insider_direction"]` / `["insider_fusion"]`
  yazılır + `phase76`/`faz76` alias. **Bot, analysis dict'i üzerinden bu skoru görür**
  (tick-loop'a invaziv dokunuş yok). İlgili sinyal yoksa `None`, analysis değişmez.

## Entegrasyon (geriye uyumlu)
- **`signal_fusion_engine` (Faz 36)** — `analysis["insider_fusion"]` varsa
  `_apply_fusion_to_out` `insider_conviction`'ı çıktıya geçirir; **insider decision
  HALT → `final_signal=HOLD`** (`INSIDER_EXPLOIT_HALT`). insider_fusion yoksa eski
  füzyon davranışı aynen korunur.
- **`mm_whale_consensus_controller` (Faz 75)** — `as_insider_signal(result)` adapteri
  Faz 75 sonucunu insider_fusion `whale_signal` girdisine çevirir (yön = (alpha−risk)/100,
  conviction = result.conviction). Mevcut Faz 75 davranışı değişmez.
