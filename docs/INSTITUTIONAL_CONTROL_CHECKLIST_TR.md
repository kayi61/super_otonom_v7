# Kurumsal kontrol listesi (TR) — super_otonom

**§1 limit tablosu** `config.RISK` / `.env` ile hizalanır. Tek satır doğrulama:

```powershell
python scripts/print_resolved_risk.py --summary
```

## §1 — Risk limitleri (RCO onayı)

| Politika (sözlü) | Config anahtarı | Varsayılan / env | RCO onay |
|------------------|-----------------|------------------|----------|
| Günlük kayıp tavanı %5 | `max_daily_loss_pct` | `MAX_DAILY_LOSS_PCT` → 0.05 | [x] |
| Haftalık kayıp %10 | `max_weekly_loss_pct` | `MAX_WEEKLY_LOSS_PCT` | [x] |
| Toplam drawdown %20 | `max_total_drawdown` | `MAX_TOTAL_DRAWDOWN` | [x] |
| Portföy exposure %12 | `max_exposure_pct` | `MAX_EXPOSURE_PCT` | [x] |
| Tek pozisyon %12 | `max_position_pct` | `MAX_POSITION_PCT` | [x] |
| Açık pozisyon sayısı | `max_open_positions` | `MAX_OPEN_POSITIONS` | [x] |
| Tek emir üst notional | `max_notional_per_order` | `MAX_NOTIONAL_PER_ORDER` | [x] |
| Stop loss %4 | `stop_loss_pct` | `STOP_LOSS_PCT` | [x] |
| Kaldıraç tavanı | `max_leverage` | `MAX_LEVERAGE` | [x] |
| Sinyal kalite min | `signal_quality_min` | `SIGNAL_QUALITY_MIN` | [x] |

## §2 — VaR / CVaR (Audit 11)

| Kontrol | Komut / kanıt | RCO |
|---------|----------------|-----|
| Faz-24 VaR seti | `portfolio_risk_engine` — param / hist / MC + CVaR | [x] |
| Cornish-Fisher VaR | VR-03 `cornish_fisher_var` — skew/kurtosis düzeltmesi | [x] |
| CVaR / Expected Shortfall | VR-04 `cvar_models` — hist / param / MC, FRTB 97.5% | [x] |
| Canlı tick VaR | RiskEngine 3-model suite (param/hist/MC) + CVaR — `tick_record_var_suite` | [x] |
| Rejim-koşullu VaR | VR-10 `RegimeConditionalVaR` — deque-backed per-regime buffers | [x] |
| Stressed VaR (Basel 2.5) | VR-11 `StressedVaR` — 5 kripto stres dönemi rescaling | [x] |
| Stres senaryo kütüphanesi | VR-12 `StressScenarioLibrary` — forward/reverse stress test | [x] |
| Kupiec POF backtest | VR-13 `kupiec_pof` — LR ~ χ²(1), nightly CI | [x] |
| Christoffersen CC | VR-14 `christoffersen_cc` — bağımsızlık + koşullu kapsam | [x] |
| Basel trafik ışığı | VR-15 `basel_traffic_light` — GREEN/YELLOW/RED + sermaye eklentisi | [x] |
| P&L attribution | VR-16 `pnl_attribution` — explained/trades/unexplained + drift | [x] |
| Pre-trade VaR gate | VR-17 `pre_trade_var_check` — marginal VaR gate <30ms | [x] |
| VaR-aware pozisyon boyutu | VR-18 `size_with_var_cap` — Kelly + VaR cap binary search | [x] |
| VaR breach kill-switch | VR-19 `_check_var_breach` — var_99/cvar_975/stressed_var → emergency_stop | [x] |
| VaR limit hiyerarşisi | VR-20 `check_limits` — strategy/portfolio/firm 3 seviye | [x] |
| Prometheus VaR suite | VR-21 `record_var_suite` — 15 VaR + 12 CVaR + limit utilisation | [x] |
| Günlük risk raporu | VR-22 `generate_report` — 10 bölüm Markdown, cron 23:55 UTC | [x] |
| Grafana risk dashboard | VR-23 `risk.json` — 14 panel, 4 template variable | [x] |
| Model envanteri | VR-24 `MODEL_INVENTORY.md` — 22 model, yarı-yıllık validasyon | [x] |
| Risk iştah beyanı | VR-25 `RISK_APPETITE.md` — 4 kategori, L1-L4 eskalasyon | [x] |
| Property-based VaR testleri | VR-26 `hypothesis` — VaR/CVaR invariant'ları | [x] |
| Rejim tespit motoru | VR-27 `RegimeDetector` — vol-threshold, z-score change-point | [x] |
| Faz-24 canlı tick'te **değil** | `live_tick_uses_portfolio_risk_engine=false` | [x] |
| `live_tick_uses_risk_engine` | `var_topology_manifest.json` — `risk_engine_3model_suite` | [x] |
| Kurumsal VaR motoru iddiası **yok** | `institutional_var_claim_allowed=false` | [x] |
| Repo taraması | `python -m super_otonom.var_topology_audit` → OK | [x] |
| Yerel gate | `scripts/fastrun_var_topology.cmd` PASS | [ ] |

