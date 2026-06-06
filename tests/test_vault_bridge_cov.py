"""VaultBridge gercek kapsama testleri — urllib mock'lanir, ag YOK.

Coverage P-6 sonrasi dogal yukseltme: super_otonom/infra/vault_bridge.py (onceki %52).
Tum HTTP cagrilari sahte urlopen ile karsilanir; gercek Vault gerekmez.
"""
from __future__ import annotations

import json
import urllib.error
from unittest.mock import patch

import pytest
from super_otonom.infra.vault_bridge import (
    VaultBridge,
    env_api_key_names,
    resolve_vault_addr,
    secrets_vault_only_mode,
)

_ADDR = "http://127.0.0.1:8200"  # 'vault' degil -> resolve_vault_addr socket cagirmaz

_ENV_KEYS = (
    "VAULT_ADDR", "VAULT_ADDR_HOST", "VAULT_ADDR_FORCE", "VAULT_TOKEN",
    "VAULT_ROLE_ID", "VAULT_SECRET_ID", "SECRETS_VAULT_ONLY",
    "SECRETS_VAULT_ONLY_AUTO", "DRY_RUN", "PAPER_MODE",
    "BINANCE_API_KEY", "BINANCE_API_SECRET", "BINANCE_KEY",
    "BINANCE_SECRET_KEY", "BINANCE_SECRET",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in _ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    yield


# ── Sahte urlopen altyapisi ──────────────────────────────────────────────


class _Resp:
    def __init__(self, body, status=200):
        self._b = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.status = status

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _healthy_handler(url, method, req):
    if url.endswith("/sys/health"):
        return _Resp({"initialized": True, "sealed": False})
    if "/auth/approle/login" in url:
        return _Resp({"auth": {"client_token": "approle-tok", "lease_duration": 3600}})
    if "/auth/token/renew-self" in url:
        return _Resp({"auth": {"lease_duration": 3600}})
    if "/sys/mounts/" in url:  # enable_kv_engine
        return _Resp(b"", status=204)
    if "/data/" in url and method == "GET":
        if url.endswith("binance"):
            return _Resp({"data": {"data": {"api_key": "AK", "api_secret": "SK"}}})
        if url.endswith("missing"):
            raise urllib.error.HTTPError(url, 404, "not found", {}, None)
        return _Resp({"data": {"data": {}}})
    if "/data/" in url and method in ("POST", "PUT"):
        return _Resp(b"", status=204)
    if "/data/" in url and method == "DELETE":
        return _Resp(b"", status=204)
    return _Resp(b"{}")


def _patch_urlopen(handler):
    def _urlopen(req, timeout=None):
        url = req.full_url
        return handler(url, req.get_method(), req)
    return patch("urllib.request.urlopen", side_effect=_urlopen)


# ── Saf fonksiyonlar ──────────────────────────────────────────────────────


def test_resolve_vault_addr_host_override(monkeypatch):
    monkeypatch.setenv("VAULT_ADDR_HOST", "http://example:9999/")
    assert resolve_vault_addr() == "http://example:9999"


def test_resolve_vault_addr_force(monkeypatch):
    monkeypatch.setenv("VAULT_ADDR_FORCE", "true")
    assert resolve_vault_addr("http://vault:8200") == "http://vault:8200"


def test_resolve_vault_addr_non_vault_host():
    assert resolve_vault_addr("http://127.0.0.1:8200") == "http://127.0.0.1:8200"


def test_resolve_vault_addr_vault_host_unresolvable():
    # 'vault' cozumlenemez -> 127.0.0.1 fallback
    with patch("socket.getaddrinfo", side_effect=OSError("no dns")):
        assert resolve_vault_addr("http://vault:8200") == "http://127.0.0.1:8200"


def test_resolve_vault_addr_vault_host_resolvable():
    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("1.2.3.4", 8200))]):
        assert resolve_vault_addr("http://vault:8200") == "http://vault:8200"


def test_secrets_vault_only_explicit_on(monkeypatch):
    monkeypatch.setenv("SECRETS_VAULT_ONLY", "true")
    assert secrets_vault_only_mode() is True


