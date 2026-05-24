"""Docker Vault: init, AppRole, .env patch. Kullanim: python -m super_otonom.infra.vault_bootstrap_docker [--reset]"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"
INIT_FILE = ROOT / "data" / "local" / "vault_init.json"
ENV_FILE = ROOT / ".env"
CONTAINER = "super_otonom_vault"
MOUNT = "secret"
BASE_PATH = "trading"


def _run(cmd: list[str], *, check: bool = True, env: dict | None = None) -> str:
    import os

    e = os.environ.copy()
    if env:
        e.update(env)
    p = subprocess.run(cmd, capture_output=True, text=True, env=e)
    if check and p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "").strip() or f"exit {p.returncode}")
    return (p.stdout or "").strip()


def docker_vault(args: list[str], token: str = "", *, allow_fail: bool = False) -> str:
    cmd = ["docker", "exec", "-e", "VAULT_ADDR=http://127.0.0.1:8200"]
    if token:
        cmd += ["-e", f"VAULT_TOKEN={token}"]
    cmd += [CONTAINER, "vault", *args]
    return _run(cmd, check=not allow_fail)


def vault_status() -> dict:
    cmd = ["docker", "exec", "-e", "VAULT_ADDR=http://127.0.0.1:8200", CONTAINER, "vault", "status", "-format=json"]
    p = subprocess.run(cmd, capture_output=True, text=True)
    raw = (p.stdout or "").strip()
    if not raw:
        raise RuntimeError((p.stderr or "").strip() or "vault status bos")
    return json.loads(raw)


def reset_vault() -> None:
    print("vault_bootstrap: volume reset...")
    _run(["docker", "compose", "-f", str(COMPOSE), "rm", "-sf", "vault"], check=False)
    out = _run(["docker", "volume", "ls", "--format", "{{.Name}}"], check=False)
    for name in out.splitlines():
        if "vault_data" in name:
            _run(["docker", "volume", "rm", name, "-f"], check=False)
    _run(["docker", "compose", "-f", str(COMPOSE), "up", "-d", "vault"])
    for _ in range(30):
        time.sleep(2)
        try:
            st = vault_status()
            if st.get("initialized") is not None:
                break
        except Exception:
            pass
    else:
        raise RuntimeError("Vault container hazir degil")
    if INIT_FILE.is_file():
        INIT_FILE.unlink()


def ensure_init() -> str:
    st = vault_status()
    if not st.get("initialized"):
        print("vault_bootstrap: init...")
        raw = docker_vault(["operator", "init", "-key-shares=1", "-key-threshold=1", "-format=json"])
        data = json.loads(raw)
        INIT_FILE.parent.mkdir(parents=True, exist_ok=True)
        INIT_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        token = data["root_token"]
        docker_vault(["operator", "unseal", data["unseal_keys_b64"][0]])
        return token
    if st.get("sealed"):
        if not INIT_FILE.is_file():
            raise RuntimeError("Vault sealed; vault_init.json yok. --reset kullanin.")
        data = json.loads(INIT_FILE.read_text(encoding="utf-8"))
        token = data["root_token"]
        docker_vault(["operator", "unseal", data["unseal_keys_b64"][0]])
        return token
    if INIT_FILE.is_file():
        return json.loads(INIT_FILE.read_text(encoding="utf-8"))["root_token"]
    raise RuntimeError("Vault initialized ama vault_init.json yok. --reset kullanin.")


def setup_approle(token: str) -> tuple[str, str]:
    try:
        docker_vault(["secrets", "enable", "-path", MOUNT, "-version=2"], token=token)
    except RuntimeError:
        pass
    policy = f'''path "{MOUNT}/data/{BASE_PATH}/*" {{
  capabilities = ["create", "read", "update", "delete", "list"]
}}
path "{MOUNT}/metadata/{BASE_PATH}/*" {{
  capabilities = ["list", "read"]
}}
'''
    subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "sh", "-c", "cat > /tmp/bot-policy.hcl"],
        input=policy,
        text=True,
        check=True,
    )
    docker_vault(["policy", "write", "super_otonom_bot", "/tmp/bot-policy.hcl"], token=token)
    try:
        docker_vault(["auth", "enable", "approle"], token=token)
    except RuntimeError:
        pass
    docker_vault(
        [
            "write",
            "auth/approle/role/super_otonom_bot",
            "token_policies=super_otonom_bot",
            "token_ttl=1h",
            "token_max_ttl=4h",
        ],
        token=token,
    )
    role_id = docker_vault(
        ["read", "-field=role_id", "auth/approle/role/super_otonom_bot/role-id"], token=token
    )
    secret_id = docker_vault(
        ["write", "-f", "-field=secret_id", "auth/approle/role/super_otonom_bot/secret-id"],
        token=token,
    )
    return role_id.strip(), secret_id.strip()


def patch_env(role_id: str, secret_id: str) -> None:
    if not ENV_FILE.is_file():
        return
    mapping = {
        "VAULT_ADDR": "http://vault:8200",
        "VAULT_ROLE_ID": role_id,
        "VAULT_SECRET_ID": secret_id,
        "VAULT_MOUNT": MOUNT,
        "VAULT_BASE_PATH": BASE_PATH,
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
    for key, val in mapping.items():
        if key not in seen:
            lines_out.append(f"{key}={val}")
    ENV_FILE.write_text("\n".join(lines_out) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="Vault volume sifirla (dev)")
    args = ap.parse_args()
    try:
        if args.reset:
            reset_vault()
        else:
            st = vault_status()
            if st.get("initialized") and not INIT_FILE.is_file():
                print("vault_bootstrap: init dosyasi yok, --reset ile sifirlaniyor...")
                reset_vault()
        token = ensure_init()
        role_id, secret_id = setup_approle(token)
        patch_env(role_id, secret_id)
        print("vault_bootstrap: OK (AppRole -> .env)")
        print("vault_bootstrap: sonraki: python -m super_otonom.infra.vault_rotate --full")
        return 0
    except Exception as exc:
        print(f"vault_bootstrap: HATA — {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
