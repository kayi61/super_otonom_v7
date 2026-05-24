"""Prompt 13 — HA / Multi-Instance testleri."""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pytest
from super_otonom.ha.coordinator import HACoordinator, HARole, HAStatus
from super_otonom.ha.health_check import HAHealthCheck
from super_otonom.ha.leader_election import LeaderElection, LeaderInfo
from super_otonom.ha.state_replicator import StateReplicator

pytestmark = pytest.mark.fastrun


# ── Fake Redis ───────────────────────────────────────────────────────────────


class FakeRedis:
    """Test amaçlı minimal Redis mock."""

    def __init__(self) -> None:
        self._store: Dict[str, str] = {}
        self._ttls: Dict[str, float] = {}  # absolute expiry time

    def set(
        self,
        name: str,
        value: Any,
        *,
        nx: bool = False,
        px: int = 0,
        ex: int = 0,
    ) -> Optional[bool]:
        self._expire_check(name)
        if nx and name in self._store:
            return None
        self._store[name] = str(value)
        if px > 0:
            self._ttls[name] = time.time() + px / 1000.0
        elif ex > 0:
            self._ttls[name] = time.time() + ex
        return True

    def get(self, name: str) -> Optional[str]:
        self._expire_check(name)
        return self._store.get(name)

    def delete(self, *names: str) -> int:
        count = 0
        for n in names:
            if n in self._store:
                del self._store[n]
                self._ttls.pop(n, None)
                count += 1
        return count

    def pttl(self, name: str) -> int:
        self._expire_check(name)
        if name not in self._store:
            return -2
        exp = self._ttls.get(name)
        if exp is None:
            return -1
        remaining = (exp - time.time()) * 1000
        return max(0, int(remaining))

    def _expire_check(self, name: str) -> None:
        exp = self._ttls.get(name)
        if exp is not None and time.time() > exp:
            self._store.pop(name, None)
            self._ttls.pop(name, None)


# ═══════════════════════════════════════════════════════════════════════════════
# LeaderElection
# ═══════════════════════════════════════════════════════════════════════════════


