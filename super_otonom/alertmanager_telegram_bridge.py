"""Alertmanager webhook -> Telegram (bot API). Port 8081, path /alert."""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Tuple

log = logging.getLogger("super_otonom.am_telegram")
_PORT = int(os.getenv("ALERT_TELEGRAM_PORT", "8081"))


def _telegram_creds() -> Tuple[str, str]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if token and chat:
        return token, chat
    try:
        from super_otonom.vault_bridge import VaultBridge

        sec = VaultBridge().get_all_secrets("telegram")
        token = str(sec.get("bot_token") or "").strip()
        chat = str(sec.get("chat_id") or "").strip()
    except Exception as exc:
        log.debug("Vault telegram okunamadi: %s", exc)
    return token, chat


def _format_alerts(body: Dict[str, Any]) -> str:
    alerts: List[Dict[str, Any]] = body.get("alerts") or []
    if not alerts:
        return "Prometheus alert (bos payload)"
    lines = [f"*{body.get('status', 'unknown').upper()}* | {body.get('groupKey', '')[:80]}"]
    for a in alerts[:8]:
        name = a.get("labels", {}).get("alertname", "?")
        sev = a.get("labels", {}).get("severity", "")
        summary = a.get("annotations", {}).get("summary", "")
        lines.append(f"- [{sev}] {name}: {summary}")
    if len(alerts) > 8:
        lines.append(f"... +{len(alerts) - 8} alert")
    return "\n".join(lines)[:4090]


def _send_telegram(text: str) -> bool:
    token, chat = _telegram_creds()
    if not token or not chat:
        log.warning("Telegram kimligi yok (TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID veya Vault)")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": chat, "text": text}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=12) as resp:
        return resp.status < 400


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        log.debug(fmt, *args)

    def do_GET(self) -> None:
        if self.path in ("/", "/health"):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        if self.path not in ("/alert", "/"):
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            body = {"alerts": [], "status": "unknown"}
        ok = False
        try:
            ok = _send_telegram(_format_alerts(body))
        except Exception as exc:
            log.error("Telegram gonderim hatasi: %s", exc)
        self.send_response(200 if ok else 202)
        self.end_headers()
        self.wfile.write(b"ok" if ok else b"no_telegram_creds")


def main() -> None:
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
    )
    token, chat = _telegram_creds()
    log.info(
        "Alertmanager-Telegram bridge :%d | telegram=%s",
        _PORT,
        "aktif" if token and chat else "YOK",
    )
    HTTPServer(("0.0.0.0", _PORT), _Handler).serve_forever()


if __name__ == "__main__":
    main()
