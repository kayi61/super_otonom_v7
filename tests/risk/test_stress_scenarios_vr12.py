"""VR-12 — Stress Scenario Library + Reverse Stress Test.

Tests:
  - Scenario loading from JSON grid (5+ scenarios)
  - StressScenario dataclass construction
  - Forward stress: single scenario PnL computation
  - Shock resolution priority: exact → category → "all"
  - Stress grid runner: worst scenario selection
  - Reverse stress: finds minimum shock for target loss
  - Per-asset PnL breakdown
  - Edge cases (empty portfolio, zero NAV, no-loss scenarios)
  - Report generation
  - Deterministic reproducibility
  - Known-value synthetic portfolio validation
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from super_otonom.risk.stress_scenarios import (
    ForwardStressResult,
    ReverseStressResult,
    StressGridResult,
    StressScenario,
    forward_stress,
    forward_stress_detailed,
    generate_stress_report,
    load_scenarios,
    reverse_stress,
    run_stress_grid,
    save_scenarios,
)

pytestmark = pytest.mark.risk

GRID_PATH = Path(__file__).resolve().parents[2] / "data" / "var_stress_grid_default.json"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _btc_heavy_portfolio() -> dict[str, float]:
    return {"BTC": 60000, "ETH": 25000, "SOL": 10000, "DOGE": 5000}


def _equal_weight_portfolio() -> dict[str, float]:
    return {"BTC": 25000, "ETH": 25000, "SOL": 25000, "AVAX": 25000}


# ── Grid file tests ──────────────────────────────────────────────────────────

class TestGridFile:
    def test_grid_file_exists(self) -> None:
        assert GRID_PATH.is_file()

    def test_grid_valid_json(self) -> None:
        data = json.loads(GRID_PATH.read_text(encoding="utf-8"))
        assert isinstance(data, list)

    def test_grid_has_at_least_5_scenarios(self) -> None:
        data = json.loads(GRID_PATH.read_text(encoding="utf-8"))
        assert len(data) >= 5

    def test_each_scenario_has_required_fields(self) -> None:
        data = json.loads(GRID_PATH.read_text(encoding="utf-8"))
        for i, sc in enumerate(data):
            assert "name" in sc, f"scenario[{i}]: missing 'name'"
            assert "shocks" in sc, f"scenario[{i}]: missing 'shocks'"
            assert isinstance(sc["shocks"], dict)

    def test_scenario_names_unique(self) -> None:
        data = json.loads(GRID_PATH.read_text(encoding="utf-8"))
        names = [sc["name"] for sc in data]
        assert len(names) == len(set(names))


# ── StressScenario dataclass ─────────────────────────────────────────────────

class TestStressScenario:
    def test_from_dict_with_horizon_h(self) -> None:
        d = {"name": "test", "shocks": {"BTC": -0.10}, "horizon_h": 4}
        sc = StressScenario.from_dict(d)
        assert sc.name == "test"
        assert sc.shocks == {"BTC": -0.10}
        assert sc.horizon_h == 4.0

    def test_from_dict_with_horizon_min(self) -> None:
        d = {"name": "flash", "shocks": {"BTC": -0.05}, "horizon_min": 30}
        sc = StressScenario.from_dict(d)
        assert sc.horizon_h == 0.5

    def test_frozen(self) -> None:
        sc = StressScenario(name="t", shocks={"BTC": -0.1})
        with pytest.raises(AttributeError):
            sc.name = "x"  # type: ignore[misc]


# ── Load / Save scenarios ────────────────────────────────────────────────────

class TestLoadSave:
    def test_load_default_grid(self) -> None:
        scenarios = load_scenarios()
        assert len(scenarios) >= 5
        assert all(isinstance(s, StressScenario) for s in scenarios)

    def test_load_specific_path(self) -> None:
        scenarios = load_scenarios(GRID_PATH)
        assert len(scenarios) >= 5

    def test_save_and_reload(self, tmp_path: Path) -> None:
        original = load_scenarios()
        out = save_scenarios(original, tmp_path / "test_grid.json")
        reloaded = load_scenarios(out)
        assert len(reloaded) == len(original)
        for o, r in zip(original, reloaded):
            assert o.name == r.name
            assert o.shocks == r.shocks


# ── Forward stress ───────────────────────────────────────────────────────────

class TestForwardStress:
    def test_btc_crash_30pct(self) -> None:
        """BTC 60% of NAV, -30% shock → -18% portfolio loss from BTC alone."""
        portfolio = {"BTC": 60000, "ETH": 40000}
        sc = StressScenario(name="test", shocks={"BTC": -0.30, "ETH": -0.40})
        pnl = forward_stress(portfolio, sc)
        expected = (60000 * -0.30 + 40000 * -0.40) / 100000
        assert abs(pnl - expected) < 1e-10

    def test_known_value_exact(self) -> None:
        """100% BTC portfolio, -30% shock → exactly -30%."""
        pnl = forward_stress({"BTC": 100000}, StressScenario(
            name="t", shocks={"BTC": -0.30},
        ))
        assert abs(pnl - (-0.30)) < 1e-10

    def test_alts_shock_applies_to_non_major(self) -> None:
        """SOL/DOGE are 'alts', should get alts shock."""
        portfolio = {"BTC": 50000, "SOL": 50000}
        sc = StressScenario(name="t", shocks={"BTC": -0.10, "alts": -0.50})
        pnl = forward_stress(portfolio, sc)
        expected = (50000 * -0.10 + 50000 * -0.50) / 100000
        assert abs(pnl - expected) < 1e-10

    def test_all_shock_fallback(self) -> None:
        """'all' shock applies when no specific match."""
        portfolio = {"BTC": 50000, "UNKNOWN_COIN": 50000}
        sc = StressScenario(name="t", shocks={"BTC": -0.10, "all": -0.20})
        pnl = forward_stress(portfolio, sc)
        expected = (50000 * -0.10 + 50000 * -0.20) / 100000
        assert abs(pnl - expected) < 1e-10

    def test_exact_match_overrides_all(self) -> None:
        """Exact asset match takes priority over 'all'."""
        portfolio = {"BTC": 100000}
        sc = StressScenario(name="t", shocks={"BTC": -0.30, "all": -0.10})
        pnl = forward_stress(portfolio, sc)
        assert abs(pnl - (-0.30)) < 1e-10

    def test_no_shock_returns_zero(self) -> None:
        """Asset with no matching shock → zero PnL contribution."""
        portfolio = {"UNKNOWN": 100000}
        sc = StressScenario(name="t", shocks={"BTC": -0.30})
        pnl = forward_stress(portfolio, sc)
        assert pnl == 0.0

    def test_positive_shock(self) -> None:
        """Positive shocks (e.g., hedge gains) should work."""
        pnl = forward_stress({"BTC": 100000}, StressScenario(
            name="t", shocks={"BTC": 0.05},
        ))
        assert abs(pnl - 0.05) < 1e-10

    def test_accepts_raw_dict(self) -> None:
        """forward_stress should accept raw dict scenario."""
        pnl = forward_stress(
            {"BTC": 100000},
            {"name": "t", "shocks": {"BTC": -0.10}, "horizon_h": 1},
        )
        assert abs(pnl - (-0.10)) < 1e-10

    def test_empty_portfolio_returns_zero(self) -> None:
        sc = StressScenario(name="t", shocks={"BTC": -0.30})
        assert forward_stress({}, sc) == 0.0

    def test_zero_nav_returns_zero(self) -> None:
        assert forward_stress({"BTC": 0}, StressScenario(
            name="t", shocks={"BTC": -0.30},
        )) == 0.0


# ── Forward stress detailed ─────────────────────────────────────────────────

class TestForwardStressDetailed:
    def test_per_asset_breakdown(self) -> None:
        portfolio = {"BTC": 60000, "ETH": 40000}
        sc = StressScenario(name="crash", shocks={"BTC": -0.30, "ETH": -0.40})
        r = forward_stress_detailed(portfolio, sc)
        assert isinstance(r, ForwardStressResult)
        assert r.scenario_name == "crash"
        assert abs(r.per_asset_pnl["BTC"] - (-18000)) < 1e-6
        assert abs(r.per_asset_pnl["ETH"] - (-16000)) < 1e-6
        assert abs(r.pnl_abs - (-34000)) < 1e-6
        assert abs(r.pnl_pct - (-0.34)) < 1e-6

    def test_pnl_pct_matches_forward_stress(self) -> None:
        portfolio = _btc_heavy_portfolio()
        sc = StressScenario(name="t", shocks={"BTC": -0.20, "alts": -0.30})
        pnl_simple = forward_stress(portfolio, sc)
        r = forward_stress_detailed(portfolio, sc)
        assert abs(pnl_simple - r.pnl_pct) < 1e-10


# ── Stress grid runner ───────────────────────────────────────────────────────

class TestStressGrid:
    def test_run_all_default_scenarios(self) -> None:
        portfolio = _btc_heavy_portfolio()
        scenarios = load_scenarios()
        grid = run_stress_grid(portfolio, scenarios)
        assert isinstance(grid, StressGridResult)
        assert grid.scenario_count >= 5
        assert grid.worst_pnl_pct <= 0

    def test_worst_scenario_is_min_pnl(self) -> None:
        portfolio = _btc_heavy_portfolio()
        scenarios = load_scenarios()
        grid = run_stress_grid(portfolio, scenarios)
        min_pnl = min(r.pnl_pct for r in grid.results)
        assert abs(grid.worst_pnl_pct - min_pnl) < 1e-12

    def test_worst_scenario_name_matches(self) -> None:
        portfolio = _btc_heavy_portfolio()
        scenarios = load_scenarios()
        grid = run_stress_grid(portfolio, scenarios)
        worst_result = min(grid.results, key=lambda r: r.pnl_pct)
        assert grid.worst_scenario == worst_result.scenario_name

    def test_btc_crash_is_worst_for_btc_heavy(self) -> None:
        """For a BTC-heavy portfolio, a BTC crash scenario should be worst."""
        portfolio = {"BTC": 80000, "ETH": 10000, "SOL": 10000}
        scenarios = load_scenarios()
        grid = run_stress_grid(portfolio, scenarios)
        # With forward-looking scenarios, hypothetical_btc_70pct_crash
        # is now worse than BTC_crash_30pct
        assert "btc_crash" in grid.worst_scenario.lower() or \
            "btc_70pct" in grid.worst_scenario.lower()

    def test_known_worst_value(self) -> None:
        """100% BTC, BTC_crash_30pct → -30% loss."""
        portfolio = {"BTC": 100000}
        sc = StressScenario(name="crash", shocks={"BTC": -0.30})
        grid = run_stress_grid(portfolio, [sc])
        assert abs(grid.worst_pnl_pct - (-0.30)) < 1e-10


# ── Reverse stress test ──────────────────────────────────────────────────────

class TestReverseStress:
    def test_basic_reverse_stress(self) -> None:
        portfolio = _btc_heavy_portfolio()
        result = reverse_stress(portfolio, target_loss_pct=0.20)
        assert isinstance(result, ReverseStressResult)
        assert result.converged
        assert abs(result.achieved_loss_pct - 0.20) < 0.01

    def test_scaling_factor_positive(self) -> None:
        portfolio = _btc_heavy_portfolio()
        result = reverse_stress(portfolio, target_loss_pct=0.20)
        assert result.scaling_factor > 0

    def test_shock_vector_non_empty(self) -> None:
        portfolio = _btc_heavy_portfolio()
        result = reverse_stress(portfolio, target_loss_pct=0.20)
        assert len(result.min_shock_vector) > 0

    def test_small_target_needs_small_scaling(self) -> None:
        """5% target loss should need smaller scaling than 40%."""
        portfolio = _btc_heavy_portfolio()
        r5 = reverse_stress(portfolio, target_loss_pct=0.05)
        r40 = reverse_stress(portfolio, target_loss_pct=0.40)
        assert r5.scaling_factor < r40.scaling_factor

    def test_pure_btc_portfolio_exact(self) -> None:
        """100% BTC, BTC_crash_30pct base → scaling = 20/30 for 20% target."""
        portfolio = {"BTC": 100000}
        sc = StressScenario(name="crash", shocks={"BTC": -0.30})
        result = reverse_stress(portfolio, target_loss_pct=0.20, scenarios=[sc])
        expected_k = 0.20 / 0.30
        assert abs(result.scaling_factor - expected_k) < 1e-10
        assert result.converged

    def test_empty_portfolio(self) -> None:
        result = reverse_stress({}, target_loss_pct=0.20)
        assert not result.converged

    def test_no_loss_scenarios(self) -> None:
        """All-positive shocks → can't achieve loss → not converged."""
        portfolio = {"BTC": 100000}
        sc = StressScenario(name="gain", shocks={"BTC": 0.10})
        result = reverse_stress(portfolio, target_loss_pct=0.20, scenarios=[sc])
        assert not result.converged

    def test_reverse_stress_uses_default_grid(self) -> None:
        portfolio = _btc_heavy_portfolio()
        result = reverse_stress(portfolio, target_loss_pct=0.20)
        assert result.base_scenario != ""


