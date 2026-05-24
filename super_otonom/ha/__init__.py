"""
High-Availability / Multi-Instance desteği.

Active-passive failover: Redis-based leader election ile tek instance
trading yapar; standby instance'lar leader lease süresi dolunca devralır.
"""

from super_otonom.ha.coordinator import HACoordinator, HARole, HAStatus
from super_otonom.ha.health_check import HAHealthCheck
from super_otonom.ha.leader_election import LeaderElection, LeaderInfo
from super_otonom.ha.state_replicator import StateReplicator

__all__ = [
    "HACoordinator",
    "HAHealthCheck",
    "HARole",
    "HAStatus",
    "LeaderElection",
    "LeaderInfo",
    "StateReplicator",
]