**Not:** 27-adım VaR/CVaR risk motoru (VR-01–VR-27) tamamlandı. RiskEngine 3-model suite canlı tick yolunda aktif. Rejim-koşullu VaR, stressed VaR, stres senaryo kütüphanesi, backtest suite (Kupiec/Christoffersen/Basel), P&L attribution, pre-trade gate, VaR limit hiyerarşisi, Prometheus suite, günlük rapor, Grafana dashboard, model envanteri ve risk iştah beyanı uygulanmıştır. Kurumsal iddia: `institutional_var_claim_allowed=false` — bu düzey kurumsal risk yönetimi iddiası için yeterli değildir.

## §3 — TWAP/VWAP yürütme (Audit 10)

| Kontrol | Komut / kanıt | RCO |
|---------|----------------|-----|
| VWAP sinyal (yürütme değil) | `hft_signal_engine.py` — `vwap_deviation_*` | [x] |
| TWAP metadata (algo değil) | `execution_profile` / `preferred_order_type` faz 75–80 | [x] |
| Algo child-order yürütme **yok** | `algo_implementation_hits` manifest'te boş | [x] |
| `execution_profile` TradeExecutor'a bağlı değil | manifest `execution_profile_wired_to_trade_executor=false` | [x] |
| Kurumsal TWAP/VWAP algo iddiası **yok** | `institutional_twap_vwap_execution_claim_allowed=false` | [x] |
| Repo taraması | `python -m super_otonom.execution_topology_audit` → OK | [x] |
| Yerel gate | `scripts/fastrun_execution_topology.cmd` PASS | [ ] |

**Not:** VWAP sinyal vardır; TWAP/VWAP **emir dilimleme router'ı** yoktur. `smart_order_router` yalnızca venue seçer.

## §4 — Test yerleşimi (Audit 9)

| Kontrol | Komut / kanıt | RCO |
|---------|----------------|-----|
| `super_otonom/test_*.py` manifest | `data/test_layout_manifest.json` — 0 in-package test | [x] |
| Wheel'de test modülü **yok** | `layout_topology_audit --verify-wheel` → 0 | [x] |
| Pytest kökü `tests/` | `pyproject.toml` testpaths | [x] |
| Kurumsal temiz paket iddiası **evet** | `institutional_production_test_layout_claim_allowed=true` | [x] |
| Yerel gate | `scripts/fastrun_test_layout.cmd` PASS | [ ] |

29 test dosyası `super_otonom/` → `tests/` altına taşınmıştır. Paket içi test borcu sıfırlanmıştır.

## §5 — BotEngine god class (Audit 8)

| Kontrol | Komut / kanıt | RCO |
|---------|----------------|-----|
| LOC manifest uyumu | `data/bot_engine_topology_manifest.json` | [x] |
| Sınıf satır tavanı | `class_line_ceiling` (varsayılan 1450) | [x] |
| God class işaretli | `god_class=true` (~1240 LOC) | [x] |
| Kurumsal tek-sorumluluk iddiası **yok** | `institutional_single_responsibility_claim_allowed=false` | [x] |
| Repo taraması | `python -m super_otonom.bot_engine_audit` → OK | [x] |
| Yerel gate | `scripts/fastrun_bot_engine_topology.cmd` PASS | [ ] |

