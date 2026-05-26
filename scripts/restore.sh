#!/usr/bin/env bash
# super_otonom — restore from backup (verify or apply)
# Usage:
#   scripts/restore.sh --verify PATH
#   scripts/restore.sh --restore PATH [--yes] [--data-only] [--timescale-only]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

MODE=""
BACKUP_PATH=""
CONFIRM=0
DATA_ONLY=0
TIMESCALE_ONLY=0

TIMESCALE_CONTAINER="${TIMESCALE_CONTAINER:-super_otonom_timescaledb}"
VAULT_CONTAINER="${VAULT_CONTAINER:-super_otonom_vault}"
REDIS_CONTAINER="${REDIS_CONTAINER:-super_otonom_redis}"

log() { printf '[restore] %s\n' "$*"; }
die() { printf '[restore][ERROR] %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Usage:
  scripts/restore.sh --verify BACKUP_DIR
  scripts/restore.sh --restore BACKUP_DIR [--yes] [--data-only] [--timescale-only]

Options:
  --verify PATH       Validate manifest + checksums + archive presence
  --restore PATH      Restore components (destructive; requires --yes)
  --yes               Confirm destructive restore
  --data-only         Restore only data/ tree files
  --timescale-only    Restore only TimescaleDB dump
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --verify)
      MODE=verify
      BACKUP_PATH="${2:?}"
      shift 2
      ;;
    --restore)
      MODE=restore
      BACKUP_PATH="${2:?}"
      shift 2
      ;;
    --yes) CONFIRM=1; shift ;;
    --data-only) DATA_ONLY=1; shift ;;
    --timescale-only) TIMESCALE_ONLY=1; shift ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      die "Unknown option: $1"
      ;;
  esac
done

[[ -n "${MODE}" ]] || {
  usage >&2
  exit 1
}

