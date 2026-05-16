"""Tek seferlik: .env'deki API anahtarlarını Vault'a yükle. Sonra .env'den anahtar satırlarını silin."""

from __future__ import annotations

import sys

from super_otonom.vault_bridge import VaultBridge


def main() -> int:
    vb = VaultBridge()
    st = vb.status()
    if not st.get("available"):
        print(
            "vault_seed: Vault erişilemiyor. VAULT_ADDR + VAULT_TOKEN veya AppRole ayarlayın.",
            file=sys.stderr,
        )
        return 1
    vb.enable_kv_engine()
    n = vb.seed_from_env()
    print(f"vault_seed: {n} exchange yolu yazıldı (secret/data/trading/*).")
    if n:
        print(
            "vault_seed: .env içindeki BINANCE_* / BYBIT_* vb. satırları kaldırın; "
            "üretimde SECRETS_VAULT_ONLY=true ve yalnızca VAULT_ROLE_ID + VAULT_SECRET_ID."
        )
    return 0 if n else 1


if __name__ == "__main__":
    raise SystemExit(main())
