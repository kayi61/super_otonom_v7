"""TWAP (Time-Weighted Average Price) order slicing scheduler.

Splits a parent order into equal-sized child orders distributed
evenly across a time window.  Each slice fires at a fixed interval
(duration / num_slices).

Usage:
    scheduler = TwapScheduler()
    plan = scheduler.create_plan("BTC/USDT", "BUY", qty=0.5,
                                 price=60000, notional=30000)
    # plan.slices → list of SliceOrder with scheduled_at timestamps
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from super_otonom.execution.base import (
    DEFAULT_TWAP_DURATION_SEC,
    DEFAULT_TWAP_SLICES,
    MAX_SLICE_VOLUME_PCT,
    AlgoType,
    ExecutionPlan,
    SliceOrder,
    SliceStatus,
)

log = logging.getLogger("super_otonom.execution.twap")


class TwapScheduler:
    """Create and manage TWAP execution plans.

    Parameters
    ----------
    num_slices : int
        Number of equal child orders (default from env/5).
    duration_sec : float
        Total execution window in seconds (default from env/300).
    max_slice_volume_pct : float
        Max single slice as fraction of avg volume (market impact cap).
    """

    def __init__(
        self,
        num_slices: int = DEFAULT_TWAP_SLICES,
        duration_sec: float = DEFAULT_TWAP_DURATION_SEC,
        max_slice_volume_pct: float = MAX_SLICE_VOLUME_PCT,
    ) -> None:
        self.num_slices = max(num_slices, 2)  # minimum 2 slices
        self.duration_sec = max(float(duration_sec), 10.0)
        self.max_slice_volume_pct = max_slice_volume_pct

    def create_plan(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        notional: float,
        avg_volume: Optional[float] = None,
        start_time: Optional[float] = None,
    ) -> ExecutionPlan:
        """Build a TWAP execution plan with evenly spaced slices.

        Parameters
        ----------
        symbol : str
            Trading pair (e.g. "BTC/USDT").
        side : str
            "BUY" or "SELL".
        qty : float
            Total quantity to execute.
        price : float
            Reference price at plan creation.
        notional : float
            Total notional value (qty * price).
        avg_volume : float, optional
            Average volume for market impact guard.
        start_time : float, optional
            Unix timestamp for first slice (default: now).

        Returns
        -------
        ExecutionPlan with populated slices.
        """
        num = self._effective_num_slices(qty, avg_volume)
        t0 = start_time if start_time is not None else time.time()
        interval = self.duration_sec / num

        slice_qty = qty / num
        slice_notional = notional / num

        slices = []
        for i in range(num):
            slices.append(
                SliceOrder(
                    index=i,
                    target_qty=slice_qty,
                    target_notional=slice_notional,
                    weight=1.0 / num,
                    scheduled_at=t0 + i * interval,
                )
            )

        plan = ExecutionPlan(
            symbol=symbol,
            side=side.upper(),
            algo=AlgoType.TWAP,
            total_qty=qty,
            total_notional=notional,
            price_at_plan=price,
            num_slices=num,
            duration_sec=self.duration_sec,
            created_at=t0,
            slices=slices,
        )

        log.info(
            "TWAP plan | %s %s | qty=%.6f notional=%.2f | "
            "%d slices over %.0fs (interval=%.1fs) | plan=%s",
            side,
            symbol,
            qty,
            notional,
            num,
            self.duration_sec,
            interval,
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

    @staticmethod
    def mark_sent(sl: SliceOrder, order_id: str) -> None:
        """Mark a slice as sent to exchange."""
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
        """Mark a slice as filled."""
        sl.status = SliceStatus.FILLED
        sl.filled_qty = filled_qty
        sl.fill_price = fill_price
        sl.fee = fee
        sl.filled_at = time.time()

    @staticmethod
    def mark_failed(sl: SliceOrder, error_msg: str = "") -> None:
        """Mark a slice as failed."""
        sl.status = SliceStatus.FAILED
        sl.error_msg = error_msg

    @staticmethod
    def mark_cancelled(sl: SliceOrder, reason: str = "") -> None:
        """Mark remaining slices as cancelled (e.g. on emergency stop)."""
        sl.status = SliceStatus.CANCELLED
        sl.error_msg = reason

    def cancel_remaining(self, plan: ExecutionPlan, reason: str = "cancelled") -> int:
        """Cancel all PENDING slices in a plan.  Returns count cancelled."""
        count = 0
        for sl in plan.slices:
            if sl.status == SliceStatus.PENDING:
                self.mark_cancelled(sl, reason)
                count += 1
        plan.update_aggregates()
        return count

    def due_slices(self, plan: ExecutionPlan, now: Optional[float] = None) -> list:
        """Return PENDING slices whose scheduled_at <= now."""
        t = now or time.time()
        return [
            s for s in plan.slices
            if s.status == SliceStatus.PENDING and s.scheduled_at <= t
        ]
