"""
Vault token/AppRole rotasyonu; root yerine sinirli admin token.

  python -m super_otonom.infra.vault_rotate --full
  python -m super_otonom.infra.vault_rotate --approle

Admin token: data/local/vault_admin_token.json (gitignore)
Unseal:      data/local/vault_init.json (root_token kaldirilir / revoke)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
INIT_FILE = ROOT / "data" / "local" / "vault_init.json"
ADMIN_FILE = ROOT / "data" / "local" / "vault_admin_token.json"
ENV_FILE = ROOT / ".env"
CONTAINER = "super_otonom_vault"
MOUNT = "secret"
BASE_PATH = "trading"
ADMIN_POLICY = "super_otonom_admin"
ADMIN_TTL = "768h"


def _run(cmd: list[str], *, check: bool = True) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "").strip() or f"exit {p.returncode}")
    return (p.stdout or "").strip()


def docker_vault(args: list[str], token: str) -> str:
    cmd = ["docker", "exec", "-e", "VAULT_ADDR=http://127.0.0.1:8200", "-e", f"VAULT_TOKEN={token}", CONTAINER, "vault", *args]
    return _run(cmd)


def load_root_token() -> str:
    if not INIT_FILE.is_file():
        raise RuntimeError(f"{INIT_FILE} yok — once bootstrap calistirin.")
    data = json.loads(INIT_FILE.read_text(encoding="utf-8"))
    rt = (data.get("root_token") or "").strip()
    if not rt:
        raise RuntimeError("root_token yok (zaten revoke edilmis olabilir); admin token kullanin.")
    return rt


def load_admin_token() -> str:
    if not ADMIN_FILE.is_file():
        raise RuntimeError(f"{ADMIN_FILE} yok — once: python -m super_otonom.infra.vault_rotate --full")
    return json.loads(ADMIN_FILE.read_text(encoding="utf-8"))["client_token"].strip()


def bootstrap_token() -> str:
    if ADMIN_FILE.is_file():
        return load_admin_token()
    return load_root_token()


def unseal_if_needed() -> None:
    st_raw = _run(
        ["docker", "exec", "-e", "VAULT_ADDR=http://127.0.0.1:8200", CONTAINER, "vault", "status", "-format=json"],
        check=False,
    )
    st = json.loads(st_raw) if st_raw else {}
    if st.get("sealed") and INIT_FILE.is_file():
        data = json.loads(INIT_FILE.read_text(encoding="utf-8"))
        _run(
            [
                "docker",
                "exec",
                "-e",
                "VAULT_ADDR=http://127.0.0.1:8200",
                CONTAINER,
                "vault",
                "operator",
                "unseal",
                data["unseal_keys_b64"][0],
            ]
        )


def write_admin_policy(token: str) -> None:
    policy = f'''# Sinirli admin — root yerine (KV + AppRole secret rotate)
path "{MOUNT}/data/{BASE_PATH}/*" {{
  capabilities = ["create", "read", "update", "delete", "list"]
}}
path "{MOUNT}/metadata/{BASE_PATH}/*" {{
  capabilities = ["list", "read"]
}}
path "auth/approle/role/super_otonom_bot/secret-id" {{
  capabilities = ["create", "update"]
}}
path "auth/approle/role/super_otonom_bot/role-id" {{
  capabilities = ["read"]
}}
path "sys/health" {{
  capabilities = ["read"]
}}
path "auth/token/renew-self" {{
  capabilities = ["update"]
}}
path "auth/token/revoke" {{
  capabilities = ["update"]
}}
path "auth/token/revoke-accessor" {{
  capabilities = ["update"]
}}
'''
    subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "sh", "-c", "cat > /tmp/admin-policy.hcl"],
        input=policy,
        text=True,
        check=True,
    )
    docker_vault(["policy", "write", ADMIN_POLICY, "/tmp/admin-policy.hcl"], token)


def create_admin_token(root_or_admin: str) -> dict[str, Any]:
    write_admin_policy(root_or_admin)
    raw = docker_vault(
        ["token", "create", f"-policy={ADMIN_POLICY}", f"-ttl={ADMIN_TTL}", "-renewable=true", "-format=json"],
        root_or_admin,
    )
    data = json.loads(raw)
    auth = data.get("auth") or data
    out = {
        "client_token": auth.get("client_token", ""),
        "accessor": auth.get("accessor", ""),
        "lease_duration": auth.get("lease_duration"),
        "created_at": int(time.time()),
        "policy": ADMIN_POLICY,
    }
    if not out["client_token"]:
        raise RuntimeError("admin token olusturulamadi")
    ADMIN_FILE.parent.mkdir(parents=True, exist_ok=True)
    ADMIN_FILE.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def revoke_root_token(root: str) -> None:
    docker_vault(["token", "revoke", root], root)
    data = json.loads(INIT_FILE.read_text(encoding="utf-8"))
    data.pop("root_token", None)
    data["root_revoked_at"] = int(time.time())
    INIT_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def rotate_approle_secret(admin_token: str) -> tuple[str, str]:
    role_id = docker_vault(["read", "-field=role_id", "auth/approle/role/super_otonom_bot/role-id"], admin_token).strip()
    secret_id = docker_vault(
        ["write", "-f", "-field=secret_id", "auth/approle/role/super_otonom_bot/secret-id"],
        admin_token,
    ).strip()
    patch_env(role_id, secret_id)
    meta = {}
    if ADMIN_FILE.is_file():
        meta = json.loads(ADMIN_FILE.read_text(encoding="utf-8"))
    meta["approle_rotated_at"] = int(time.time())
    meta["role_id"] = role_id
    ADMIN_FILE.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return role_id, secret_id


def patch_env(role_id: str, secret_id: str) -> None:
    if not ENV_FILE.is_file():
        return
    mapping = {
        "VAULT_ROLE_ID": role_id,
        "VAULT_SECRET_ID": secret_id,
    }
    seen: set[str] = set()
    lines_out: list[str] = []
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)=", line)
        if m:
            key = m.group(1)
            if key == "VAULT_TOKEN":
                continue
            if key in mapping:
                if key in seen:
                    continue
                seen.add(key)
                lines_out.append(f"{key}={mapping[key]}")
                continue
        lines_out.append(line)
    ENV_FILE.write_text("\n".join(lines_out) + "\n", encoding="utf-8")


def renew_admin_token() -> None:
    token = load_admin_token()
    try:
        raw = docker_vault(["token", "renew", "-self", "-format=json"], token)
        data = json.loads(raw)
        auth = data.get("auth") or data
        meta = json.loads(ADMIN_FILE.read_text(encoding="utf-8"))
        meta["client_token"] = auth.get("client_token") or token
        meta["lease_duration"] = auth.get("lease_duration")
        meta["renewed_at"] = int(time.time())
        ADMIN_FILE.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    except RuntimeError:
        create_admin_token(token)


def full_rotation() -> None:
    unseal_if_needed()
    root = load_root_token()
    print("vault_rotate: sinirli admin token olusturuluyor...")
    create_admin_token(root)
    admin = load_admin_token()
    print("vault_rotate: AppRole secret_id yenileniyor...")
    rotate_approle_secret(admin)
    print("vault_rotate: root token revoke...")
    revoke_root_token(root)
    print("vault_rotate: TAMAM — root kaldirildi; admin -> vault_admin_token.json; UI/CLI icin admin token kullanin.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="Admin token + AppRole rotate + root revoke")
    ap.add_argument("--approle", action="store_true", help="Yalnizca AppRole secret_id rotate")
    ap.add_argument("--renew-admin", action="store_true", help="Admin token yenile")
    args = ap.parse_args()
    try:
        unseal_if_needed()
        if args.full:
            full_rotation()
        elif args.renew_admin:
            if ADMIN_FILE.is_file():
                renew_admin_token()
            else:
                root = load_root_token()
                create_admin_token(root)
                revoke_root_token(root)
            print("vault_rotate: admin token yenilendi.")
        elif args.approle:
            rotate_approle_secret(bootstrap_token())
            print("vault_rotate: AppRole secret_id guncellendi (.env).")
        else:
            ap.print_help()
            return 1
        return 0
    except Exception as exc:
        print(f"vault_rotate: HATA — {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
