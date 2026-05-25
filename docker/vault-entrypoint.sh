#!/bin/sh
# Vault ana süreç — non-root (UID/GID 100). Dizin izinleri vault-init ile hazırlanır.
set -e
exec vault server -config=/vault/config/vault.hcl
