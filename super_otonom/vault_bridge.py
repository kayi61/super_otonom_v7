from __future__ import annotations

"""
VaultBridge v1.1
─────────────────────────────────────────────────────────────────────────────
HashiCorp Vault ile güvenli API anahtarı yönetimi.

Üretim (canlı, SECRETS_VAULT_ONLY): yalnızca Vault KV; .env'de API anahtarı yok.
Kimlik: VAULT_ADDR + (AppRole: VAULT_ROLE_ID + VAULT_SECRET_ID) veya kısa ömürlü VAULT_TOKEN.

Geliştirme: Vault kapalıysa .env fallback (SECRETS_VAULT_ONLY=false).

Kullanım:
    vault = VaultBridge()
    api_key = vault.get_secret("binance", "api_key")
    vault.put_secret("binance", {"api_key": "xxx", "api_secret": "yyy"})
    vault.status()
"""

import json
import logging
import os
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional
from urllib.parse import urlparse

log = logging.getLogger("super_otonom.vault_bridge")

_VAULT_ADDR = os.getenv("VAULT_ADDR", "http://vault:8200")


def resolve_vault_addr(preferred: str = "") -> str:
    """Docker icin http://vault:8200; Windows host CLI icin http://127.0.0.1:8200."""
    host_override = os.getenv("VAULT_ADDR_HOST", "").strip().rstrip("/")
    if host_override:
        return host_override
    addr = (preferred or os.getenv("VAULT_ADDR", "http://vault:8200")).strip().rstrip("/")
    if os.getenv("VAULT_ADDR_FORCE", "").strip().lower() in ("1", "true", "yes", "on"):
        return addr
    try:
        hostname = (urlparse(addr).hostname or "").lower()
        port = urlparse(addr).port or 8200
    except Exception:
        return addr
    if hostname not in ("vault", "super_otonom_vault"):
        return addr
    try:
        socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        return addr
    except OSError:
        fallback = f"http://127.0.0.1:{port}"
        log.debug("VAULT_ADDR host fallback: %s -> %s", addr, fallback)
        return fallback
_VAULT_MOUNT = os.getenv("VAULT_MOUNT", "secret")
_VAULT_BASE_PATH = os.getenv("VAULT_BASE_PATH", "trading")
_VAULT_TIMEOUT = int(os.getenv("VAULT_TIMEOUT", "5"))
_TOKEN_RENEW_LEEWAY_SEC = 60

# .env fallback haritası — yalnızca SECRETS_VAULT_ONLY kapalıyken
_ENV_FALLBACK: Dict[str, Dict[str, str]] = {
    "binance": {
        "api_key": "BINANCE_API_KEY",
        "api_secret": "BINANCE_API_SECRET",
    },
    "okx": {
        "api_key": "OKX_API_KEY",
        "api_secret": "OKX_API_SECRET",
        "api_password": "OKX_API_PASSWORD",
    },
    "bybit": {
        "api_key": "BYBIT_API_KEY",
        "api_secret": "BYBIT_API_SECRET",
    },
    "kucoin": {
        "api_key": "KUCOIN_API_KEY",
        "api_secret": "KUCOIN_API_SECRET",
        "api_passphrase": "KUCOIN_API_PASSPHRASE",
    },
    "coinbase": {
        "api_key": "COINBASE_API_KEY",
        "api_secret": "COINBASE_API_SECRET",
    },
    "gateio": {
        "api_key": "GATEIO_API_KEY",
        "api_secret": "GATEIO_API_SECRET",
    },
    "telegram": {
        "bot_token": "TELEGRAM_BOT_TOKEN",
        "chat_id": "TELEGRAM_CHAT_ID",
    },
}


