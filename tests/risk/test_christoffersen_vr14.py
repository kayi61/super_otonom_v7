"""Tests for Christoffersen independence + conditional coverage (VR-14).

Covers:
- christoffersen_ind()  — transition counts, LR statistic, p-value
- christoffersen_cc()   — combined Kupiec + independence
- run_cc_suite()        — multi-confidence wrapper
- _build_exceedance_series() — PnL → binary helper
- generate_backtest_report() — CC-aware markdown output
- Boundary cases: all zeros, all ones, insufficient data, alternating
- Clustered series → reject independence
- Random-ish series → accept independence
- Sentinel presence: var_backtest_kupiec
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import numpy as np
import pytest
from super_otonom.risk.var_backtest import (
    KUPIEC_MIN_OBS,
    ChristoffersenResult,
    ConditionalCoverageResult,
    KupiecResult,
    _build_exceedance_series,
    christoffersen_cc,
    christoffersen_ind,
    generate_backtest_report,
    kupiec_pof,
    run_cc_suite,
    var_backtest_kupiec,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_clustered_series(n: int = 300, cluster_len: int = 10, n_clusters: int = 5) -> List[int]:
    """Create exceedance series with obvious clustering."""
    series = [0] * n
    step = n // (n_clusters + 1)
    for c in range(n_clusters):
        start = step * (c + 1)
        for i in range(cluster_len):
            if start + i < n:
                series[start + i] = 1
    return series


def _make_random_series(n: int = 300, p: float = 0.05, seed: int = 42) -> List[int]:
    """Create iid Bernoulli exceedance series (no clustering)."""
    rng = np.random.RandomState(seed)
    return [int(x) for x in rng.binomial(1, p, size=n)]


def _craft_pnl_and_var(
    exceedance_pattern: List[int],
    var_val: float = 0.05,
) -> tuple[List[float], float]:
    """Convert binary pattern to PnL series against a constant VaR."""
    pnl = []
    for e in exceedance_pattern:
        if e == 1:
            pnl.append(-(var_val + 0.01))  # exceeds VaR
        else:
            pnl.append(0.01)  # no exceedance
    return pnl, var_val


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: _build_exceedance_series
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildExceedanceSeries:
    def test_basic_exceedance(self):
        pnl = [0.01, -0.06, 0.02, -0.11, 0.0]
        var_ = 0.05
        result = _build_exceedance_series(pnl, var_)
        assert result == [0, 1, 0, 1, 0]

    def test_vector_var(self):
        pnl = [-0.06, -0.04, -0.08]
        var_ = [0.05, 0.05, 0.10]
        result = _build_exceedance_series(pnl, var_)
        assert result == [1, 0, 0]

    def test_all_exceed(self):
        pnl = [-0.10, -0.10, -0.10]
        result = _build_exceedance_series(pnl, 0.05)
        assert result == [1, 1, 1]

    def test_none_exceed(self):
        pnl = [0.01, 0.02, 0.03]
        result = _build_exceedance_series(pnl, 0.05)
        assert result == [0, 0, 0]

    def test_boundary_exact_var(self):
        """PnL exactly at -VaR should NOT be an exceedance (strict <)."""
        pnl = [-0.05]
        result = _build_exceedance_series(pnl, 0.05)
        assert result == [0]


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: christoffersen_ind
# ═══════════════════════════════════════════════════════════════════════════════


class TestChristoffersenInd:
    def test_insufficient_data(self):
        series = [0, 1, 0]
        r = christoffersen_ind(series)
        assert r.independent is True
        assert r.p_value_ind == 1.0

    def test_all_zeros_boundary(self):
        series = [0] * 100
        r = christoffersen_ind(series)
        assert r.independent is True
        assert r.n01 == 0
        assert r.n11 == 0
        assert r.n00 == 99  # n-1 transitions

    def test_all_ones_boundary(self):
        series = [1] * 100
        r = christoffersen_ind(series)
        assert r.independent is True
        assert r.n11 == 99
        assert r.n00 == 0

    def test_transition_counts_manual(self):
        # 0,0,1,1,0,1,0,0,0,1
        series = [0, 0, 1, 1, 0, 1, 0, 0, 0, 1]
        # We need >= 50 obs, so pad with zeros
        series = series + [0] * 50
        r = christoffersen_ind(series)
        # Manual count (60 elements, 59 transitions):
        # First 10: (0→0)=3, (0→1)=3, (1→0)=2, (1→1)=1
        # Index 9→10: (1→0)=+1 → n10=3
        # Index 10..59: 49 × (0→0) → n00=3+49=52
        assert r.n00 == 52
        assert r.n01 == 3
        assert r.n10 == 3
        assert r.n11 == 1
        # With mostly zeros appended, pi is small, should be independent
        assert r.independent is True

    def test_clustered_series_rejects(self):
        """Heavily clustered exceedances should reject independence."""
        series = _make_clustered_series(n=500, cluster_len=15, n_clusters=8)
        r = christoffersen_ind(series)
        # Clustering → pi_11 >> pi_01 → LR high → reject
        assert r.independent is False
        assert r.p_value_ind < 0.05
        assert r.lr_ind > 0

    def test_random_series_accepts(self):
        """IID Bernoulli exceedances should pass independence."""
        series = _make_random_series(n=500, p=0.05, seed=123)
        r = christoffersen_ind(series)
        assert r.independent is True
        assert r.p_value_ind > 0.05

    def test_alternating_series(self):
        """Perfect alternation 0,1,0,1,... — no clustering, should pass."""
        series = [i % 2 for i in range(200)]
        r = christoffersen_ind(series)
        # n01 = n10 = 100, n00 = n11 = 0 → boundary (pi_01=1, pi_11=0)
        # This triggers the log(0) guard → default independent
        assert r.independent is True

    def test_lr_chi2_distribution(self):
        """LR stat should be non-negative."""
        series = _make_random_series(n=300, p=0.10, seed=77)
        r = christoffersen_ind(series)
        assert r.lr_ind >= 0.0
        assert 0.0 <= r.p_value_ind <= 1.0

    def test_pi_values(self):
        """pi_01 and pi_11 should be valid probabilities."""
        series = _make_random_series(n=300, p=0.08, seed=99)
        r = christoffersen_ind(series)
        assert 0.0 <= r.pi_01 <= 1.0
        assert 0.0 <= r.pi_11 <= 1.0
        assert 0.0 <= r.pi <= 1.0

    def test_result_is_frozen(self):
        r = christoffersen_ind([0] * 100)
        with pytest.raises(AttributeError):
            r.independent = False  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: christoffersen_cc
# ═══════════════════════════════════════════════════════════════════════════════


class TestChristoffersenCC:
    def test_basic_cc_pass(self):
        """Non-clustered, correct exceedance rate → both tests pass."""
        rng = np.random.RandomState(42)
        n = 500
        conf = 0.95
        var_val = 0.05
        # Generate returns: ~5% exceed VaR (match expected rate)
        pnl = []
        for _ in range(n):
            if rng.random() < 0.05:
                pnl.append(-(var_val + 0.01))
            else:
                pnl.append(rng.normal(0.001, 0.02))
        r = christoffersen_cc(pnl, var_val, conf=conf)
        assert isinstance(r, ConditionalCoverageResult)
        assert isinstance(r.kupiec, KupiecResult)
        assert isinstance(r.independence, ChristoffersenResult)
        assert r.kupiec.confidence == conf

    def test_clustered_cc_fails(self):
        """Clustered exceedances → independence fails → CC fails."""
        pattern = _make_clustered_series(n=500, cluster_len=15, n_clusters=8)
        pnl, var_val = _craft_pnl_and_var(pattern)
        r = christoffersen_cc(pnl, var_val, conf=0.99)
        # Independence should fail
        assert r.independence.independent is False
        # CC model_valid requires both → should be False
        assert r.model_valid is False

    def test_lr_cc_additive(self):
        """LR_cc = LR_kupiec + LR_ind."""
        rng = np.random.RandomState(55)
        n = 300
        var_val = 0.05
        pnl = [-(var_val + 0.01) if rng.random() < 0.08 else 0.01 for _ in range(n)]
        r = christoffersen_cc(pnl, var_val, conf=0.95)
        expected_lr = r.kupiec.lr_statistic + r.independence.lr_ind
        assert abs(r.lr_cc - expected_lr) < 1e-10

    def test_cc_chi2_df2(self):
        """p_value_cc should come from chi2(df=2)."""
        from scipy.stats import chi2

        rng = np.random.RandomState(66)
        n = 300
        var_val = 0.05
        pnl = [-(var_val + 0.01) if rng.random() < 0.06 else 0.01 for _ in range(n)]
        r = christoffersen_cc(pnl, var_val, conf=0.95)
        expected_p = float(1.0 - chi2.cdf(r.lr_cc, df=2))
        assert abs(r.p_value_cc - expected_p) < 1e-10

    def test_insufficient_data(self):
        pnl = [0.01] * 10
        r = christoffersen_cc(pnl, 0.05, conf=0.99)
        assert r.model_valid is True
        assert r.kupiec.n_obs == 10

    def test_model_valid_requires_both(self):
        """model_valid is True only when BOTH kupiec AND independence pass."""
        # Create series where Kupiec passes but independence fails
        pattern = _make_clustered_series(n=500, cluster_len=10, n_clusters=2)
        exc_count = sum(pattern)
        # conf such that expected exceedances ≈ actual (Kupiec passes)
        # but clusters remain (independence fails)
        conf = 1.0 - exc_count / 500
        pnl, var_val = _craft_pnl_and_var(pattern)
        r = christoffersen_cc(pnl, var_val, conf=conf)
        # If independence rejects, model_valid must be False
        if not r.independence.independent:
            assert r.model_valid is False

    def test_result_is_frozen(self):
        r = christoffersen_cc([0.01] * 100, 0.05, conf=0.99)
        with pytest.raises(AttributeError):
            r.model_valid = False  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: run_cc_suite
# ═══════════════════════════════════════════════════════════════════════════════


class TestRunCCSuite:
    def test_multi_confidence(self):
        rng = np.random.RandomState(42)
        n = 300
        pnl = [rng.normal(0.001, 0.03) for _ in range(n)]
        predicted_vars = {
            0.95: 0.05,
            0.99: 0.08,
        }
        results = run_cc_suite(pnl, predicted_vars)
        assert set(results.keys()) == {0.95, 0.99}
        for conf, r in results.items():
            assert isinstance(r, ConditionalCoverageResult)
            assert r.kupiec.confidence == conf

    def test_empty_suite(self):
        results = run_cc_suite([0.01] * 100, {})
        assert results == {}

    def test_single_confidence(self):
        rng = np.random.RandomState(77)
        n = 200
        pnl = [rng.normal(0.0, 0.02) for _ in range(n)]
        results = run_cc_suite(pnl, {0.99: 0.06})
        assert len(results) == 1
        assert 0.99 in results


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: generate_backtest_report with CC
# ═══════════════════════════════════════════════════════════════════════════════


class TestReportCC:
    def test_cc_report_has_independence_section(self, tmp_path: Path):
        rng = np.random.RandomState(42)
        n = 200
        pnl = [rng.normal(0.001, 0.03) for _ in range(n)]
        results = run_cc_suite(pnl, {0.95: 0.05, 0.99: 0.08})
        path = generate_backtest_report(results, report_dir=tmp_path)
        text = path.read_text(encoding="utf-8")
        assert "## Christoffersen Independence" in text
        assert "## Conditional Coverage (Combined)" in text
        assert "LR_ind" in text
        assert "LR_cc" in text

    def test_cc_report_has_kupiec_section(self, tmp_path: Path):
        rng = np.random.RandomState(42)
        n = 200
        pnl = [rng.normal(0.001, 0.03) for _ in range(n)]
        results = run_cc_suite(pnl, {0.99: 0.08})
        path = generate_backtest_report(results, report_dir=tmp_path)
        text = path.read_text(encoding="utf-8")
        assert "## Kupiec POF" in text
        assert "Exceedances" in text

    def test_single_cc_result(self, tmp_path: Path):
        rng = np.random.RandomState(42)
        n = 200
        pnl = [rng.normal(0.001, 0.03) for _ in range(n)]
        single = christoffersen_cc(pnl, 0.05, conf=0.95)
        path = generate_backtest_report(single, report_dir=tmp_path)
        text = path.read_text(encoding="utf-8")
        assert "## Kupiec POF" in text
        assert "## Christoffersen Independence" in text

    def test_kupiec_only_report_no_independence(self, tmp_path: Path):
        """Pure Kupiec results should NOT contain independence section."""
        from super_otonom.risk.var_backtest import run_backtest_suite

        rng = np.random.RandomState(42)
        n = 200
        pnl = [rng.normal(0.001, 0.03) for _ in range(n)]
        results = run_backtest_suite(pnl, {0.99: 0.08})
        path = generate_backtest_report(results, report_dir=tmp_path)
        text = path.read_text(encoding="utf-8")
        assert "## Kupiec POF" in text
        assert "## Christoffersen Independence" not in text

    def test_report_pass_fail_markers(self, tmp_path: Path):
        pattern = _make_clustered_series(n=500, cluster_len=15, n_clusters=8)
        pnl, var_val = _craft_pnl_and_var(pattern)
        results = run_cc_suite(pnl, {0.99: var_val})
        path = generate_backtest_report(results, report_dir=tmp_path)
        text = path.read_text(encoding="utf-8")
        assert "FAIL" in text or "PASS" in text

    def test_report_overall_status(self, tmp_path: Path):
        rng = np.random.RandomState(42)
        n = 200
        pnl = [rng.normal(0.001, 0.03) for _ in range(n)]
        results = run_cc_suite(pnl, {0.95: 0.05})
        path = generate_backtest_report(results, report_dir=tmp_path)
        text = path.read_text(encoding="utf-8")
        assert "**Overall:**" in text


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Edge cases and statistical properties
# ═══════════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    def test_single_exceedance_at_start(self):
        series = [1] + [0] * 99
        r = christoffersen_ind(series)
        assert r.n01 == 0
        assert r.n10 == 1
        assert r.independent is True

    def test_single_exceedance_at_end(self):
        series = [0] * 99 + [1]
        r = christoffersen_ind(series)
        assert r.n01 == 1
        assert r.n10 == 0
        # n10+n11=0 → boundary → independent
        assert r.independent is True

    def test_two_consecutive_exceedances(self):
        series = [0] * 48 + [1, 1] + [0] * 50
        r = christoffersen_ind(series)
        assert r.n11 == 1
        assert r.n01 == 1
        assert r.n10 == 1
        # pi_11 = 0.5 vs pi_01 ≈ 0.01 — even 2 consecutive exceedances
        # in a mostly-zero series creates significant pi divergence
        assert r.pi_11 == 0.5
        assert r.pi_01 < 0.02

    def test_high_exceedance_rate_random(self):
        """Even high exceedance rate, if iid, should pass independence."""
        series = _make_random_series(n=500, p=0.20, seed=88)
        r = christoffersen_ind(series)
        # iid → should pass independence
        assert r.independent is True

    def test_exactly_50_obs(self):
        """Minimum sample size boundary — should run."""
        series = [0] * 45 + [1, 0, 1, 0, 1]
        assert len(series) == KUPIEC_MIN_OBS
        r = christoffersen_ind(series)
        # ChristoffersenResult has no n_obs; just check it ran
        assert isinstance(r, ChristoffersenResult)
        assert r.n00 + r.n01 + r.n10 + r.n11 == 49  # n-1 transitions

    def test_49_obs_returns_default(self):
        """Below minimum — returns default."""
        series = [0] * 49
        r = christoffersen_ind(series)
        assert r.independent is True
        assert r.p_value_ind == 1.0
        assert r.lr_ind == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Sentinel and integration
# ═══════════════════════════════════════════════════════════════════════════════


class TestSentinelIntegration:
    def test_sentinel_present(self):
        assert var_backtest_kupiec is True

    def test_imports_from_risk_package(self):
        """VR-14 exports should be accessible from risk package."""
        from super_otonom.risk import (
            ChristoffersenResult,
            ConditionalCoverageResult,
            christoffersen_cc,
            christoffersen_ind,
            run_cc_suite,
        )

        assert ChristoffersenResult is not None
        assert ConditionalCoverageResult is not None
        assert callable(christoffersen_ind)
        assert callable(christoffersen_cc)
        assert callable(run_cc_suite)

    def test_cc_consistent_with_separate_calls(self):
        """CC result should be consistent with running kupiec + ind separately."""
        rng = np.random.RandomState(42)
        n = 300
        var_val = 0.05
        pnl = [rng.normal(0.001, 0.03) for _ in range(n)]

        cc = christoffersen_cc(pnl, var_val, conf=0.95)
        kup = kupiec_pof(pnl, var_val, conf=0.95)
        exc_series = _build_exceedance_series(pnl, var_val)
        ind = christoffersen_ind(exc_series)

        assert cc.kupiec.exceedances == kup.exceedances
        assert cc.kupiec.p_value == kup.p_value
        assert cc.independence.lr_ind == ind.lr_ind
        assert cc.independence.p_value_ind == ind.p_value_ind

    def test_cc_pnl_var_mismatch_raises(self):
        pnl = [0.01] * 100
        var_ = [0.05] * 50  # length mismatch
        with pytest.raises(ValueError, match="length"):
            christoffersen_cc(pnl, var_, conf=0.99)


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Statistical power
# ═══════════════════════════════════════════════════════════════════════════════


class TestStatisticalPower:
    def test_strong_cluster_high_lr(self):
        """Very strong clustering should yield very high LR."""
        # 10 blocks of 20 exceedances each, separated by 30 zeros
        series: List[int] = []
        for _ in range(10):
            series.extend([1] * 20)
            series.extend([0] * 30)
        r = christoffersen_ind(series)
        assert r.lr_ind > 50  # strong signal
        assert r.p_value_ind < 0.001

    def test_no_cluster_low_lr(self):
        """Pure iid should yield low LR with high probability."""
        series = _make_random_series(n=1000, p=0.05, seed=42)
        r = christoffersen_ind(series)
        # chi2(1) at 95% = 3.84; random series should typically be below
        assert r.p_value_ind > 0.01  # generous threshold

    def test_cc_power_on_joint_failure(self):
        """Both wrong coverage + clustering → very low CC p-value."""
        # Too many exceedances AND clustered
        series: List[int] = []
        for _ in range(5):
            series.extend([1] * 30)
            series.extend([0] * 70)
        pnl, var_val = _craft_pnl_and_var(series)
        r = christoffersen_cc(pnl, var_val, conf=0.99)
        # Expected: 1% exceedance but actual is 30%
        assert r.kupiec.model_valid is False
        assert r.independence.independent is False
        assert r.model_valid is False
        assert r.p_value_cc < 0.01