class TestLeaderElection:
    def test_acquire_leader(self) -> None:
        r = FakeRedis()
        le = LeaderElection(redis=r, instance_id="node-1")
        assert le.try_acquire() is True
        assert le.is_leader is True

    def test_second_instance_cannot_acquire(self) -> None:
        r = FakeRedis()
        le1 = LeaderElection(redis=r, instance_id="node-1")
        le2 = LeaderElection(redis=r, instance_id="node-2")
        le1.try_acquire()
        assert le2.try_acquire() is False
        assert le2.is_leader is False

    def test_release_and_reacquire(self) -> None:
        r = FakeRedis()
        le1 = LeaderElection(redis=r, instance_id="node-1")
        le2 = LeaderElection(redis=r, instance_id="node-2")
        le1.try_acquire()
        le1.release()
        assert le1.is_leader is False
        assert le2.try_acquire() is True

    def test_heartbeat_renews_lease(self) -> None:
        r = FakeRedis()
        le = LeaderElection(redis=r, instance_id="node-1", heartbeat_interval=0.0)
        le.try_acquire()
        assert le.heartbeat() is True
        assert r.get("ha:leader") == "node-1"

    def test_heartbeat_detects_lost_leadership(self) -> None:
        r = FakeRedis()
        le = LeaderElection(redis=r, instance_id="node-1", heartbeat_interval=0.0)
        le.try_acquire()
        # Başka biri devralmış
        r._store["ha:leader"] = "node-2"
        assert le.heartbeat() is False
        assert le.is_leader is False

    def test_degraded_mode_no_redis(self) -> None:
        le = LeaderElection(redis=None, instance_id="solo")
        assert le.is_degraded is True
        assert le.is_leader is True
        assert le.try_acquire() is True
        assert le.heartbeat() is True

    def test_get_leader_info(self) -> None:
        r = FakeRedis()
        le = LeaderElection(redis=r, instance_id="node-1")
        le.try_acquire()
        info = le.get_leader_info()
        assert info.instance_id == "node-1"
        assert info.is_self is True
        assert info.ttl_ms > 0

    def test_get_leader_info_other_leader(self) -> None:
        r = FakeRedis()
        le1 = LeaderElection(redis=r, instance_id="node-1")
        le2 = LeaderElection(redis=r, instance_id="node-2")
        le1.try_acquire()
        info = le2.get_leader_info()
        assert info.instance_id == "node-1"
        assert info.is_self is False

    def test_status_dict(self) -> None:
        r = FakeRedis()
        le = LeaderElection(redis=r, instance_id="node-1")
        le.try_acquire()
        d = le.status_dict()
        assert d["is_leader"] is True
        assert d["instance_id"] == "node-1"
        assert "leader_ttl_ms" in d

    def test_redis_error_enters_degraded(self) -> None:
        r = MagicMock()
        r.set.side_effect = ConnectionError("boom")
        le = LeaderElection(redis=r, instance_id="node-1")
        assert le.try_acquire() is True  # degraded → always leader
        assert le.is_degraded is True

    def test_release_noop_when_not_leader(self) -> None:
        r = FakeRedis()
        le = LeaderElection(redis=r, instance_id="node-1")
        le.release()  # should not raise

    def test_custom_key_and_lease(self) -> None:
        r = FakeRedis()
        le = LeaderElection(
            redis=r,
            instance_id="x",
            leader_key="custom:lock",
            lease_ms=5000,
        )
        le.try_acquire()
        assert r.get("custom:lock") == "x"

    def test_reacquire_own_lock(self) -> None:
        """Restart sonrası kendi lock'unu görünce leader olmalı."""
        r = FakeRedis()
        r.set("ha:leader", "node-1", px=15000)
        le = LeaderElection(redis=r, instance_id="node-1")
        assert le.try_acquire() is True
        assert le.is_leader is True


# ═══════════════════════════════════════════════════════════════════════════════
# StateReplicator
# ═══════════════════════════════════════════════════════════════════════════════


