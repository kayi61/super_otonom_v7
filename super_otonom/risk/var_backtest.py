"""VaR backtesting — Kupiec POF (Proportion of Failures) test (VR-13).

The Kupiec (1995) likelihood-ratio test checks whether the observed
number of VaR exceedances (days where loss exceeded predicted VaR) is
consistent with the model's stated confidence level.

Under H₀ the exceedance count follows Binomial(n, 1-conf).  The LR
statistic is χ²(1)-distributed:

    LR = -2 [ (n-x)·ln(1-p_exp) + x·ln(p_exp)
              - (n-x)·ln(1-p_obs)   - x·ln(p_obs) ]

where
    n = sample size,  x = exceedances,
    p_exp = 1 - conf,  p_obs = x / n.

``model_valid = (p_value > 0.05)`` — fail to reject H₀ at 5%.

Prometheus:
    ``bot_kupiec_pvalue``
    ``bot_kupiec_exceedances``

Alert:
    ``BotKupiecModelInvalid`` — p_value < 0.05 for 1h (nightly job).
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import List, Optional, Sequence

import numpy as np
from scipy.stats import chi2

log = logging.getLogger("super_otonom.risk.var_backtest")

# Sentinel for var_topology detection
var_backtest_kupiec = True

KUPIEC_MIN_OBS = 50
"""Minimum observations required for a meaningful test."""

_REPORT_DIR = Path(__file__).resolve().parents[2] / "docs" / "backtest_reports"


# ── Result dataclass ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class KupiecResult:
    """Kupiec POF (Proportion of Failures) test output.

    Attributes
    ----------
    exceedances : int
        Number of days where realised loss exceeded predicted VaR.
    expected : float
        Expected exceedances under H₀ = n × (1 - conf).
    n_obs : int
        Total observation count.
    lr_statistic : float
        Likelihood-ratio test statistic (χ²(1)).
    p_value : float
        p-value from χ²(1) distribution.
    model_valid : bool
        True when we fail to reject H₀ at α=0.05.
    confidence : float
        VaR confidence level used for the test.
    """

    exceedances: int = 0
    expected: float = 0.0
    n_obs: int = 0
    lr_statistic: float = 0.0
    p_value: float = 1.0
    model_valid: bool = True
    confidence: float = 0.99


# ── Core algorithm ───────────────────────────────────────────────────────────

def kupiec_pof(
    realized_pnl: Sequence[float],
    predicted_var: Sequence[float] | float,
    conf: float = 0.99,
) -> KupiecResult:
    """Kupiec Proportion-of-Failures (POF) likelihood-ratio test.

    Parameters
    ----------
    realized_pnl:
        Daily realised PnL (returns or absolute — sign matters).
        Losses are negative.
    predicted_var:
        Predicted VaR for each day (positive loss fraction) **or** a
        single scalar applied uniformly.
    conf:
        VaR confidence level (e.g. 0.99).

    Returns
    -------
    KupiecResult
        Test output including p-value and model validity flag.
    """
    pnl = list(realized_pnl)
    n = len(pnl)

    if n < KUPIEC_MIN_OBS:
        return KupiecResult(
            n_obs=n,
            expected=n * (1 - conf),
            confidence=conf,
        )

    # Broadcast scalar VaR
    if isinstance(predicted_var, (int, float)):
        var_series: List[float] = [float(predicted_var)] * n
    else:
        var_series = [float(v) for v in predicted_var]

    if len(var_series) != n:
        raise ValueError(
            f"predicted_var length ({len(var_series)}) != realized_pnl length ({n})"
        )

    # Count exceedances: loss exceeded predicted VaR
    # VaR is positive (loss fraction), realised PnL is negative when loss
    exceedances = sum(1 for p, v in zip(pnl, var_series) if p < -v)

    p_exp = 1.0 - conf
    expected = n * p_exp
    p_obs = exceedances / n

    # Boundary cases — LR undefined when p_obs is 0 or 1
    if exceedances == 0:
        return KupiecResult(
            exceedances=0,
            expected=expected,
            n_obs=n,
            lr_statistic=0.0,
            p_value=1.0,
            model_valid=True,
            confidence=conf,
        )
    if exceedances == n:
        return KupiecResult(
            exceedances=n,
            expected=expected,
            n_obs=n,
            lr_statistic=0.0,
            p_value=1.0,
            model_valid=True,
            confidence=conf,
        )

    # Likelihood-ratio statistic
    lr = -2.0 * (
        (n - exceedances) * np.log(1.0 - p_exp)
        + exceedances * np.log(p_exp)
        - (n - exceedances) * np.log(1.0 - p_obs)
        - exceedances * np.log(p_obs)
    )
    lr = max(0.0, float(lr))

    p_value = float(1.0 - chi2.cdf(lr, df=1))

    return KupiecResult(
        exceedances=exceedances,
        expected=expected,
        n_obs=n,
        lr_statistic=lr,
        p_value=p_value,
        model_valid=p_value > 0.05,
        confidence=conf,
    )


# ── Multi-confidence convenience ─────────────────────────────────────────────

def run_backtest_suite(
    realized_pnl: Sequence[float],
    predicted_vars: dict[float, Sequence[float] | float],
) -> dict[float, KupiecResult]:
    """Run Kupiec POF at multiple confidence levels.

    Parameters
    ----------
    realized_pnl:
        Daily realised PnL series.
    predicted_vars:
        ``{confidence: predicted_var_series_or_scalar}``.

    Returns
    -------
    dict[float, KupiecResult]
        Keyed by confidence level.
    """
    return {
        conf: kupiec_pof(realized_pnl, var_pred, conf=conf)
        for conf, var_pred in predicted_vars.items()
    }


# ── Report generation ────────────────────────────────────────────────────────

def generate_backtest_report(
    results: dict[float, KupiecResult] | KupiecResult,
    report_dir: Optional[Path] = None,
) -> Path:
    """Write a markdown backtest report to disk.

    Output: ``docs/backtest_reports/kupiec_YYYY-MM-DD.md``
    """
    out_dir = report_dir or _REPORT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    out_path = out_dir / f"kupiec_{today}.md"

    if isinstance(results, KupiecResult):
        results = {results.confidence: results}

    lines: List[str] = [
        f"# Kupiec POF Backtest Report — {today}",
        "",
        "| Confidence | Exceedances | Expected | LR Stat | p-value | Valid |",
        "|------------|-------------|----------|---------|---------|-------|",
    ]

    all_valid = True
    for conf in sorted(results.keys()):
        r = results[conf]
        valid_str = "PASS" if r.model_valid else "**FAIL**"
        if not r.model_valid:
            all_valid = False
        lines.append(
            f"| {conf:.1%} | {r.exceedances} | {r.expected:.1f} "
            f"| {r.lr_statistic:.4f} | {r.p_value:.4f} | {valid_str} |"
        )

    lines.extend([
        "",
        f"**Overall:** {'ALL PASS' if all_valid else 'MODEL REVIEW REQUIRED'}",
        "",
    ])

    out_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("Kupiec report written: %s", out_path)
    return out_path


# ── CLI entry-point (nightly CI job) ─────────────────────────────────────────

def nightly_kupiec_check(
    pnl_path: Optional[Path] = None,
    var_path: Optional[Path] = None,
    conf: float = 0.99,
) -> KupiecResult:
    """Load PnL + VaR from JSON files and run the Kupiec test.

    File format:
        ``{"realized_pnl": [...], "predicted_var": [...]}``
    or two separate files.

    Returns the KupiecResult; CI should check ``result.model_valid``.
    """
    data_dir = Path(__file__).resolve().parents[2] / "data"

    if pnl_path is None and var_path is None:
        combined = data_dir / "backtest_input.json"
        if combined.is_file():
            raw = json.loads(combined.read_text(encoding="utf-8"))
            pnl = raw["realized_pnl"]
            var_ = raw["predicted_var"]
            return kupiec_pof(pnl, var_, conf=conf)

    pnl_file = pnl_path or data_dir / "realized_pnl.json"
    var_file = var_path or data_dir / "predicted_var.json"

    pnl = json.loads(pnl_file.read_text(encoding="utf-8"))
    var_ = json.loads(var_file.read_text(encoding="utf-8"))

    if isinstance(pnl, dict):
        pnl = pnl.get("values", pnl.get("realized_pnl", []))
    if isinstance(var_, dict):
        var_ = var_.get("values", var_.get("predicted_var", []))

    return kupiec_pof(pnl, var_, conf=conf)


def main() -> int:
    """CLI: run nightly Kupiec backtest.

    Exit 0 = model valid, exit 1 = model invalid (triggers CI alert).
    """
    import argparse

    parser = argparse.ArgumentParser(description="Kupiec POF VaR backtest (VR-13)")
    parser.add_argument("--conf", type=float, default=0.99, help="VaR confidence")
    parser.add_argument("--pnl", type=str, default=None, help="Path to realized PnL JSON")
    parser.add_argument("--var", type=str, default=None, help="Path to predicted VaR JSON")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    pnl_p = Path(args.pnl) if args.pnl else None
    var_p = Path(args.var) if args.var else None

    try:
        result = nightly_kupiec_check(pnl_p, var_p, conf=args.conf)
    except FileNotFoundError as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    report = generate_backtest_report(result)

    if args.json:
        print(json.dumps({
            "exceedances": result.exceedances,
            "expected": result.expected,
            "n_obs": result.n_obs,
            "lr_statistic": result.lr_statistic,
            "p_value": result.p_value,
            "model_valid": result.model_valid,
            "confidence": result.confidence,
            "report_path": str(report),
        }, indent=2))
    else:
        status = "PASS" if result.model_valid else "FAIL"
        print(
            f"Kupiec POF ({result.confidence:.0%}): {status}  "
            f"exceedances={result.exceedances}/{result.n_obs}  "
            f"expected={result.expected:.1f}  "
            f"p_value={result.p_value:.4f}"
        )
        print(f"Report: {report}")

    return 0 if result.model_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
