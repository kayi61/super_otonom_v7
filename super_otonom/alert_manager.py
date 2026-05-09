from __future__ import annotations

"""
AlertManager v1.0
─────────────────────────────────────────────────────────────────────────────
Sprint 4 M1 — Alarm mekanizması

Emergency stop, büyük NAV farkı, circuit breaker açılması gibi kritik olayları
webhook (Slack/Discord/Telegram/email) üzerinden bildirir.

Desteklenen kanallar:
    WEBHOOK_URL env → Slack/Discord/genel HTTP POST
    ALERT_EMAIL env → Email (SMTP, opsiyonel)

Kullanım (bot_engine veya main_loop içinde):
    alerts = AlertManager()
    alerts.emergency("dynamic_daily_loss", nav=9500.0)
    alerts.nav_diff(diff=500.0, diff_pct=5.2)
    alerts.circuit_breaker("BTC/USDT", "OPEN")
"""

import json
import logging
import os
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger("super_otonom.alerts")

_WEBHOOK_URL   = os.getenv("WEBHOOK_URL", "")
_ALERT_LEVEL   = os.getenv("ALERT_LEVEL", "WARNING")   # DEBUG/INFO/WARNING/CRITICAL
_COOLDOWN_SEC  = int(os.getenv("ALERT_COOLDOWN_SEC", "300"))   # aynı alarm 5 dk'da bir
_MAX_HISTORY   = 200


@dataclass
class AlertEvent:
    ts:        float
    level:     str    # INFO / WARNING / CRITICAL
    category:  str    # EMERGENCY / NAV_DIFF / CIRCUIT_BREAKER / SYSTEM
    title:     str
    body:      str
    sent:      bool   = False
    error:     str    = ""


