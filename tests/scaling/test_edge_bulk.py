"""Edge case yüzeyleri — OMEGA, merge, kill tracker (150 = 20+60+70)."""

from __future__ import annotations

import pytest
from super_otonom.kill_switch import HardLimitTracker
from super_otonom.omega_regime import compute_omega_regime
from super_otonom.pre_trade_gate import merge_entry_notional

_BQ2 = (45, 88)
_REG = ("NOISY", "TRENDING", "MEAN_REVERTING", "UNKNOWN", "")


@pytest.mark.parametrize("bq", _BQ2)
@pytest.mark.parametrize("reg", _REG)
@pytest.mark.parametrize("flash", (False, True))
def test_edge_omega_quality_regime_flash(bq: int, reg: str, flash: bool) -> None:
    oreg, qm, sf, adj, _ln = compute_omega_regime(
        {
            "regime": reg,
            "hurst": 0.52,
            "volatility": 0.02,
            "flash_crash": flash,
        },
        bq,
    )
    assert oreg
    assert 0.2 <= sf <= 1.2
    assert 0.4 <= qm <= 1.2
    assert 0 <= adj <= 100


@pytest.mark.parametrize("mo", range(10))
@pytest.mark.parametrize("wx", range(6))
def test_edge_merge_notional_grid(mo: int, wx: int) -> None:
    tech = float(mo * 25)
    if wx % 3 == 0:
        ob: object | None = None
    elif wx % 3 == 1:
        ob = float((wx % 5) * 30 + 1)
    else:
        ob = ("bad", "ob")[wx % 2]
    n, src, blk = merge_entry_notional(tech, ob)
    assert n >= 0.0
    assert src
    assert isinstance(blk, str)


@pytest.mark.parametrize("mx", range(5))
@pytest.mark.parametrize("wy", range(7))
@pytest.mark.parametrize("jz", range(2))
def test_edge_hard_limit_tracker_surface(mx: int, wy: int, jz: int) -> None:
    h = HardLimitTracker(
        max_orders=1 + (mx % 8),
        window_sec=0.08 + wy * 0.03,
        max_price_jump_pct=0.005 + (jz % 5) * 0.01,
    )
    for _ in range(min(3, 1 + mx % 3)):
        h.record_order()
    h.check_price_tick("S", 100.0 + jz * 0.1)
    h.check_price_tick("S", 100.05 + wy * 0.02)
    st = h.status_line()
    assert "orders_in_window" in st
