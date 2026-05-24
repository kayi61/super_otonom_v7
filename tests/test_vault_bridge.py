from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

from super_otonom.infra.vault_bridge import VaultBridge, env_api_key_names, secrets_vault_only_mode


def test_secrets_vault_only_explicit():
    with patch.dict(os.environ, {"SECRETS_VAULT_ONLY": "true", "DRY_RUN": "true"}, clear=False):
        assert secrets_vault_only_mode() is True


def test_secrets_vault_only_auto_live():
    env = {
        "SECRETS_VAULT_ONLY": "",
        "SECRETS_VAULT_ONLY_AUTO": "true",
        "DRY_RUN": "false",
        "PAPER_MODE": "false",
    }
    with patch.dict(os.environ, env, clear=False):
        assert secrets_vault_only_mode() is True


def test_vault_only_skips_env(monkeypatch):
    monkeypatch.setenv("SECRETS_VAULT_ONLY", "true")
    monkeypatch.setenv("BINANCE_API_KEY", "from-env-should-not-appear")
    monkeypatch.setenv("VAULT_TOKEN", "test-token")

    health = {"initialized": True, "sealed": False}

    def fake_urlopen(req, timeout=5):
        url = req.full_url
        if url.endswith("/v1/sys/health"):
            return MagicMock(read=lambda: json.dumps(health).encode(), status=200, __enter__=lambda s: s, __exit__=lambda *a: None)
        if "/data/trading/binance" in url:
            body = {"data": {"data": {"api_key": "from-vault", "api_secret": "sec"}}}
            return MagicMock(
                read=lambda: json.dumps(body).encode(),
                status=200,
                __enter__=lambda s: s,
                __exit__=lambda *a: None,
            )
        raise AssertionError(url)

    with patch("urllib.request.urlopen", fake_urlopen):
        vb = VaultBridge(token="test-token")
        assert vb.status()["vault_only"] is True
        got = vb.get_all_secrets("binance")
        assert got.get("api_key") == "from-vault"
        assert got.get("api_secret") == "sec"


def test_approle_login_sets_token(monkeypatch):
    monkeypatch.delenv("VAULT_TOKEN", raising=False)
    monkeypatch.setenv("VAULT_ROLE_ID", "role-abc")
    monkeypatch.setenv("VAULT_SECRET_ID", "secret-xyz")
    monkeypatch.setenv("SECRETS_VAULT_ONLY", "false")

    login_body = {"auth": {"client_token": "s.xyz", "lease_duration": 3600}}
    health = {"initialized": True, "sealed": False}
    calls: list[str] = []

    def fake_urlopen(req, timeout=5):
        calls.append(req.full_url)
        if req.full_url.endswith("/v1/auth/approle/login"):
            return MagicMock(
                read=lambda: json.dumps(login_body).encode(),
                status=200,
                __enter__=lambda s: s,
                __exit__=lambda *a: None,
            )
        if req.full_url.endswith("/v1/sys/health"):
            return MagicMock(
                read=lambda: json.dumps(health).encode(),
                status=200,
                __enter__=lambda s: s,
                __exit__=lambda *a: None,
            )
        raise AssertionError(req.full_url)

    with patch("urllib.request.urlopen", fake_urlopen):
        vb = VaultBridge()
        assert vb.status()["available"] is True
        assert vb.status()["auth"] == "approle"
        assert any("approle/login" in u for u in calls)


def test_env_api_key_names_nonempty():
    assert "BINANCE_API_KEY" in env_api_key_names()
