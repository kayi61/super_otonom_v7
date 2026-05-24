"""TWAP / VWAP algo execution tests.

Validates:
- TWAP splits orders into equal time-weighted slices
- VWAP distributes slices by volume profile weights
- SliceOrder lifecycle (PENDING → SENT → FILLED / FAILED / CANCELLED)
- ExecutionPlan aggregation and fill tracking
- Market impact guard (max_slice_volume_pct)
- should_use_algo_execution threshold logic
- Edge cases: zero qty, tiny notional, cancel_remaining, due_slices
"""

from __future__ import annotations

import pytest
from super_otonom.execution.base import (
    AlgoType,
    ExecutionPlan,
    SliceOrder,
    SliceStatus,
    should_use_algo_execution,
)
from super_otonom.execution.twap import TwapScheduler
from super_otonom.execution.vwap import (
    _DEFAULT_CRYPTO_VOLUME_PROFILE,
    VwapScheduler,
    _normalize_profile,
    _select_profile_weights,
)

# ── TWAP tests ───────────────────────────────────────────────────────────────


class TestTwapScheduler:
    def test_twap_splits_orders_equal(self) -> None:
        """TWAP creates N equal slices summing to total qty."""
        sched = TwapScheduler(num_slices=5, duration_sec=300)
        plan = sched.create_plan(
            "BTC/USDT", "BUY", qty=1.0, price=60000, notional=60000,
            start_time=1000.0,
        )

        assert plan.algo == AlgoType.TWAP
        assert plan.num_slices == 5
        assert len(plan.slices) == 5
        assert plan.total_qty == 1.0
        assert plan.total_notional == 60000

        # Each slice gets equal qty
        for sl in plan.slices:
            assert sl.target_qty == pytest.approx(0.2, abs=1e-9)
            assert sl.weight == pytest.approx(0.2, abs=1e-9)

        # Sum of slice qtys equals total
        total = sum(s.target_qty for s in plan.slices)
        assert total == pytest.approx(1.0, abs=1e-9)

    def test_twap_timing_evenly_spaced(self) -> None:
        """Slices are evenly spaced across the duration."""
        sched = TwapScheduler(num_slices=4, duration_sec=200)
        plan = sched.create_plan(
            "ETH/USDT", "SELL", qty=10.0, price=3000, notional=30000,
            start_time=0.0,
        )

        times = [s.scheduled_at for s in plan.slices]
        assert times == [0.0, 50.0, 100.0, 150.0]

    def test_twap_minimum_two_slices(self) -> None:
        """num_slices is clamped to minimum 2."""
        sched = TwapScheduler(num_slices=1, duration_sec=60)
        plan = sched.create_plan(
            "SOL/USDT", "BUY", qty=100, price=150, notional=15000,
            start_time=0.0,
        )
        assert plan.num_slices >= 2
        assert len(plan.slices) >= 2

    def test_twap_market_impact_guard(self) -> None:
        """Large qty relative to volume → more slices to limit impact."""
        sched = TwapScheduler(
            num_slices=3,
            duration_sec=300,
            max_slice_volume_pct=0.01,  # 1% of avg volume per slice
        )
        plan = sched.create_plan(
            "BTC/USDT", "BUY", qty=100.0, price=60000, notional=6_000_000,
            avg_volume=1000.0,  # avg volume = 1000
            start_time=0.0,
        )
        # max_slice = 1000 * 0.01 = 10 → need at least 100/10+1 = 11 slices
        assert plan.num_slices >= 11

    def test_twap_slice_lifecycle(self) -> None:
        """Slice status transitions: PENDING → SENT → FILLED."""
        sched = TwapScheduler(num_slices=2, duration_sec=60)
        plan = sched.create_plan(
            "BTC/USDT", "BUY", qty=1.0, price=60000, notional=60000,
        )
        sl = plan.slices[0]
        assert sl.status == SliceStatus.PENDING

        sched.mark_sent(sl, "order_123")
        assert sl.status == SliceStatus.SENT
        assert sl.order_id == "order_123"

        sched.mark_filled(sl, filled_qty=0.5, fill_price=59990, fee=0.1)
        assert sl.status == SliceStatus.FILLED
        assert sl.filled_qty == 0.5
        assert sl.fill_price == 59990
        assert sl.fee == 0.1

    def test_twap_mark_failed(self) -> None:
        """Slice can be marked as failed."""
        sl = SliceOrder(index=0, target_qty=1.0)
        TwapScheduler.mark_failed(sl, "timeout")
        assert sl.status == SliceStatus.FAILED
        assert sl.error_msg == "timeout"

    def test_twap_cancel_remaining(self) -> None:
        """cancel_remaining cancels all PENDING slices."""
        sched = TwapScheduler(num_slices=4, duration_sec=120)
        plan = sched.create_plan(
            "BTC/USDT", "BUY", qty=2.0, price=60000, notional=120000,
        )
        # Fill first slice
        sched.mark_sent(plan.slices[0], "o1")
        sched.mark_filled(plan.slices[0], 0.5, 60000)

        cancelled = sched.cancel_remaining(plan, "emergency_stop")
        assert cancelled == 3  # 3 remaining PENDING slices
        assert all(
            s.status == SliceStatus.CANCELLED
            for s in plan.slices[1:]
        )
        assert plan.slices[0].status == SliceStatus.FILLED

    def test_twap_due_slices(self) -> None:
        """due_slices returns only slices whose time has come."""
        sched = TwapScheduler(num_slices=3, duration_sec=300)
        plan = sched.create_plan(
            "BTC/USDT", "BUY", qty=1.5, price=60000, notional=90000,
            start_time=1000.0,
        )
        # interval = 300/3 = 100s → slices at t=1000, 1100, 1200
        # At t=1050, only first slice (t=1000) is due
        due = sched.due_slices(plan, now=1050.0)
        assert len(due) == 1
        assert due[0].index == 0

        # At t=1150, first two slices (t=1000, t=1100) are due
        due = sched.due_slices(plan, now=1150.0)
        assert len(due) == 2

    def test_twap_sell_side(self) -> None:
        """TWAP works for SELL orders."""
        sched = TwapScheduler(num_slices=3, duration_sec=60)
        plan = sched.create_plan(
            "ETH/USDT", "SELL", qty=5.0, price=3000, notional=15000,
        )
        assert plan.side == "SELL"
        assert len(plan.slices) == 3


