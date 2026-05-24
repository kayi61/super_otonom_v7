"""
State Replicator — açık pozisyon ve PnL state'ini Redis'e yazar.

Leader instance state'i periyodik olarak Redis'e yazar.  Failover
durumunda yeni leader bu state'i Redis'ten okuyup kaldığı yerden
devam eder.

Redis yoksa dosya-tabanlı fallback (mevcut bot_state.json) kullanılır.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

log = logging.getLogger("super_otonom.ha.state_replicator")

STATE_KEY = os.getenv("HA_STATE_KEY", "ha:bot_state")
STATE_TTL_SEC = int(os.getenv("HA_STATE_TTL_SEC", "120"))
REPLICATE_INTERVAL_SEC = float(os.getenv("HA_REPLICATE_SEC", "10.0"))


@dataclass
class StateReplicator:
    """
    Açık pozisyon, PnL history ve capital state'ini Redis'e çoğaltır.

    Kullanım::

        rep = StateReplicator(redis_client, instance_id="node-1")
        rep.replicate(state_dict)   # leader her N saniyede çağırır
        state = rep.load_latest()   # yeni leader failover'da yükler
    """

    redis: Any = None
    instance_id: str = ""
    state_key: str = STATE_KEY
    state_ttl_sec: int = STATE_TTL_SEC
    replicate_interval: float = REPLICATE_INTERVAL_SEC

    _last_replicate: float = field(default=0.0, init=False, repr=False)
    _degraded: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.redis is None:
            self._degraded = True

    @property
    def is_degraded(self) -> bool:
        return self._degraded

    def replicate(self, state: Dict[str, Any], *, force: bool = False) -> bool:
        """
        State'i Redis'e yaz.

        Interval kontrolü yapar — çok sık çağrılsa bile throttle eder.
        ``force=True`` ile interval atlanır (shutdown öncesi son yazma).
        """
        now = time.time()
        if not force and (now - self._last_replicate < self.replicate_interval):
            return True

        payload = {
            "instance_id": self.instance_id,
            "timestamp": now,
            "state": state,
        }

        if self._degraded:
            # Dosya fallback — mevcut bot_state.json mekanizması devam
            return True

        try:
            data = json.dumps(payload, default=str, ensure_ascii=False)
            self.redis.set(self.state_key, data, ex=self.state_ttl_sec)
            self._last_replicate = now
            return True
        except Exception as exc:
            log.error("StateReplicator.replicate hata: %s", exc)
            return False

    def load_latest(self) -> Optional[Dict[str, Any]]:
        """
        Redis'ten en son kaydedilmiş state'i yükle.

        Failover sırasında yeni leader bu metodu çağırır.
        Dönüş: state dict veya None (veri yok / stale).
        """
        if self._degraded:
            return None

        try:
            raw = self.redis.get(self.state_key)
            if raw is None:
                return None
            payload = json.loads(raw)
            ts = float(payload.get("timestamp", 0))
            age = time.time() - ts
            if age > self.state_ttl_sec * 2:
                log.warning(
                    "StateReplicator: state çok eski | age=%.0fs limit=%ds",
                    age,
                    self.state_ttl_sec * 2,
                )
                return None
            return payload
        except Exception as exc:
            log.error("StateReplicator.load_latest hata: %s", exc)
            return None

    def extract_positions(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Replicated state'ten açık pozisyon listesini çıkar."""
        state = payload.get("state", {})
        return list(state.get("open_positions", {}).values())

    def extract_pnl_history(self, payload: Dict[str, Any]) -> Sequence[float]:
        """Replicated state'ten PnL history'yi çıkar."""
        state = payload.get("state", {})
        return state.get("pnl_history", [])

    def clear(self) -> None:
        """Redis'teki state'i sil (temiz shutdown)."""
        if self._degraded:
            return
        try:
            self.redis.delete(self.state_key)
        except Exception as exc:
            log.warning("StateReplicator.clear hata: %s", exc)

    def status_dict(self) -> dict:
        """Monitoring endpoint için durum."""
        info: Dict[str, Any] = {
            "is_degraded": self._degraded,
            "state_key": self.state_key,
            "state_ttl_sec": self.state_ttl_sec,
            "replicate_interval": self.replicate_interval,
            "last_replicate": self._last_replicate,
        }
        if not self._degraded and self.redis is not None:
            try:
                raw = self.redis.get(self.state_key)
                if raw:
                    payload = json.loads(raw)
                    info["last_state_ts"] = payload.get("timestamp")
                    info["last_state_instance"] = payload.get("instance_id")
                else:
                    info["last_state_ts"] = None
            except Exception:
                info["last_state_ts"] = "error"
        return info