def secrets_vault_only_mode() -> bool:
    """Üretim: API anahtarları yalnızca Vault'tan; .env'deki borsa anahtarları yok sayılır."""
    raw = os.getenv("SECRETS_VAULT_ONLY", "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    auto = os.getenv("SECRETS_VAULT_ONLY_AUTO", "true").strip().lower()
    if auto in ("0", "false", "no", "off"):
        return False
    dry = os.getenv("DRY_RUN", "").strip().lower() in ("1", "true", "yes", "on")
    paper = os.getenv("PAPER_MODE", "true").strip().lower() in ("1", "true", "yes", "on")
    return not dry and not paper


def env_api_key_names() -> list[str]:
    """Borsa / Telegram API anahtarı ortam değişkenleri (denetim için)."""
    names: list[str] = []
    for key_map in _ENV_FALLBACK.values():
        names.extend(key_map.values())
    names.extend(("BINANCE_KEY", "BINANCE_SECRET_KEY", "BINANCE_SECRET"))
    return sorted(set(names))


class VaultBridge:
    """
    Vault KV v2 + isteğe bağlı .env fallback.

    Öncelik (vault_only değilse): .env ∪ Vault (Vault dolu alanları üstün yazar).
    vault_only: yalnızca Vault; erişilemezse boş döner ve uyarı loglar.
    """

    def __init__(
        self,
        addr: str = "",
        token: str = "",
        mount: str = _VAULT_MOUNT,
    ):
        self._addr = resolve_vault_addr(addr or _VAULT_ADDR)
        self._mount = mount
        self._token = token.strip() if token else ""
        self._token_expires: float = 0.0
        self._available = False
        self._vault_only = secrets_vault_only_mode()
        self._cache: Dict[str, Dict[str, str]] = {}
        self._cache_ts: Dict[str, float] = {}
        self._cache_ttl = 300

        if not self._token:
            self._token = os.getenv("VAULT_TOKEN", "").strip()
        if not self._token:
            self._approle_login()
        if self._token:
            self._available = self._check_health()
        elif self._vault_only:
            log.error(
                "SECRETS_VAULT_ONLY aktif ancak VAULT_TOKEN veya AppRole yok — "
                "VAULT_ADDR + VAULT_ROLE_ID + VAULT_SECRET_ID ayarlayın"
            )
        else:
            log.info("Vault kimliği yok — .env fallback aktif (geliştirme)")
        self._publish_availability()

    def _publish_availability(self) -> None:
        try:
            from super_otonom.ops_metrics import set_dependency_up

            set_dependency_up("vault", self._available)
        except Exception:
            pass

    # ── Auth ────────────────────────────────────────────────────────────

    def _approle_login(self) -> bool:
        role_id = os.getenv("VAULT_ROLE_ID", "").strip()
        secret_id = os.getenv("VAULT_SECRET_ID", "").strip()
        if not role_id or not secret_id:
            return False
        try:
            url = f"{self._addr}/v1/auth/approle/login"
            payload = json.dumps({"role_id": role_id, "secret_id": secret_id}).encode()
            req = urllib.request.Request(url, data=payload, method="POST")
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=_VAULT_TIMEOUT) as resp:
                body = json.loads(resp.read())
            auth = body.get("auth") or {}
            token = str(auth.get("client_token") or "").strip()
            if not token:
                log.warning("AppRole login: client_token boş")
                return False
            self._token = token
            lease = int(auth.get("lease_duration") or 3600)
            self._token_expires = time.time() + max(lease - _TOKEN_RENEW_LEEWAY_SEC, 120)
            log.info("Vault AppRole login başarılı (lease ~%ds)", lease)
            return True
        except Exception as exc:
            if self._vault_only:
                log.warning("Vault AppRole login başarısız: %s", exc)
            else:
                log.debug("Vault AppRole login başarısız (env fallback): %s", exc)
            return False

    def _renew_token_if_needed(self) -> None:
        if not self._token or self._token_expires <= 0:
            return
        if time.time() < self._token_expires:
            return
        try:
            url = f"{self._addr}/v1/auth/token/renew-self"
            req = urllib.request.Request(url, data=b"{}", method="POST")
            req.add_header("X-Vault-Token", self._token)
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=_VAULT_TIMEOUT) as resp:
                body = json.loads(resp.read())
            auth = body.get("auth") or {}
            lease = int(auth.get("lease_duration") or 3600)
            self._token_expires = time.time() + max(lease - _TOKEN_RENEW_LEEWAY_SEC, 120)
            log.debug("Vault token yenilendi (~%ds)", lease)
        except Exception:
            if self._approle_login():
                self._available = self._check_health()
            else:
                self._available = False
                log.warning("Vault token süresi doldu ve yenilenemedi")
            self._publish_availability()

    def _request_headers(self) -> Dict[str, str]:
        self._renew_token_if_needed()
        return {"X-Vault-Token": self._token}

    # ── Health ──────────────────────────────────────────────────────────

    def _check_health(self) -> bool:
        try:
            url = f"{self._addr}/v1/sys/health"
            req = urllib.request.Request(url, method="GET")
            for k, v in self._request_headers().items():
                req.add_header(k, v)
            with urllib.request.urlopen(req, timeout=_VAULT_TIMEOUT) as resp:
                data = json.loads(resp.read())
                ok = data.get("initialized") and not data.get("sealed")
                if ok:
                    log.info(
                        "Vault bağlantısı OK (vault_only=%s, initialized=%s, sealed=%s)",
                        self._vault_only,
                        data.get("initialized"),
                        data.get("sealed"),
                    )
                else:
                    log.warning("Vault erişilebilir ama sealed veya uninitialized")
                return bool(ok)
        except Exception as exc:
            if self._vault_only:
                log.error("Vault erişilemedi (SECRETS_VAULT_ONLY): %s", exc)
            else:
                log.warning("Vault erisilemedi (%s) - .env fallback", exc)
            return False

    def status(self) -> Dict[str, Any]:
        return {
            "available": self._available,
            "addr": self._addr,
            "mount": self._mount,
            "vault_only": self._vault_only,
            "auth": "approle" if os.getenv("VAULT_ROLE_ID") else ("token" if self._token else "none"),
            "cached_paths": list(self._cache.keys()),
            "fallback": not self._vault_only and not self._available,
        }

    def probe_kv_fields(self, exchange: str, fields: tuple[str, ...] = ("api_key", "api_secret")) -> Dict[str, bool]:
        """KV'de alan dolu mu (deger dondurmez — denetim icin)."""
        if not self._available:
            return {f: False for f in fields}
        data = self._vault_read(exchange) or {}
        return {f: bool(str(data.get(f) or "").strip()) for f in fields}

    def kv_path_display(self, exchange: str) -> str:
        """Denetim raporu icin tam KV yolu (sır yok)."""
        return f"{self._mount}/data/{_VAULT_BASE_PATH}/{exchange}"

    # ── Read ────────────────────────────────────────────────────────────

    def _vault_read(self, path: str) -> Optional[Dict[str, str]]:
        if not self._available:
            return None
        try:
            url = f"{self._addr}/v1/{self._mount}/data/{_VAULT_BASE_PATH}/{path}"
            req = urllib.request.Request(url, method="GET")
            for k, v in self._request_headers().items():
                req.add_header(k, v)
            with urllib.request.urlopen(req, timeout=_VAULT_TIMEOUT) as resp:
                body = json.loads(resp.read())
                return body.get("data", {}).get("data", {})
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                log.debug("Vault path bulunamadı: %s", path)
            else:
                log.warning("Vault okuma hatası (%s): HTTP %d", path, exc.code)
            return None
        except Exception as exc:
            log.warning("Vault okuma hatası (%s): %s", path, exc)
            return None

    def _env_secrets(self, exchange: str) -> Dict[str, str]:
        merged: Dict[str, str] = {}
        env_map = _ENV_FALLBACK.get(exchange, {})
        for k, env_name in env_map.items():
            val = os.getenv(env_name, "")
            if val:
                merged[k] = val.strip()
        if exchange == "binance":
            if not merged.get("api_key"):
                ak = os.getenv("BINANCE_API_KEY", "").strip() or os.getenv("BINANCE_KEY", "").strip()
                if ak:
                    merged["api_key"] = ak
            if not merged.get("api_secret"):
                ask = (
                    os.getenv("BINANCE_API_SECRET", "").strip()
                    or os.getenv("BINANCE_SECRET_KEY", "").strip()
                    or os.getenv("BINANCE_SECRET", "").strip()
                )
                if ask:
                    merged["api_secret"] = ask
        return merged

    def _merged_secrets(self, exchange: str) -> Dict[str, str]:
        now = time.time()
        if exchange in self._cache:
            if now - self._cache_ts.get(exchange, 0) < self._cache_ttl:
                return dict(self._cache[exchange])

        merged: Dict[str, str] = {}
        if not self._vault_only:
            merged = self._env_secrets(exchange)

        if self._available:
            data = self._vault_read(exchange)
            if data:
                for k, v in data.items():
                    if v is not None and str(v).strip():
                        merged[k] = str(v).strip()
        elif self._vault_only:
            log.error("Vault yok — %s secret okunamadı (SECRETS_VAULT_ONLY)", exchange)

        self._cache[exchange] = merged
        self._cache_ts[exchange] = now
        return merged

    def get_secret(self, exchange: str, key: str) -> str:
        return self._merged_secrets(exchange).get(key, "")

    def get_all_secrets(self, exchange: str) -> Dict[str, str]:
        return dict(self._merged_secrets(exchange))

    # ── Write ───────────────────────────────────────────────────────────

    def put_secret(self, path: str, data: Dict[str, str]) -> bool:
        if not self._available:
            log.warning("Vault erişilemez — secret yazılamadı: %s", path)
            return False
        try:
            url = f"{self._addr}/v1/{self._mount}/data/{_VAULT_BASE_PATH}/{path}"
            payload = json.dumps({"data": data}).encode()
            req = urllib.request.Request(url, data=payload, method="POST")
            for k, v in self._request_headers().items():
                req.add_header(k, v)
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=_VAULT_TIMEOUT) as resp:
                if resp.status in (200, 204):
                    log.info("Vault secret yazıldı: %s (%d anahtar)", path, len(data))
                    self._cache[path] = data
                    self._cache_ts[path] = time.time()
                    return True
        except Exception as exc:
            log.error("Vault yazma hatası (%s): %s", path, exc)
        return False

    def delete_secret(self, path: str) -> bool:
        if not self._available:
            return False
        try:
            url = f"{self._addr}/v1/{self._mount}/data/{_VAULT_BASE_PATH}/{path}"
            req = urllib.request.Request(url, method="DELETE")
            for k, v in self._request_headers().items():
                req.add_header(k, v)
            with urllib.request.urlopen(req, timeout=_VAULT_TIMEOUT) as resp:
                if resp.status in (200, 204):
                    self._cache.pop(path, None)
                    log.info("Vault secret silindi: %s", path)
                    return True
        except Exception as exc:
            log.error("Vault silme hatası (%s): %s", path, exc)
        return False

    def enable_kv_engine(self) -> bool:
        if not self._available:
            return False
        try:
            url = f"{self._addr}/v1/sys/mounts/{self._mount}"
            payload = json.dumps({"type": "kv", "options": {"version": "2"}}).encode()
            req = urllib.request.Request(url, data=payload, method="POST")
            for k, v in self._request_headers().items():
                req.add_header(k, v)
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=_VAULT_TIMEOUT):
                log.info("KV v2 secrets engine etkinleştirildi: %s", self._mount)
                return True
        except urllib.error.HTTPError as exc:
            if exc.code == 400:
                log.debug("KV engine zaten mevcut: %s", self._mount)
                return True
            log.error("KV engine etkinleştirme hatası: HTTP %d", exc.code)
        except Exception as exc:
            log.error("KV engine etkinleştirme hatası: %s", exc)
        return False

    def seed_from_env(self) -> int:
        """Tek seferlik: .env'deki borsa anahtarlarını Vault KV'ye taşı (sonra .env'den silin)."""
        if not self._available:
            log.warning("Vault erişilemez — seed yapılamadı")
            return 0
        count = 0
        for exchange, key_map in _ENV_FALLBACK.items():
            data = {}
            for secret_key, env_name in key_map.items():
                val = os.getenv(env_name, "")
                if val:
                    data[secret_key] = val.strip()
            if exchange == "binance" and not data.get("api_key"):
                ak = os.getenv("BINANCE_API_KEY", "").strip() or os.getenv("BINANCE_KEY", "").strip()
                if ak:
                    data["api_key"] = ak
            if exchange == "binance" and not data.get("api_secret"):
                ask = (
                    os.getenv("BINANCE_API_SECRET", "").strip()
                    or os.getenv("BINANCE_SECRET_KEY", "").strip()
                    or os.getenv("BINANCE_SECRET", "").strip()
                )
                if ask:
                    data["api_secret"] = ask
            if data and self.put_secret(exchange, data):
                count += 1
                log.info("Vault seed: %s (%d anahtar)", exchange, len(data))
        return count