# ── VWAP tests ───────────────────────────────────────────────────────────────


class TestVwapScheduler:
    def test_vwap_volume_profile_weights(self) -> None:
        """VWAP distributes qty proportionally to volume profile."""
        profile = [1.0, 2.0, 3.0, 2.0, 1.0]  # simple profile
        sched = VwapScheduler(
            num_slices=5, duration_sec=300, volume_profile=profile,
        )
        plan = sched.create_plan(
            "BTC/USDT", "BUY", qty=9.0, price=60000, notional=540000,
            volume_profile=profile, start_time=0.0, start_hour=0,
        )

        assert plan.algo == AlgoType.VWAP
        assert plan.num_slices == 5

        # Normalize: [1,2,3,2,1] → [1/9, 2/9, 3/9, 2/9, 1/9]
        assert plan.slices[0].target_qty == pytest.approx(1.0, abs=0.01)
        assert plan.slices[1].target_qty == pytest.approx(2.0, abs=0.01)
        assert plan.slices[2].target_qty == pytest.approx(3.0, abs=0.01)

        # Sum equals total
        total = sum(s.target_qty for s in plan.slices)
        assert total == pytest.approx(9.0, abs=1e-6)

        # Weights sum to 1
        weight_sum = sum(s.weight for s in plan.slices)
        assert weight_sum == pytest.approx(1.0, abs=1e-6)

    def test_vwap_default_crypto_profile(self) -> None:
        """Uses default crypto U-shape profile when none provided."""
        sched = VwapScheduler(num_slices=5, duration_sec=300)
        plan = sched.create_plan(
            "BTC/USDT", "BUY", qty=1.0, price=60000, notional=60000,
            start_time=0.0, start_hour=0,
        )
        # Slices should have different weights (not uniform)
        weights = [s.weight for s in plan.slices]
        assert not all(w == weights[0] for w in weights)

    def test_vwap_market_impact_guard(self) -> None:
        """Large qty → more slices to cap per-slice volume."""
        sched = VwapScheduler(
            num_slices=3,
            duration_sec=300,
            max_slice_volume_pct=0.01,
        )
        plan = sched.create_plan(
            "BTC/USDT", "BUY", qty=50.0, price=60000, notional=3_000_000,
            avg_volume=500.0,
            start_time=0.0,
            start_hour=0,
        )
        # max_slice = 500 * 0.01 = 5 → need at least 50/5+1 = 11
        assert plan.num_slices >= 11

    def test_vwap_cancel_remaining(self) -> None:
        """cancel_remaining works for VWAP plans."""
        profile = [1.0, 1.0, 1.0]
        sched = VwapScheduler(num_slices=3, volume_profile=profile)
        plan = sched.create_plan(
            "ETH/USDT", "BUY", qty=3.0, price=3000, notional=9000,
            volume_profile=profile, start_hour=0,
        )
        sched.mark_filled(plan.slices[0], 1.0, 3000)
        cancelled = sched.cancel_remaining(plan, "halt")
        assert cancelled == 2

    def test_vwap_due_slices(self) -> None:
        """due_slices respects scheduled_at for VWAP."""
        profile = [1.0, 1.0, 1.0]
        sched = VwapScheduler(num_slices=3, duration_sec=300, volume_profile=profile)
        plan = sched.create_plan(
            "BTC/USDT", "BUY", qty=3.0, price=60000, notional=180000,
            volume_profile=profile, start_time=1000.0, start_hour=0,
        )
        due = sched.due_slices(plan, now=1050.0)
        assert len(due) == 1


# ── Profile helper tests ─────────────────────────────────────────────────────


