"""
HA Coordinator — leader election, state replication ve health check
bileşenlerini orkestre eder.

BotEngine.shutdown() → coordinator.graceful_shutdown()
BotEngine.__init__ → coordinator.start()

Kullanım::

    coord = HACoordinator.from_env()
    coord.start()
    ...
    if coord.is_leader:
        # trading yap
        coord.on_tick(state_dict)
    ...
    coord.graceful_shutdown()
"""

from __future__ import annotations

import enum
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from super_otonom.ha.health_check import HAHealthCheck
from super_otonom.ha.leader_election import LeaderElection
from super_otonom.ha.state_replicator import StateReplicator

log = logging.getLogger("super_otonom.ha.coordinator")


class HARole(enum.Enum):
    LEADER = "leader"
    STANDBY = "standby"
    DEGRADED = "degraded"


@dataclass(frozen=True)
class HAStatus:
    """Immutable HA durum snapshot'ı."""

    role: HARole
    instance_id: str
    is_leader: bool
    is_degraded: bool
    uptime_sec: float
    tick_count: int
    leader_info_instance: str = ""
    leader_info_ttl_ms: int = 0


@dataclass
class HACoordinator:
    """
    Tüm HA bileşenlerini orkestre eden merkezi koordinatör.

    Active-passive model:
    - Leader: trading yapar, state'i Redis'e replike eder
    - Standby: leader lease'ini izler, lease dolunca devralır
    """

    election: LeaderElection
    replicator: StateReplicator
    health: HAHealthCheck

    _started: bool = field(default=False, init=False, repr=False)
    _start_time: float = field(default=0.0, init=False, repr=False)

    # ── Factory ──────────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls, redis_client: Any = None) -> HACoordinator:
        """
        Ortam değişkenlerinden HA coordinator oluştur.

        Redis yoksa tüm bileşenler degraded modda çalışır.
        """
        instance_id = os.getenv("HA_INSTANCE_ID", "")
        if not instance_id:
            import uuid

            instance_id = uuid.uuid4().hex[:12]

        election = LeaderElection(redis=redis_client, instance_id=instance_id)
        replicator = StateReplicator(redis=redis_client, instance_id=instance_id)
        health = HAHealthCheck(instance_id=instance_id)

        return cls(election=election, replicator=replicator, health=health)

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> bool:
        """
        HA başlat: leader election dene.

        Dönüş: bu instance leader mı.
        """
        self._started = True
        self._start_time = time.time()

        acquired = self.election.try_acquire()
        self.health.set_leader(acquired)

        if acquired:
            log.info(
                "HACoordinator: LEADER olarak başladı | id=%s",
                self.election.instance_id,
            )
            # Failover ise önceki state'i yükle
            prev = self.replicator.load_latest()
            if prev and prev.get("instance_id") != self.election.instance_id:
                log.info(
                    "HACoordinator: önceki leader state'i yüklendi | "
                    "from=%s ts=%.0f",
                    prev.get("instance_id"),
                    prev.get("timestamp", 0),
                )
        else:
            log.info(
                "HACoordinator: STANDBY olarak başladı | id=%s",
                self.election.instance_id,
            )

        return acquired

    def on_tick(self, state: Optional[Dict[str, Any]] = None) -> bool:
        """
        Her tick sonunda çağrılır.

        1. Heartbeat yenile (leader ise)
        2. Health kaydet
        3. State replike et (leader ise)
        4. Leader değilse: leader olup olmadığını kontrol et

        Dönüş: bu instance hâlâ leader mı.
        """
        self.health.record_tick()

        if self.election.is_leader:
            # Leader: heartbeat + state replicate
            still_leader = self.election.heartbeat()
            if not still_leader:
                log.warning("HACoordinator: leader kaybedildi!")
                self.health.set_leader(False)
                self.health.set_trading_ready(False)
                return False
            if state:
                self.replicator.replicate(state)
            return True

        # Standby: leader election tekrar dene
        acquired = self.election.try_acquire()
        if acquired:
            log.info("HACoordinator: standby → LEADER geçişi!")
            self.health.set_leader(True)
            prev = self.replicator.load_latest()
            if prev:
                log.info(
                    "HACoordinator: failover state yüklendi | ts=%.0f",
                    prev.get("timestamp", 0),
                )
        return acquired

    def graceful_shutdown(self, final_state: Optional[Dict[str, Any]] = None) -> None:
        """
        Temiz kapanış:

        1. Son state'i Redis'e yaz (force)
        2. Leader lock'u bırak
        3. State key'i temizleme (yeni leader yükleyecek)
        """
        log.info(
            "HACoordinator: graceful shutdown başladı | id=%s leader=%s",
            self.election.instance_id,
            self.election.is_leader,
        )

        if self.election.is_leader and final_state:
            self.replicator.replicate(final_state, force=True)

        self.election.release()
        self.health.set_leader(False)
        self.health.set_trading_ready(False)
        self._started = False

    # ── Properties ───────────────────────────────────────────────────────────

    @property
    def is_leader(self) -> bool:
        return self.election.is_leader

    @property
    def role(self) -> HARole:
        if self.election.is_degraded:
            return HARole.DEGRADED
        return HARole.LEADER if self.election.is_leader else HARole.STANDBY

    @property
    def instance_id(self) -> str:
        return self.election.instance_id

    # ── Status ───────────────────────────────────────────────────────────────

    def status(self) -> HAStatus:
        """Immutable HA durum snapshot'ı."""
        info = self.election.get_leader_info()
        return HAStatus(
            role=self.role,
            instance_id=self.election.instance_id,
            is_leader=self.election.is_leader,
            is_degraded=self.election.is_degraded,
            uptime_sec=round(time.time() - self._start_time, 1) if self._started else 0.0,
            tick_count=self.health._tick_count,
            leader_info_instance=info.instance_id,
            leader_info_ttl_ms=info.ttl_ms,
        )

    def full_status_dict(self) -> Dict[str, Any]:
        """Monitoring endpoint için tam JSON raporu."""
        return {
            "ha_role": self.role.value,
            "election": self.election.status_dict(),
            "replicator": self.replicator.status_dict(),
            "health": self.health.full_status(),
            "started": self._started,
        }

    def load_previous_state(self) -> Optional[Dict[str, Any]]:
        """Failover state'ini yükle — coordinator dışından erişim için."""
        return self.replicator.load_latest()
