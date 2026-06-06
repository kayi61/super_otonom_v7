"""Binance testnet anahtar/baglanti preflight teshisi (kok-sebep: 1-char Vault key).

Amac: "fetch_balance 400" muglakligini EYLEME DONUSTURULEBILIR teshise cevirmek.
Botun KULLANACAGI anahtari (Vault, SECRETS_VAULT_ONLY'ye saygili) cozer, formatini
dogrular, sonra Binance testnet'e GERCEK kimlikli probe atar (fetch_balance) ve
"calisiyor / su yuzden calismiyor" der. Sir asla ekrana yazilmaz (maskelenir).

Kullanim:
    python -m super_otonom.infra.binance_testnet_preflight
    python -m super_otonom.infra.binance_testnet_preflight --from-env   # SEED_API_KEY/SECRET

Cikis kodu: 0 = anahtar testnet'te calisiyor; 1 = sorun (sebep yazdirilir).
"""
from __future__ import annotations

import argparse
import asyncio
import os
from dataclasses import dataclass
from typing import Any, Callable, Optional, Tuple

# Gercek borsa anahtarlari uzundur (Binance ~64). 1-char paste bug'ini erken yakala.
_MIN_KEY_LEN = 16


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    stage: str          # resolve | validate | probe
    reason: str
    key_info: str = ""  # maskeli (sir yok)
    usdt: Optional[float] = None

    def render(self) -> str:
        head = "PASS" if self.ok else "FAIL"
        body = f"[{head}] stage={self.stage} | {self.reason}"
        if self.key_info:
            body += f" | key={self.key_info}"
        if self.usdt is not None:
            body += f" | USDT={self.usdt:.2f}"
        return body


def mask(secret: str) -> str:
    """Sirri maskele — yalnizca uzunluk + ilk2/son2 (kisa ise tamamen gizli)."""
    s = str(secret or "")
    n = len(s)
    if n == 0:
        return "<bos>"
    if n <= 6:
        return f"<{n} char, gizli>"
    return f"{s[:2]}…{s[-2:]} ({n} char)"


def classify_key(api_key: str, api_secret: str) -> Tuple[bool, str]:
    """Anahtar FORMAT dogrulamasi (probe oncesi, ag yok). (ok, reason)."""
    ak = str(api_key or "").strip()
    sk = str(api_secret or "").strip()
    if not ak or not sk:
        return False, "api_key/api_secret BOS — Vault'a anahtar yazilmamis."
    if len(ak) < _MIN_KEY_LEN or len(sk) < _MIN_KEY_LEN:
        return False, (
            f"anahtar COK KISA (api_key={len(ak)} char, api_secret={len(sk)} char). "
            "Gercek anahtarlar ~64 char — getpass paste tam olmamis (1-char bug). "
            "scripts/seed_binance_to_vault.py --from-env ile yeniden seed et."
        )
    if ak != api_key or sk != api_secret:
        return False, "anahtar bas/son bosluk iceriyor — temiz yapistir."
    return True, "format ok"


def diagnose_error(exc: BaseException) -> str:
    """ccxt/ag hatasini insan-okur teshise cevir (eylem onerisiyle)."""
    s = str(exc)
    name = type(exc).__name__
    low = s.lower()
    if "-2014" in s or "api-key format invalid" in low:
        return "Anahtar FORMATI gecersiz (-2014). Yanlis/bozuk anahtar — yeniden seed et."
    if "-2015" in s or "invalid api-key" in low:
        return (
            "Anahtar gecersiz veya IP/izin sorunu (-2015). Testnet anahtarini "
            "(testnet.binance.vision) ve IP whitelist'i kontrol et."
        )
    if "Authentication" in name or "401" in s or "signature" in low:
        return "Kimlik dogrulama basarisiz — api_key/api_secret yanlis veya saat kaymasi."
    if (
        "Network" in name
        or "timeout" in low
        or "getaddrinfo" in low
        or "connection" in low
        or "ssl" in low
    ):
        return "Ag/erisim hatasi — internet/proxy/DNS veya testnet host erisilemez."
    if "Permission" in name:
        return "Izin reddedildi — anahtarin testnet izinleri eksik."
    return f"Bilinmeyen borsa hatasi: {name}: {s[:200]}"


