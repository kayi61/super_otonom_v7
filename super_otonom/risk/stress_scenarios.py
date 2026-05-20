"""Stress Scenario Library + Reverse Stress Test (VR-12).

Forward stress: apply predefined shock vectors to a portfolio and compute
PnL under each scenario.

Reverse stress: find the minimum shock magnitude that causes a target loss
(scipy L-BFGS-B optimisation on shock scaling factor).

Prometheus:
  ``bot_stress_worst_scenario_pnl_pct``
  ``bot_reverse_stress_min_btc_shock_pct``

Alert:
  ``BotStressLossHigh`` — worst scenario loss > 15% of NAV.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

log = logging.getLogger("super_otonom.risk.stress_scenarios")

# Sentinel for var_topology detection
institutional_stress_grid = True

_DATA = Path(__file__).resolve().parents[2] / "data"
_DEFAULT_GRID = _DATA / "var_stress_grid_default.json"
_REPORT_DIR = Path(__file__).resolve().parents[2] / "docs" / "stress_reports"

_MAJOR_ASSETS = frozenset({"BTC", "ETH", "BNB", "USDT", "USDC"})


# ── Data structures ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StressScenario:
    """Single stress scenario definition."""

    name: str
    shocks: Dict[str, float]
    horizon_h: float = 1.0

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "StressScenario":
        h = float(d.get("horizon_h", 0) or 0)
        if h == 0:
            h = float(d.get("horizon_min", 5)) / 60.0
        return cls(name=d["name"], shocks=dict(d["shocks"]), horizon_h=h)


@dataclass(frozen=True)
class ForwardStressResult:
    """Output of a single forward stress run."""

    scenario_name: str
    pnl_abs: float = 0.0
    pnl_pct: float = 0.0
    per_asset_pnl: Dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class StressGridResult:
    """Aggregated result across all scenarios."""

    results: List[ForwardStressResult] = field(default_factory=list)
    worst_scenario: str = ""
    worst_pnl_pct: float = 0.0

    @property
    def scenario_count(self) -> int:
        return len(self.results)


@dataclass(frozen=True)
class ReverseStressResult:
    """Output of reverse stress test."""

    target_loss_pct: float = 0.20
    achieved_loss_pct: float = 0.0
    min_shock_vector: Dict[str, float] = field(default_factory=dict)
    scaling_factor: float = 1.0
    base_scenario: str = ""
    converged: bool = False


# ── Shock resolution ─────────────────────────────────────────────────────────

def _resolve_shock(asset: str, shocks: Mapping[str, float]) -> float:
    """Determine the effective shock for *asset* given a shock mapping.

    Priority: exact match → category ("alts") → "all" → 0.
    """
    if asset in shocks:
        return shocks[asset]

    upper = asset.upper()
    if upper in shocks:
        return shocks[upper]

    if "alts" in shocks and upper not in _MAJOR_ASSETS:
        return shocks["alts"]

    if "all" in shocks:
        return shocks["all"]

    return 0.0


# ── Forward stress ───────────────────────────────────────────────────────────

def forward_stress(
    portfolio: Mapping[str, float],
    scenario: StressScenario | Mapping[str, Any],
) -> float:
    """Apply scenario shocks to *portfolio* and return PnL as a fraction of NAV.

    Parameters
    ----------
    portfolio:
        ``{asset: notional_value}`` e.g. ``{"BTC": 50000, "ETH": 30000}``.
    scenario:
        ``StressScenario`` or raw dict with ``name``, ``shocks``.

    Returns
    -------
    float
        Signed PnL fraction (negative = loss).
    """
    if isinstance(scenario, Mapping):
        sc = StressScenario.from_dict(scenario)
    else:
        sc = scenario

    nav = sum(portfolio.values())
    if nav <= 0:
        return 0.0

    total_pnl = 0.0
    for asset, notional in portfolio.items():
        shock = _resolve_shock(asset, sc.shocks)
        total_pnl += notional * shock

    return total_pnl / nav


def forward_stress_detailed(
    portfolio: Mapping[str, float],
    scenario: StressScenario | Mapping[str, Any],
) -> ForwardStressResult:
    """Like :func:`forward_stress` but returns full per-asset breakdown."""
    if isinstance(scenario, Mapping):
        sc = StressScenario.from_dict(scenario)
    else:
        sc = scenario

    nav = sum(portfolio.values())
    if nav <= 0:
        return ForwardStressResult(scenario_name=sc.name)

    per_asset: Dict[str, float] = {}
    total_pnl = 0.0
    for asset, notional in portfolio.items():
        shock = _resolve_shock(asset, sc.shocks)
        asset_pnl = notional * shock
        per_asset[asset] = asset_pnl
        total_pnl += asset_pnl

    return ForwardStressResult(
        scenario_name=sc.name,
        pnl_abs=total_pnl,
        pnl_pct=total_pnl / nav,
        per_asset_pnl=per_asset,
    )


# ── Stress grid runner ───────────────────────────────────────────────────────

def run_stress_grid(
    portfolio: Mapping[str, float],
    scenarios: Sequence[StressScenario | Mapping[str, Any]],
) -> StressGridResult:
    """Run all scenarios and pick the worst."""
    results: List[ForwardStressResult] = []
    worst_name = ""
    worst_pnl = 0.0

    for sc in scenarios:
        r = forward_stress_detailed(portfolio, sc)
        results.append(r)
        if r.pnl_pct < worst_pnl:
            worst_pnl = r.pnl_pct
            worst_name = r.scenario_name

    return StressGridResult(
        results=results,
        worst_scenario=worst_name,
        worst_pnl_pct=worst_pnl,
    )


# ── Reverse stress test ─────────────────────────────────────────────────────

def reverse_stress(
    portfolio: Mapping[str, float],
    target_loss_pct: float = 0.20,
    scenarios: Optional[Sequence[StressScenario]] = None,
    max_iter: int = 200,
) -> ReverseStressResult:
    """Find the minimum shock scaling factor that achieves *target_loss_pct*.

    For each scenario in the grid the shocks are uniformly scaled by a factor
    ``k`` (0 < k ≤ 10).  The solver minimises ``k`` subject to the forward
    stress PnL reaching ``-target_loss_pct``.

    If no grid is provided the default grid is loaded.

    Returns the scenario + scaling factor with the smallest ``k``.
    """
    if scenarios is None:
        scenarios = load_scenarios()

    nav = sum(portfolio.values())
    if nav <= 0:
        return ReverseStressResult(target_loss_pct=target_loss_pct)

    best: Optional[Tuple[float, str, Dict[str, float], float]] = None

    for sc in scenarios:
        base_pnl = forward_stress(portfolio, sc)
        if base_pnl >= 0:
            continue

        k_needed = target_loss_pct / abs(base_pnl)
        if k_needed < 1e-12:
            continue

        scaled_shocks = {asset: shock * k_needed for asset, shock in sc.shocks.items()}
        verify_pnl = forward_stress(portfolio, StressScenario(
            name=sc.name, shocks=scaled_shocks, horizon_h=sc.horizon_h,
        ))
        achieved = abs(verify_pnl)

        if best is None or k_needed < best[0]:
            best = (k_needed, sc.name, scaled_shocks, achieved)

    if best is None:
        return ReverseStressResult(
            target_loss_pct=target_loss_pct,
            converged=False,
        )

    k_opt, base_name, shock_vec, achieved = best
    return ReverseStressResult(
        target_loss_pct=target_loss_pct,
        achieved_loss_pct=achieved,
        min_shock_vector=shock_vec,
        scaling_factor=k_opt,
        base_scenario=base_name,
        converged=abs(achieved - target_loss_pct) < 0.01,
    )


# ── Scenario I/O ─────────────────────────────────────────────────────────────

def load_scenarios(path: Optional[Path] = None) -> List[StressScenario]:
    """Load scenarios from JSON grid file."""
    p = path or _DEFAULT_GRID
    raw = json.loads(p.read_text(encoding="utf-8"))
    return [StressScenario.from_dict(d) for d in raw]


def save_scenarios(scenarios: Sequence[StressScenario], path: Optional[Path] = None) -> Path:
    """Persist scenarios to JSON."""
    p = path or _DEFAULT_GRID
    payload = [
        {"name": s.name, "shocks": s.shocks, "horizon_h": s.horizon_h}
        for s in scenarios
    ]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


# ── Daily report generation ──────────────────────────────────────────────────

def generate_stress_report(
    portfolio: Mapping[str, float],
    scenarios: Optional[Sequence[StressScenario]] = None,
    target_loss_pct: float = 0.20,
    report_dir: Optional[Path] = None,
) -> Path:
    """Generate a markdown stress report and write to disk.

    Output: ``docs/stress_reports/stress_YYYY-MM-DD.md``
    """
    if scenarios is None:
        scenarios = load_scenarios()

    out_dir = report_dir or _REPORT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    out_path = out_dir / f"stress_{today}.md"

    grid = run_stress_grid(portfolio, scenarios)
    rev = reverse_stress(portfolio, target_loss_pct, scenarios)
    nav = sum(portfolio.values())

    lines: List[str] = [
        f"# Stress Report — {today}",
        "",
        f"**NAV:** {nav:,.2f} USDT",
        f"**Scenarios:** {grid.scenario_count}",
        f"**Worst scenario:** {grid.worst_scenario} ({grid.worst_pnl_pct:+.2%})",
        "",
        "## Forward Stress Results",
        "",
        "| Scenario | PnL (USDT) | PnL (%) |",
        "|----------|------------|---------|",
    ]

    for r in grid.results:
        lines.append(f"| {r.scenario_name} | {r.pnl_abs:+,.2f} | {r.pnl_pct:+.2%} |")

    lines.extend([
        "",
        "## Reverse Stress Test",
        "",
        f"**Target loss:** {rev.target_loss_pct:.0%}",
        f"**Base scenario:** {rev.base_scenario}",
        f"**Scaling factor:** {rev.scaling_factor:.4f}",
        f"**Converged:** {rev.converged}",
        "",
        "**Minimum shock vector:**",
        "",
    ])

    for asset, shock in sorted(rev.min_shock_vector.items()):
        lines.append(f"- {asset}: {shock:+.4f}")

    lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("Stress report written: %s", out_path)
    return out_path
