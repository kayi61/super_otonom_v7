#!/bin/sh
# vault-unseal sidecar - YEREL GELISTIRME auto-unseal.
#
# UYARI (uretim): bu yaklasim unseal anahtarini diskte (vault_init.json) tutar.
# Uretimde cloud KMS / Vault transit auto-unseal kullanin; init dosyasini
# konteynere mount ETMEYIN. Bu sidecar yalnizca yerel/dev icindir.
#
# ASCII-only + LF (.gitattributes ile zorlanir) -- PowerShell/sh parse bug'lari onlenir.
# CR-safe: tr -d '\n\r ' ile CRLF init dosyalari da calisir.
# Not: yalnizca tek-share (unseal_threshold=1) icin. Coklu share gerekiyorsa
# birden fazla anahtar gonderilmeli (bu dev kurulumu icin threshold=1).
set -e
INIT="${VAULT_INIT_FILE:-/vault/init/vault_init.json}"
export VAULT_ADDR="${VAULT_ADDR:-http://vault:8200}"
INTERVAL="${VAULT_UNSEAL_INTERVAL:-15}"

echo "vault-unseal: watcher started (addr=$VAULT_ADDR interval=${INTERVAL}s)"
while true; do
  if [ -f "$INIT" ]; then
    SEALED=$(vault status -format=json 2>/dev/null | tr -d '\n\r ' | sed -n 's/.*"sealed":\([a-z]*\).*/\1/p')
    if [ "$SEALED" = "true" ]; then
      KEY=$(tr -d '\n\r ' < "$INIT" | sed -n 's/.*"unseal_keys_b64":\["\([^"]*\)".*/\1/p')
      if [ -n "$KEY" ]; then
        if vault operator unseal "$KEY" >/dev/null 2>&1; then
          echo "vault-unseal: unsealed ($(date -u +%H:%M:%SZ))"
        else
          echo "vault-unseal: unseal attempt failed (retry in ${INTERVAL}s)"
        fi
      else
        echo "vault-unseal: WARN unseal_keys_b64 not found in $INIT"
      fi
    fi
  fi
  sleep "$INTERVAL"
done