def _default_handler(api_key: str, api_secret: str) -> Any:
    """Gercek AsyncExchangeHandler (testnet=True + BINANCE_TESTNET acik)."""
    os.environ["BINANCE_TESTNET"] = "true"
    from super_otonom.exchange_async import AsyncExchangeHandler

    return AsyncExchangeHandler("binance", api_key=api_key, api_secret=api_secret, testnet=True)


async def probe_testnet(
    api_key: str,
    api_secret: str,
    *,
    handler_factory: Optional[Callable[[str, str], Any]] = None,
) -> Tuple[bool, str, Optional[float]]:
    """Binance testnet'e GERCEK kimlikli probe (fetch_balance). (ok, reason, usdt)."""
    factory = handler_factory or _default_handler
    handler = factory(api_key, api_secret)
    try:
        bal = await handler.fetch_balance()
        usdt = float((bal.get("total") or {}).get("USDT", 0) or 0)
        return True, "Binance testnet kimlik dogrulama OK.", usdt
    except Exception as exc:  # noqa: BLE001
        return False, diagnose_error(exc), None
    finally:
        close = getattr(handler, "close", None)
        if close is not None:
            try:
                res = close()
                if asyncio.iscoroutine(res):
                    await res
            except Exception:  # noqa: BLE001
                pass


def _resolve_keys(from_env: bool, addr: str) -> Tuple[str, str, str]:
    """Botun kullandigi anahtari coz. (api_key, api_secret, source)."""
    if from_env:
        ak = os.getenv("SEED_API_KEY", "").strip() or os.getenv("BINANCE_API_KEY", "").strip()
        sk = (
            os.getenv("SEED_API_SECRET", "").strip()
            or os.getenv("BINANCE_API_SECRET", "").strip()
        )
        return ak, sk, "env"
    os.environ.setdefault("VAULT_ADDR", addr)
    from super_otonom.infra.vault_bridge import VaultBridge

    vb = VaultBridge()
    ak = vb.get_secret("binance", "api_key")
    sk = vb.get_secret("binance", "api_secret")
    return ak, sk, "vault"


async def run_preflight(
    *,
    from_env: bool = False,
    addr: str = "http://127.0.0.1:8200",
    handler_factory: Optional[Callable[[str, str], Any]] = None,
) -> PreflightResult:
    """Tam zincir: coz -> format dogrula -> gercek probe."""
    api_key, api_secret, source = _resolve_keys(from_env, addr)
    key_info = mask(api_key)

    if not api_key or not api_secret:
        return PreflightResult(
            False, "resolve",
            f"Anahtar bulunamadi (source={source}). Vault'a seed edildi mi?",
            key_info,
        )

    ok_fmt, reason_fmt = classify_key(api_key, api_secret)
    if not ok_fmt:
        return PreflightResult(False, "validate", reason_fmt, key_info)

    ok_probe, reason_probe, usdt = await probe_testnet(
        api_key, api_secret, handler_factory=handler_factory
    )
    return PreflightResult(ok_probe, "probe", reason_probe, key_info, usdt)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Binance testnet anahtar preflight teshisi")
    p.add_argument("--from-env", action="store_true", help="anahtari env'den oku (Vault yerine)")
    p.add_argument("--addr", default="http://127.0.0.1:8200", help="VAULT_ADDR")
    args = p.parse_args(argv)

    result = asyncio.run(run_preflight(from_env=args.from_env, addr=args.addr))
    print(result.render())
    if not result.ok:
        print("  -> Sonraki adim: gecerli testnet anahtarini seed et:")
        print("     $env:SEED_API_KEY='...'; $env:SEED_API_SECRET='...'")
        print("     python scripts/seed_binance_to_vault.py --from-env")
        print("     python -m super_otonom.infra.binance_testnet_preflight")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