class AlertManager:
    """
    Merkezi alarm yöneticisi.

    Özellikler:
    - Cooldown: aynı kategori için _COOLDOWN_SEC içinde tek alarm
    - Seviye filtresi: ALERT_LEVEL altındaki olaylar gönderilmez
    - Webhook: Slack/Discord uyumlu JSON payload
    - Bellekte son 200 event — status() için
    """

    _LEVELS = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "CRITICAL": 3}

    def __init__(
        self,
        webhook_url: str = "",
        cooldown_sec: int = _COOLDOWN_SEC,
        min_level: str = _ALERT_LEVEL,
    ):
        self._webhook    = webhook_url or _WEBHOOK_URL
        self._cooldown   = cooldown_sec
        self._min_level  = min_level
        self._history:   List[AlertEvent] = []
        self._last_sent: Dict[str, float] = {}   # category → last send ts
        log.info(
            "AlertManager başlatıldı | webhook=%s | cooldown=%ds | min_level=%s",
            "var" if self._webhook else "YOK",
            cooldown_sec, min_level,
        )

    # ── Alarm metodları ───────────────────────────────────────────────────────

    def emergency(self, code: str, nav: float = 0.0, detail: str = "") -> None:
        """Emergency stop tetiklendiğinde çağır."""
        self._send(
            level="CRITICAL",
            category="EMERGENCY",
            title=f"🚨 EMERGENCY STOP: {code}",
            body=(
                f"Kod: `{code}`\n"
                f"NAV: {nav:.2f}\n"
                + (f"Detay: {detail}" if detail else "")
            ),
        )

    def nav_diff(self, diff: float, diff_pct: float, local: float = 0.0, exchange: float = 0.0) -> None:
        """Reconciliation NAV farkı eşiği aşınca çağır."""
        level = "CRITICAL" if abs(diff_pct) >= 10 else "WARNING"
        self._send(
            level=level,
            category="NAV_DIFF",
            title=f"⚠️ NAV FARKI: {diff_pct:.2f}%",
            body=(
                f"Yerel NAV: {local:.2f}\n"
                f"Borsa NAV: {exchange:.2f}\n"
                f"Fark: {diff:+.2f} ({diff_pct:.2f}%)"
            ),
        )

    def circuit_breaker(self, symbol: str, state: str, reason: str = "") -> None:
        """Circuit breaker açılınca çağır."""
        self._send(
            level="WARNING",
            category=f"CIRCUIT_BREAKER_{symbol}",
            title=f"⚡ Circuit Breaker: {symbol} → {state}",
            body=f"Sembol: {symbol}\nDurum: {state}\n" + (f"Sebep: {reason}" if reason else ""),
        )

    def stale_data(self, symbol: str, age_sec: float) -> None:
        """Stale data tespit edilince çağır."""
        self._send(
            level="WARNING",
            category=f"STALE_{symbol}",
            title=f"🕐 Stale Data: {symbol}",
            body=f"Sembol: {symbol}\nVeri yaşı: {age_sec:.0f}s",
        )

    def backoff(self, error_count: int, wait_sec: int) -> None:
        """Exponential backoff tetiklenince çağır (sadece yüksek sayıda)."""
        if error_count < 3:
            return
        self._send(
            level="WARNING",
            category="BACKOFF",
            title=f"🔄 Backoff: {error_count}. ardışık hata",
            body=f"Ardışık hata: {error_count}\nBekleme: {wait_sec}s",
        )

    def system(self, event: str, detail: str = "", level: str = "INFO") -> None:
        """Genel sistem olayı."""
        self._send(
            level=level,
            category=f"SYSTEM_{event}",
            title=f"ℹ️ Sistem: {event}",
            body=detail,
        )

    def tca_anomaly(self, symbol: str, expected_slip: float, actual_slip: float) -> None:
        """TCA: Slippage beklenenin çok üzerinde."""
        self._send(
            level="WARNING",
            category=f"TCA_{symbol}",
            title=f"📊 TCA Anomali: {symbol}",
            body=(
                f"Sembol: {symbol}\n"
                f"Beklenen slippage: {expected_slip:.4f}%\n"
                f"Gerçekleşen: {actual_slip:.4f}%"
            ),
        )

    # ── İç işleyiş ───────────────────────────────────────────────────────────

    def _send(self, level: str, category: str, title: str, body: str) -> None:
        """Alarm oluştur, cooldown kontrolü yap, webhook'a gönder."""
        # Seviye filtresi
        if self._LEVELS.get(level, 0) < self._LEVELS.get(self._min_level, 0):
            return

        # Cooldown kontrolü
        now = time.time()
        last = self._last_sent.get(category, 0)
        if now - last < self._cooldown:
            log.debug(
                "AlertManager | cooldown | %s | %.0fs kaldı",
                category, self._cooldown - (now - last),
            )
            return

        event = AlertEvent(
            ts=now, level=level, category=category,
            title=title, body=body,
        )
        self._history.append(event)
        if len(self._history) > _MAX_HISTORY:
            self._history = self._history[-_MAX_HISTORY:]

        # Log her zaman
        log_fn = {
            "CRITICAL": log.critical,
            "WARNING":  log.warning,
            "INFO":     log.info,
        }.get(level, log.info)
        log_fn("ALERT | %s | %s | %s", level, category, title)

        # Webhook gönder
        if self._webhook:
            self._post_webhook(event)
        else:
            log.debug("AlertManager | webhook yok — sadece log")

        self._last_sent[category] = now

    def _post_webhook(self, event: AlertEvent) -> None:
        """Slack/Discord uyumlu JSON POST."""
        payload = {
            "text": f"*{event.title}*\n{event.body}",
            "attachments": [{
                "color": {
                    "CRITICAL": "#ff0000",
                    "WARNING":  "#ff9900",
                    "INFO":     "#36a64f",
                }.get(event.level, "#cccccc"),
                "footer": f"super_otonom | {event.level} | {event.category}",
                "ts": int(event.ts),
            }],
        }
        try:
            data = json.dumps(payload).encode("utf-8")
            req  = urllib.request.Request(
                self._webhook,
                data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                event.sent = True
                log.debug("AlertManager | webhook OK | status=%d", resp.status)
        except Exception as exc:
            event.error = str(exc)
            log.error("AlertManager | webhook HATA | %s | %s", event.category, exc)

    # ── Status ────────────────────────────────────────────────────────────────

    def snapshot(self) -> Dict[str, Any]:
        recent = self._history[-10:]
        return {
            "webhook_active":  bool(self._webhook),
            "total_alerts":    len(self._history),
            "recent":          [
                {"ts": e.ts, "level": e.level, "title": e.title, "sent": e.sent}
                for e in recent
            ],
            "cooldown_sec":    self._cooldown,
            "min_level":       self._min_level,
        }
