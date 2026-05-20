"""Tests for Basel Traffic Light VaR backtest (VR-15).

Covers:
- basel_traffic_light() — zone classification + capital add-on
- basel_traffic_light_from_pnl() — end-to-end from PnL + VaR
- TrafficLightResult frozen dataclass
- GREEN zone: 0-4 exceedances
- YELLOW zone: 5-9 exceedances with graduated add-ons
- RED zone: 10+ exceedances
- generate_backtest_report() with traffic light section
- Boundary cases, windowing, edge conditions
- Risk package exports
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import numpy as np
import pytest
from super_otonom.risk.var_backtest import (
    BASEL_WINDOW,
    TrafficLightResult,
    basel_traffic_light,
    basel_traffic_light_from_pnl,
    generate_backtest_report,
    kupiec_pof,
    run_backtest_suite,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _craft_pnl_series(
    n: int, n_exceed: int, var_val: float = 0.05, seed: int = 42,
) -> tuple[List[float], float]:
    """Create a PnL series with exactly n_exceed exceedances."""
    rng = np.random.RandomState(seed)
    pnl: List[float] = []
    placed = 0
    for i in range(n):
        if placed < n_exceed and i < n_exceed:
            pnl.append(-(var_val + 0.01 + rng.random() * 0.02))
            placed += 1
        else:
            pnl.append(abs(rng.normal(0.001, 0.02)))
    return pnl, var_val


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: basel_traffic_light (direct exceedance count)
# ═══════════════════════════════════════════════════════════════════════════════


class TestBaselTrafficLight:
    """Core zone classification from exceedance count."""

    def test_green_zero_exceedances(self):
        r = basel_traffic_light(0)
        assert r.zone == "GREEN"
        assert r.capital_addon == 0.0
        assert r.exceedances == 0

    def test_green_four_exceedances(self):
        r = basel_traffic_light(4)
        assert r.zone == "GREEN"
        assert r.capital_addon == 0.0
        assert r.exceedances == 4

    def test_yellow_five_exceedances(self):
        r = basel_traffic_light(5)
        assert r.zone == "YELLOW"
        assert r.capital_addon == 0.40
        assert r.exceedances == 5

    def test_yellow_six_exceedances(self):
        r = basel_traffic_light(6)
        assert r.zone == "YELLOW"
        assert r.capital_addon == 0.50

    def test_yellow_seven_exceedances(self):
        r = basel_traffic_light(7)
        assert r.zone == "YELLOW"
        assert r.capital_addon == 0.65

    def test_yellow_eight_exceedances(self):
        r = basel_traffic_light(8)
        assert r.zone == "YELLOW"
        assert r.capital_addon == 0.75

    def test_yellow_nine_exceedances(self):
        r = basel_traffic_light(9)
        assert r.zone == "YELLOW"
        assert r.capital_addon == 0.85

    def test_red_ten_exceedances(self):
        r = basel_traffic_light(10)
        assert r.zone == "RED"
        assert r.capital_addon == 1.0
        assert r.exceedances == 10

    def test_red_high_exceedances(self):
        r = basel_traffic_light(50)
        assert r.zone == "RED"
        assert r.capital_addon == 1.0

    def test_negative_exceedances_clamped(self):
        """Negative exceedance count should be clamped to 0 → GREEN."""
        r = basel_traffic_light(-3)
        assert r.zone == "GREEN"
        assert r.exceedances == 0
        assert r.capital_addon == 0.0

    def test_default_confidence(self):
        r = basel_traffic_light(0)
        assert r.confidence == 0.99

    def test_custom_confidence(self):
        r = basel_traffic_light(0, conf=0.95)
        assert r.confidence == 0.95

    def test_default_window(self):
        r = basel_traffic_light(0)
        assert r.window == BASEL_WINDOW
        assert r.window == 250

    def test_custom_window(self):
        r = basel_traffic_light(0, window=500)
        assert r.window == 500

    def test_result_is_frozen(self):
        r = basel_traffic_light(3)
        with pytest.raises(AttributeError):
            r.zone = "RED"  # type: ignore[misc]

    def test_green_yellow_boundary(self):
        """4 → GREEN, 5 → YELLOW (boundary check)."""
        r4 = basel_traffic_light(4)
        r5 = basel_traffic_light(5)
        assert r4.zone == "GREEN"
        assert r5.zone == "YELLOW"

    def test_yellow_red_boundary(self):
        """9 → YELLOW, 10 → RED (boundary check)."""
        r9 = basel_traffic_light(9)
        r10 = basel_traffic_light(10)
        assert r9.zone == "YELLOW"
        assert r10.zone == "RED"


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: graduated capital add-ons
# ═══════════════════════════════════════════════════════════════════════════════


class TestGraduatedAddons:
    """Verify Basel Committee graduated capital multiplier add-ons."""

    def test_addon_monotonically_increasing(self):
        """Capital add-on increases with exceedance count in yellow zone."""
        addons = [
            basel_traffic_light(e).capital_addon for e in range(5, 10)
        ]
        for i in range(1, len(addons)):
            assert addons[i] > addons[i - 1], (
                f"Add-on for {5 + i} exceedances ({addons[i]}) "
                f"should be > add-on for {4 + i} ({addons[i - 1]})"
            )

    def test_green_addon_always_zero(self):
        for e in range(5):
            r = basel_traffic_light(e)
            assert r.capital_addon == 0.0, f"{e} exceedances should have 0 add-on"

    def test_red_addon_always_one(self):
        for e in [10, 15, 25, 100]:
            r = basel_traffic_light(e)
            assert r.capital_addon == 1.0, f"{e} exceedances should have 1.0 add-on"

    def test_exact_basel_table(self):
        """Verify exact values from Basel Committee table."""
        expected = {5: 0.40, 6: 0.50, 7: 0.65, 8: 0.75, 9: 0.85}
        for exc, addon in expected.items():
            r = basel_traffic_light(exc)
            assert r.capital_addon == addon, (
                f"Basel table: {exc} exc → +{addon}, got +{r.capital_addon}"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: basel_traffic_light_from_pnl
# ═══════════════════════════════════════════════════════════════════════════════


class TestTrafficLightFromPnL:
    """End-to-end: PnL + VaR → traffic light."""

    def test_green_from_pnl(self):
        pnl, var_val = _craft_pnl_series(250, n_exceed=2)
        r = basel_traffic_light_from_pnl(pnl, var_val)
        assert r.zone == "GREEN"
        assert r.exceedances == 2
        assert r.window == 250

    def test_yellow_from_pnl(self):
        pnl, var_val = _craft_pnl_series(250, n_exceed=7)
        r = basel_traffic_light_from_pnl(pnl, var_val)
        assert r.zone == "YELLOW"
        assert r.exceedances == 7
        assert r.capital_addon == 0.65

    def test_red_from_pnl(self):
        pnl, var_val = _craft_pnl_series(250, n_exceed=12)
        r = basel_traffic_light_from_pnl(pnl, var_val)
        assert r.zone == "RED"
        assert r.exceedances == 12

    def test_uses_last_250_obs(self):
        """With 500 obs, should only use last 250."""
        # First 250: many exceedances, last 250: few
        pnl_early, var_val = _craft_pnl_series(250, n_exceed=20, seed=11)
        pnl_late, _ = _craft_pnl_series(250, n_exceed=2, seed=22)
        pnl = pnl_early + pnl_late
        r = basel_traffic_light_from_pnl(pnl, var_val)
        assert r.zone == "GREEN"
        assert r.exceedances == 2

    def test_short_series_uses_all(self):
        """Fewer than 250 obs → use all available (with warning)."""
        pnl, var_val = _craft_pnl_series(100, n_exceed=3)
        r = basel_traffic_light_from_pnl(pnl, var_val)
        assert r.zone == "GREEN"
        assert r.window == 100
        assert r.exceedances == 3

    def test_scalar_var(self):
        pnl, var_val = _craft_pnl_series(250, n_exceed=5)
        r = basel_traffic_light_from_pnl(pnl, var_val)
        assert r.exceedances == 5

    def test_vector_var(self):
        n = 250
        var_val = 0.05
        pnl, _ = _craft_pnl_series(n, n_exceed=5)
        var_series = [var_val] * n
        r = basel_traffic_light_from_pnl(pnl, var_series)
        assert r.exceedances == 5

    def test_length_mismatch_raises(self):
        pnl = [0.01] * 100
        var_ = [0.05] * 50
        with pytest.raises(ValueError, match="length"):
            basel_traffic_light_from_pnl(pnl, var_)

    def test_no_exceedances(self):
        pnl = [0.01] * 250
        r = basel_traffic_light_from_pnl(pnl, 0.05)
        assert r.zone == "GREEN"
        assert r.exceedances == 0

    def test_all_exceedances(self):
        pnl = [-0.10] * 250
        r = basel_traffic_light_from_pnl(pnl, 0.05)
        assert r.zone == "RED"
        assert r.exceedances == 250

    def test_custom_window(self):
        pnl, var_val = _craft_pnl_series(500, n_exceed=3)
        r = basel_traffic_light_from_pnl(pnl, var_val, window=500)
        assert r.window == 500


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Report generation with traffic light
# ═══════════════════════════════════════════════════════════════════════════════


class TestReportTrafficLight:
    def test_report_includes_traffic_light_section(self, tmp_path: Path):
        pnl, var_val = _craft_pnl_series(250, n_exceed=3)
        kupiec = kupiec_pof(pnl, var_val, conf=0.99)
        tl = basel_traffic_light(3)
        path = generate_backtest_report(kupiec, report_dir=tmp_path, traffic_light=tl)
        text = path.read_text(encoding="utf-8")
        assert "## Basel Traffic Light" in text
        assert "GREEN" in text
        assert "250d" in text

    def test_report_yellow_zone(self, tmp_path: Path):
        pnl, var_val = _craft_pnl_series(250, n_exceed=7)
        kupiec = kupiec_pof(pnl, var_val, conf=0.99)
        tl = basel_traffic_light(7)
        path = generate_backtest_report(kupiec, report_dir=tmp_path, traffic_light=tl)
        text = path.read_text(encoding="utf-8")
        assert "YELLOW" in text
        assert "+0.65" in text

    def test_report_red_zone_triggers_review(self, tmp_path: Path):
        tl = basel_traffic_light(12)
        kupiec = kupiec_pof([0.01] * 100, 0.05, conf=0.99)
        path = generate_backtest_report(kupiec, report_dir=tmp_path, traffic_light=tl)
        text = path.read_text(encoding="utf-8")
        assert "**RED**" in text
        assert "MODEL REVIEW REQUIRED" in text

    def test_report_without_traffic_light(self, tmp_path: Path):
        """No traffic_light arg → no section."""
        kupiec = kupiec_pof([0.01] * 100, 0.05, conf=0.99)
        path = generate_backtest_report(kupiec, report_dir=tmp_path)
        text = path.read_text(encoding="utf-8")
        assert "## Basel Traffic Light" not in text

    def test_report_traffic_light_with_multi_conf(self, tmp_path: Path):
        rng = np.random.RandomState(42)
        n = 250
        pnl = [rng.normal(0.001, 0.03) for _ in range(n)]
        results = run_backtest_suite(pnl, {0.95: 0.05, 0.99: 0.08})
        tl = basel_traffic_light(2)
        path = generate_backtest_report(results, report_dir=tmp_path, traffic_light=tl)
        text = path.read_text(encoding="utf-8")
        assert "## Kupiec POF" in text
        assert "## Basel Traffic Light" in text


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Integration + sentinel + exports
# ═══════════════════════════════════════════════════════════════════════════════


class TestIntegration:
    def test_exports_from_risk_package(self):
        from super_otonom.risk import (
            BASEL_WINDOW,
            TrafficLightResult,
            basel_traffic_light,
            basel_traffic_light_from_pnl,
        )

        assert BASEL_WINDOW == 250
        assert TrafficLightResult is not None
        assert callable(basel_traffic_light)
        assert callable(basel_traffic_light_from_pnl)

    def test_traffic_light_consistent_with_kupiec(self):
        """Exceedance count from Kupiec and traffic light should agree."""
        pnl, var_val = _craft_pnl_series(250, n_exceed=5)
        kup = kupiec_pof(pnl, var_val, conf=0.99)
        tl = basel_traffic_light_from_pnl(pnl, var_val, conf=0.99)
        assert tl.exceedances == kup.exceedances

    def test_all_zones_sweep(self):
        """Sweep through all zones with a single parametrized approach."""
        cases = [
            (0, "GREEN"), (4, "GREEN"),
            (5, "YELLOW"), (9, "YELLOW"),
            (10, "RED"), (20, "RED"),
        ]
        for exc, expected_zone in cases:
            r = basel_traffic_light(exc)
            assert r.zone == expected_zone, (
                f"{exc} exceedances → expected {expected_zone}, got {r.zone}"
            )

    def test_dataclass_fields(self):
        r = TrafficLightResult()
        assert r.zone == "GREEN"
        assert r.exceedances == 0
        assert r.capital_addon == 0.0
        assert r.window == 250
        assert r.confidence == 0.99
