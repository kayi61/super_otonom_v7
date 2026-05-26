# DR Runbook — Backup & Restore (PROMPT 7)

Operasyonel felaket kurtarma adımları. Üst seviye plan: [DR_BCP.md](DR_BCP.md).

---

## 1. Otomatik yedekleme

### Linux / Docker (önerilen)

```bash
# Tek seferlik
./scripts/backup.sh

# Önizleme
./scripts/backup.sh --dry-run

# Compose cron sidecar (günlük 02:00 UTC)
docker compose --profile backup up -d backup
docker logs -f super_otonom_backup
```

**Hedef dizin:** `data/backup/<YYYYMMDD-HHMMSS>/`

**İçerik:**

| Bileşen | Dosya |
|---------|--------|
| TimescaleDB | `timescale/timescale.dump` (klines, trades, signals, equity_curve, capital_journal) |
| Vault (file) | `vault/vault_data.tar.gz` |
| Vault (raft) | `vault/vault_raft.snap` |
| Redis | `redis/dump.rdb` |
| Bot data | `data/*` (capital_journal.jsonl, positions.json, realized_pnl.json, …) |
| Manifest | `BACKUP_MANIFEST.txt`, `checksums.sha256` |

**Retention (GFS):** 7 günlük + 4 haftalık + 3 aylık anchor (Python rotasyon).

### Windows

```powershell
scripts\backup_daily.cmd
# veya
powershell -File scripts\backup_daily.ps1 -DryRun
```

### GitHub Actions

Workflow: `.github/workflows/nightly-backup.yml` — her gece `backup.sh --dry-run` + `restore.sh --verify` fixture.

---

## 2. Yedek bütünlüğü doğrulama

```bash
./scripts/restore.sh --verify data/backup/20260526-020000
```

Kontroller:

- `BACKUP_MANIFEST.txt` mevcut
- `checksums.sha256` (varsa) doğrulanır
- `timescale.dump` — `pg_restore -l` (pg_restore kuruluysa)
- Vault / Redis artefakt varlığı

---

## 3. Geri yükleme prosedürü

> **Uyarı:** `--restore` üretim verisini ezer. Bakım penceresi açın; `docker compose down` sonrası dikkatli olun (`down -v` volume siler).

### 3.1 Yalnızca bot `data/` dosyaları (en hızlı)

```bash
./scripts/restore.sh --restore data/backup/YYYYMMDD-HHMMSS --data-only --yes
```

Kopyalanan dosyalar: `capital_journal.jsonl`, `positions.json`, `realized_pnl.json`, `bot_state.json`, audit/reconcile dizinleri.

### 3.2 TimescaleDB

```bash
# Stack ayakta, timescaledb healthy
./scripts/restore.sh --restore data/backup/YYYYMMDD-HHMMSS --timescale-only --yes
```

`pg_restore --clean --if-exists` kullanılır — mevcut tablo verisi silinip yedekten yüklenir.

### 3.3 Redis

```bash
./scripts/restore.sh --restore data/backup/YYYYMMDD-HHMMSS --yes
```

Redis durdurulur, `dump.rdb` kopyalanır, yeniden başlatılır.

### 3.4 Vault (file storage — dev compose)

1. `docker compose stop vault bot`
2. `vault_data` volume yedekten geri yükle:
   ```bash
   docker run --rm -v super_otonom_v7_vault_data:/vault/data \
     -v "$(pwd)/data/backup/YYYYMMDD-HHMMSS/vault":/src:ro \
     alpine sh -c "rm -rf /vault/data/* && tar xzf /src/vault_data.tar.gz -C /vault"
   ```
3. `data/local/vault_init.json` ile unseal: `scripts/vault_unseal.ps1` (Windows) veya dokümantasyon
4. `docker compose up -d vault bot`

### 3.5 Tam senaryo (sunucu kaybı)

1. Yeni host — repo clone, `.env` geri yükle (güvenli kasa)
2. Son yedeği kopyala → `data/backup/`
3. `./scripts/restore.sh --verify <backup-dir>`
4. `./scripts/restore.sh --restore <backup-dir> --yes`
5. `docker compose up -d`
6. `deploy_env_check`, reconciliation, Prometheus/Grafana kontrol

---

## 4. Doğrulama checklist (restore sonrası)

- [ ] `python -m super_otonom.deploy_env_check` → exit 0
- [ ] Vault unsealed, bot metrics `/metrics` 200
- [ ] `data/reconcile/` son rapor temiz
- [ ] Timescale: `SELECT count(*) FROM capital_journal;` (opsiyonel)
- [ ] RCO: [INSTITUTIONAL_CONTROL_CHECKLIST_TR.md](INSTITUTIONAL_CONTROL_CHECKLIST_TR.md) ilgili maddeler

---

## 5. İlgili dosyalar

| Dosya | Açıklama |
|-------|----------|
| `scripts/backup.sh` | Birleşik yedek |
| `scripts/restore.sh` | Verify + restore |
| `scripts/backup_daily.ps1` | Windows günlük yedek |
| `docker-compose.yml` | `backup` servisi (`--profile backup`) |
| `.github/workflows/nightly-backup.yml` | CI dry-run |
