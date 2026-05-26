#!/bin/sh
# Cron sidecar: daily backup via scripts/backup.sh (requires docker.sock)
set -eu

CRON_LINE="${BACKUP_CRON:-0 2 * * *} REPO_ROOT=${REPO_ROOT:-/app} BACKUP_ROOT=${BACKUP_ROOT:-/backup} /bin/bash /app/scripts/backup.sh >> /var/log/backup.log 2>&1"

mkdir -p /var/log
echo "${CRON_LINE}" > /etc/crontabs/root
chmod 0644 /etc/crontabs/root

echo "[backup-sidecar] cron: ${BACKUP_CRON:-0 2 * * *}"
echo "[backup-sidecar] BACKUP_ROOT=${BACKUP_ROOT} REPO_ROOT=${REPO_ROOT}"

# Optional immediate run on start (set BACKUP_RUN_ON_START=1)
if [ "${BACKUP_RUN_ON_START:-0}" = "1" ]; then
  /bin/bash /app/scripts/backup.sh || true
fi

exec crond -f -l 2
