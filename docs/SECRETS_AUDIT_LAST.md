# Sir denetimi (PROMPT 2) — 2026-05-16 15:04:18 UTC

| Alan | Deger |
|------|--------|
| Makine | `DESKTOP-98LUGLH` |
| Repo | `C:\Users\lonek\Desktop\super otomonv7\super_otonom_v7` |
| Genel sonuc | **FAIL** |
| .env dosyasi | `C:\Users\lonek\Desktop\super otomonv7\super_otonom_v7\.env` (var) |

## Checklist

| Madde | Sonuc | Not |
|-------|--------|-----|
| Mevcut profil: DRY_RUN | **PASS** | True |
| Mevcut profil: PAPER_MODE | **PASS** | True |
| Mevcut profil: LIVE_CONFIRM | **WARN** | '' |
| .env icinde duz metin BINANCE/borsa anahtari (dosya) | **PASS** | (yok) |
| .env icinde TELEGRAM_* (uyari; canlida Vault onerilir) | **WARN** | TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID |
| Ortamda duz metin BINANCE/borsa anahtari (process env) | **PASS** | (yok) |
| SECRETS_VAULT_ONLY (simdiki cozumleme) | **WARN** | False |
| Vault erisilebilir | **FAIL** | addr=http://127.0.0.1:8200 auth=approle |
| Vault KV dolu (secret/data/trading/binance) | **WARN** | api_key=hayir api_secret=hayir |
| deploy_env_check (mevcut .env) | **PASS** | exit=0 |
| deploy_env_check (canli profil sim: DRY_RUN=false PAPER=false LIVE_CONFIRM=YES SECRETS_VAULT_ONLY=true) | **FAIL** | exit=1 |

## deploy_env_check ozeti (son satirlar, sir yok)

### Mevcut profil
```text
# P0 - INSTITUTIONAL sect.1 alignment (resolved RISK; no secrets)
# Compare each line to INSTITUTIONAL_CONTROL_CHECKLIST_TR.md section 1 table.

- max_daily_loss_pct = 0.05 (~%5)  [source: env:MAX_DAILY_LOSS_PCT] | table row: %5 policy wording must match
- max_weekly_loss_pct = 0.1 (~%10)  [source: default] | table row: %10 policy wording must match
- max_total_drawdown = 0.2 (~%20)  [source: env:MAX_TOTAL_DRAWDOWN] | table row: %20 policy wording must match
- max_exposure_pct = 0.12 (~%12)  [source: env:MAX_EXPOSURE_PCT] | table row: %12 policy wording must match
- max_position_pct = 0.12 (~%12)  [source: env:MAX_POSITION_PCT] | table row: %12 policy wording must match
- max_open_positions = 1  [source: env:MAX_OPEN_POSITIONS]
- max_notional_per_order = 50000.0  [source: default]
- stop_loss_pct = 0.04 (~%4)  [source: env:STOP_LOSS_PCT] | table row: %4 policy wording must match
- take_profit_pct = 0.3 (~%30)  [source: env:TAKE_PROFIT_PCT] | table row: %30 policy wording must match
- max_leverage = 1.0  [source: default]
- signal_quality_min = 62  [source: env:SIGNAL_QUALITY_MIN]
- exposure_breach_emergency = false  [source: default]
- min_notional = 10.0  [source: default]

# One-line verification example (internal note / PR): "max_daily_loss_pct=0.05 (~%5), INSTITUTIONAL sect.1 daily loss %5 - OK" or fix table / env / commit.

PAIRS (4): BTC/USDT, ETH/USDT, BNB/USDT, SOL/USDT
deploy_env_check: A9 / canlÄ± .env â€” engelleyici sorun yok (META_REGIME_MODE='shadow', paper_mode=True, LIVE_CONFIRM='').
deploy_env_check: P0 - INSTITUTIONAL sect.1 alignment (resolved RISK; no .env required): max_daily_loss_pct=0.05
deploy_env_check: P0 â€” Ã§Ã¶zÃ¼mlenmiÅŸ RISK Ã¶zeti (INSTITUTIONAL sect.1 ile karÅŸÄ±laÅŸtÄ±rÄ±n):
deploy_env_check: baÅŸarÄ± zaman damgasÄ± â€” deploy_env_check_last_ok.json (canlÄ± tick kilidi iÃ§in RUNBOOK #tatbikat-env).
Vault AppRole login baÅŸarÄ±sÄ±z: HTTP Error 503: Service Unavailable
Vault AppRole login baÅŸarÄ±sÄ±z: HTTP Error 503: Service Unavailable
```

### Canli profil simulasyonu
```text
Vault AppRole login baÅŸarÄ±sÄ±z: HTTP Error 503: Service Unavailable
SECRETS_VAULT_ONLY aktif ancak VAULT_TOKEN veya AppRole yok â€” VAULT_ADDR + VAULT_ROLE_ID + VAULT_SECRET_ID ayarlayÄ±n
Vault yok â€” binance secret okunamadÄ± (SECRETS_VAULT_ONLY)
Vault yok â€” bybit secret okunamadÄ± (SECRETS_VAULT_ONLY)
Vault yok â€” kucoin secret okunamadÄ± (SECRETS_VAULT_ONLY)
Vault yok â€” okx secret okunamadÄ± (SECRETS_VAULT_ONLY)
Vault yok â€” coinbase secret okunamadÄ± (SECRETS_VAULT_ONLY)
Vault yok â€” gateio secret okunamadÄ± (SECRETS_VAULT_ONLY)
Vault AppRole login baÅŸarÄ±sÄ±z: HTTP Error 503: Service Unavailable
SECRETS_VAULT_ONLY aktif ancak VAULT_TOKEN veya AppRole yok â€” VAULT_ADDR + VAULT_ROLE_ID + VAULT_SECRET_ID ayarlayÄ±n
[HATA] CanlÄ± profil + SECRETS_VAULT_ONLY â€” Vault eriÅŸilemiyor. VAULT_ADDR + AppRole (VAULT_ROLE_ID, VAULT_SECRET_ID) veya kÄ±sa Ã¶mÃ¼rlÃ¼ VAULT_TOKEN.
[HATA] API anahtarlarÄ± .env/ortamda â€” Ã¼retimde yalnÄ±zca Vault KV: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID. TaÅŸÄ±ma: python -m super_otonom.vault_seed
```

## Emir gonderimi

Canli profilde deploy_env_check veya Vault-only iken anahtar sizintisi varsa `main_loop` / config yolu gercek emir gondermemeli (LIVE_CONFIRM + SECRETS_VAULT_ONLY kapilari).

## Yenileme

```powershell
Set-Location -LiteralPath '<repo_koku>'
.\scripts\fastrun_secrets_audit.cmd
```

