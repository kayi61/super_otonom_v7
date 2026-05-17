# Kurumsal kontrol listesi (TR) — super_otonom

**§1 limit tablosu** `config.RISK` / `.env` ile hizalanır. Tek satır doğrulama:

```powershell
python scripts/print_resolved_risk.py --summary
```

## §1 — Risk limitleri (RCO onayı)

| Politika (sözlü) | Config anahtarı | Varsayılan / env | RCO onay |
|------------------|-----------------|------------------|----------|
| Günlük kayıp tavanı %5 | `max_daily_loss_pct` | `MAX_DAILY_LOSS_PCT` → 0.05 | [ ] |
| Haftalık kayıp %10 | `max_weekly_loss_pct` | `MAX_WEEKLY_LOSS_PCT` | [ ] |
| Toplam drawdown %20 | `max_total_drawdown` | `MAX_TOTAL_DRAWDOWN` | [ ] |
| Portföy exposure %12 | `max_exposure_pct` | `MAX_EXPOSURE_PCT` | [ ] |
| Tek pozisyon %12 | `max_position_pct` | `MAX_POSITION_PCT` | [ ] |
| Açık pozisyon sayısı | `max_open_positions` | `MAX_OPEN_POSITIONS` | [ ] |
| Tek emir üst notional | `max_notional_per_order` | `MAX_NOTIONAL_PER_ORDER` | [ ] |
| Stop loss %4 | `stop_loss_pct` | `STOP_LOSS_PCT` | [ ] |
| Kaldıraç tavanı | `max_leverage` | `MAX_LEVERAGE` | [ ] |
| Sinyal kalite min | `signal_quality_min` | `SIGNAL_QUALITY_MIN` | [ ] |

## §2 — TWAP/VWAP yürütme (Audit 10)

| Kontrol | Komut / kanıt | RCO |
|---------|----------------|-----|
| VWAP sinyal (yürütme değil) | `hft_signal_engine.py` — `vwap_deviation_*` | [ ] |
| TWAP metadata (algo değil) | `execution_profile` / `preferred_order_type` faz 75–80 | [ ] |
| Algo child-order yürütme **yok** | `algo_implementation_hits` manifest'te boş | [ ] |
| `execution_profile` TradeExecutor'a bağlı değil | manifest `execution_profile_wired_to_trade_executor=false` | [ ] |
| Kurumsal TWAP/VWAP algo iddiası **yok** | `institutional_twap_vwap_execution_claim_allowed=false` | [ ] |
| Repo taraması | `python -m super_otonom.execution_topology_audit` → OK | [ ] |
| Yerel gate | `scripts/fastrun_execution_topology.cmd` PASS | [ ] |

**Not:** VWAP sinyal vardır; TWAP/VWAP **emir dilimleme router'ı** yoktur. `smart_order_router` yalnızca venue seçer.

## §3 — Test yerleşimi (Audit 9)

| Kontrol | Komut / kanıt | RCO |
|---------|----------------|-----|
| `super_otonom/test_*.py` manifest | `data/test_layout_manifest.json` | [ ] |
| Wheel'de test modülü **yok** | `layout_topology_audit --verify-wheel` → 0 | [ ] |
| Pytest kökü `tests/` | `pyproject.toml` testpaths | [ ] |
| Kurumsal temiz paket iddiası **yok** | `institutional_production_test_layout_claim_allowed=false` | [ ] |
| Yerel gate | `scripts/fastrun_test_layout.cmd` PASS | [ ] |

Yeni `super_otonom/test_*.py`: manifest güncelle + wheel doğrula.

## §4 — BotEngine god class (Audit 8)

| Kontrol | Komut / kanıt | RCO |
|---------|----------------|-----|
| LOC manifest uyumu | `data/bot_engine_topology_manifest.json` | [ ] |
| Sınıf satır tavanı | `class_line_ceiling` (varsayılan 1100) | [ ] |
| God class işaretli | `god_class=true` (~1000+ LOC) | [ ] |
| Kurumsal tek-sorumluluk iddiası **yok** | `institutional_single_responsibility_claim_allowed=false` | [ ] |
| Repo taraması | `python -m super_otonom.bot_engine_audit` → OK | [ ] |
| Yerel gate | `scripts/fastrun_bot_engine_topology.cmd` PASS | [ ] |