class TestProfileHelpers:
    def test_normalize_profile(self) -> None:
        result = _normalize_profile([10.0, 20.0, 30.0, 40.0])
        assert sum(result) == pytest.approx(1.0)
        assert result[0] == pytest.approx(0.1)

    def test_normalize_profile_all_zeros(self) -> None:
        """All-zero profile → uniform."""
        result = _normalize_profile([0.0, 0.0, 0.0])
        assert len(result) == 3
        assert all(w == pytest.approx(1 / 3) for w in result)

    def test_select_profile_weights_wraps(self) -> None:
        """Profile wraps around when start_hour + num_slices > len."""
        profile = [1.0, 2.0, 3.0, 4.0]
        weights = _select_profile_weights(profile, 3, start_hour=3)
        # indices: 3, 0, 1 → raw = [4, 1, 2] → normalized
        assert len(weights) == 3
        assert sum(weights) == pytest.approx(1.0)

    def test_select_profile_weights_empty_profile(self) -> None:
        """Empty profile → uniform weights."""
        weights = _select_profile_weights([], 4, start_hour=0)
        assert len(weights) == 4
        assert all(w == pytest.approx(0.25) for w in weights)

    def test_default_crypto_profile_sane(self) -> None:
        """Default profile has 24 entries, all positive, sums close to 1."""
        assert len(_DEFAULT_CRYPTO_VOLUME_PROFILE) == 24
        assert all(v > 0 for v in _DEFAULT_CRYPTO_VOLUME_PROFILE)
        assert sum(_DEFAULT_CRYPTO_VOLUME_PROFILE) == pytest.approx(1.0, abs=0.01)


# ── ExecutionPlan tests ──────────────────────────────────────────────────────


class TestExecutionPlan:
    def test_plan_fill_ratio(self) -> None:
        plan = ExecutionPlan(total_qty=10.0)
        plan.filled_qty = 5.0
        assert plan.fill_ratio == pytest.approx(0.5)

    def test_plan_fill_ratio_zero_qty(self) -> None:
        plan = ExecutionPlan(total_qty=0.0)
        assert plan.fill_ratio == 0.0

    def test_plan_is_done(self) -> None:
        plan = ExecutionPlan(
            slices=[
                SliceOrder(index=0, status=SliceStatus.FILLED),
                SliceOrder(index=1, status=SliceStatus.FAILED),
                SliceOrder(index=2, status=SliceStatus.CANCELLED),
            ]
        )
        assert plan.is_done is True

    def test_plan_not_done_with_pending(self) -> None:
        plan = ExecutionPlan(
            slices=[
                SliceOrder(index=0, status=SliceStatus.FILLED),
                SliceOrder(index=1, status=SliceStatus.PENDING),
            ]
        )
        assert plan.is_done is False

    def test_plan_next_slice(self) -> None:
        plan = ExecutionPlan(
            slices=[
                SliceOrder(index=0, status=SliceStatus.FILLED, scheduled_at=100),
                SliceOrder(index=1, status=SliceStatus.PENDING, scheduled_at=200),
                SliceOrder(index=2, status=SliceStatus.PENDING, scheduled_at=150),
            ]
        )
        nxt = plan.next_slice
        assert nxt is not None
        assert nxt.index == 2  # scheduled_at=150 < 200

    def test_plan_update_aggregates(self) -> None:
        plan = ExecutionPlan(
            total_qty=2.0,
            slices=[
                SliceOrder(
                    index=0, status=SliceStatus.FILLED,
                    filled_qty=0.8, fill_price=60000, fee=0.5,
                ),
                SliceOrder(
                    index=1, status=SliceStatus.FILLED,
                    filled_qty=1.2, fill_price=60100, fee=0.7,
                ),
            ],
        )
        plan.update_aggregates()
        assert plan.filled_qty == pytest.approx(2.0)
        assert plan.total_fee == pytest.approx(1.2)
        expected_avg = (0.8 * 60000 + 1.2 * 60100) / 2.0
        assert plan.avg_fill_price == pytest.approx(expected_avg)
        assert plan.completed is True

    def test_plan_to_dict(self) -> None:
        sched = TwapScheduler(num_slices=2, duration_sec=60)
        plan = sched.create_plan(
            "BTC/USDT", "BUY", qty=1.0, price=60000, notional=60000,
        )
        d = plan.to_dict()
        assert d["algo"] == "TWAP"
        assert len(d["slices"]) == 2
        assert "fill_ratio" in d

    def test_slice_to_dict(self) -> None:
        sl = SliceOrder(index=0, target_qty=1.0, status=SliceStatus.PENDING)
        d = sl.to_dict()
        assert d["status"] == "PENDING"
        assert d["target_qty"] == 1.0


# ── Threshold tests ──────────────────────────────────────────────────────────


class TestThreshold:
    def test_should_use_algo_execution_above_threshold(self) -> None:
        assert should_use_algo_execution(10_000.0) is True

    def test_should_use_algo_execution_below_threshold(self) -> None:
        assert should_use_algo_execution(1_000.0) is False

    def test_should_use_algo_execution_at_threshold(self) -> None:
        # Default MIN_TWAP_NOTIONAL = 5000
        assert should_use_algo_execution(5_000.0) is True

    def test_should_use_algo_execution_zero(self) -> None:
        assert should_use_algo_execution(0.0) is False