# ── Report generation ────────────────────────────────────────────────────────

class TestReportGeneration:
    def test_generates_markdown_file(self, tmp_path: Path) -> None:
        portfolio = _btc_heavy_portfolio()
        out = generate_stress_report(portfolio, report_dir=tmp_path)
        assert out.exists()
        assert out.suffix == ".md"

    def test_report_contains_sections(self, tmp_path: Path) -> None:
        portfolio = _btc_heavy_portfolio()
        out = generate_stress_report(portfolio, report_dir=tmp_path)
        content = out.read_text(encoding="utf-8")
        assert "# Stress Report" in content
        assert "## Forward Stress Results" in content
        assert "## Reverse Stress Test" in content

    def test_report_filename_has_date(self, tmp_path: Path) -> None:
        portfolio = _btc_heavy_portfolio()
        out = generate_stress_report(portfolio, report_dir=tmp_path)
        assert "stress_" in out.name
        assert out.name.endswith(".md")

    def test_report_contains_all_scenarios(self, tmp_path: Path) -> None:
        portfolio = _btc_heavy_portfolio()
        scenarios = load_scenarios()
        out = generate_stress_report(portfolio, scenarios=scenarios, report_dir=tmp_path)
        content = out.read_text(encoding="utf-8")
        for sc in scenarios:
            assert sc.name in content


