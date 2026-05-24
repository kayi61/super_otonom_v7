"""VWAP (Volume-Weighted Average Price) order slicing scheduler.

Distributes child orders proportionally to an intraday volume profile.
Heavier slices during high-volume periods reduce market impact and
achieve fills closer to the volume-weighted average price.

Usage:
    scheduler = VwapScheduler()
    plan = scheduler.create_plan("BTC/USDT", "BUY", qty=0.5,
                                 price=60000, notional=30000,
                                 volume_profile=[0.15, 0.10, 0.08, ...])
"""

from __future__ import annotations

import logging
import time
from typing import List, Optional

from super_otonom.execution.base import (
    DEFAULT_TWAP_DURATION_SEC,
    DEFAULT_TWAP_SLICES,
    MAX_SLICE_VOLUME_PCT,
    AlgoType,
    ExecutionPlan,
    SliceOrder,
    SliceStatus,
)

log = logging.getLogger("super_otonom.execution.vwap")

# U-shaped crypto intraday volume profile (24 hourly buckets, normalized).
# Higher weight during Asian open (0-3 UTC), London open (7-9),
# US open (13-16), and late NY session (20-22).
_DEFAULT_CRYPTO_VOLUME_PROFILE: List[float] = [
    0.050, 0.048, 0.046, 0.044,   #  0- 3 UTC  (Asian prime)
    0.035, 0.032, 0.030, 0.038,   #  4- 7 UTC  (quiet -> London pre)
    0.044, 0.046, 0.042, 0.038,   #  8-11 UTC  (London)
    0.036, 0.044, 0.048, 0.050,   # 12-15 UTC  (US open)
    0.046, 0.042, 0.036, 0.034,   # 16-19 UTC  (US afternoon)
    0.038, 0.044, 0.046, 0.043,   # 20-23 UTC  (late NY / Asian pre)
]


def _normalize_profile(profile: List[float]) -> List[float]:
    """Normalize a volume profile so weights sum to 1.0."""
    total = sum(profile)
    if total <= 0:
        n = len(profile) or 1
        return [1.0 / n] * (len(profile) or 1)
    return [w / total for w in profile]


def _select_profile_weights(
    full_profile: List[float],
    num_slices: int,
    start_hour: Optional[int] = None,
) -> List[float]:
    """Extract and normalize `num_slices` consecutive weights from profile.

    Wraps around at 24 hours.  If profile has fewer entries than slices,
    cycles through the profile.
    """
    if not full_profile:
        return [1.0 / max(num_slices, 1)] * num_slices

    n = len(full_profile)
    hour = start_hour if start_hour is not None else int(time.time() / 3600) % n

    raw = []
    for i in range(num_slices):
        idx = (hour + i) % n
        raw.append(max(full_profile[idx], 0.0))

    return _normalize_profile(raw)


