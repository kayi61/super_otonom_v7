"""VR-13 — Kupiec POF (Proportion of Failures) backtest tests.

Tests:
  - KupiecResult dataclass correctness
  - Kupiec LR statistic formula verification
  - Exact exceedance counting
  - Boundary: zero exceedances, all exceedances
  - Scalar VaR broadcast
  - Length mismatch error
  - Minimum observations guard (< 50)
  - Synthetic: known exceedance rate → p-value > 0.05 (valid model)
  - Synthetic: excessive exceedances → p-value < 0.05 (invalid model)
  - Multi-confidence suite
  - Report generation
  - CLI entry-point (nightly_kupiec_check)
  - Deterministic reproducibility
  - Binomial consistency check
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from scipy.stats import binom, chi2
from super_otonom.risk.var_backtest import (
    KUPIEC_MIN_OBS,
    KupiecResult,
    generate_backtest_report,
    kupiec_pof,
    nightly_kupiec_check,
    run_backtest_suite,
)

pytestmark = pytest.mark.risk


# ── Helpers ──────────────────────────────────────────────────────────────────

def _normal_pnl(
    n: int = 250,
    mean: float = 0.001,
    std: float = 0.02,
    seed: int = 42,
) -> list[float]:
    rng = np.random.RandomState(seed)
    return rng.normal(mean, std, n).tolist()


def _constant_var(val: float, n: int = 250) -> list[float]:
    return [val] * n


def _craft_exceedances(
    n: int = 250,
    var_val: float = 0.05,
    n_exceed: int = 3,
    seed: int = 42,
) -> tuple[list[float], list[float]]:
    """Build PnL series with *exactly* n_exceed exceedances."""
    rng = np.random.RandomState(seed)
    # Non-exceeding returns: small positive or small negative but > -var_val
    pnl = (rng.uniform(-var_val * 0.5, var_val * 0.5, n)).tolist()
    # Inject exactly n_exceed exceedances at the start
    for i in range(min(n_exceed, n)):
        pnl[i] = -(var_val + rng.uniform(0.01, 0.05))
    var_series = [var_val] * n
    return pnl, var_series


# ── KupiecResult dataclass ───────────────────────────────────────────────────

class TestKupiecResult:
    def test_frozen(self) -> None:
        r = KupiecResult()
        with pytest.raises(AttributeError):
            r.p_value = 0.5  # type: ignore[misc]

    def test_defaults(self) -> None:
        r = KupiecResult()
        assert r.exceedances == 0
        assert r.expected == 0.0
        assert r.n_obs == 0
        assert r.lr_statistic == 0.0
        assert r.p_value == 1.0
        assert r.model_valid is True
        assert r.confidence == 0.99


# ── Exceedance counting ─────────────────────────────────────────────────────

class TestExceedanceCounting:
    def test_exact_count(self) -> None:
        # Craft series with exactly 7 exceedances (n >= KUPIEC_MIN_OBS)
        pnl_big, var_big = _craft_exceedances(n=100, var_val=0.05, n_exceed=7)
        r = kupiec_pof(pnl_big, var_big, conf=0.99)
        assert r.exceedances == 7
        assert r.n_obs == 100

    def test_zero_exceedances(self) -> None:
        pnl, var_series = _craft_exceedances(n=100, n_exceed=0)
        r = kupiec_pof(pnl, var_series, conf=0.99)
        assert r.exceedances == 0
        assert r.p_value == 1.0
        assert r.model_valid is True

    def test_all_exceedances(self) -> None:
        pnl = [-0.10] * 100  # all exceed var=0.05
        r = kupiec_pof(pnl, 0.05, conf=0.99)
        assert r.exceedances == 100
        assert r.p_value == 1.0  # boundary → 1.0

    def test_scalar_var_broadcast(self) -> None:
        """Scalar predicted_var should be broadcast to all days."""
        pnl, _ = _craft_exceedances(n=100, var_val=0.05, n_exceed=3)
        r = kupiec_pof(pnl, 0.05, conf=0.99)
        assert r.exceedances == 3
        assert r.n_obs == 100


# ── Input validation ─────────────────────────────────────────────────────────

class TestInputValidation:
    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="length"):
            kupiec_pof([0.01] * 100, [0.05] * 50, conf=0.99)

    def test_below_min_obs(self) -> None:
        pnl = [0.01] * (KUPIEC_MIN_OBS - 1)
        r = kupiec_pof(pnl, 0.05, conf=0.99)
        assert r.n_obs == KUPIEC_MIN_OBS - 1
        assert r.model_valid is True  # insufficient data → default valid
        assert r.exceedances == 0


# ── LR statistic formula ────────────────────────────────────────────────────

class TestLRStatistic:
    def test_lr_formula_manual(self) -> None:
        """Verify LR matches the Kupiec (1995) formula manually."""
        n = 250
        x = 5  # exceedances
        conf = 0.99
        p_exp = 1 - conf  # 0.01
        p_obs = x / n  # 0.02

        lr_expected = -2.0 * (
            (n - x) * np.log(1.0 - p_exp)
            + x * np.log(p_exp)
            - (n - x) * np.log(1.0 - p_obs)
            - x * np.log(p_obs)
        )
        pv_expected = float(1.0 - chi2.cdf(lr_expected, df=1))

        pnl, var_series = _craft_exceedances(n=250, var_val=0.05, n_exceed=5)
        r = kupiec_pof(pnl, var_series, conf=0.99)

        assert abs(r.lr_statistic - lr_expected) < 1e-8
        assert abs(r.p_value - pv_expected) < 1e-8

    def test_lr_non_negative(self) -> None:
        """LR statistic should always be >= 0."""
        pnl, var_series = _craft_exceedances(n=200, var_val=0.05, n_exceed=2)
        r = kupiec_pof(pnl, var_series, conf=0.99)
        assert r.lr_statistic >= 0.0

    def test_p_value_in_range(self) -> None:
        pnl, var_series = _craft_exceedances(n=200, var_val=0.05, n_exceed=4)
        r = kupiec_pof(pnl, var_series, conf=0.99)
        assert 0.0 <= r.p_value <= 1.0


# ── Model validity ───────────────────────────────────────────────────────────

class TestModelValidity:
    def test_valid_model_low_exceedances(self) -> None:
        """~1% exceedances at 99% conf → model valid."""
        n = 500
        n_exceed = 5  # 1% of 500
        pnl, var_series = _craft_exceedances(n=n, var_val=0.05, n_exceed=n_exceed)
        r = kupiec_pof(pnl, var_series, conf=0.99)
        assert r.model_valid is True
        assert r.p_value > 0.05

    def test_invalid_model_excess_exceedances(self) -> None:
        """~10% exceedances at 99% conf → model invalid."""
        n = 500
        n_exceed = 50  # 10% >> 1%
        pnl, var_series = _craft_exceedances(n=n, var_val=0.05, n_exceed=n_exceed)
        r = kupiec_pof(pnl, var_series, conf=0.99)
        assert r.model_valid is False
        assert r.p_value < 0.05

    def test_95_conf_valid(self) -> None:
        """~5% exceedances at 95% conf → valid."""
        n = 400
        n_exceed = 20  # 5% of 400
        pnl, var_series = _craft_exceedances(n=n, var_val=0.03, n_exceed=n_exceed)
        r = kupiec_pof(pnl, var_series, conf=0.95)
        assert r.model_valid is True

    def test_95_conf_invalid(self) -> None:
        """~20% exceedances at 95% conf → invalid."""
        n = 400
        n_exceed = 80  # 20% >> 5%
        pnl, var_series = _craft_exceedances(n=n, var_val=0.03, n_exceed=n_exceed)
        r = kupiec_pof(pnl, var_series, conf=0.95)
        assert r.model_valid is False


# ── Synthetic portfolio: binomial consistency ────────────────────────────────

class TestBinomialConsistency:
    def test_exceedance_within_binomial_bounds(self) -> None:
        """Exceedances from a correct model should fall within binomial CI."""
        n = 1000
        conf = 0.99
        p_exp = 1 - conf
        rng = np.random.RandomState(2025)

        # Generate returns from known distribution, then compute exact VaR
        returns = rng.normal(0.001, 0.02, n)
        var_99 = float(-np.percentile(returns, (1 - conf) * 100))

        r = kupiec_pof(returns.tolist(), var_99, conf=conf)

        # 99.9% binomial CI
        lo = binom.ppf(0.0005, n, p_exp)
        hi = binom.ppf(0.9995, n, p_exp)
        assert lo <= r.exceedances <= hi, (
            f"exceedances={r.exceedances} outside [{lo}, {hi}]"
        )

    def test_correct_model_passes(self) -> None:
        """A correctly specified model should pass Kupiec > 90% of the time."""
        pass_count = 0
        n = 500
        conf = 0.99

        for seed in range(50):
            rng = np.random.RandomState(seed + 1000)
            returns = rng.normal(0.001, 0.02, n)
            var_99 = float(-np.percentile(returns, (1 - conf) * 100))
            r = kupiec_pof(returns.tolist(), var_99, conf=conf)
            if r.model_valid:
                pass_count += 1

        # Under correct model, p_value > 0.05 should hold ≥ 90% of the time
        assert pass_count >= 40, f"Only {pass_count}/50 passed"

    def test_wrong_model_fails_often(self) -> None:
        """A consistently under-predicting model should fail often."""
        fail_count = 0
        n = 500
        conf = 0.99

        for seed in range(30):
            rng = np.random.RandomState(seed + 2000)
            returns = rng.normal(-0.005, 0.04, n)  # volatile + negative drift
            # Use a VaR that's way too small (from a calm distribution)
            var_too_small = 0.01  # 1% VaR, but actual losses are much worse
            r = kupiec_pof(returns.tolist(), var_too_small, conf=conf)
            if not r.model_valid:
                fail_count += 1

        assert fail_count >= 20, f"Only {fail_count}/30 failed (expected most)"


# ── Multi-confidence suite ───────────────────────────────────────────────────

class TestBacktestSuite:
    def test_run_multiple_confs(self) -> None:
        pnl = _normal_pnl(n=300)
        var_95 = float(-np.percentile(pnl, 5))
        var_99 = float(-np.percentile(pnl, 1))

        results = run_backtest_suite(pnl, {0.95: var_95, 0.99: var_99})
        assert 0.95 in results
        assert 0.99 in results
        assert all(isinstance(v, KupiecResult) for v in results.values())

    def test_suite_each_conf_independent(self) -> None:
        pnl = _normal_pnl(n=300)
        var_99 = float(-np.percentile(pnl, 1))

        suite = run_backtest_suite(pnl, {0.99: var_99})
        single = kupiec_pof(pnl, var_99, conf=0.99)

        assert suite[0.99].exceedances == single.exceedances
        assert abs(suite[0.99].p_value - single.p_value) < 1e-12


# ── Report generation ────────────────────────────────────────────────────────

class TestReportGeneration:
    def test_generates_markdown(self, tmp_path: Path) -> None:
        pnl, var_s = _craft_exceedances(n=100, var_val=0.05, n_exceed=2)
        r = kupiec_pof(pnl, var_s, conf=0.99)
        out = generate_backtest_report(r, report_dir=tmp_path)
        assert out.exists()
        assert out.suffix == ".md"

    def test_report_contains_sections(self, tmp_path: Path) -> None:
        pnl, var_s = _craft_exceedances(n=100, var_val=0.05, n_exceed=2)
        r = kupiec_pof(pnl, var_s, conf=0.99)
        out = generate_backtest_report(r, report_dir=tmp_path)
        content = out.read_text(encoding="utf-8")
        assert "# Kupiec POF Backtest Report" in content
        assert "Confidence" in content
        assert "p-value" in content

    def test_multi_conf_report(self, tmp_path: Path) -> None:
        pnl = _normal_pnl(n=300)
        var_95 = float(-np.percentile(pnl, 5))
        var_99 = float(-np.percentile(pnl, 1))
        results = run_backtest_suite(pnl, {0.95: var_95, 0.99: var_99})
        out = generate_backtest_report(results, report_dir=tmp_path)
        content = out.read_text(encoding="utf-8")
        assert "95.0%" in content
        assert "99.0%" in content

    def test_fail_marker_in_report(self, tmp_path: Path) -> None:
        pnl, var_s = _craft_exceedances(n=500, var_val=0.05, n_exceed=50)
        r = kupiec_pof(pnl, var_s, conf=0.99)
        out = generate_backtest_report(r, report_dir=tmp_path)
        content = out.read_text(encoding="utf-8")
        assert "FAIL" in content


# ── Nightly CI entry-point ───────────────────────────────────────────────────

class TestNightlyCheck:
    def test_combined_file(self, tmp_path: Path) -> None:
        pnl, var_s = _craft_exceedances(n=100, var_val=0.05, n_exceed=1)
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        combined = data_dir / "backtest_input.json"
        combined.write_text(json.dumps({
            "realized_pnl": pnl,
            "predicted_var": var_s,
        }), encoding="utf-8")

        # Patch _DATA path by calling kupiec_pof directly
        raw = json.loads(combined.read_text(encoding="utf-8"))
        r = kupiec_pof(raw["realized_pnl"], raw["predicted_var"], conf=0.99)
        assert r.model_valid is True

    def test_separate_files(self, tmp_path: Path) -> None:
        pnl, var_s = _craft_exceedances(n=100, var_val=0.05, n_exceed=1)
        pnl_f = tmp_path / "pnl.json"
        var_f = tmp_path / "var.json"
        pnl_f.write_text(json.dumps(pnl), encoding="utf-8")
        var_f.write_text(json.dumps(var_s), encoding="utf-8")
        r = nightly_kupiec_check(pnl_path=pnl_f, var_path=var_f, conf=0.99)
        assert isinstance(r, KupiecResult)
        assert r.model_valid is True

    def test_missing_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            nightly_kupiec_check(
                pnl_path=Path("/nonexistent/pnl.json"),
                var_path=Path("/nonexistent/var.json"),
            )


# ── Edge cases ───────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_exactly_min_obs(self) -> None:
        pnl, var_s = _craft_exceedances(n=KUPIEC_MIN_OBS, var_val=0.05, n_exceed=1)
        r = kupiec_pof(pnl, var_s, conf=0.99)
        assert r.n_obs == KUPIEC_MIN_OBS
        assert r.exceedances == 1

    def test_large_sample(self) -> None:
        pnl, var_s = _craft_exceedances(n=2000, var_val=0.05, n_exceed=20)
        r = kupiec_pof(pnl, var_s, conf=0.99)
        assert r.n_obs == 2000
        assert r.exceedances == 20

    def test_very_high_confidence(self) -> None:
        """99.9% confidence → expected exceedances very low."""
        pnl, var_s = _craft_exceedances(n=1000, var_val=0.10, n_exceed=1)
        r = kupiec_pof(pnl, var_s, conf=0.999)
        assert abs(r.expected - 1.0) < 1e-10  # 1000 × 0.001
        assert r.model_valid is True


# ── Deterministic reproducibility ────────────────────────────────────────────

class TestReproducibility:
    def test_same_inputs_same_output(self) -> None:
        pnl, var_s = _craft_exceedances(n=200, var_val=0.05, n_exceed=4)
        r1 = kupiec_pof(pnl, var_s, conf=0.99)
        r2 = kupiec_pof(pnl, var_s, conf=0.99)
        assert r1.exceedances == r2.exceedances
        assert r1.lr_statistic == r2.lr_statistic
        assert r1.p_value == r2.p_value


# ── Topology sentinel ────────────────────────────────────────────────────────

class TestTopologySentinel:
    def test_sentinel_present(self) -> None:
        from super_otonom.risk.var_backtest import var_backtest_kupiec
        assert var_backtest_kupiec is True
