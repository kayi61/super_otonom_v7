#!/usr/bin/env bash
# super_otonom — unified backup (TimescaleDB, Vault, Redis, data/)
# Usage: scripts/backup.sh [--dry-run] [--backup-root PATH] [--skip-retention]
# Retention (GFS): 7 daily + 4 weekly + 3 monthly anchors
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

DRY_RUN=0
SKIP_RETENTION=0
BACKUP_ROOT="${BACKUP_ROOT:-data/backup}"
DAILY_KEEP=7
WEEKLY_KEEP=4
MONTHLY_KEEP=3

TIMESCALE_CONTAINER="${TIMESCALE_CONTAINER:-super_otonom_timescaledb}"
VAULT_CONTAINER="${VAULT_CONTAINER:-super_otonom_vault}"
REDIS_CONTAINER="${REDIS_CONTAINER:-super_otonom_redis}"
TIMESCALE_HOST="${TIMESCALE_HOST:-timescaledb}"
REDIS_HOST="${REDIS_HOST:-redis}"

TIMESCALE_TABLES=(klines trades signals equity_curve capital_journal)

DATA_FILES=(
  data/capital_journal.jsonl
  data/positions.json
  data/realized_pnl.json
  data/bot_state.json
  data/pending_orders.json
  data/orders.jsonl
)
DATA_DIRS=(data/audit data/recon data/reconcile data/reports)

log() { printf '[backup] %s\n' "$*"; }
warn() { printf '[backup][WARN] %s\n' "$*" >&2; }

usage() {
  cat <<'EOF'
Usage: scripts/backup.sh [OPTIONS]

Options:
  --dry-run           Print actions only; do not write backups
  --backup-root PATH  Backup parent directory (default: data/backup)
  --skip-retention    Skip GFS retention pruning after backup
  -h, --help          Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --backup-root)
      BACKUP_ROOT="${2:?}"
      shift 2
      ;;
    --skip-retention) SKIP_RETENTION=1; shift ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -f "${REPO_ROOT}/.env" ]]; then
  # .env SIRLAR icindir; CLI kontrol bayraklarini (DRY_RUN/SKIP_RETENTION) EZMEMELI.
  # set -a ile source her seyi import eder -> .env'deki stray DRY_RUN=true `--dry-run`'i
  # eziyordu (CI'da flaky, line 310 "unbound variable"). CLI'yi koru, source sonrasi geri yukle.
  __cli_dry_run="${DRY_RUN}"
  __cli_skip_retention="${SKIP_RETENTION}"
  set -a
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/.env"
  set +a
  DRY_RUN="${__cli_dry_run}"
  SKIP_RETENTION="${__cli_skip_retention}"
  unset __cli_dry_run __cli_skip_retention
fi

POSTGRES_USER="${POSTGRES_USER:-superotonom}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-}"
POSTGRES_DB="${POSTGRES_DB:-trading}"
export PGPASSWORD="${POSTGRES_PASSWORD}"

STAMP="$(date -u +%Y%m%d-%H%M%S)"
UTC_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
DEST="${REPO_ROOT}/${BACKUP_ROOT}/${STAMP}"

docker_ok() {
  command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1
}

container_running() {
  docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null | grep -q true
}

backup_timescale() {
  local out="${DEST}/timescale"
  mkdir -p "${out}"
  local -a targs=()
  local t
  for t in "${TIMESCALE_TABLES[@]}"; do
    targs+=(-t "${t}")
  done

  if docker_ok && container_running "${TIMESCALE_CONTAINER}"; then
    if [[ "${DRY_RUN}" == "1" ]]; then
      log "[dry-run] pg_dump via docker ${TIMESCALE_CONTAINER} tables: ${TIMESCALE_TABLES[*]}"
      return 0
    fi
    docker exec "${TIMESCALE_CONTAINER}" pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
      "${targs[@]}" -Fc -f /tmp/timescale.dump
    docker cp "${TIMESCALE_CONTAINER}:/tmp/timescale.dump" "${out}/timescale.dump"
    docker exec "${TIMESCALE_CONTAINER}" rm -f /tmp/timescale.dump
    log "OK timescale.dump"
  elif [[ -n "${POSTGRES_PASSWORD}" ]] && command -v pg_dump >/dev/null 2>&1; then
    if [[ "${DRY_RUN}" == "1" ]]; then
      log "[dry-run] pg_dump -h ${TIMESCALE_HOST} tables: ${TIMESCALE_TABLES[*]}"
      return 0
    fi
    pg_dump -h "${TIMESCALE_HOST}" -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
      "${targs[@]}" -Fc -f "${out}/timescale.dump"
    log "OK timescale.dump"
  else
    warn "TimescaleDB backup skipped (no container or pg_dump + credentials)"
    return 0
  fi
}