class VwapScheduler:
    """Create and manage VWAP execution plans.

    Parameters
    ----------
    num_slices : int
        Number of child orders (default from env/5).
    duration_sec : float
        Total execution window in seconds (default from env/300).
    volume_profile : list[float] | None
        Intraday volume profile (hourly buckets, any length).
        Defaults to a standard crypto U-shape profile.
    max_slice_volume_pct : float
        Max single slice as fraction of avg volume.
    """

    def __init__(
        self,
        num_slices: int = DEFAULT_TWAP_SLICES,
        duration_sec: float = DEFAULT_TWAP_DURATION_SEC,
        volume_profile: Optional[List[float]] = None,
        max_slice_volume_pct: float = MAX_SLICE_VOLUME_PCT,
    ) -> None:
        self.num_slices = max(num_slices, 2)
        self.duration_sec = max(float(duration_sec), 10.0)
        self.volume_profile = volume_profile or list(_DEFAULT_CRYPTO_VOLUME_PROFILE)
        self.max_slice_volume_pct = max_slice_volume_pct

    def create_plan(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        notional: float,
        volume_profile: Optional[List[float]] = None,
        avg_volume: Optional[float] = None,
        start_time: Optional[float] = None,
        start_hour: Optional[int] = None,
    ) -> ExecutionPlan:
        """Build a VWAP execution plan with volume-weighted slices.

        Parameters
        ----------
        symbol : str
            Trading pair.
        side : str
            "BUY" or "SELL".
        qty : float
            Total quantity.
        price : float
            Reference price.
        notional : float
            Total notional.
        volume_profile : list[float] | None
            Override volume profile for this plan.
        avg_volume : float | None
            Average volume for market impact guard.
        start_time : float | None
            Unix timestamp for first slice.
        start_hour : int | None
            Starting hour in profile (default: current UTC hour).

        Returns
        -------
        ExecutionPlan
        """
        num = self._effective_num_slices(qty, avg_volume)
        profile = volume_profile or self.volume_profile
        weights = _select_profile_weights(profile, num, start_hour=start_hour)

        t0 = start_time if start_time is not None else time.time()
        interval = self.duration_sec / num

        slices = []
        for i in range(num):
            w = weights[i]
            slices.append(
                SliceOrder(
                    index=i,
                    target_qty=qty * w,
                    target_notional=notional * w,
                    weight=w,
                    scheduled_at=t0 + i * interval,
                )
            )

        plan = ExecutionPlan(
            symbol=symbol,
            side=side.upper(),
            algo=AlgoType.VWAP,
            total_qty=qty,
            total_notional=notional,
            price_at_plan=price,
            num_slices=num,
            duration_sec=self.duration_sec,
            created_at=t0,
            slices=slices,
        )

        log.info(
            "VWAP plan | %s %s | qty=%.6f notional=%.2f | "
            "%d slices over %.0fs | weights=%s | plan=%s",
            side,
            symbol,
            qty,
            notional,
            num,
            self.duration_sec,
            [f"{w:.3f}" for w in weights],
            plan.plan_id,
        )
        return plan

    def _effective_num_slices(
        self,
        qty: float,
        avg_volume: Optional[float],
    ) -> int:
        """Adjust slice count upward if single slice would exceed volume cap."""
        num = self.num_slices
        if avg_volume and avg_volume > 0 and self.max_slice_volume_pct > 0:
            max_slice_qty = avg_volume * self.max_slice_volume_pct
            if max_slice_qty > 0:
                min_slices = int(qty / max_slice_qty) + 1
                num = max(num, min_slices)
        return num

    # ── Slice lifecycle (delegate to TwapScheduler statics) ──────────────

    @staticmethod
    def mark_sent(sl: SliceOrder, order_id: str) -> None:
        sl.status = SliceStatus.SENT
        sl.order_id = order_id
        sl.sent_at = time.time()

    @staticmethod
    def mark_filled(
        sl: SliceOrder,
        filled_qty: float,
        fill_price: float,
        fee: float = 0.0,
    ) -> None:
        sl.status = SliceStatus.FILLED
        sl.filled_qty = filled_qty
        sl.fill_price = fill_price
        sl.fee = fee
        sl.filled_at = time.time()

    @staticmethod
    def mark_failed(sl: SliceOrder, error_msg: str = "") -> None:
        sl.status = SliceStatus.FAILED
        sl.error_msg = error_msg

    def cancel_remaining(self, plan: ExecutionPlan, reason: str = "cancelled") -> int:
        count = 0
        for sl in plan.slices:
            if sl.status == SliceStatus.PENDING:
                sl.status = SliceStatus.CANCELLED
                sl.error_msg = reason
                count += 1
        plan.update_aggregates()
        return count

    def due_slices(self, plan: ExecutionPlan, now: Optional[float] = None) -> list:
        t = now or time.time()
        return [
            s for s in plan.slices
            if s.status == SliceStatus.PENDING and s.scheduled_at <= t
        ]
