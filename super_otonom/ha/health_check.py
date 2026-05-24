"""
HA-aware health check endpoint.

Mevcut ``health_summary.py``'yi genişleterek HA durumunu da raporlar.
Liveness (process canlı mı) ve readiness (trading yapabilir mi) ayrımı.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict

log = logging.getLogger("super_otonom.ha.health_check")


@dataclass
class HAHealthCheck:
    """
    Kubernetes-tarzı liveness + readiness probe'ları.

    - **liveness**: Process canlı mı? (heartbeat son N saniye içinde mi)
    - **readiness**: Trading yapabilir mi? (leader mı, exchange bağlı mı)

    Kullanım::

        hc = HAHealthCheck()
        hc.record_heartbeat()
        hc.set_trading_ready(True)
        print(hc.liveness())   # {"alive": True, ...}
        print(hc.readiness())  # {"ready": True, ...}
    """

    instance_id: str = ""
    liveness_timeout_sec: float = 30.0

    _last_heartbeat: float = field(default_factory=time.time, init=False, repr=False)
    _trading_ready: bool = field(default=False, init=False, repr=False)
    _is_leader: bool = field(default=False, init=False, repr=False)
    _start_time: float = field(default_factory=time.time, init=False, repr=False)
    _last_tick_ts: float = field(default=0.0, init=False, repr=False)
    _tick_count: int = field(default=0, init=False, repr=False)
    _error_count: int = field(default=0, init=False, repr=False)
    _components: Dict[str, bool] = field(default_factory=dict, init=False, repr=False)

    # ── Heartbeat ────────────────────────────────────────────────────────────

    def record_heartbeat(self) -> None:
        """Her tick sonunda çağır — liveness kanıtı."""
        self._last_heartbeat = time.time()

    def record_tick(self) -> None:
        """Tick sayacını artır ve heartbeat kaydet."""
        self._tick_count += 1
        self._last_tick_ts = time.time()
        self.record_heartbeat()

    def record_error(self) -> None:
        """Hata sayacını artır."""
        self._error_count += 1

    # ── Durum ayarları ───────────────────────────────────────────────────────

    def set_trading_ready(self, ready: bool) -> None:
        self._trading_ready = ready

    def set_leader(self, is_leader: bool) -> None:
        self._is_leader = is_leader

    def set_component_health(self, name: str, healthy: bool) -> None:
        """Alt bileşen sağlığını kaydet (exchange, redis, ws, vb.)."""
        self._components[name] = healthy

    # ── Probe'lar ────────────────────────────────────────────────────────────

    def liveness(self) -> Dict[str, Any]:
        """
        Liveness probe: process canlı mı?

        Heartbeat son ``liveness_timeout_sec`` içindeyse alive=True.
        """
        now = time.time()
        age = now - self._last_heartbeat
        alive = age <= self.liveness_timeout_sec
        return {
            "alive": alive,
            "instance_id": self.instance_id,
            "uptime_sec": round(now - self._start_time, 1),
            "last_heartbeat_age_sec": round(age, 1),
            "tick_count": self._tick_count,
            "error_count": self._error_count,
        }

    def readiness(self) -> Dict[str, Any]:
        """
        Readiness probe: trading yapabilir mi?

        Ready koşulları:
        1. Alive olmalı
        2. Trading ready flag True olmalı
        3. Leader olmalı (veya HA devre dışı)
        """
        live = self.liveness()
        ready = live["alive"] and self._trading_ready and self._is_leader
        return {
            "ready": ready,
            "alive": live["alive"],
            "is_leader": self._is_leader,
            "trading_ready": self._trading_ready,
            "instance_id": self.instance_id,
            "components": dict(self._components),
        }

    def full_status(self) -> Dict[str, Any]:
        """Tam sağlık raporu — monitoring dashboard için."""
        live = self.liveness()
        ready = self.readiness()
        return {
            "liveness": live,
            "readiness": ready,
            "ha": {
                "is_leader": self._is_leader,
                "instance_id": self.instance_id,
            },
            "stats": {
                "tick_count": self._tick_count,
                "error_count": self._error_count,
                "last_tick_ts": self._last_tick_ts,
                "uptime_sec": live["uptime_sec"],
            },
            "components": dict(self._components),
        }

    def format_health_line(self) -> str:
        """Tek satırlık sağlık özeti — log / terminal için."""
        role = "LEADER" if self._is_leader else "STANDBY"
        ready = "READY" if self._trading_ready else "NOT_READY"
        age = time.time() - self._last_heartbeat
        return (
            f"[{role}] {ready} | ticks={self._tick_count} "
            f"errs={self._error_count} hb_age={age:.1f}s "
            f"id={self.instance_id}"
        )

    def to_prometheus_labels(self) -> Dict[str, str]:
        """Prometheus metric label'ları için."""
        return {
            "instance_id": self.instance_id,
            "role": "leader" if self._is_leader else "standby",
        }