backup_vault() {
  local out="${DEST}/vault"
  mkdir -p "${out}"

  if ! docker_ok || ! container_running "${VAULT_CONTAINER}"; then
    warn "Vault backup skipped (container not running)"
    return 0
  fi

  local storage
  storage="$(docker exec "${VAULT_CONTAINER}" vault status -format=json 2>/dev/null | sed -n 's/.*"storage_type"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1 || true)"

  if [[ "${storage}" == "raft" ]]; then
    if [[ "${DRY_RUN}" == "1" ]]; then
      log "[dry-run] vault operator raft snapshot save"
      return 0
    fi
    docker exec "${VAULT_CONTAINER}" vault operator raft snapshot save /tmp/vault.snap
    docker cp "${VAULT_CONTAINER}:/tmp/vault.snap" "${out}/vault_raft.snap"
    docker exec "${VAULT_CONTAINER}" rm -f /tmp/vault.snap
    log "OK vault_raft.snap"
  else
    log "Vault file storage — archiving /vault/data (not raft snapshot)"
    if [[ "${DRY_RUN}" == "1" ]]; then
      log "[dry-run] vault data tar archive"
      return 0
    fi
    docker exec "${VAULT_CONTAINER}" tar czf /tmp/vault_data.tar.gz -C /vault data
    docker cp "${VAULT_CONTAINER}:/tmp/vault_data.tar.gz" "${out}/vault_data.tar.gz"
    docker exec "${VAULT_CONTAINER}" rm -f /tmp/vault_data.tar.gz
    log "OK vault_data.tar.gz"
  fi
}

backup_redis() {
  local out="${DEST}/redis"
  mkdir -p "${out}"

  if docker_ok && container_running "${REDIS_CONTAINER}"; then
    if [[ "${DRY_RUN}" == "1" ]]; then
      log "[dry-run] redis-cli BGSAVE + copy dump.rdb"
      return 0
    fi
    docker exec "${REDIS_CONTAINER}" redis-cli BGSAVE
    sleep 2
    if docker cp "${REDIS_CONTAINER}:/data/dump.rdb" "${out}/dump.rdb" 2>/dev/null; then
      log "OK redis/dump.rdb"
    else
      warn "Redis RDB copy failed (check /data/dump.rdb path)"
    fi
  elif command -v redis-cli >/dev/null 2>&1; then
    if [[ "${DRY_RUN}" == "1" ]]; then
      log "[dry-run] redis-cli -h ${REDIS_HOST} BGSAVE"
    else
      redis-cli -h "${REDIS_HOST}" BGSAVE
      warn "redis-cli BGSAVE issued; copy dump.rdb from Redis volume manually"
    fi
  else
    warn "Redis backup skipped"
  fi
}

backup_data_tree() {
  local out="${DEST}/data"
  mkdir -p "${out}"
  local rel src name
  for rel in "${DATA_FILES[@]}"; do
    src="${REPO_ROOT}/${rel}"
    if [[ -f "${src}" ]]; then
      name="$(basename "${rel}")"
      if [[ "${DRY_RUN}" == "1" ]]; then
        log "[dry-run] copy ${rel} -> data/${name}"
      else
        cp -f "${src}" "${out}/${name}"
        log "OK ${rel}"
      fi
    fi
  done
  for rel in "${DATA_DIRS[@]}"; do
    src="${REPO_ROOT}/${rel}"
    if [[ -d "${src}" ]]; then
      name="$(basename "${rel}")"
      if [[ "${DRY_RUN}" == "1" ]]; then
        log "[dry-run] copydir ${rel} -> data/${name}/"
      else
        cp -a "${src}" "${out}/${name}"
        log "OK ${rel}/"
      fi
    fi
  done
}