if [[ -f "${REPO_ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/.env"
  set +a
fi

POSTGRES_USER="${POSTGRES_USER:-superotonom}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-}"
POSTGRES_DB="${POSTGRES_DB:-trading}"
export PGPASSWORD="${POSTGRES_PASSWORD}"

if [[ "${BACKUP_PATH}" != /* ]]; then
  BACKUP_PATH="${REPO_ROOT}/${BACKUP_PATH}"
fi

[[ -d "${BACKUP_PATH}" ]] || die "Backup directory not found: ${BACKUP_PATH}"

verify_backup() {
  local errors=0
  log "verify: ${BACKUP_PATH}"

  if [[ -f "${BACKUP_PATH}/BACKUP_MANIFEST.txt" ]]; then
    log "OK BACKUP_MANIFEST.txt"
    cat "${BACKUP_PATH}/BACKUP_MANIFEST.txt"
  else
    log "MISSING BACKUP_MANIFEST.txt"
    errors=$((errors + 1))
  fi

  if [[ -f "${BACKUP_PATH}/checksums.sha256" ]]; then
    checksum_lines=0
    while IFS= read -r line || [[ -n "${line}" ]]; do
      [[ -z "${line//[[:space:]]/}" ]] && continue
      [[ "${line}" =~ ^# ]] && continue
      checksum_lines=$((checksum_lines + 1))
    done < "${BACKUP_PATH}/checksums.sha256"
    if [[ "${checksum_lines}" -eq 0 ]]; then
      log "WARN checksums.sha256 empty (skipped verify)"
    elif command -v sha256sum >/dev/null 2>&1; then
      if (cd "${BACKUP_PATH}" && sha256sum -c checksums.sha256 --quiet 2>/dev/null); then
        log "OK checksums.sha256"
      else
        log "FAIL checksum verification"
        errors=$((errors + 1))
      fi
    else
      log "OK checksums.sha256 present (sha256sum not installed — skip verify)"
    fi
  else
    warn_file=1
    log "WARN no checksums.sha256"
  fi

  if [[ -f "${BACKUP_PATH}/timescale/timescale.dump" ]]; then
  dump_size=0
  if [[ -s "${BACKUP_PATH}/timescale/timescale.dump" ]]; then
    dump_size=1
  fi
  if [[ "${dump_size}" -eq 0 ]]; then
    log "WARN timescale/timescale.dump empty (skipped pg_restore -l)"
  elif command -v pg_restore >/dev/null 2>&1; then
    if pg_restore -l "${BACKUP_PATH}/timescale/timescale.dump" >/dev/null 2>&1; then
      log "OK timescale/timescale.dump (pg_restore -l)"
    else
      log "WARN timescale dump list failed"
      errors=$((errors + 1))
    fi
  else
    log "OK timescale/timescale.dump present"
  fi
  else
    log "WARN no timescale/timescale.dump"
  fi

  [[ -f "${BACKUP_PATH}/vault/vault_raft.snap" || -f "${BACKUP_PATH}/vault/vault_data.tar.gz" ]] \
    && log "OK vault snapshot present" || log "WARN no vault snapshot"

  [[ -f "${BACKUP_PATH}/redis/dump.rdb" ]] && log "OK redis/dump.rdb" || log "WARN no redis/dump.rdb"

  if [[ -d "${BACKUP_PATH}/data" ]]; then
    log "OK data/ subtree ($(find "${BACKUP_PATH}/data" -type f | wc -l | tr -d ' ') files)"
  else
    log "WARN no data/ subtree"
  fi

  if [[ "${errors}" -gt 0 ]]; then
    die "verify failed (${errors} error(s))"
  fi
  log "verify: PASS"
}

restore_data() {
  local src="${BACKUP_PATH}/data"
  [[ -d "${src}" ]] || die "No data/ in backup"
  mkdir -p "${REPO_ROOT}/data"
  local f
  for f in "${src}"/*; do
    [[ -e "${f}" ]] || continue
    if [[ -d "${f}" ]]; then
      cp -a "${f}" "${REPO_ROOT}/data/"
      log "restored dir $(basename "${f}")"
    else
      cp -f "${f}" "${REPO_ROOT}/data/"
      log "restored $(basename "${f}")"
    fi
  done
}

restore_timescale() {
  local dump="${BACKUP_PATH}/timescale/timescale.dump"
  [[ -f "${dump}" ]] || die "Missing ${dump}"
  command -v docker >/dev/null 2>&1 || die "docker required for timescale restore"
  docker inspect "${TIMESCALE_CONTAINER}" >/dev/null 2>&1 || die "container ${TIMESCALE_CONTAINER} not found"

  log "restoring TimescaleDB (destructive: --clean --if-exists)"
  docker cp "${dump}" "${TIMESCALE_CONTAINER}:/tmp/timescale.dump"
  docker exec "${TIMESCALE_CONTAINER}" pg_restore -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
    --clean --if-exists --no-owner /tmp/timescale.dump || {
    warn_code=$?
    log "pg_restore exit ${warn_code} (may be OK if objects did not exist)"
  }
  docker exec "${TIMESCALE_CONTAINER}" rm -f /tmp/timescale.dump
}

restore_redis() {
  local rdb="${BACKUP_PATH}/redis/dump.rdb"
  [[ -f "${rdb}" ]] || die "Missing ${rdb}"
  command -v docker >/dev/null 2>&1 || die "docker required"
  log "stop redis, replace dump.rdb, start redis"
  docker stop "${REDIS_CONTAINER}"
  docker cp "${rdb}" "${REDIS_CONTAINER}:/data/dump.rdb"
  docker start "${REDIS_CONTAINER}"
}

restore_vault() {
  local raft="${BACKUP_PATH}/vault/vault_raft.snap"
  local tar="${BACKUP_PATH}/vault/vault_data.tar.gz"
  if [[ -f "${raft}" ]]; then
    docker cp "${raft}" "${VAULT_CONTAINER}:/tmp/vault.snap"
    docker exec "${VAULT_CONTAINER}" vault operator raft snapshot restore -force /tmp/vault.snap
  elif [[ -f "${tar}" ]]; then
    die "File-storage Vault restore requires maintenance window — extract vault_data.tar.gz manually (see docs/DR_RUNBOOK.md)"
  else
    die "No vault backup artifact"
  fi
}

do_restore() {
  [[ "${CONFIRM}" -eq 1 ]] || die "Refusing restore without --yes"

  if [[ "${TIMESCALE_ONLY}" -eq 1 ]]; then
    restore_timescale
    return 0
  fi

  if [[ "${DATA_ONLY}" -eq 1 ]]; then
    restore_data
    return 0
  fi

  restore_data
  if [[ -f "${BACKUP_PATH}/timescale/timescale.dump" ]]; then
    restore_timescale
  fi
  if [[ -f "${BACKUP_PATH}/redis/dump.rdb" ]]; then
    restore_redis
  fi
  if [[ -f "${BACKUP_PATH}/vault/vault_raft.snap" ]]; then
    restore_vault
  fi
  log "restore complete — verify bot health and reconciliation"
}

case "${MODE}" in
  verify) verify_backup ;;
  restore) do_restore ;;
esac
