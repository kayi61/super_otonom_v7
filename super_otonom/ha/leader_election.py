"""
Redis-based leader election — distributed lock with TTL lease.

Mekanizma:
    SET ha:leader <instance_id> NX PX <lease_ms>

Leader lease'i periyodik olarak yeniler (heartbeat).  Yenileyemezse
(crash, network partition) lease süresi dolunca başka instance devralır.

Redis yoksa veya bağlanamazsa ``LeaderElection`` degraded modda çalışır
ve instance'ı her zaman leader olarak raporlar (tek-instance uyumluluk).
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

log = logging.getLogger("super_otonom.ha.leader_election")

# ── Varsayılan ayarlar ───────────────────────────────────────────────────────
LEADER_KEY = os.getenv("HA_LEADER_KEY", "ha:leader")
LEASE_MS = int(os.getenv("HA_LEASE_MS", "15000"))  # 15s
HEARTBEAT_INTERVAL_SEC = float(os.getenv("HA_HEARTBEAT_SEC", "5.0"))
INSTANCE_ID = os.getenv("HA_INSTANCE_ID", "")


class RedisLike(Protocol):
    """Redis client'ın leader election için gerekli alt kümesi."""

    def set(self, name: str, value: Any, *, nx: bool = False, px: int = 0) -> Any: ...
    def get(self, name: str) -> Any: ...
    def delete(self, *names: str) -> Any: ...
    def pttl(self, name: str) -> int: ...


@dataclass(frozen=True)
class LeaderInfo:
    """Mevcut leader hakkında bilgi."""

    instance_id: str
    is_self: bool
    ttl_ms: int = 0
    elected_at: float = 0.0


@dataclass
class LeaderElection:
    """
    Redis SET NX + PX tabanlı leader election.

    Kullanım::

        le = LeaderElection(redis_client)
        if le.try_acquire():
            # ben leader'ım, trading yap
            ...
        le.heartbeat()  # periyodik olarak çağır
    """

    redis: Optional[RedisLike] = None
    instance_id: str = field(default_factory=lambda: INSTANCE_ID or uuid.uuid4().hex[:12])
    leader_key: str = LEADER_KEY
    lease_ms: int = LEASE_MS
    heartbeat_interval: float = HEARTBEAT_INTERVAL_SEC

    # ── İç durum ─────────────────────────────────────────────────────────────
    _is_leader: bool = field(default=False, init=False, repr=False)
    _last_heartbeat: float = field(default=0.0, init=False, repr=False)
    _elected_at: float = field(default=0.0, init=False, repr=False)
    _degraded: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.redis is None:
            self._degraded = True
            self._is_leader = True
            log.warning(
                "LeaderElection: Redis yok — degraded mod, "
                "instance=%s her zaman leader",
                self.instance_id,
            )

    # ── Public API ───────────────────────────────────────────────────────────

    @property
    def is_leader(self) -> bool:
        return self._is_leader

    @property
    def is_degraded(self) -> bool:
        return self._degraded

    def try_acquire(self) -> bool:
        """Leader lock'u almayı dene.  True → bu instance leader oldu."""
        if self._degraded:
            return True
        assert self.redis is not None
        try:
            result = self.redis.set(
                self.leader_key,
                self.instance_id,
                nx=True,
                px=self.lease_ms,
            )
            if result:
                self._is_leader = True
                self._elected_at = time.time()
                self._last_heartbeat = time.time()
                log.info(
                    "LeaderElection: LEADER olundu | instance=%s lease=%dms",
                    self.instance_id,
                    self.lease_ms,
                )
                return True

            # Lock başkasında — kontrol et
            current = self.redis.get(self.leader_key)
            if current == self.instance_id:
                # Bizim zaten — muhtemelen restart
                self._is_leader = True
                self._elected_at = time.time()
                return True

            self._is_leader = False
            return False
        except Exception as exc:
            log.error("LeaderElection.try_acquire hata: %s", exc)
            self._enter_degraded("try_acquire error")
            return True

    def heartbeat(self) -> bool:
        """
        Leader lease'ini yenile.

        Leader değilse veya degraded moddaysa no-op.
        Dönüş: lease yenilenebildi mi.
        """
        if self._degraded:
            return True
        if not self._is_leader:
            return False
        assert self.redis is not None

        now = time.time()
        if now - self._last_heartbeat < self.heartbeat_interval:
            return True  # çok erken, atla

        try:
            current = self.redis.get(self.leader_key)
            if current != self.instance_id:
                # Başkası leader olmuş (lease expire + takeover)
                log.warning(
                    "LeaderElection: leader kaybedildi | "
                    "beklenen=%s mevcut=%s",
                    self.instance_id,
                    current,
                )
                self._is_leader = False
                return False

            # Lease yenile — SET XX PX
            self.redis.set(
                self.leader_key,
                self.instance_id,
                nx=False,
                px=self.lease_ms,
            )
            self._last_heartbeat = now
            return True
        except Exception as exc:
            log.error("LeaderElection.heartbeat hata: %s", exc)
            self._enter_degraded("heartbeat error")
            return True

    def release(self) -> None:
        """Leader lock'u bırak (graceful shutdown)."""
        if self._degraded or not self._is_leader:
            return
        assert self.redis is not None
        try:
            current = self.redis.get(self.leader_key)
            if current == self.instance_id:
                self.redis.delete(self.leader_key)
                log.info(
                    "LeaderElection: lock bırakıldı | instance=%s",
                    self.instance_id,
                )
        except Exception as exc:
            log.warning("LeaderElection.release hata: %s", exc)
        self._is_leader = False

    def get_leader_info(self) -> LeaderInfo:
        """Mevcut leader hakkında bilgi döner."""
        if self._degraded:
            return LeaderInfo(
                instance_id=self.instance_id,
                is_self=True,
                ttl_ms=self.lease_ms,
                elected_at=self._elected_at,
            )
        if self.redis is None:
            return LeaderInfo(instance_id="unknown", is_self=False)
        try:
            current = self.redis.get(self.leader_key)
            ttl = self.redis.pttl(self.leader_key)
            return LeaderInfo(
                instance_id=current or "none",
                is_self=(current == self.instance_id),
                ttl_ms=max(0, ttl),
                elected_at=self._elected_at if current == self.instance_id else 0.0,
            )
        except Exception:
            return LeaderInfo(instance_id="unknown", is_self=self._is_leader)

    # ── Yardımcılar ──────────────────────────────────────────────────────────

    def _enter_degraded(self, reason: str) -> None:
        if not self._degraded:
            log.warning(
                "LeaderElection: degraded moda geçildi — %s | "
                "instance=%s leader olarak devam",
                reason,
                self.instance_id,
            )
        self._degraded = True
        self._is_leader = True

    def status_dict(self) -> dict:
        """Monitoring / JSON endpoint için durum."""
        info = self.get_leader_info()
        return {
            "instance_id": self.instance_id,
            "is_leader": self._is_leader,
            "is_degraded": self._degraded,
            "leader_key": self.leader_key,
            "lease_ms": self.lease_ms,
            "current_leader": info.instance_id,
            "leader_ttl_ms": info.ttl_ms,
            "elected_at": self._elected_at,
        }