write_manifest() {
  local git_sha="unknown"
  if command -v git >/dev/null 2>&1; then
    git_sha="$(git -C "${REPO_ROOT}" rev-parse HEAD 2>/dev/null || echo unknown)"
  fi
  if [[ "${DRY_RUN}" == "1" ]]; then
    log "[dry-run] write BACKUP_MANIFEST.txt"
    return 0
  fi
  cat >"${DEST}/BACKUP_MANIFEST.txt" <<EOF
backup_utc=${UTC_ISO}
backup_folder=${STAMP}
repo_root=${REPO_ROOT}
git_head=${git_sha}
timescale_tables=${TIMESCALE_TABLES[*]}
retention_gfs=daily:${DAILY_KEEP},weekly:${WEEKLY_KEEP},monthly:${MONTHLY_KEEP}
EOF
  log "OK BACKUP_MANIFEST.txt"
}

write_checksums() {
  if [[ "${DRY_RUN}" == "1" ]]; then
    log "[dry-run] write checksums.sha256"
    return 0
  fi
  if command -v sha256sum >/dev/null 2>&1; then
    (cd "${DEST}" && find . -type f ! -name checksums.sha256 -print0 | sort -z | xargs -0 sha256sum) \
      >"${DEST}/checksums.sha256" || true
  elif command -v shasum >/dev/null 2>&1; then
    (cd "${DEST}" && find . -type f ! -name checksums.sha256 -print0 | sort -z | xargs -0 shasum -a 256) \
      >"${DEST}/checksums.sha256" || true
  fi
  log "OK checksums.sha256"
}

# GFS retention: keep newest 7 + 4 weekly + 3 monthly anchors (Python for portability)
apply_gfs_retention() {
  local parent="${REPO_ROOT}/${BACKUP_ROOT}"
  [[ -d "${parent}" ]] || return 0
  if [[ "${DRY_RUN}" == "1" ]]; then
    log "[dry-run] GFS retention daily=${DAILY_KEEP} weekly=${WEEKLY_KEEP} monthly=${MONTHLY_KEEP}"
    return 0
  fi
  command -v python3 >/dev/null 2>&1 || {
    warn "python3 missing — skipping GFS retention"
    return 0
  }
  python3 - "${parent}" "${DAILY_KEEP}" "${WEEKLY_KEEP}" "${MONTHLY_KEEP}" <<'PY'
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

parent = Path(sys.argv[1])
daily_keep = int(sys.argv[2])
weekly_keep = int(sys.argv[3])
monthly_keep = int(sys.argv[4])
pat = re.compile(r"^\d{8}-\d{6}$")

dirs = sorted([p.name for p in parent.iterdir() if p.is_dir() and pat.match(p.name)])
if not dirs:
    sys.exit(0)

protect: set[str] = set()
protect.update(dirs[-daily_keep:])

week_map: dict[str, str] = {}
for name in dirs:
    dt = datetime.strptime(name[:8], "%Y%m%d")
    key = f"{dt.isocalendar().year}-W{dt.isocalendar().week:02d}"
    week_map[key] = name
for key in sorted(week_map)[-weekly_keep:]:
    protect.add(week_map[key])

month_map: dict[str, str] = {}
for name in dirs:
    month_map[name[:6]] = name
for key in sorted(month_map)[-monthly_keep:]:
    protect.add(month_map[key])

for name in dirs:
    if name not in protect:
        print(f"[backup] prune {name}", flush=True)
        shutil.rmtree(parent / name, ignore_errors=True)
PY
}

main() {
  log "dest=${DEST} dry_run=${DRY_RUN}"
  if [[ "${DRY_RUN}" == "0" ]]; then
    mkdir -p "${DEST}"
  fi

  backup_timescale
  backup_vault
  backup_redis
  backup_data_tree
  write_manifest
  write_checksums

  if [[ "${SKIP_RETENTION}" == "0" ]]; then
    apply_gfs_retention
  fi

  log "done."
}

main "$@"
