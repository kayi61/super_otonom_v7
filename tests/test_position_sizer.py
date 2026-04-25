"""PositionSizer validate_and_calculate (Faz 1)."""
from __future__ import annotations

import time

from super_otonom.position_sizer import PositionSizer


def _order_book_healthy() -> dict:
    bids = [[50_000.0, 2.0 + i * 0.1] for i in range(5)]
    asks = [[50_100.0, 2.0 + i * 0.1] for i in range(5)]
    return {"bids": bids, "asks": asks}


def test_validate_fails_on_stale_candle() -> None:
    s = PositionSizer(max_position_pct=0.1, min_notional=5.0)
    old_ms = (time.time() - 5.0) * 1000.0
    r = s.validate_and_calculate(
        "BTC/USDT",
        10_000.0,
        _order_book_healthy(),
        last_candle_ts=old_ms,
        max_candle_age_ms=500.0,
        volatility=0.01,
        ai_conf=0.6,
    )
    assert r == 0.0


def test_validate_fails_on_empty_order_book() -> None:
    s = PositionSizer(max_position_pct=0.1, min_notional=5.0)
    now = time.time() * 1000.0
    assert (
        s.validate_and_calculate(
            "BTC/USDT",
            10_000.0,
            {"bids": [], "asks": []},
            last_candle_ts=now,
            volatility=0.01,
            ai_conf=0.6,
        )
        == 0.0
    )


def test_validate_fails_on_flash_crash_imbalance() -> None:
    s = PositionSizer(max_position_pct=0.1, min_notional=5.0)
    now = time.time() * 1000.0
    # Almost no bid depth vs ask → imbalance < 0.3
    ob = {
        "bids": [[50_000.0, 0.01]],
        "asks": [[50_100.0, 10.0]] * 5,
    }
    r = s.validate_and_calculate(
        "BTC/USDT",
        10_000.0,
        ob,
        last_candle_ts=now,
        min_bid_imbalance=0.3,
        volatility=0.01,
        ai_conf=0.6,
    )
    assert r == 0.0


def test_validate_returns_positive_on_sane_inputs() -> None:
    s = PositionSizer(max_position_pct=0.2, min_notional=1.0)
    now = time.time() * 1000.0
    r = s.validate_and_calculate(
        "BTC/USDT",
        50_000.0,
        _order_book_healthy(),
        last_candle_ts=now,
        volatility=0.02,
        ai_conf=0.7,
    )
    assert r > 0.0
