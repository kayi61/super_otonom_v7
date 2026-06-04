# Token Unlock & Vesting Tracker (PROMPT-5.1)

`super_otonom/signals/token_unlock_tracker.py` — token unlock takvimini ve vesting
schedule'ı takip eder; `news_event_intelligence` (Faz 23) unlock bölümünü ve
`alternative_data_engine` (Faz 27) tokenomics bölümünü zenginleştirir.

Kaynaklar: TokenUnlocks.app / Dune Analytics (enjekte edilebilir `http_get`).
Analiz fonksiyonları saftır; testler ağsız (`tests/test_token_unlock_tracker_p51.py`).

## 1. Unlock takvimi (`analyze_token_unlock`)

- Olaylar → `UnlockEvent` (date, pct_of_circulating, type, category, days_until, severity).
- Pencere özetleri: **7 / 30 / 90 gün** (`WindowSummary`: count, total_pct, max_pct, max_severity).
- Unlock miktarı / circulating supply oranı; **>%5 supply unlock → yüksek satış baskısı**
  (`high_sell_pressure`).

## 2. Cliff vs Linear + kategori

`event_severity(pct, type, category)` (intrinsik tehlike, 0..1):

- **Tip**: `cliff` (×1.0, tek seferde büyük → tehlikeli) > `linear` (×0.5, yavaş).
- **Kategori**: `team`/`investor` (×1.0/0.95) > `ecosystem`/`public`/`community` (×0.5–0.6).
- `severity = clamp01( clamp01(pct/0.08) × (0.45 + 0.55 × tip×kategori) )`.

## 3. Geçmiş davranış (`backtest_unlock_impact`)

Geçmiş unlock kayıtları (`post_move_pct` veya `price_before`+`price_after`,
`team_sold`, `drawdown_pct`):

- `avg_post_move_pct` — önceki unlock'lar sonrası ortalama fiyat hareketi.
- `sold_rate` — team token'ı satma oranı.
- Geçmişte ort. ≤ −%2 düşüş veya yüksek satış oranı → risk yükselir, alpha düşer.

## 4. Otomatik risk ayarı (`UnlockSignal`)

| Koşul | Etki |
|-------|------|
| 7 gün içinde ≥%5 unlock | `risk ≥ 0.6`, `position_size_multiplier = 0.5`, `BLOCK` |
| 30 gün içinde büyük unlock | `position_size_multiplier = 0.75` |
| Unlock günü (≤24s, ≥%2) | `trade_permission = BLOCK` |
| Unlock yakın + büyük borsa girişi (whale ≥ $5M) | `urgent = True`, `HALT`, mult ≤ 0.4 |

- `alpha_bias` `[-1,0]` — yaklaşan ağır unlock → negatif (satış baskısı).

## Köprü + Parser + Collector

- `analyze_unlock_data(dict)` — `token_unlock` alt dict (`schedule`/`events` +
  `circulating_supply`/`history`/`whale_exchange_inflow_usd`/`now_ms`) veya düz
  `unlock_schedule` listesi.
- `parse_token_unlocks_app`, `parse_dune` + mock'lanabilir `UnlockCollector`.

## Entegrasyon (geriye uyumlu)

### `news_event_intelligence` (Faz 23)
`token_unlock` / `unlock_schedule` varsa: `unlock_proximity_risk` tracker riskiyle
`max()` alınır; tracker `BLOCK`/`HALT` derse `trade_permission` yükseltilir;
`news.unlock_tracker` bloğu eklenir. Veri yoksa davranış değişmez.

### `alternative_data_engine` (Faz 27)
`token_unlock` varsa: `risk_score` tracker riskiyle `max()`, `alpha_score` tracker
`alpha_bias` (negatif) ile düşürülür; tracker `BLOCK`/`HALT` → `trade_permission`;
`alternative_data.unlock` bloğu eklenir. Tokenomics değerlendirmesiyle birlikte çalışır.
Veri yoksa davranış değişmez; hata Faz 23/27'yi asla bozmaz.
