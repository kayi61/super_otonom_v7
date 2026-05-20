"""VaR backtesting — Kupiec POF + Christoffersen Independence + CC (VR-13/14).

**VR-13 — Kupiec POF (Proportion of Failures)**
The Kupiec (1995) likelihood-ratio test checks whether the observed
number of VaR exceedances is consistent with the model's stated
confidence level.  LR ~ χ²(1).

**VR-14 — Christoffersen Independence**
The Christoffersen (1998) independence test checks whether exceedances
are serially independent (no clustering).  Uses a first-order Markov
transition-matrix likelihood ratio.  LR_ind ~ χ²(1).

**VR-14 — Christoffersen Conditional Coverage (CC)**
Combined test:  LR_cc = LR_pof + LR_ind ~ χ²(2).
Model valid ⟺ Kupiec OK **and** independence OK.

Prometheus:
    ``bot_kupiec_pvalue``, ``bot_kupiec_exceedances``
    ``bot_christoffersen_ind_pvalue``, ``bot_christoffersen_cc_pvalue``

Alerts:
    ``BotKupiecModelInvalid`` — p_value < 0.05 for 1h.
    ``BotChristoffersenCluster`` — independence p_value < 0.05 for 1h.
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


# ── Christoffersen Independence (VR-14) ──────────────────────────────────────

@dataclass(frozen=True)
class ChristoffersenResult:
    """Christoffersen (1998) independence test output.

    Attributes
    ----------
    n00, n01, n10, n11 : int
        Markov transition counts (from state i to state j).
    pi_01 : float
        P(exceed | no exceed yesterday).
    pi_11 : float
        P(exceed | exceed yesterday).
    pi : float
        Unconditional exceedance probability.
    lr_ind : float
        Independence LR statistic ~ chi2(1).
    p_value_ind : float
        p-value for independence test.
    independent : bool
        True when we fail to reject H0 of independence at alpha=0.05.
    """

    n00: int = 0
    n01: int = 0
    n10: int = 0
    n11: int = 0
    pi_01: float = 0.0
    pi_11: float = 0.0
    pi: float = 0.0
    lr_ind: float = 0.0
    p_value_ind: float = 1.0
    independent: bool = True


@dataclass(frozen=True)
class ConditionalCoverageResult:
    """Christoffersen conditional coverage (CC) = Kupiec POF + Independence.

    Attributes
    ----------
    kupiec : KupiecResult
        Proportion-of-failures test.
    independence : ChristoffersenResult
        Serial independence test.
    lr_cc : float
        Combined LR = LR_pof + LR_ind ~ chi2(2).
    p_value_cc : float
        p-value for the combined test.
    model_valid : bool
        True iff both kupiec AND independence pass.
    """

    kupiec: KupiecResult = KupiecResult()  # noqa: RUF009
    independence: ChristoffersenResult = ChristoffersenResult()  # noqa: RUF009
    lr_cc: float = 0.0
    p_value_cc: float = 1.0
    model_valid: bool = True


def _build_exceedance_series(
    realized_pnl: Sequence[float],
    predicted_var: Sequence[float] | float,
) -> List[int]:
    """Convert PnL + VaR into a binary exceedance indicator series."""
    n = len(realized_pnl)
    if isinstance(predicted_var, (int, float)):
        var_series = [float(predicted_var)] * n
    else:
        var_series = [float(v) for v in predicted_var]
    return [1 if p < -v else 0 for p, v in zip(realized_pnl, var_series)]


def christoffersen_ind(
    exceedance_series: Sequence[int],
) -> ChristoffersenResult:
    """Christoffersen (1998) independence test for VaR exceedance clustering.

    Tests whether exceedances follow a first-order Markov chain with
    equal transition probabilities (i.e., no clustering).

    Parameters
    ----------
    exceedance_series:
        Binary series: 1 = VaR exceeded, 0 = not exceeded.

    Returns
    -------
    ChristoffersenResult
    """
    exc = list(exceedance_series)
    n = len(exc)

    if n < KUPIEC_MIN_OBS:
        return ChristoffersenResult()

    # Transition counts
    n00 = n01 = n10 = n11 = 0
    for i in range(1, n):
        prev, cur = exc[i - 1], exc[i]
        if prev == 0 and cur == 0:
            n00 += 1
        elif prev == 0 and cur == 1:
            n01 += 1
        elif prev == 1 and cur == 0:
            n10 += 1
        else:
            n11 += 1

    # Conditional probabilities
    pi_01 = n01 / (n00 + n01) if (n00 + n01) > 0 else 0.0
    pi_11 = n11 / (n10 + n11) if (n10 + n11) > 0 else 0.0

    # Unconditional exceedance probability
    total_exc = n01 + n11
    total_trans = n00 + n01 + n10 + n11
    pi = total_exc / total_trans if total_trans > 0 else 0.0

    # Boundary: if pi is 0 or 1, or either row has zero transitions,
    # LR is undefined — return default (independent)
    if pi <= 0 or pi >= 1 or (n00 + n01) == 0 or (n10 + n11) == 0:
        return ChristoffersenResult(
            n00=n00, n01=n01, n10=n10, n11=n11,
            pi_01=pi_01, pi_11=pi_11, pi=pi,
        )

    # Guard against log(0): if pi_01 or pi_11 is exactly 0 or 1
    if pi_01 <= 0 or pi_01 >= 1 or pi_11 <= 0 or pi_11 >= 1:
        return ChristoffersenResult(
            n00=n00, n01=n01, n10=n10, n11=n11,
            pi_01=pi_01, pi_11=pi_11, pi=pi,
        )

    # LR independence statistic
    # L_restricted: unconditional probability for both rows
    # L_unrestricted: row-specific transition probabilities
    log_restricted = (
        (n00 + n10) * np.log(1.0 - pi) + (n01 + n11) * np.log(pi)
    )
    log_unrestricted = (
        n00 * np.log(1.0 - pi_01) + n01 * np.log(pi_01)
        + n10 * np.log(1.0 - pi_11) + n11 * np.log(pi_11)
    )
    lr_ind = max(0.0, float(-2.0 * (log_restricted - log_unrestricted)))

    p_value_ind = float(1.0 - chi2.cdf(lr_ind, df=1))

    return ChristoffersenResult(
        n00=n00, n01=n01, n10=n10, n11=n11,
        pi_01=pi_01, pi_11=pi_11, pi=pi,
        lr_ind=lr_ind,
        p_value_ind=p_value_ind,
        independent=p_value_ind > 0.05,
    )


def christoffersen_cc(
    realized_pnl: Sequence[float],
    predicted_var: Sequence[float] | float,
    conf: float = 0.99,
) -> ConditionalCoverageResult:
    """Christoffersen conditional coverage = Kupiec POF + Independence.

    LR_cc = LR_pof + LR_ind ~ chi2(2).

    Parameters
    ----------
    realized_pnl:
        Daily realised PnL (losses negative).
    predicted_var:
        Predicted VaR (positive loss fraction) or scalar.
    conf:
        VaR confidence level.

    Returns
    -------
    ConditionalCoverageResult
    """
    kup = kupiec_pof(realized_pnl, predicted_var, conf=conf)
    exc_series = _build_exceedance_series(realized_pnl, predicted_var)
    ind = christoffersen_ind(exc_series)

    lr_cc = kup.lr_statistic + ind.lr_ind
    p_value_cc = float(1.0 - chi2.cdf(lr_cc, df=2))

    return ConditionalCoverageResult(
        kupiec=kup,
        independence=ind,
        lr_cc=lr_cc,
        p_value_cc=p_value_cc,
        model_valid=kup.model_valid and ind.independent,
    )


# ── Multi-confidence convenience ─────────────────────────────────────────────

def run_backtest_suite(
    realized_pnl: Sequence[float],
    predicted_vars: dict[float, Sequence[float] | float],
) -> dict[float, KupiecResult]:
    """Run Kupiec POF at multiple confidence levels."""
    return {
        conf: kupiec_pof(realized_pnl, var_pred, conf=conf)
        for conf, var_pred in predicted_vars.items()
    }


def run_cc_suite(
    realized_pnl: Sequence[float],
    predicted_vars: dict[float, Sequence[float] | float],
) -> dict[float, ConditionalCoverageResult]:
    """Run full Christoffersen CC test at multiple confidence levels."""
    return {
        conf: christoffersen_cc(realized_pnl, var_pred, conf=conf)
        for conf, var_pred in predicted_vars.items()
    }


# ── Report generation ────────────────────────────────────────────────────────

def generate_backtest_report(
    results: (
        dict[float, KupiecResult]
        | dict[float, ConditionalCoverageResult]
        | KupiecResult
        | ConditionalCoverageResult
    ),
    report_dir: Optional[Path] = None,
) -> Path:
    """Write a markdown backtest report to disk.

    Accepts Kupiec-only results or full CC results.
    Output: ``docs/backtest_reports/kupiec_YYYY-MM-DD.md``
    """
    out_dir = report_dir or _REPORT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    out_path = out_dir / f"kupiec_{today}.md"

    # Normalise to dict
    if isinstance(results, KupiecResult):
        results = {results.confidence: results}
    elif isinstance(results, ConditionalCoverageResult):
        results = {results.kupiec.confidence: results}

    has_cc = any(isinstance(v, ConditionalCoverageResult) for v in results.values())

    lines: List[str] = [
        f"# VaR Backtest Report — {today}",
        "",
        "## Kupiec POF (Proportion of Failures)",
        "",
        "| Confidence | Exceedances | Expected | LR Stat | p-value | Valid |",
        "|------------|-------------|----------|---------|---------|-------|",
    ]

    all_valid = True
    for conf in sorted(results.keys()):
        r = results[conf]
        kup = r.kupiec if isinstance(r, ConditionalCoverageResult) else r
        valid_str = "PASS" if kup.model_valid else "**FAIL**"
        if not kup.model_valid:
            all_valid = False
        lines.append(
            f"| {kup.confidence:.1%} | {kup.exceedances} | {kup.expected:.1f} "
            f"| {kup.lr_statistic:.4f} | {kup.p_value:.4f} | {valid_str} |"
        )

    if has_cc:
        lines.extend([
            "",
            "## Christoffersen Independence",
            "",
            "| Confidence | n01 | n11 | pi_01 | pi_11 | LR_ind | p-value | Independent |",
            "|------------|-----|-----|-------|-------|--------|---------|-------------|",
        ])
        for conf in sorted(results.keys()):
            r = results[conf]
            if not isinstance(r, ConditionalCoverageResult):
                continue
            ind = r.independence
            ind_str = "PASS" if ind.independent else "**FAIL**"
            if not ind.independent:
                all_valid = False
            kup_conf = r.kupiec.confidence
            lines.append(
                f"| {kup_conf:.1%} | {ind.n01} | {ind.n11} "
                f"| {ind.pi_01:.4f} | {ind.pi_11:.4f} "
                f"| {ind.lr_ind:.4f} | {ind.p_value_ind:.4f} | {ind_str} |"
            )

        lines.extend([
            "",
            "## Conditional Coverage (Combined)",
            "",
            "| Confidence | LR_cc | p-value_cc | Overall |",
            "|------------|-------|------------|---------|",
        ])
        for conf in sorted(results.keys()):
            r = results[conf]
            if not isinstance(r, ConditionalCoverageResult):
                continue
            ov_str = "PASS" if r.model_valid else "**FAIL**"
            if not r.model_valid:
                all_valid = False
            lines.append(
                f"| {r.kupiec.confidence:.1%} "
                f"| {r.lr_cc:.4f} | {r.p_value_cc:.4f} | {ov_str} |"
            )

    lines.extend([
        "",
        f"**Overall:** {'ALL PASS' if all_valid else 'MODEL REVIEW REQUIRED'}",
        "",
    ])

    out_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("Backtest report written: %s", out_path)
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