class TestStateReplicator:
    def test_replicate_and_load(self) -> None:
        r = FakeRedis()
        rep = StateReplicator(redis=r, instance_id="node-1", replicate_interval=0.0)
        state = {"open_positions": {"BTCUSDT": {"qty": 0.1}}, "pnl_history": [0.01, -0.02]}
        rep.replicate(state)
        loaded = rep.load_latest()
        assert loaded is not None
        assert loaded["state"]["open_positions"]["BTCUSDT"]["qty"] == 0.1
        assert loaded["instance_id"] == "node-1"

    def test_extract_positions(self) -> None:
        rep = StateReplicator(instance_id="x")
        payload = {
            "state": {"open_positions": {"BTC": {"qty": 1}, "ETH": {"qty": 2}}},
        }
        pos = rep.extract_positions(payload)
        assert len(pos) == 2

    def test_extract_pnl_history(self) -> None:
        rep = StateReplicator(instance_id="x")
        payload = {"state": {"pnl_history": [0.01, 0.02, -0.01]}}
        pnl = rep.extract_pnl_history(payload)
        assert len(pnl) == 3

    def test_degraded_no_redis(self) -> None:
        rep = StateReplicator(redis=None, instance_id="solo")
        assert rep.is_degraded is True
        assert rep.replicate({"test": 1}) is True  # no-op success
        assert rep.load_latest() is None

    def test_load_stale_returns_none(self) -> None:
        r = FakeRedis()
        rep = StateReplicator(redis=r, instance_id="x", state_ttl_sec=1, replicate_interval=0.0)
        old_payload = json.dumps(
            {"instance_id": "x", "timestamp": time.time() - 300, "state": {}}
        )
        r.set("ha:bot_state", old_payload)
        assert rep.load_latest() is None

    def test_clear(self) -> None:
        r = FakeRedis()
        rep = StateReplicator(redis=r, instance_id="x", replicate_interval=0.0)
        rep.replicate({"a": 1})
        rep.clear()
        assert r.get("ha:bot_state") is None

    def test_throttle(self) -> None:
        r = FakeRedis()
        rep = StateReplicator(redis=r, instance_id="x", replicate_interval=999.0)
        rep.replicate({"first": True}, force=True)
        # Throttled — should return True but not actually write
        old_ts = json.loads(r.get("ha:bot_state"))["timestamp"]
        rep.replicate({"second": True})
        new_ts = json.loads(r.get("ha:bot_state"))["timestamp"]
        assert old_ts == new_ts  # throttled, eski değer

    def test_force_bypasses_throttle(self) -> None:
        r = FakeRedis()
        rep = StateReplicator(redis=r, instance_id="x", replicate_interval=999.0)
        rep.replicate({"first": True}, force=True)
        old_ts = json.loads(r.get("ha:bot_state"))["timestamp"]
        time.sleep(0.01)
        rep.replicate({"second": True}, force=True)
        new_ts = json.loads(r.get("ha:bot_state"))["timestamp"]
        assert new_ts > old_ts

    def test_status_dict(self) -> None:
        r = FakeRedis()
        rep = StateReplicator(redis=r, instance_id="x", replicate_interval=0.0)
        rep.replicate({"a": 1})
        d = rep.status_dict()
        assert d["is_degraded"] is False
        assert d["last_state_instance"] == "x"

    def test_redis_error_returns_false(self) -> None:
        r = MagicMock()
        r.set.side_effect = ConnectionError("boom")
        rep = StateReplicator(redis=r, instance_id="x", replicate_interval=0.0)
        assert rep.replicate({"a": 1}) is False


# ═══════════════════════════════════════════════════════════════════════════════
# HAHealthCheck
# ═══════════════════════════════════════════════════════════════════════════════


class TestHAHealthCheck:
    def test_liveness_alive(self) -> None:
        hc = HAHealthCheck(instance_id="n1")
        hc.record_heartbeat()
        live = hc.liveness()
        assert live["alive"] is True
        assert live["instance_id"] == "n1"

    def test_liveness_dead(self) -> None:
        hc = HAHealthCheck(instance_id="n1", liveness_timeout_sec=0.0)
        hc._last_heartbeat = time.time() - 10
        live = hc.liveness()
        assert live["alive"] is False

    def test_readiness_leader_and_ready(self) -> None:
        hc = HAHealthCheck(instance_id="n1")
        hc.record_heartbeat()
        hc.set_leader(True)
        hc.set_trading_ready(True)
        r = hc.readiness()
        assert r["ready"] is True

    def test_readiness_standby_not_ready(self) -> None:
        hc = HAHealthCheck(instance_id="n1")
        hc.record_heartbeat()
        hc.set_leader(False)
        hc.set_trading_ready(True)
        r = hc.readiness()
        assert r["ready"] is False

    def test_readiness_not_trading_ready(self) -> None:
        hc = HAHealthCheck(instance_id="n1")
        hc.record_heartbeat()
        hc.set_leader(True)
        hc.set_trading_ready(False)
        r = hc.readiness()
        assert r["ready"] is False

    def test_record_tick(self) -> None:
        hc = HAHealthCheck(instance_id="n1")
        hc.record_tick()
        hc.record_tick()
        assert hc._tick_count == 2

    def test_record_error(self) -> None:
        hc = HAHealthCheck(instance_id="n1")
        hc.record_error()
        hc.record_error()
        assert hc._error_count == 2

    def test_component_health(self) -> None:
        hc = HAHealthCheck(instance_id="n1")
        hc.set_component_health("redis", True)
        hc.set_component_health("exchange", False)
        assert hc._components["redis"] is True
        assert hc._components["exchange"] is False

    def test_full_status(self) -> None:
        hc = HAHealthCheck(instance_id="n1")
        hc.record_tick()
        hc.set_leader(True)
        fs = hc.full_status()
        assert "liveness" in fs
        assert "readiness" in fs
        assert "ha" in fs
        assert fs["ha"]["is_leader"] is True

    def test_format_health_line(self) -> None:
        hc = HAHealthCheck(instance_id="node-1")
        hc.set_leader(True)
        hc.set_trading_ready(True)
        line = hc.format_health_line()
        assert "LEADER" in line
        assert "READY" in line
        assert "node-1" in line

    def test_format_health_line_standby(self) -> None:
        hc = HAHealthCheck(instance_id="node-2")
        line = hc.format_health_line()
        assert "STANDBY" in line

    def test_prometheus_labels(self) -> None:
        hc = HAHealthCheck(instance_id="n1")
        hc.set_leader(True)
        labels = hc.to_prometheus_labels()
        assert labels["role"] == "leader"

    def test_readiness_dead_not_ready(self) -> None:
        hc = HAHealthCheck(instance_id="n1", liveness_timeout_sec=0.0)
        hc._last_heartbeat = time.time() - 10
        hc.set_leader(True)
        hc.set_trading_ready(True)
        r = hc.readiness()
        assert r["ready"] is False  # dead → not ready


