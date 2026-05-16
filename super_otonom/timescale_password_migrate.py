"""
Timescale/Postgres parolasini .env ile volume icindeki kullaniciya esitle.

  python -m super_otonom.timescale_password_migrate
  python -m super_otonom.timescale_password_migrate --reset-volume  # dev: veri siler

Volume ilk kurulumda farkli parolayla olusturulduysa POSTGRES_PASSWORD env sonradan etkisizdir;
bu script ALTER USER ile gunceller ve ag (scram) uzerinden dogrular.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
COMPOSE = ROOT / "docker-compose.yml"
CONTAINER = "super_otonom_timescaledb"


def _env_val(key: str) -> str:
    if not ENV_FILE.is_file():
        raise RuntimeError(f"{ENV_FILE} yok")
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        m = re.match(rf"^\s*{re.escape(key)}=(.*)$", line)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    raise RuntimeError(f".env icinde {key} yok")


def _run(cmd: list[str], *, check: bool = True) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "").strip())
    return (p.stdout or "").strip()


def _local_psql(user: str, db: str, sql: str) -> str:
    return _run(
        [
            "docker",
            "exec",
            CONTAINER,
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            user,
            "-d",
            db,
            "-c",
            sql,
        ]
    )


def _net_psql(host: str, user: str, db: str, password: str) -> bool:
    p = subprocess.run(
        [
            "docker",
            "exec",
            "-e",
            f"PGPASSWORD={password}",
            CONTAINER,
            "psql",
            "-h",
            host,
            "-U",
            user,
            "-d",
            db,
            "-c",
            "SELECT 1;",
        ],
        capture_output=True,
        text=True,
    )
    return p.returncode == 0


def migrate_password() -> None:
    user = _env_val("POSTGRES_USER") or "superotonom"
    db = _env_val("POSTGRES_DB") or "trading"
    new_pw = _env_val("POSTGRES_PASSWORD")
    if not new_pw:
        raise RuntimeError("POSTGRES_PASSWORD bos")

  # trust (local socket) ile baglan — volume icindeki gercek kullanici
    safe = new_pw.replace("'", "''")
    print(f"timescale_migrate: ALTER USER {user} ...")
    _local_psql(user, db, f"ALTER USER {user} WITH PASSWORD '{safe}';")

    if not _net_psql("timescaledb", user, db, new_pw):
        raise RuntimeError("Ag uzerinden yeni parola ile baglanti basarisiz")
    print("timescale_migrate: ag (scram) dogrulama OK — .env ile volume uyumlu.")


def reset_volume() -> None:
    print("timescale_migrate: volume reset (dev — tum DB verisi silinir)...")
    _run(["docker", "compose", "-f", str(COMPOSE), "stop", "timescaledb", "bot", "grafana"], check=False)
    _run(["docker", "compose", "-f", str(COMPOSE), "rm", "-sf", "timescaledb"], check=False)
    out = _run(["docker", "volume", "ls", "--format", "{{.Name}}"], check=False)
    for name in out.splitlines():
        if "timescale_data" in name:
            _run(["docker", "volume", "rm", name, "-f"], check=False)
    _run(["docker", "compose", "-f", str(COMPOSE), "up", "-d", "timescaledb"])
    print("timescale_migrate: timescaledb yeniden baslatildi (.env parolasi ile init).")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset-volume", action="store_true", help="Dev: volume sil ve sifirdan kur")
    args = ap.parse_args()
    try:
        if args.reset_volume:
            reset_volume()
        else:
            migrate_password()
        return 0
    except Exception as exc:
        print(f"timescale_migrate: HATA — {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
