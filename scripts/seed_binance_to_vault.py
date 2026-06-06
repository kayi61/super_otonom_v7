"""Binance API anahtarini DOGRUDAN Vault'a yazar — .env'e hic degmeden.

Anahtar gizli girilir (getpass): ekranda gorunmez, shell gecmisine dusmez,
disk uzerinde duz metin .env dosyasi olusmaz.

Kullanim (proje kokunden):
    python scripts/seed_binance_to_vault.py
    python scripts/seed_binance_to_vault.py --exchange bybit
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_INIT = _REPO / "data" / "local" / "vault_init.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exchange", default="binance", help="borsa anahtari (varsayilan: binance)")
    ap.add_argument("--addr", default="http://127.0.0.1:8200", help="VAULT_ADDR")
    ap.add_argument(
        "--from-env",
        action="store_true",
        help="anahtarlari SEED_API_KEY / SEED_API_SECRET env'den oku (getpass paste sorunu varsa)",
    )
    args = ap.parse_args()

    # Vault token — once env, yoksa vault_init.json'dan (root_token)
    token = os.getenv("VAULT_TOKEN", "").strip()
    if not token and _INIT.is_file():
        try:
            token = (json.loads(_INIT.read_text(encoding="utf-8")) or {}).get("root_token", "")
        except (OSError, ValueError):
            token = ""
    if not token:
        print(
            "HATA: Vault token yok. VAULT_TOKEN ayarlayin veya data/local/vault_init.json olsun.",
            file=sys.stderr,
        )
        return 1

    os.environ["VAULT_ADDR"] = args.addr
    os.environ["VAULT_TOKEN"] = token

    from super_otonom.infra.vault_bridge import VaultBridge

    vb = VaultBridge()
    if not vb.status().get("available"):
        print(
            f"HATA: Vault erisilemiyor ({args.addr}). 'docker compose up -d vault' + unseal.",
            file=sys.stderr,
        )
        return 1

    if args.from_env:
        api_key = os.getenv("SEED_API_KEY", "").strip()
        api_secret = os.getenv("SEED_API_SECRET", "").strip()
        print(f"Vault OK. {args.exchange} anahtarlari SEED_API_KEY/SEED_API_SECRET env'den okundu.")
    else:
        print(f"Vault OK. {args.exchange} anahtarlarini girin (giris GIZLI — ekranda gorunmez):")
        api_key = getpass.getpass("  api_key   : ").strip()
        api_secret = getpass.getpass("  api_secret: ").strip()
    if not api_key or not api_secret:
        print(
            "HATA: api_key/api_secret bos olamaz."
            + (" SEED_API_KEY/SEED_API_SECRET ayarli mi?" if args.from_env else ""),
            file=sys.stderr,
        )
        return 1

    # KOK SEBEP korumasi: getpass bazi terminallerde (Windows PowerShell paste)
    # yapistirmayi tam yakalayamaz; sadece 1-2 karakter okunup gecersiz anahtar
    # Vault'a yazilir -> borsa /account 400 verir, sebep gizli kalir. Erken yakala.
    # Gercek borsa anahtarlari uzundur (Binance ~64 karakter).
    _MIN_KEY_LEN = 16
    if len(api_key) < _MIN_KEY_LEN or len(api_secret) < _MIN_KEY_LEN:
        print(
            f"HATA: anahtar COK KISA (api_key={len(api_key)} char, "
            f"api_secret={len(api_secret)} char). Gercek borsa anahtarlari ~64 karakter.\n"
            "  -> Yapistirma tam olmadi (getpass paste sorunu). Tekrar calistirin;\n"
            "     PowerShell'de sag-tik ile yapistirip TEK Enter'a basin.\n"
            "  -> Alternatif: $env:SEED_API_KEY / $env:SEED_API_SECRET ile --from-env.",
            file=sys.stderr,
        )
        return 1

    try:
        vb.enable_kv_engine()
    except Exception:
        pass  # zaten aktifse sorun degil

    ok = vb.put_secret(args.exchange, {"api_key": api_key, "api_secret": api_secret})
    if not ok:
        print("HATA: Vault'a yazilamadi.", file=sys.stderr)
        return 1

    probe = vb.probe_kv_fields(args.exchange, ("api_key", "api_secret"))
    print(f"YAZILDI -> Vault KV {args.exchange}: api_key={probe.get('api_key')} api_secret={probe.get('api_secret')}")
    print("Anahtar .env'e veya shell gecmisine YAZILMADI. Canli icin: SECRETS_VAULT_ONLY=true")
    return 0 if all(probe.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
