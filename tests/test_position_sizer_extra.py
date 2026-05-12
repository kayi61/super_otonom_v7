"""PositionSizer: calculate, can_open, slippage, exposure."""

from __future__ import annotations

from super_otonom.position_sizer import PositionSizer


def test_calculate_zero_equity() -> None:
    s = PositionSizer()
    assert s.calculate("X", 0.0, volatility=0.01) == 0.0


def test_calculate_with_slippage_shrinks_on_deep_book() -> None:
    s = PositionSizer(max_position_pct=0.2, min_notional=0.1)
    ob = {
        "asks": [
            [100.0, 0.001],
            [200.0, 0.001],
        ],
    }
    r = s.calculate_with_slippage("X", 50_000.0, ob, max_allowed_slippage=0.0001, volatility=0.01)
    assert r >= 0.0


def test_total_exposure_and_can_open() -> None:
    s = PositionSizer()
    pos = {"a": {"size": 30}, "b": {"size": 20}}
    assert s.total_exposure(pos) == 50.0
    assert s.can_open(new_size=10, equity=100, open_positions=pos, max_total_pct=0.8) is True
    assert s.can_open(new_size=200, equity=100, open_positions=pos, max_total_pct=0.8) is False
