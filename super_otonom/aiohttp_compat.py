"""aiohttp TCPConnector ayarlari: Windows DNS ve proxy ortam degiskenleri."""

from __future__ import annotations

import os
import socket
import sys
from typing import Any


def aiohttp_trust_env() -> bool:
    """
    HTTP(S)_PROXY yanlis/kirik ise aiohttp DNS ve TLS'de garip hatalar verebilir.
    SUPER_OTONOM_AIOHTTP_TRUST_ENV=0 ile proxy env yoksayilir.
    Windows varsayilan: kapali (kurumsal proxy gerekiyorsa SUPER_OTONOM_AIOHTTP_TRUST_ENV=1).
    """
    raw = os.getenv("SUPER_OTONOM_AIOHTTP_TRUST_ENV", "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    if sys.platform == "win32":
        return False
    return True


def aiohttp_ipv4_only() -> bool:
    return os.getenv("SUPER_OTONOM_AIOHTTP_IPV4_ONLY", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def make_tcp_connector(loop: Any, ssl_context: Any | None = None) -> Any:
    import aiohttp
    from aiohttp.resolver import ThreadedResolver

    # aiodns kuruluysa aiohttp.DefaultResolver == AsyncResolver (c-ares);
    # Windows'ta "Could not contact DNS servers" uretir. ThreadedResolver -> sistem getaddrinfo.
    kw: dict[str, Any] = {
        "loop": loop,
        "use_dns_cache": False,
        "resolver": ThreadedResolver(loop),
        "enable_cleanup_closed": True,
    }
    if ssl_context is not None:
        kw["ssl"] = ssl_context
    if aiohttp_ipv4_only():
        kw["family"] = socket.AF_INET
    return aiohttp.TCPConnector(**kw)


def make_client_session(loop: Any, ssl_context: Any | None = None) -> Any:
    import aiohttp

    return aiohttp.ClientSession(
        loop=loop,
        connector=make_tcp_connector(loop, ssl_context=ssl_context),
        trust_env=aiohttp_trust_env(),
    )
