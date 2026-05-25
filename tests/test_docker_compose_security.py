"""PROMPT-01: Vault non-root, cap_drop, vault-init, nginx rate limit, TLS dokümantasyonu."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"
NGINX = ROOT / "docker" / "nginx" / "nginx.conf"
README = ROOT / "README.md"
TLS_OVERLAY = ROOT / "docker-compose.tls.yml"


def _compose_text() -> str:
    return COMPOSE.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", [COMPOSE, NGINX, ROOT / "docker" / "vault-entrypoint.sh"])
def test_prompt01_files_exist(path: Path) -> None:
    assert path.is_file(), f"missing: {path}"


def test_vault_runs_non_root() -> None:
    text = _compose_text()
    assert 'user: "0:0"' not in text.split("vault:")[-1] or "vault-init" in text
    vault_block = re.search(r"^\s{2}vault:\n(.*?)(?=^\s{2}\w|\Z)", text, re.M | re.S)
    assert vault_block, "vault service block missing"
    block = vault_block.group(1)
    assert 'user: "100:100"' in block
    assert "cap_drop:" in block and "ALL" in block
    assert "IPC_LOCK" in block
    assert "chmod -R 777" not in text


def test_vault_init_service() -> None:
    text = _compose_text()
    assert "vault-init:" in text
    init = re.search(r"^\s{2}vault-init:\n(.*?)(?=^\s{2}\w|\Z)", text, re.M | re.S)
    assert init
    assert 'user: "0:0"' in init.group(1)
    assert "chown -R 100:100" in text


def test_vault_depends_on_init() -> None:
    text = _compose_text()
    vault_block = re.search(r"^\s{2}vault:\n(.*?)(?=^\s{2}\w|\Z)", text, re.M | re.S)
    assert vault_block
    assert "vault-init:" in vault_block.group(1)
    assert "service_completed_successfully" in vault_block.group(1)


def test_nginx_rate_limiting() -> None:
    conf = NGINX.read_text(encoding="utf-8")
    assert "limit_req_zone" in conf
    assert "limit_req zone=bot_general" in conf
    assert "limit_req zone=grafana_ui" in conf


def test_tls_production_documented() -> None:
    readme = README.read_text(encoding="utf-8")
    tls = TLS_OVERLAY.read_text(encoding="utf-8")
    assert "TLS" in readme and "zorunlu" in readme.lower()
    assert "ZORUNLU" in tls or "zorunlu" in tls.lower()


def test_docker_compose_config_quiet() -> None:
    try:
        subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE), "config", "--quiet"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        pytest.skip("docker CLI not installed")
    except subprocess.CalledProcessError as exc:
        pytest.fail(f"docker compose config failed:\n{exc.stderr or exc.stdout}")