# ── Edge cases ───────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_single_asset_portfolio(self) -> None:
        pnl = forward_stress({"BTC": 100000}, StressScenario(
            name="t", shocks={"BTC": -0.50},
        ))
        assert abs(pnl - (-0.50)) < 1e-10

    def test_many_assets_with_alts_shock(self) -> None:
        portfolio = {f"ALT_{i}": 1000 for i in range(50)}
        portfolio["BTC"] = 50000
        sc = StressScenario(name="t", shocks={"BTC": -0.10, "alts": -0.30})
        pnl = forward_stress(portfolio, sc)
        nav = sum(portfolio.values())
        expected = (50000 * -0.10 + 50 * 1000 * -0.30) / nav
        assert abs(pnl - expected) < 1e-10

    def test_case_insensitive_exact_match(self) -> None:
        """Asset 'btc' should match shock key 'BTC'."""
        portfolio = {"btc": 100000}
        # Note: _resolve_shock checks upper-cased key
        sc = StressScenario(name="t", shocks={"BTC": -0.20})
        pnl = forward_stress(portfolio, sc)
        assert abs(pnl - (-0.20)) < 1e-10

    def test_usdt_depeg_scenario(self) -> None:
        """USDT depeg: USDT holdings lose value."""
        portfolio = {"USDT": 100000}
        sc = StressScenario(name="depeg", shocks={"USDT": -0.05})
        # Note: uses exact match on "USDT" key
        pnl = forward_stress(portfolio, sc)
        assert abs(pnl - (-0.05)) < 1e-10