def test_secrets_vault_only_explicit_off(monkeypatch):
    monkeypatch.setenv("SECRETS_VAULT_ONLY", "false")
    assert secrets_vault_only_mode() is False


def test_secrets_vault_only_auto_off(monkeypatch):
    monkeypatch.setenv("SECRETS_VAULT_ONLY_AUTO", "false")
    assert secrets_vault_only_mode() is False


def test_secrets_vault_only_live_mode(monkeypatch):
    # dry=false + paper=false -> canli -> vault_only True
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("PAPER_MODE", "false")
    assert secrets_vault_only_mode() is True


def test_secrets_vault_only_paper_default():
    # PAPER_MODE varsayilan 'true' -> vault_only False
    assert secrets_vault_only_mode() is False


def test_env_api_key_names_contains_binance():
    names = env_api_key_names()
    assert "BINANCE_API_KEY" in names
    assert names == sorted(set(names))


# ── VaultBridge: erisilebilir (saglikli) yol ───────────────────────────────


def test_bridge_available_read_write_delete(monkeypatch):
    monkeypatch.setenv("SECRETS_VAULT_ONLY", "false")
    with _patch_urlopen(_healthy_handler):
        vb = VaultBridge(addr=_ADDR, token="root-token")
        st = vb.status()
        assert st["available"] is True
        assert st["auth"] == "token"
        assert vb.get_secret("binance", "api_key") == "AK"
        assert vb.get_all_secrets("binance")["api_secret"] == "SK"
        assert vb.probe_kv_fields("binance") == {"api_key": True, "api_secret": True}
        assert "binance" in vb.kv_path_display("binance")
        assert vb.put_secret("binance", {"api_key": "x" * 20}) is True
        assert vb.delete_secret("binance") is True
        assert vb.enable_kv_engine() is True


def test_bridge_read_404_returns_empty(monkeypatch):
    monkeypatch.setenv("SECRETS_VAULT_ONLY", "true")
    with _patch_urlopen(_healthy_handler):
        vb = VaultBridge(addr=_ADDR, token="root-token")
        assert vb.get_secret("missing", "api_key") == ""


def test_bridge_enable_kv_already_exists(monkeypatch):
    def handler(url, method, req):
        if url.endswith("/sys/health"):
            return _Resp({"initialized": True, "sealed": False})
        if "/sys/mounts/" in url:
            raise urllib.error.HTTPError(url, 400, "exists", {}, None)
        return _Resp(b"{}")

    with _patch_urlopen(handler):
        vb = VaultBridge(addr=_ADDR, token="root-token")
        assert vb.enable_kv_engine() is True  # 400 = zaten var -> True


def test_bridge_seed_from_env(monkeypatch):
    monkeypatch.setenv("SECRETS_VAULT_ONLY", "false")
    monkeypatch.setenv("BINANCE_API_KEY", "K" * 30)
    monkeypatch.setenv("BINANCE_API_SECRET", "S" * 30)
    with _patch_urlopen(_healthy_handler):
        vb = VaultBridge(addr=_ADDR, token="root-token")
        assert vb.seed_from_env() >= 1


# ── VaultBridge: erisilemez / fallback yollari ─────────────────────────────


def test_bridge_unavailable_writes_return_false(monkeypatch):
    monkeypatch.setenv("SECRETS_VAULT_ONLY", "false")

    def sealed_handler(url, method, req):
        if url.endswith("/sys/health"):
            return _Resp({"initialized": True, "sealed": True})  # sealed -> available False
        return _Resp(b"{}")

    with _patch_urlopen(sealed_handler):
        vb = VaultBridge(addr=_ADDR, token="root-token")
        assert vb.status()["available"] is False
        assert vb.put_secret("binance", {"a": "b"}) is False
        assert vb.delete_secret("binance") is False
        assert vb.enable_kv_engine() is False
        assert vb.seed_from_env() == 0
        assert vb.probe_kv_fields("binance") == {"api_key": False, "api_secret": False}