Kısmi delegasyon: `engine_managers`, `pipelines` — tam ayrıştırma değil.

## §6 — Paket topolojisi / god package (Audit 7)

| Kontrol | Komut / kanıt | RCO |
|---------|----------------|-----|
| Düz modül sayısı manifest ile uyumlu | `data/package_topology_manifest.json` | [x] |
| Üretim modül tavanı | `flat_production_ceiling` (varsayılan 125) | [x] |
| Yalnızca `pipelines/` + `risk/` alt paket | `allowed_subpackages` | [x] |
| Kurumsal modüler sınır iddiası **yok** | `institutional_modular_boundary_claim_allowed=false` | [x] |
| Repo taraması | `python -m super_otonom.package_topology_audit` → OK | [x] |
| Yerel gate | `scripts/fastrun_package_topology.cmd` PASS | [ ] |

Yeni kök modül: `python -m super_otonom.package_topology --write-manifest` + PR.

## §7 — Saat / clock skew (Audit 6)

| Kontrol | Komut / kanıt | RCO |
|---------|----------------|-----|
| Borsa skew metrik + alarm | `bot_clock_skew_abs_ms`, `BotClockSkewHigh` | [x] |
| Host NTP sondası (best-effort) | `bot_host_ntp_synchronized` | [x] |
| Kurumsal NTP iddiası **yok** | `institutional_ntp_claim_allowed=false` | [x] |
| Repo taraması | `python -m super_otonom.clock_skew_audit` → OK | [x] |
| Yerel gate | `scripts/fastrun_clock_skew.cmd` PASS | [ ] |

Mum sırası: `check_candle_timestamps_monotonic` (backtest evreni uyarısı).

## §8 — Dağıtım / HA (Audit 5)

| Kontrol | Komut / kanıt | RCO |
|---------|----------------|-----|
| Tek bot instance (compose) | `bot_replicas=1`, sabit `container_name` | [x] |
| Kurumsal HA iddiası **yok** | `institutional_ha_claim_allowed=false` | [x] |
| Repo sahte HA ifadesi yok | `python -m super_otonom.ha_audit` → OK | [x] |
| Yerel gate | `scripts/fastrun_ha.cmd` PASS | [ ] |

Süreklilik: `restart: unless-stopped` + `docs/DR_BCP.md` yedek — bu **HA değil**, tek host SPOF.

## §9 — Geri test / survivorship (Audit 4)

| Kontrol | Komut / kanıt | RCO |
|---------|----------------|-----|
| Tek sembol backtest kurumsal evren iddiası **yok** | `backtester.py` docstring; `survivorship_disclosure` | [x] |
| Çok sembol + point-in-time takvim | `edge_evidence --symbols ... --universe-schedule data/universe_schedule_binance.json` | [x] |
| Delist penceresi (sentetik/ccxt) | `scripts/fastrun_survivorship.cmd` PASS | [ ] |
| Repo taraması (sahte iddia yok) | `python -m super_otonom.survivorship_audit` → OK | [x] |

Takvim verisi OHLCV türetilmiştir; resmi delist tarihi değildir — harici doğrulama gerekir.

## §10 — Takvim (özet)

- [ ] Çeyrek: `docs/AUDIT.md` kontrol listesi (operasyonel — canlıda yapılacak)
- [x] Sürüm öncesi: `fastrun_p09` + CI yeşil
- [x] Canlı öncesi: `fastrun_go_live` + `deploy_env_check`
- [ ] Survivorship: `scripts/fastrun_survivorship.cmd` (operasyonel — canlıda yapılacak)

## §11 — Kara / beyaz liste

- [x] Canlı API: yalnız Vault KV (`SECRETS_VAULT_ONLY=true`)
- [x] `.env` içinde düz metin API anahtarı yok
- [x] Testnet anahtarı mainnet ile karışmıyor

## §12 — İmza (solo RCO varsayılan)

| Rol | Ad | Tarih | İmza |
|-----|-----|-------|------|
| RCO | | | [ ] |

İlgili: `docs/P09_BANDS.md`, `docs/RUNBOOK.md`, `docs/AUDIT.md`
