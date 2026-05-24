"""Shared types for algo execution — SliceOrder, ExecutionPlan, helpers."""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

# ── Configuration via env ────────────────────────────────────────────────────

def _env_float(name: str, default: float) -> float:
    """Read float from env with fallback."""
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# Minimum notional (USD) to activate TWAP/VWAP — below this, single-shot order
MIN_TWAP_NOTIONAL: float = _env_float("MIN_TWAP_NOTIONAL", 5_000.0)

# Default number of slices for TWAP
DEFAULT_TWAP_SLICES: int = _env_int("DEFAULT_TWAP_SLICES", 5)

# Default total duration for TWAP (seconds)
DEFAULT_TWAP_DURATION_SEC: int = _env_int("DEFAULT_TWAP_DURATION_SEC", 300)

# Maximum single slice as fraction of avg volume (market impact guard)
MAX_SLICE_VOLUME_PCT: float = _env_float("MAX_SLICE_VOLUME_PCT", 0.02)


# ── Enums ────────────────────────────────────────────────────────────────────


class SliceStatus(str, Enum):
    """Lifecycle state of a single order slice."""
    PENDING = "PENDING"
    SENT = "SENT"
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AlgoType(str, Enum):
    TWAP = "TWAP"
    VWAP = "VWAP"


# ── Data classes ─────────────────────────────────────────────────────────────


@dataclass
class SliceOrder:
    """A single child order within a TWAP/VWAP execution plan."""

    slice_id: str = field(default_factory=lambda: f"sl_{uuid.uuid4().hex[:12]}")
    index: int = 0                   # 0-based slice index
    target_qty: float = 0.0          # quantity to fill in this slice
    target_notional: float = 0.0     # notional value of this slice (USD)
    weight: float = 0.0              # fraction of total [0,1]
    scheduled_at: float = 0.0        # unix timestamp when this slice should fire
    status: SliceStatus = SliceStatus.PENDING

    # Fill tracking
    filled_qty: float = 0.0
    fill_price: float = 0.0
    fee: float = 0.0
    sent_at: float = 0.0
    filled_at: float = 0.0
    order_id: str = ""               # linked OrderEngine order_id
    error_msg: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class ExecutionPlan:
    """Complete TWAP/VWAP plan for a parent order."""

    plan_id: str = field(default_factory=lambda: f"ep_{uuid.uuid4().hex[:12]}")
    symbol: str = ""
    side: str = "BUY"
    algo: AlgoType = AlgoType.TWAP
    total_qty: float = 0.0
    total_notional: float = 0.0
    price_at_plan: float = 0.0       # reference price when plan was created
    num_slices: int = 0
    duration_sec: float = 0.0
    created_at: float = field(default_factory=time.time)

    slices: List[SliceOrder] = field(default_factory=list)

    # Aggregate tracking
    filled_qty: float = 0.0
    filled_notional: float = 0.0
    avg_fill_price: float = 0.0
    total_fee: float = 0.0
    completed: bool = False

    @property
    def fill_ratio(self) -> float:
        """Fraction of total qty filled [0, 1]."""
        if self.total_qty <= 0:
            return 0.0
        return min(self.filled_qty / self.total_qty, 1.0)

    @property
    def pending_slices(self) -> List[SliceOrder]:
        return [s for s in self.slices if s.status == SliceStatus.PENDING]

    @property
    def next_slice(self) -> Optional[SliceOrder]:
        """Next PENDING slice by scheduled time."""
        pending = self.pending_slices
        if not pending:
            return None
        return min(pending, key=lambda s: s.scheduled_at)

    @property
    def is_done(self) -> bool:
        """True when all slices are in a terminal state."""
        terminal = {SliceStatus.FILLED, SliceStatus.FAILED, SliceStatus.CANCELLED}
        return all(s.status in terminal for s in self.slices)

    def update_aggregates(self) -> None:
        """Recompute aggregate fill stats from slices."""
        total_qty = 0.0
        total_cost = 0.0
        total_fee = 0.0
        for s in self.slices:
            if s.status in (SliceStatus.FILLED, SliceStatus.PARTIAL):
                total_qty += s.filled_qty
                total_cost += s.filled_qty * s.fill_price
                total_fee += s.fee
        self.filled_qty = total_qty
        self.total_fee = total_fee
        if total_qty > 0:
            self.avg_fill_price = total_cost / total_qty
            self.filled_notional = total_cost
        self.completed = self.is_done

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["algo"] = self.algo.value
        d["slices"] = [s.to_dict() for s in self.slices]
        d["fill_ratio"] = self.fill_ratio
        return d


def should_use_algo_execution(notional: float) -> bool:
    """Return True if notional exceeds MIN_TWAP_NOTIONAL threshold."""
    return notional >= MIN_TWAP_NOTIONAL
