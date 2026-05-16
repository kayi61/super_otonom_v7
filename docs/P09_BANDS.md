# P0.9+ — 9 bant (kod vs süreç/altyapı)

**Tek komut (yerel kapılar):** `scripts/fastrun_p09.ps1`

## Bantlar

| # | Bant | Tür | Repo durumu | Sonraki somut adım |
|---|------|-----|-------------|-------------------|
| 1 | CI / lint / release_gate | Kod | Yeşil (`ci.yml`) | — |
| 2 | Bağımlılık güvenliği | Kod | Yeşil (`fastrun_security`, Dependabot) | — |
| 3 | Test + coverage | Kod | Yeşil (`pytest-full`, %90) | — |
| 4 | Gözlemlenebilirlik | Altyapı | Drill | `scripts\fastrun_observability.cmd` → `docs/OBSERVABILITY_DRILL.md` |
| 5 | Vault / sırlar | Altyapı + süreç | Denetim | `scripts\fastrun_secrets_audit.cmd` → `docs/SECRETS_AUDIT_LAST.md`; seed: `vault_seed.cmd` |
| 6 | Canlı açma sözleşmesi | Süreç | RUNBOOK + `fastrun_go_live` | Aşama 3 canlı tatbikat |
| 7 | Kurumsal kontrol listesi | Süreç | **Bu PR** | `INSTITUTIONAL_CONTROL_CHECKLIST_TR.md` |
| 8 | DR / yedekleme | Süreç + altyapı | **Bu PR** | `scripts/backup_daily.ps1` + cron |
| 9 | Dal koruması / RCO | Süreç (GitHub) | **Aktif** | `docs/BRANCH_PROTECTION_STATUS.md` — yenile: `scripts\report_branch_protection_status.ps1 -WriteDoc` |

## Önce ele alınan 3 madde (öneri)

### PR-1 — Bant 7: Kurumsal checklist

- Dosya: `docs/INSTITUTIONAL_CONTROL_CHECKLIST_TR.md` (§1 limit tablosu)
- Doğrulama: `python scripts/print_resolved_risk.py --summary`
- CI: doküman only → `ci-quick` yeterli

### PR-2 — Bant 8: Yedekleme

- Dosya: `scripts/backup_daily.ps1`, `scripts/backup_daily.cmd`
- Kaynak: `docs/DR_BCP.md` günlük yedek bloğu
- Doğrulama: `powershell -File scripts/backup_daily.ps1 -DryRun`

### PR-3 — Bant 9: GitHub süreç

- Repo dışı: Settings → Branch protection → `ci-quick`, `pytest-full`, `dependency-security`
- Repo içi: `.github/REQUIRED_CHECKS.md` güncelle (zaten varsa kontrol)

## Yerel fastrun sırası

```powershell
cd "C:\Users\lonek\Desktop\super otomonv7\super_otonom_v7"
git pull
scripts\fastrun_p09.cmd
```

**Not:** Komutları `C:\Users\lonek` altında değil, repo kökünde çalıştırın.

### Sık uyarılar (sim için normal)

| Çıktı | Anlam |
|-------|--------|
| `PermissionError` … `pytest-temproot` | Windows pytest temizliği; testler geçtiyse yok sayın |
| `Vault AppRole login … getaddrinfo` | Vault/Docker kapalı; sim (`DRY_RUN`) için sorun değil |
| `vault_seed … 10061` / `503` | Vault sealed veya port: `scripts\vault_seed.cmd` (otomatik unseal) |
| `running scripts is disabled` | `.ps1` yerine **`.cmd`** kullanın (`fastrun_vault.cmd`, `env_harden_secrets.cmd`) |
| `env_harden` API satırlarını sildi | Anahtarları geçici `.env` / `data\local\telegram.env` → `vault_seed.cmd` → `env_harden_secrets.cmd` |
| Redis kline hep boş / “stale” | `REDIS_KLINE_MAX_AGE_MS` / `REDIS_KLINE_TIMEFRAME` (Faz 4); eski anahtar: `RedisBridge.clear_stale_kline_keys()` |
| `apiKey` / `-2008` recon öncesi | `RECON_SIM_SKIP_SIGNED_FETCH=1` (Faz 5) veya read-only anahtar + `RECON_FETCH_BALANCE_IN_SIM=1` |

İsteğe bağlı (Docker açık):

```powershell
scripts\fastrun_vault.cmd
powershell -File scripts\fastrun_observability.ps1
```
