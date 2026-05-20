"""Tests for P&L Attribution + Unexplained PnL Drift Detection (VR-16).

Covers:
- attribute_pnl() — full decomposition into explained/trades/unexplained
- Known PnL decomposition → unexplained ≈ 0
- Drift detection at 10 bps threshold
- Multi-day series (attribute_pnl_series)
- Report generation (markdown)
- SimpleTrade helper
- Edge cases: zero capital, empty positions, no trades
- Risk package exports
- Sentinel presence
"""

from __future__ import annotations

from pathlib import Path

import pytest
from super_otonom.risk.pnl_attribution import (
    PNL_DRIFT_THRESHOLD,
    PNL_DRIFT_THRESHOLD_BPS,
    PnLAttributionSeries,
    SimpleTrade,
    attribute_pnl,
    attribute_pnl_series,
    attribution_to_dict,
    generate_attribution_report,
    pnl_attribution_active,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _simple_scenario(
    price_change: float = 10.0,
    trade_pnl: float = 0.0,
    extra_cost: float = 0.0,
) -> dict:
    """Build a simple scenario with one position (BTC).

    price_change: how much BTC price moved (market)
    trade_pnl: realized PnL from intraday trades
    extra_cost: unexplained component (fees, slippage, etc.)

    The end **quantity** is adjusted so that:
        explained = price_change  (mark-to-market on opening qty)
        actual    = price_change + trade_pnl + extra_cost
        unexplained = extra_cost
    """
    p_start = 100.0
    p_end = p_start + price_change
    qty_start = 1.0

    # explained = (p_end - p_start) * qty_start = price_change ✓
    # actual = qty_end * p_end - qty_start * p_start
    # We need actual = price_change + trade_pnl + extra_cost
    # So qty_end * p_end = p_start + price_change + trade_pnl + extra_cost
    # qty_end = (p_start + price_change + trade_pnl + extra_cost) / p_end
    if p_end != 0:
        qty_end = (p_start + price_change + trade_pnl + extra_cost) / p_end
    else:
        qty_end = 0.0

    trades = [SimpleTrade(pnl=trade_pnl)] if trade_pnl != 0 else []

    return {
        "positions_start": {"BTC": qty_start},
        "positions_end": {"BTC": qty_end},
        "prices_start": {"BTC": p_start},
        "prices_end": {"BTC": p_end},
        "trades": trades,
        "total_capital": 10000.0,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Core attribution — known decomposition
# ═══════════════════════════════════════════════════════════════════════════════


class TestKnownDecomposition:
    """Known PnL decomposition → unexplained ≈ 0."""

    def test_pure_mark_to_market(self):
        """Only price change, no trades → unexplained = 0."""
        sc = _simple_scenario(price_change=5.0)
        r = attribute_pnl(**sc)
        assert abs(r.explained - 5.0) < 1e-10
        assert abs(r.trades) < 1e-10
        assert abs(r.unexplained) < 1e-10
        assert abs(r.actual_pnl - 5.0) < 1e-10

    def test_pure_trade_pnl(self):
        """No price change, only trade PnL → unexplained = 0."""
        sc = _simple_scenario(price_change=0.0, trade_pnl=3.0)
        r = attribute_pnl(**sc)
        assert abs(r.explained) < 1e-10
        assert abs(r.trades - 3.0) < 1e-10
        assert abs(r.unexplained) < 1e-10

    def test_combined_explained_and_trades(self):
        """Both price change and trade PnL → unexplained = 0."""
        sc = _simple_scenario(price_change=5.0, trade_pnl=2.0)
        r = attribute_pnl(**sc)
        assert abs(r.explained - 5.0) < 1e-10
        assert abs(r.trades - 2.0) < 1e-10
        assert abs(r.unexplained) < 1e-10
        assert abs(r.actual_pnl - 7.0) < 1e-10

    def test_known_unexplained(self):
        """Inject known unexplained (e.g. fees) → residual matches."""
        fee = 0.5
        sc = _simple_scenario(price_change=5.0, trade_pnl=2.0, extra_cost=fee)
        r = attribute_pnl(**sc)
        assert abs(r.explained - 5.0) < 1e-10
        assert abs(r.trades - 2.0) < 1e-10
        assert abs(r.unexplained - fee) < 1e-10

    def test_negative_price_change(self):
        """Negative price move → negative explained PnL."""
        sc = _simple_scenario(price_change=-8.0)
        r = attribute_pnl(**sc)
        assert abs(r.explained - (-8.0)) < 1e-10
        assert abs(r.unexplained) < 1e-10

    def test_identity_actual_equals_sum(self):
        """actual_pnl = explained + trades + unexplained (always)."""
        sc = _simple_scenario(price_change=3.0, trade_pnl=1.5, extra_cost=0.25)
        r = attribute_pnl(**sc)
        recomposed = r.explained + r.trades + r.unexplained
        assert abs(r.actual_pnl - recomposed) < 1e-10


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Drift detection
# ═══════════════════════════════════════════════════════════════════════════════


class TestDriftDetection:
    def test_no_drift_below_threshold(self):
        """Unexplained < 10 bps → no drift."""
        # 10000 capital, 10 bps = 1.0 USDT
        sc = _simple_scenario(price_change=5.0, extra_cost=0.5)
        r = attribute_pnl(**sc)
        # 0.5 / 10000 = 5 bps < 10 bps
        assert r.drift_detected is False
        assert r.unexplained_bps < PNL_DRIFT_THRESHOLD_BPS

    def test_drift_above_threshold(self):
        """Unexplained > 10 bps → drift detected."""
        # 10000 capital, need > 1.0 USDT unexplained for > 10 bps
        sc = _simple_scenario(price_change=5.0, extra_cost=20.0)
        r = attribute_pnl(**sc)
        # 20.0 / 10000 = 0.002 = 20 bps > 10 bps
        assert r.drift_detected is True
        assert r.unexplained_bps > PNL_DRIFT_THRESHOLD_BPS

    def test_negative_drift_also_detected(self):
        """Negative unexplained (actual < expected) → drift detected."""
        sc = _simple_scenario(price_change=5.0, extra_cost=-20.0)
        r = attribute_pnl(**sc)
        # -20.0 / 10000 = -0.002 → |20 bps| > 10 bps
        assert r.drift_detected is True
        assert r.unexplained < 0

    def test_exact_threshold_boundary(self):
        """Exactly at threshold → NOT drift (strict >)."""
        # 10 bps of 10000 = 1.0 exactly
        sc = _simple_scenario(price_change=5.0, extra_cost=1.0)
        r = attribute_pnl(**sc)
        # 1.0 / 10000 = 10 bps = 0.001 exactly
        # PNL_DRIFT_THRESHOLD = 0.001, strict > → not drift
        assert r.drift_detected is False

    def test_just_above_threshold(self):
        """Just above threshold → drift detected."""
        # 10.01 / 10000 = 0.001001 → 10.01 bps, just over 10 bps
        sc = _simple_scenario(price_change=5.0, extra_cost=10.01)
        r = attribute_pnl(**sc)
        assert r.drift_detected is True

    def test_threshold_constants(self):
        assert PNL_DRIFT_THRESHOLD_BPS == 10
        assert abs(PNL_DRIFT_THRESHOLD - 0.001) < 1e-12

    def test_unexplained_bps_calculation(self):
        sc = _simple_scenario(price_change=0.0, extra_cost=5.0)
        r = attribute_pnl(**sc)
        # 5.0 / 10000 = 0.0005 = 5.0 bps
        assert abs(r.unexplained_bps - 5.0) < 1e-6


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Multi-position scenarios
# ═══════════════════════════════════════════════════════════════════════════════


class TestMultiPosition:
    def test_two_positions_explained(self):
        """Two assets, both move → explained = sum of moves."""
        r = attribute_pnl(
            positions_start={"BTC": 1.0, "ETH": 10.0},
            positions_end={"BTC": 1.0, "ETH": 10.0},
            prices_start={"BTC": 100.0, "ETH": 10.0},
            prices_end={"BTC": 110.0, "ETH": 12.0},
            trades=[],
            total_capital=10000.0,
        )
        # Explained: (110-100)*1 + (12-10)*10 = 10 + 20 = 30
        assert abs(r.explained - 30.0) < 1e-10
        assert abs(r.unexplained) < 1e-10

    def test_position_added_intraday(self):
        """New position at end → not in start → unexplained captures it."""
        r = attribute_pnl(
            positions_start={"BTC": 1.0},
            positions_end={"BTC": 1.0, "ETH": 5.0},
            prices_start={"BTC": 100.0, "ETH": 10.0},
            prices_end={"BTC": 100.0, "ETH": 10.0},
            trades=[SimpleTrade(pnl=0.0)],
            total_capital=10000.0,
        )
        # BTC unchanged, ETH nav_end = 50, but not in start
        # actual_pnl = (100 + 50) - (100) = 50
        # explained = (100-100)*1 = 0
        # trades = 0
        # unexplained = 50 - 0 - 0 = 50
        assert abs(r.unexplained - 50.0) < 1e-10

    def test_multiple_trades(self):
        r = attribute_pnl(
            positions_start={"BTC": 1.0},
            positions_end={"BTC": 1.0},
            prices_start={"BTC": 100.0},
            prices_end={"BTC": 105.0},
            trades=[SimpleTrade(pnl=1.0), SimpleTrade(pnl=2.0), SimpleTrade(pnl=-0.5)],
            total_capital=10000.0,
        )
        assert abs(r.trades - 2.5) < 1e-10
        assert r.n_trades == 3


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Edge cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    def test_zero_capital_raises(self):
        with pytest.raises(ValueError, match="total_capital must be positive"):
            attribute_pnl({}, {}, {}, {}, [], total_capital=0.0)

    def test_negative_capital_raises(self):
        with pytest.raises(ValueError, match="total_capital must be positive"):
            attribute_pnl({}, {}, {}, {}, [], total_capital=-100.0)

    def test_empty_positions(self):
        r = attribute_pnl(
            positions_start={},
            positions_end={},
            prices_start={},
            prices_end={},
            trades=[],
            total_capital=10000.0,
        )
        assert r.explained == 0.0
        assert r.trades == 0.0
        assert r.unexplained == 0.0
        assert r.drift_detected is False

    def test_missing_end_price(self):
        """Position has no end price → treated as 0."""
        r = attribute_pnl(
            positions_start={"BTC": 1.0},
            positions_end={"BTC": 1.0},
            prices_start={"BTC": 100.0},
            prices_end={},  # no end price
            trades=[],
            total_capital=10000.0,
        )
        # explained = (0 - 100) * 1 = -100
        # nav_end = 1 * 0 = 0, nav_start = 100
        # actual_pnl = 0 - 100 = -100
        # unexplained = -100 - (-100) - 0 = 0
        assert abs(r.explained - (-100.0)) < 1e-10
        assert abs(r.unexplained) < 1e-10

    def test_missing_start_price(self):
        """Position has no start price → treated as 0."""
        r = attribute_pnl(
            positions_start={"BTC": 1.0},
            positions_end={"BTC": 1.0},
            prices_start={},  # no start price
            prices_end={"BTC": 100.0},
            trades=[],
            total_capital=10000.0,
        )
        # explained = (100 - 0) * 1 = 100
        assert abs(r.explained - 100.0) < 1e-10

    def test_result_is_frozen(self):
        r = attribute_pnl({}, {}, {}, {}, [], total_capital=10000.0)
        with pytest.raises(AttributeError):
            r.explained = 999.0  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: SimpleTrade
# ═══════════════════════════════════════════════════════════════════════════════


class TestSimpleTrade:
    def test_default(self):
        t = SimpleTrade()
        assert t.pnl == 0.0
        assert t.symbol == ""

    def test_custom(self):
        t = SimpleTrade(pnl=5.5, symbol="ETH")
        assert t.pnl == 5.5
        assert t.symbol == "ETH"

    def test_frozen(self):
        t = SimpleTrade(pnl=1.0)
        with pytest.raises(AttributeError):
            t.pnl = 2.0  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Multi-day series
# ═══════════════════════════════════════════════════════════════════════════════


class TestPnLSeries:
    def test_basic_series(self):
        snapshots = []
        for day in range(5):
            sc = _simple_scenario(price_change=float(day), extra_cost=0.0)
            del sc["total_capital"]
            snapshots.append(sc)
        r = attribute_pnl_series(snapshots, total_capital=10000.0)
        assert isinstance(r, PnLAttributionSeries)
        assert len(r.daily) == 5
        assert r.drift_days == 0

    def test_series_with_drift(self):
        snapshots = []
        for day in range(5):
            # day 3: inject large unexplained (20 bps > 10 bps threshold)
            cost = 20.0 if day == 3 else 0.0
            sc = _simple_scenario(price_change=1.0, extra_cost=cost)
            del sc["total_capital"]
            snapshots.append(sc)
        r = attribute_pnl_series(snapshots, total_capital=10000.0)
        assert r.drift_days == 1
        assert r.daily[3].drift_detected is True
        assert r.daily[0].drift_detected is False

    def test_series_totals(self):
        snapshots = [
            _simple_scenario(price_change=2.0, trade_pnl=1.0, extra_cost=0.5),
            _simple_scenario(price_change=3.0, trade_pnl=0.5, extra_cost=0.0),
        ]
        for sc in snapshots:
            del sc["total_capital"]
        r = attribute_pnl_series(snapshots, total_capital=10000.0)
        assert abs(r.total_explained - 5.0) < 1e-10
        assert abs(r.total_trades - 1.5) < 1e-10
        assert abs(r.total_unexplained - 0.5) < 1e-10

    def test_series_dict_trades(self):
        """Trades as raw dicts (JSON-friendly input)."""
        snap = {
            "positions_start": {"BTC": 1.0},
            "positions_end": {"BTC": 1.0},
            "prices_start": {"BTC": 100.0},
            "prices_end": {"BTC": 105.0},
            "trades": [{"pnl": 2.0}, {"pnl": -0.5}],
        }
        r = attribute_pnl_series([snap], total_capital=10000.0)
        assert len(r.daily) == 1
        assert abs(r.daily[0].trades - 1.5) < 1e-10

    def test_empty_series(self):
        r = attribute_pnl_series([], total_capital=10000.0)
        assert len(r.daily) == 0
        assert r.drift_days == 0
        assert r.max_abs_unexplained_bps == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Report generation
# ═══════════════════════════════════════════════════════════════════════════════


class TestReport:
    def test_single_attribution_report(self, tmp_path: Path):
        sc = _simple_scenario(price_change=5.0, trade_pnl=1.0, extra_cost=0.3)
        r = attribute_pnl(**sc)
        path = generate_attribution_report(r, report_dir=tmp_path)
        text = path.read_text(encoding="utf-8")
        assert "# P&L Attribution Report" in text
        assert "## Attribution" in text
        assert "Explained" in text
        assert "Unexplained" in text
        assert "Drift Analysis" in text

    def test_series_report(self, tmp_path: Path):
        snapshots = []
        for _ in range(3):
            sc = _simple_scenario(price_change=2.0, extra_cost=0.1)
            del sc["total_capital"]
            snapshots.append(sc)
        r = attribute_pnl_series(snapshots, total_capital=10000.0)
        path = generate_attribution_report(r, report_dir=tmp_path)
        text = path.read_text(encoding="utf-8")
        assert "## Summary" in text
        assert "## Daily Detail" in text
        assert "Days analysed" in text

    def test_drift_report_shows_status(self, tmp_path: Path):
        # 20.0 / 10000 = 20 bps > 10 bps → drift
        sc = _simple_scenario(price_change=5.0, extra_cost=20.0)
        r = attribute_pnl(**sc)
        path = generate_attribution_report(r, report_dir=tmp_path)
        text = path.read_text(encoding="utf-8")
        assert "DRIFT DETECTED" in text


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Serialization
# ═══════════════════════════════════════════════════════════════════════════════


class TestSerialization:
    def test_attribution_to_dict(self):
        sc = _simple_scenario(price_change=5.0, trade_pnl=1.0)
        r = attribute_pnl(**sc)
        d = attribution_to_dict(r)
        assert isinstance(d, dict)
        assert "explained" in d
        assert "trades" in d
        assert "unexplained" in d
        assert "drift_detected" in d
        assert d["explained"] == r.explained
        assert d["trades"] == r.trades

    def test_dict_json_serializable(self):
        import json

        sc = _simple_scenario(price_change=5.0)
        r = attribute_pnl(**sc)
        d = attribution_to_dict(r)
        s = json.dumps(d)
        assert isinstance(s, str)


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Integration + exports + sentinel
# ═══════════════════════════════════════════════════════════════════════════════


class TestIntegration:
    def test_sentinel_present(self):
        assert pnl_attribution_active is True

    def test_exports_from_risk_package(self):
        from super_otonom.risk import (
            PNL_DRIFT_THRESHOLD_BPS,
            PnLAttribution,
            PnLAttributionSeries,
            SimpleTrade,
            attribute_pnl,
            attribute_pnl_series,
            attribution_to_dict,
            generate_attribution_report,
        )

        assert PNL_DRIFT_THRESHOLD_BPS == 10
        assert callable(attribute_pnl)
        assert callable(attribute_pnl_series)
        assert callable(attribution_to_dict)
        assert callable(generate_attribution_report)
        assert PnLAttribution is not None
        assert PnLAttributionSeries is not None
        assert SimpleTrade is not None

    def test_large_portfolio_performance(self):
        """100 positions should complete quickly."""
        pos = {f"SYM{i}": float(i + 1) for i in range(100)}
        prices_s = {f"SYM{i}": 100.0 + i for i in range(100)}
        prices_e = {f"SYM{i}": 101.0 + i for i in range(100)}
        trades = [SimpleTrade(pnl=0.1) for _ in range(50)]
        r = attribute_pnl(
            positions_start=pos,
            positions_end=pos,
            prices_start=prices_s,
            prices_end=prices_e,
            trades=trades,
            total_capital=1_000_000.0,
        )
        assert r.n_positions == 100
        assert r.n_trades == 50
        # Each position gained 1.0 * qty
        expected_explained = sum(float(i + 1) * 1.0 for i in range(100))
        assert abs(r.explained - expected_explained) < 1e-6
        expected_trades = 50 * 0.1
        assert abs(r.trades - expected_trades) < 1e-10