Kısmi delegasyon: `engine_managers`, `pipelines` — tam ayrıştırma değil.

## §5 — Paket topolojisi / god package (Audit 7)

| Kontrol | Komut / kanıt | RCO |
|---------|----------------|-----|
| Düz modül sayısı manifest ile uyumlu | `data/package_topology_manifest.json` | [ ] |
| Üretim modül tavanı | `flat_production_ceiling` (varsayılan 125) | [ ] |
| Yalnızca `pipelines/` alt paket | `allowed_subpackages` | [ ] |
| Kurumsal modüler sınır iddiası **yok** | `institutional_modular_boundary_claim_allowed=false` | [ ] |
| Repo taraması | `python -m super_otonom.package_topology_audit` → OK | [ ] |
| Yerel gate | `scripts/fastrun_package_topology.cmd` PASS | [ ] |

Yeni kök modül: `python -m super_otonom.package_topology --write-manifest` + PR.

## §6 — Saat / clock skew (Audit 6)

| Kontrol | Komut / kanıt | RCO |
|---------|----------------|-----|
| Borsa skew metrik + alarm | `bot_clock_skew_abs_ms`, `BotClockSkewHigh` | [ ] |
| Host NTP sondası (best-effort) | `bot_host_ntp_synchronized` | [ ] |
| Kurumsal NTP iddiası **yok** | `institutional_ntp_claim_allowed=false` | [ ] |
| Repo taraması | `python -m super_otonom.clock_skew_audit` → OK | [ ] |
| Yerel gate | `scripts/fastrun_clock_skew.cmd` PASS | [ ] |

Mum sırası: `check_candle_timestamps_monotonic` (backtest evreni uyarısı).

## §7 — Dağıtım / HA (Audit 5)

| Kontrol | Komut / kanıt | RCO |
|---------|----------------|-----|
| Tek bot instance (compose) | `bot_replicas=1`, sabit `container_name` | [ ] |
| Kurumsal HA iddiası **yok** | `institutional_ha_claim_allowed=false` | [ ] |
| Repo sahte HA ifadesi yok | `python -m super_otonom.ha_audit` → OK | [ ] |
| Yerel gate | `scripts/fastrun_ha.cmd` PASS | [ ] |

Süreklilik: `restart: unless-stopped` + `docs/DR_BCP.md` yedek — bu **HA değil**, tek host SPOF.

## §8 — Geri test / survivorship (Audit 4)

| Kontrol | Komut / kanıt | RCO |
|---------|----------------|-----|
| Tek sembol backtest kurumsal evren iddiası **yok** | `backtester.py` docstring; `survivorship_disclosure` | [ ] |
| Çok sembol + point-in-time takvim | `edge_evidence --symbols ... --universe-schedule data/universe_schedule_binance.json` | [ ] |
| Delist penceresi (sentetik/ccxt) | `scripts/fastrun_survivorship.cmd` PASS | [ ] |
| Repo taraması (sahte iddia yok) | `python -m super_otonom.survivorship_audit` → OK | [ ] |

Takvim verisi OHLCV türetilmiştir; resmi delist tarihi değildir — harici doğrulama gerekir.

## §9 — Takvim (özet)

- [ ] Çeyrek: `docs/AUDIT.md` kontrol listesi
- [ ] Sürüm öncesi: `fastrun_p09` + CI yeşil
- [ ] Canlı öncesi: `fastrun_go_live` + `deploy_env_check`
- [ ] Survivorship: `scripts/fastrun_survivorship.cmd`

## §10 — Kara / beyaz liste

- [ ] Canlı API: yalnız Vault KV (`SECRETS_VAULT_ONLY=true`)
- [ ] `.env` içinde düz metin API anahtarı yok
- [ ] Testnet anahtarı mainnet ile karışmıyor

## §11 — İmza (solo RCO varsayılan)

| Rol | Ad | Tarih | İmza |
|-----|-----|-------|------|
| RCO | | | [ ] |

İlgili: `docs/P09_BANDS.md`, `docs/RUNBOOK.md`, `docs/AUDIT.md`