# ── Deterministic reproducibility ────────────────────────────────────────────

class TestReproducibility:
    def test_forward_stress_deterministic(self) -> None:
        portfolio = _btc_heavy_portfolio()
        sc = load_scenarios()[0]
        r1 = forward_stress(portfolio, sc)
        r2 = forward_stress(portfolio, sc)
        assert r1 == r2

    def test_reverse_stress_deterministic(self) -> None:
        portfolio = _btc_heavy_portfolio()
        r1 = reverse_stress(portfolio, target_loss_pct=0.20)
        r2 = reverse_stress(portfolio, target_loss_pct=0.20)
        assert r1.scaling_factor == r2.scaling_factor
        assert r1.base_scenario == r2.base_scenario

    def test_grid_result_deterministic(self) -> None:
        portfolio = _btc_heavy_portfolio()
        scenarios = load_scenarios()
        g1 = run_stress_grid(portfolio, scenarios)
        g2 = run_stress_grid(portfolio, scenarios)
        assert g1.worst_pnl_pct == g2.worst_pnl_pct
        assert g1.worst_scenario == g2.worst_scenario


# ── Topology sentinel ────────────────────────────────────────────────────────

class TestTopologySentinel:
    def test_sentinel_present(self) -> None:
        from super_otonom.risk.stress_scenarios import institutional_stress_grid

        assert institutional_stress_grid is True

    def test_topology_detects_grid(self) -> None:
        from super_otonom.var_topology import inspect_var_topology

        topo = inspect_var_topology()
        assert topo.institutional_stress_grid_present is True
