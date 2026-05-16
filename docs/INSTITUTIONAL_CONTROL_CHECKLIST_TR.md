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

## §8 — Takvim (özet)

- [ ] Çeyrek: `docs/AUDIT.md` kontrol listesi
- [ ] Sürüm öncesi: `fastrun_p09` + CI yeşil
- [ ] Canlı öncesi: `fastrun_go_live` + `deploy_env_check`

## §9 — Kara / beyaz liste

- [ ] Canlı API: yalnız Vault KV (`SECRETS_VAULT_ONLY=true`)
- [ ] `.env` içinde düz metin API anahtarı yok
- [ ] Testnet anahtarı mainnet ile karışmıyor

## §10 — İmza (solo RCO varsayılan)

| Rol | Ad | Tarih | İmza |
|-----|-----|-------|------|
| RCO | | | [ ] |

İlgili: `docs/P09_BANDS.md`, `docs/RUNBOOK.md`, `docs/AUDIT.md`
