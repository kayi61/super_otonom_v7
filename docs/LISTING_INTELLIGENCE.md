# Exchange Listing & Delisting Detector (PROMPT-5.2)

`super_otonom/signals/listing_intelligence.py` — borsa listing/delisting olaylarını
erken tespit eder; `news_event_intelligence` (Faz 23) `is_exchange_listing` bayrağıyla
entegre çalışır. Analiz fonksiyonları saftır; testler ağsız
(`tests/test_listing_intelligence_p52.py`).

## 1. Listing sinyalleri (erken tespit) — `listing_probability`

| Sinyal | Katkı |
|--------|-------|
| Borsa duyurusu (`announcement_detected`) | +0.45 |
| API'de yeni symbol (`api_symbol_added`) | +0.32 |
| Borsa cüzdanına transfer (on-chain) | +0.26 |
| Test wallet'ta token | +0.22 |
| ≥2 Tier-2 borsada listeli → **Tier-1 yakında** | +0.28 |
| `confirmed_listing` (onay) | prob → ≥0.95 |

## 2. Delisting sinyalleri — `delisting_risk`

- Delisting duyurusu → 0.9; Regulatory/compliance (SEC) → 0.8.
- Volume ani düşüş (`volume_drop_pct`, 0.7 = %70) → orantılı risk.
- Proje durması + volume kuruması → 0.5.

## 3. Listing impact modeli — `listing_impact`

- **Tier-1** (Binance/Coinbase) → ort. **+%50** (30–80 aralığı proxy),
  Tier-2 +%15, Tier-3 +%5.
- `dump_window_hours = 48` (listing sonrası dump genellikle 24–72h).
- `buy_rumor_window` — pre-listing (onaylanmadan) "buy the rumor" penceresi.
- `history` verilirse beklenen hareket backtest ortalamasıyla override edilir.

## 4. Otomatik trade sinyali — `analyze_listing` → `ListingSignal`

| Durum | action | trade_permission |
|-------|--------|------------------|
| Yüksek olasılıklı listing (≥0.65) | `open_small` (pos 0.3, alpha +) | ALLOW |
| Onaylı listing (pre-dump) | `scale_up` (pos 0.7) | ALLOW |
| Onaylı + dump penceresi (≤48h) | `take_profit` | ALLOW |
| Delisting riski ≥0.6 | `close` (pos 0.0, alpha −) | BLOCK / **HALT** (duyuru/SEC → urgent) |

- `predicted_tier` — borsa adından veya ≥2 Tier-2 → Tier-1.
- `parse_announcement` (blog/announcement keyword), `detect_new_symbols` (API diff),
  mock'lanabilir `ListingCollector`.

## Faz 23 entegrasyonu (`news_event_intelligence`)

`listing` / `delisting` alt dict'i veya düz sinyal anahtarları varsa:
- `alpha_score` += `0.12 × listing_alpha_bias` (listing → buy the rumor).
- `risk_score` = `max(risk, listing_risk_score)` (delisting/dump).
- Tracker `BLOCK`/`HALT` (delisting) → `trade_permission`.
- `news.listing_intelligence` bloğu eklenir.

**Geriye uyumluluk**: yalın `is_exchange_listing` bayrağı tek başına yeni modülü
**tetiklemez** (eski Faz 23 listing-boost davranışı korunur); yalnız yapılandırılmış
listing/delisting verisi geldiğinde aktive olur. Hata Faz 23'ü asla bozmaz.