# ═══════════════════════════════════════════════════════════════════════════════
# HACoordinator
# ═══════════════════════════════════════════════════════════════════════════════


class TestHACoordinator:
    def _make_coordinator(
        self, redis: Any = None, instance_id: str = "test-1"
    ) -> HACoordinator:
        el = LeaderElection(redis=redis, instance_id=instance_id)
        rep = StateReplicator(redis=redis, instance_id=instance_id, replicate_interval=0.0)
        hc = HAHealthCheck(instance_id=instance_id)
        return HACoordinator(election=el, replicator=rep, health=hc)

    def test_start_as_leader(self) -> None:
        r = FakeRedis()
        coord = self._make_coordinator(r, "node-1")
        assert coord.start() is True
        assert coord.is_leader is True
        assert coord.role == HARole.LEADER

    def test_start_as_standby(self) -> None:
        r = FakeRedis()
        c1 = self._make_coordinator(r, "node-1")
        c1.start()
        c2 = self._make_coordinator(r, "node-2")
        assert c2.start() is False
        assert c2.role == HARole.STANDBY

    def test_on_tick_leader(self) -> None:
        r = FakeRedis()
        coord = self._make_coordinator(r, "node-1")
        coord.start()
        coord.election._last_heartbeat = 0  # force heartbeat
        state = {"open_positions": {}, "pnl_history": []}
        assert coord.on_tick(state) is True
        # State replicated
        assert r.get("ha:bot_state") is not None

    def test_on_tick_standby_tries_acquire(self) -> None:
        r = FakeRedis()
        c1 = self._make_coordinator(r, "node-1")
        c1.start()
        c2 = self._make_coordinator(r, "node-2")
        c2.start()  # standby
        # Node-1 still holds lock
        assert c2.on_tick() is False

    def test_failover(self) -> None:
        r = FakeRedis()
        c1 = self._make_coordinator(r, "node-1")
        c1.start()
        c1.election._last_heartbeat = 0
        c1.on_tick({"open_positions": {"BTC": {"qty": 0.5}}, "pnl_history": [0.01]})

        # Node-1 çöker — lock release
        c1.election.release()

        # Node-2 devralır
        c2 = self._make_coordinator(r, "node-2")
        assert c2.start() is True
        assert c2.is_leader is True

    def test_graceful_shutdown(self) -> None:
        r = FakeRedis()
        coord = self._make_coordinator(r, "node-1")
        coord.start()
        coord.graceful_shutdown({"final": True})
        assert coord.is_leader is False
        # Lock released
        assert r.get("ha:leader") is None

    def test_graceful_shutdown_writes_final_state(self) -> None:
        r = FakeRedis()
        coord = self._make_coordinator(r, "node-1")
        coord.start()
        coord.graceful_shutdown({"final_positions": {"BTC": 0.1}})
        raw = r.get("ha:bot_state")
        assert raw is not None
        assert "final_positions" in raw

    def test_status_snapshot(self) -> None:
        r = FakeRedis()
        coord = self._make_coordinator(r, "node-1")
        coord.start()
        s = coord.status()
        assert isinstance(s, HAStatus)
        assert s.is_leader is True
        assert s.role == HARole.LEADER
        assert s.instance_id == "node-1"

    def test_full_status_dict(self) -> None:
        r = FakeRedis()
        coord = self._make_coordinator(r, "node-1")
        coord.start()
        d = coord.full_status_dict()
        assert d["ha_role"] == "leader"
        assert "election" in d
        assert "replicator" in d
        assert "health" in d

    def test_degraded_mode(self) -> None:
        coord = self._make_coordinator(redis=None, instance_id="solo")
        coord.start()
        assert coord.role == HARole.DEGRADED
        assert coord.is_leader is True

    def test_from_env(self) -> None:
        coord = HACoordinator.from_env(redis_client=None)
        assert coord.election.is_degraded is True
        assert len(coord.instance_id) > 0

    def test_on_tick_lost_leadership(self) -> None:
        r = FakeRedis()
        coord = self._make_coordinator(r, "node-1")
        coord.start()
        coord.election._last_heartbeat = 0  # force heartbeat
        # Simulate another instance stealing leadership
        r._store["ha:leader"] = "node-2"
        assert coord.on_tick() is False
        assert coord.health._is_leader is False

    def test_standby_acquires_after_leader_crash(self) -> None:
        r = FakeRedis()
        c1 = self._make_coordinator(r, "node-1")
        c1.start()
        # Simulate crash: delete leader key
        r.delete("ha:leader")
        c2 = self._make_coordinator(r, "node-2")
        assert c2.on_tick() is True  # acquires leadership
        assert c2.is_leader is True

    def test_load_previous_state(self) -> None:
        r = FakeRedis()
        c1 = self._make_coordinator(r, "node-1")
        c1.start()
        c1.election._last_heartbeat = 0
        c1.on_tick({"positions": {"BTC": 1}})
        c1.election.release()

        c2 = self._make_coordinator(r, "node-2")
        prev = c2.load_previous_state()
        assert prev is not None
        assert prev["state"]["positions"]["BTC"] == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Integration — LeaderInfo dataclass
# ═══════════════════════════════════════════════════════════════════════════════


class TestLeaderInfo:
    def test_frozen(self) -> None:
        info = LeaderInfo(instance_id="a", is_self=True)
        with pytest.raises(AttributeError):
            info.instance_id = "b"  # type: ignore[misc]

    def test_defaults(self) -> None:
        info = LeaderInfo(instance_id="x", is_self=False)
        assert info.ttl_ms == 0
        assert info.elected_at == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# Import tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestImports:
    def test_package_imports(self) -> None:
        import super_otonom.ha as ha

        assert ha.HACoordinator is not None
        assert ha.HAHealthCheck is not None
        assert ha.HARole.LEADER.value == "leader"
        assert ha.HAStatus is not None
        assert ha.LeaderElection is not None
        assert ha.LeaderInfo is not None
        assert ha.StateReplicator is not None

    def test_ha_status_frozen(self) -> None:
        s = HAStatus(
            role=HARole.LEADER,
            instance_id="x",
            is_leader=True,
            is_degraded=False,
            uptime_sec=10.0,
            tick_count=5,
        )
        assert s.role == HARole.LEADER
        with pytest.raises(AttributeError):
            s.role = HARole.STANDBY  # type: ignore[misc]
