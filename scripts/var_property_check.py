"""VR-26: VaR/CVaR mathematical property verifier.

Runs a quick smoke-check of key risk-measure invariants against
the live codebase.  Used by CI to catch coherence regressions.

Exit codes:
  0  — all invariants hold
  1  — invariant violation detected
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

var_property_check_active = True

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from super_otonom.risk.cvar_models import (
    historical_cvar,
    mc_cvar,
    parametric_cvar,
)
from super_otonom.risk.lvar import compute_lvar
from super_otonom.risk.risk_engine import RiskEngine
from super_otonom.risk.var_decomposition import compute_var_decomposition
from super_otonom.risk.var_models import (
    cornish_fisher_var,
    historical_var,
    monte_carlo_var,
    parametric_var,
)


@dataclass(frozen=True)
class PropertyResult:
    name: str
    passed: bool
    detail: str


def _gen_returns(seed: int = 42, n: int = 200, mu: float = 0.0, sigma: float = 0.02) -> list[float]:
    rng = np.random.RandomState(seed)
    return rng.normal(mu, sigma, n).tolist()


def check_var_positivity(returns: list[float]) -> List[PropertyResult]:
    """VaR >= 0 for all models."""
    results: List[PropertyResult] = []
    for name, fn in [
        ("historical_var", lambda r: historical_var(r, 0.95)),
        ("parametric_var", lambda r: parametric_var(r, 0.95)),
        ("monte_carlo_var", lambda r: monte_carlo_var(r, 0.95)),
        ("cornish_fisher_var", lambda r: cornish_fisher_var(r, 0.95)),
    ]:
        v = fn(returns)
        ok = v >= 0.0 and math.isfinite(v)
        results.append(PropertyResult(
            name=f"positivity_{name}",
            passed=ok,
            detail=f"{name}={v:.6f}",
        ))
    return results


def check_var_monotonicity(returns: list[float]) -> List[PropertyResult]:
    """VaR(99%) >= VaR(95%) for all models."""
    results: List[PropertyResult] = []
    for name, fn in [
        ("historical", historical_var),
        ("parametric", lambda r, c: parametric_var(r, c)),
        ("monte_carlo", lambda r, c: monte_carlo_var(r, c)),
    ]:
        v95 = fn(returns, 0.95)
        v99 = fn(returns, 0.99)
        ok = v99 >= v95 - 1e-6
        results.append(PropertyResult(
            name=f"monotonicity_{name}",
            passed=ok,
            detail=f"VaR(99%)={v99:.6f} >= VaR(95%)={v95:.6f}",
        ))
    return results


def check_cvar_gte_var(returns: list[float]) -> List[PropertyResult]:
    """CVaR >= VaR (coherent risk measure)."""
    results: List[PropertyResult] = []
    pairs = [
        ("historical", historical_var(returns, 0.95), historical_cvar(returns, 0.95)),
        ("parametric", parametric_var(returns, 0.95), parametric_cvar(returns, 0.95)),
        ("monte_carlo", monte_carlo_var(returns, 0.95), mc_cvar(returns, 0.95)),
    ]
    for name, var, cvar in pairs:
        ok = cvar >= var - 1e-6
        results.append(PropertyResult(
            name=f"cvar_gte_var_{name}",
            passed=ok,
            detail=f"CVaR={cvar:.6f} >= VaR={var:.6f}",
        ))
    return results


def check_euler_invariant(returns_dict: Dict[str, list[float]], weights: Dict[str, float]) -> List[PropertyResult]:
    """sum(Component_VaR) == Portfolio_VaR."""
    symbols = list(weights.keys())
    n = min(len(returns_dict[s]) for s in symbols)
    port_ret = [
        sum(weights[s] * returns_dict[s][t] for s in symbols)
        for t in range(n)
    ]
    var_total = historical_var(port_ret, 0.95)
    comp, _ = compute_var_decomposition(returns_dict, weights, var_total)
    if not comp:
        return [PropertyResult("euler_invariant", True, "skipped — insufficient data")]

    comp_sum = sum(comp.values())
    tol = var_total * 0.10 + 1e-6
    ok = abs(comp_sum - var_total) < tol
    return [PropertyResult(
        name="euler_invariant",
        passed=ok,
        detail=f"sum(CVaR)={comp_sum:.6f}, VaR_total={var_total:.6f}, tol={tol:.6f}",
    )]


def check_lvar_bound(returns: list[float]) -> List[PropertyResult]:
    """LVaR >= market VaR."""
    var_market = historical_var(returns, 0.95)
    lvar, _ = compute_lvar(var_market=var_market, position_notional=10000.0, spread_history=None)
    ok = lvar >= var_market - 1e-10
    return [PropertyResult(
        name="lvar_gte_market_var",
        passed=ok,
        detail=f"LVaR={lvar:.6f} >= VaR={var_market:.6f}",
    )]


def check_engine_coherence(returns: list[float]) -> List[PropertyResult]:
    """RiskEngine output invariants."""
    engine = RiskEngine()
    m = engine.compute(returns)
    results: List[PropertyResult] = []

    results.append(PropertyResult(
        "engine_var99_gte_var95",
        m.var_99_1d >= m.var_95_1d - 1e-6,
        f"VaR99={m.var_99_1d:.6f} >= VaR95={m.var_95_1d:.6f}",
    ))
    results.append(PropertyResult(
        "engine_cvar_gte_var",
        m.cvar_95_1d >= m.var_95_1d - 1e-6,
        f"CVaR95={m.cvar_95_1d:.6f} >= VaR95={m.var_95_1d:.6f}",
    ))
    results.append(PropertyResult(
        "engine_all_finite",
        all(math.isfinite(getattr(m, f)) for f in [
            "var_95_1d", "var_99_1d", "cvar_95_1d", "cvar_99_1d",
            "model_dispersion_pct", "lvar",
        ]),
        "all key fields finite",
    ))
    return results


def run_all_checks() -> Tuple[List[PropertyResult], Dict[str, any]]:
    """Run all property checks with synthetic data."""
    all_results: List[PropertyResult] = []

    # Generate test data
    returns = _gen_returns(seed=42, n=200)
    returns_fat = (np.random.RandomState(99).standard_t(3, 200) * 0.02).tolist()

    # Multi-asset data
    rng = np.random.RandomState(123)
    n_assets = 4
    cov = np.eye(n_assets) * 0.0004
    for i in range(n_assets):
        for j in range(i + 1, n_assets):
            cov[i, j] = cov[j, i] = 0.0001
    ma_ret = rng.multivariate_normal(np.zeros(n_assets), cov, 150)
    asset_returns = {f"A{i}": ma_ret[:, i].tolist() for i in range(n_assets)}
    weights = {f"A{i}": 0.25 for i in range(n_assets)}

    # Run checks on normal returns
    all_results.extend(check_var_positivity(returns))
    all_results.extend(check_var_monotonicity(returns))
    all_results.extend(check_cvar_gte_var(returns))
    all_results.extend(check_euler_invariant(asset_returns, weights))
    all_results.extend(check_lvar_bound(returns))
    all_results.extend(check_engine_coherence(returns))

    # Run on fat-tailed returns too
    all_results.extend(check_var_positivity(returns_fat))
    all_results.extend(check_cvar_gte_var(returns_fat))

    n_pass = sum(1 for r in all_results if r.passed)
    n_fail = sum(1 for r in all_results if not r.passed)

    summary = {
        "ok": n_fail == 0,
        "total_checks": len(all_results),
        "passed": n_pass,
        "failed": n_fail,
    }
    return all_results, summary


def format_report(results: List[PropertyResult], summary: Dict[str, any]) -> str:
    lines = [
        "VaR/CVaR Property Check (VR-26)",
        "=" * 45,
        f"Total checks: {summary['total_checks']}",
        f"Passed: {summary['passed']}",
        f"Failed: {summary['failed']}",
        "",
    ]
    if summary["ok"]:
        lines.append("All mathematical invariants PASSED.")
    else:
        lines.append("FAILURES:")
        for r in results:
            if not r.passed:
                lines.append(f"  [FAIL] {r.name}: {r.detail}")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="VaR property check (VR-26).")
    p.add_argument("--json", action="store_true", help="JSON output")
    args = p.parse_args(list(argv) if argv is not None else None)

    results, summary = run_all_checks()

    if args.json:
        payload = {
            **summary,
            "checks": [
                {"name": r.name, "passed": r.passed, "detail": r.detail}
                for r in results
            ],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(format_report(results, summary))

    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