def test_bridge_env_fallback_no_token(monkeypatch):
    # token yok, vault_only false -> .env fallback, binance env okunur
    monkeypatch.setenv("SECRETS_VAULT_ONLY", "false")
    monkeypatch.setenv("BINANCE_API_KEY", "ENVKEY123456")
    monkeypatch.setenv("BINANCE_API_SECRET", "ENVSEC123456")

    def unreachable(url, method, req):
        raise urllib.error.URLError("conn refused")

    with _patch_urlopen(unreachable):
        vb = VaultBridge(addr=_ADDR)  # token yok
        st = vb.status()
        assert st["available"] is False
        assert st["fallback"] is True
        assert vb.get_secret("binance", "api_key") == "ENVKEY123456"


def test_bridge_vault_only_no_token_logs(monkeypatch):
    # vault_only True ama token/approle yok -> available False, fallback False
    monkeypatch.setenv("SECRETS_VAULT_ONLY", "true")
    vb = VaultBridge(addr=_ADDR)
    assert vb.status()["available"] is False
    assert vb.status()["fallback"] is False


def test_bridge_approle_login(monkeypatch):
    monkeypatch.setenv("SECRETS_VAULT_ONLY", "true")
    monkeypatch.setenv("VAULT_ROLE_ID", "rid")
    monkeypatch.setenv("VAULT_SECRET_ID", "sid")
    with _patch_urlopen(_healthy_handler):
        vb = VaultBridge(addr=_ADDR)  # token yok -> approle login
        assert vb.status()["available"] is True
        assert vb.status()["auth"] == "approle"


def test_bridge_approle_login_no_token_in_response(monkeypatch):
    monkeypatch.setenv("VAULT_ROLE_ID", "rid")
    monkeypatch.setenv("VAULT_SECRET_ID", "sid")

    def handler(url, method, req):
        if "/auth/approle/login" in url:
            return _Resp({"auth": {"client_token": ""}})  # bos token
        if url.endswith("/sys/health"):
            return _Resp({"initialized": True, "sealed": False})
        return _Resp(b"{}")

    with _patch_urlopen(handler):
        vb = VaultBridge(addr=_ADDR)
        assert vb.status()["available"] is False


def test_bridge_token_renew_when_expired(monkeypatch):
    monkeypatch.setenv("SECRETS_VAULT_ONLY", "false")
    with _patch_urlopen(_healthy_handler):
        vb = VaultBridge(addr=_ADDR, token="root-token")
        vb._token_expires = 1.0  # gecmis -> renew tetikle
        # _request_headers -> _renew_token_if_needed -> renew-self cagrilir
        hdr = vb._request_headers()
        assert hdr["X-Vault-Token"]
        assert vb._token_expires > 1000.0  # yenilendi


def test_bridge_health_unreachable_env_fallback(monkeypatch):
    monkeypatch.setenv("SECRETS_VAULT_ONLY", "false")

    def boom(url, method, req):
        raise urllib.error.URLError("refused")

    with _patch_urlopen(boom):
        vb = VaultBridge(addr=_ADDR, token="root-token")
        assert vb.status()["available"] is False


# ── Hata yollari (except / fallback dallari) ───────────────────────────────


def test_renew_failure_falls_back_to_approle(monkeypatch):
    monkeypatch.setenv("SECRETS_VAULT_ONLY", "false")
    monkeypatch.setenv("VAULT_ROLE_ID", "rid")
    monkeypatch.setenv("VAULT_SECRET_ID", "sid")

    def handler(url, method, req):
        if url.endswith("/sys/health"):
            return _Resp({"initialized": True, "sealed": False})
        if "/auth/token/renew-self" in url:
            raise urllib.error.URLError("renew down")
        if "/auth/approle/login" in url:
            return _Resp({"auth": {"client_token": "new-tok", "lease_duration": 3600}})
        return _Resp(b"{}")

    with _patch_urlopen(handler):
        vb = VaultBridge(addr=_ADDR, token="root-token")
        vb._token_expires = 1.0  # gecmis -> renew dene
        vb._request_headers()  # renew patlar -> approle retry
        assert vb._token == "new-tok"


def test_renew_and_approle_both_fail(monkeypatch):
    monkeypatch.setenv("SECRETS_VAULT_ONLY", "false")

    def handler(url, method, req):
        if url.endswith("/sys/health"):
            return _Resp({"initialized": True, "sealed": False})
        if "/auth/token/renew-self" in url:
            raise urllib.error.URLError("down")
        return _Resp(b"{}")

    with _patch_urlopen(handler):
        vb = VaultBridge(addr=_ADDR, token="root-token")
        vb._token_expires = 1.0
        vb._request_headers()  # renew patlar, role/secret yok -> approle fail
        assert vb._available is False


def test_vault_read_generic_exception(monkeypatch):
    monkeypatch.setenv("SECRETS_VAULT_ONLY", "true")

    def handler(url, method, req):
        if url.endswith("/sys/health"):
            return _Resp({"initialized": True, "sealed": False})
        if "/data/" in url:
            raise ValueError("bozuk yanit")  # HTTPError DEGIL -> genel except
        return _Resp(b"{}")

    with _patch_urlopen(handler):
        vb = VaultBridge(addr=_ADDR, token="root-token")
        assert vb.get_secret("binance", "api_key") == ""


def test_put_secret_exception(monkeypatch):
    def handler(url, method, req):
        if url.endswith("/sys/health"):
            return _Resp({"initialized": True, "sealed": False})
        if "/data/" in url and method == "POST":
            raise urllib.error.URLError("yazma patladi")
        return _Resp(b"{}")

    with _patch_urlopen(handler):
        vb = VaultBridge(addr=_ADDR, token="root-token")
        assert vb.put_secret("binance", {"api_key": "x" * 20}) is False


def test_delete_secret_exception(monkeypatch):
    def handler(url, method, req):
        if url.endswith("/sys/health"):
            return _Resp({"initialized": True, "sealed": False})
        if "/data/" in url and method == "DELETE":
            raise urllib.error.URLError("silme patladi")
        return _Resp(b"{}")

    with _patch_urlopen(handler):
        vb = VaultBridge(addr=_ADDR, token="root-token")
        assert vb.delete_secret("binance") is False


def test_enable_kv_non400_httperror(monkeypatch):
    def handler(url, method, req):
        if url.endswith("/sys/health"):
            return _Resp({"initialized": True, "sealed": False})
        if "/sys/mounts/" in url:
            raise urllib.error.HTTPError(url, 500, "server error", {}, None)
        return _Resp(b"{}")

    with _patch_urlopen(handler):
        vb = VaultBridge(addr=_ADDR, token="root-token")
        assert vb.enable_kv_engine() is False  # 500 -> False (400 degil)


def test_enable_kv_generic_exception(monkeypatch):
    def handler(url, method, req):
        if url.endswith("/sys/health"):
            return _Resp({"initialized": True, "sealed": False})
        if "/sys/mounts/" in url:
            raise ValueError("beklenmeyen")
        return _Resp(b"{}")

    with _patch_urlopen(handler):
        vb = VaultBridge(addr=_ADDR, token="root-token")
        assert vb.enable_kv_engine() is False


def test_env_secrets_binance_alt_keys(monkeypatch):
    # BINANCE_API_KEY yok ama BINANCE_KEY / BINANCE_SECRET_KEY var -> fallback dallari
    monkeypatch.setenv("SECRETS_VAULT_ONLY", "false")
    monkeypatch.setenv("BINANCE_KEY", "ALTKEY1234567890")
    monkeypatch.setenv("BINANCE_SECRET_KEY", "ALTSEC1234567890")

    def unreachable(url, method, req):
        raise urllib.error.URLError("down")

    with _patch_urlopen(unreachable):
        vb = VaultBridge(addr=_ADDR)
        assert vb.get_secret("binance", "api_key") == "ALTKEY1234567890"
        assert vb.get_secret("binance", "api_secret") == "ALTSEC1234567890"


def test_seed_from_env_binance_alt_keys(monkeypatch):
    monkeypatch.setenv("SECRETS_VAULT_ONLY", "false")
    monkeypatch.setenv("BINANCE_KEY", "K" * 30)
    monkeypatch.setenv("BINANCE_SECRET", "S" * 30)
    with _patch_urlopen(_healthy_handler):
        vb = VaultBridge(addr=_ADDR, token="root-token")
        assert vb.seed_from_env() >= 1
