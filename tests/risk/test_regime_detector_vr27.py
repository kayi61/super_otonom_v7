"""VR-27: Regime Detection Engine tests.

Tests cover:
  - Volatility-threshold regime classification
  - Z-score change-point detection
  - RegimeDetector fit/update/query lifecycle
  - Integration with RegimeConditionalVaR (VR-10)
  - Edge cases: constant returns, short series, crash scenarios
  - CLI (--json)
  - Sentinel + audit allowlist
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[2]
from tests._prompt04_source import module_source_path

_PKG = _ROOT / "super_otonom"
sys.path.insert(0, str(_ROOT))

from super_otonom.risk.regime_detector import (
    Regime,
    RegimeDetector,
    RegimeHistory,
    RegimeState,
    classify_volatility_threshold,
    detect_and_load_regimes,
    detect_change_points,
)
from super_otonom.risk.regime_var import RegimeConditionalVaR

# ── Helpers ────────────────────────────────────────────────────────────────


def _calm_returns(n: int = 200, seed: int = 42) -> list[float]:
    """Low-vol positive drift (TRENDING)."""
    rng = np.random.RandomState(seed)
    return (rng.normal(0.002, 0.005, n)).tolist()


def _ranging_returns(n: int = 200, seed: int = 42) -> list[float]:
    """Medium-vol mean-reverting (RANGING)."""
    rng = np.random.RandomState(seed)
    return (rng.normal(0.0, 0.015, n)).tolist()


def _crash_returns(n: int = 200, seed: int = 42) -> list[float]:
    """High-vol negative drift (CRASH_RISK)."""
    rng = np.random.RandomState(seed)
    return (rng.normal(-0.03, 0.06, n)).tolist()


def _mixed_returns(seed: int = 42) -> list[float]:
    """Trending → Ranging → Crash → Trending."""
    rng = np.random.RandomState(seed)
    calm = rng.normal(0.002, 0.005, 80).tolist()
    ranging = rng.normal(0.0, 0.015, 60).tolist()
    crash = rng.normal(-0.03, 0.06, 40).tolist()
    recovery = rng.normal(0.003, 0.008, 60).tolist()
    return calm + ranging + crash + recovery


# ── Volatility-Threshold Classification ────────────────────────────────────


class TestVolatilityThreshold:
    """VR-27: Volatility-based regime classification."""

    def test_calm_market_trending(self):
        returns = _calm_returns(200)
        regimes, confs = classify_volatility_threshold(returns)
        assert len(regimes) == 200
        assert len(confs) == 200
        # Majority should be TRENDING in calm market
        trending_pct = sum(1 for r in regimes if r == "TRENDING") / len(regimes)
        assert trending_pct > 0.2

    def test_crash_market_detected(self):
        returns = _crash_returns(200)
        regimes, confs = classify_volatility_threshold(returns)
        crash_pct = sum(1 for r in regimes if r == "CRASH_RISK") / len(regimes)
        assert crash_pct > 0.05

    def test_all_valid_regimes(self):
        returns = _mixed_returns()
        regimes, _ = classify_volatility_threshold(returns)
        valid = {Regime.TRENDING.value, Regime.RANGING.value, Regime.CRASH_RISK.value}
        assert all(r in valid for r in regimes)

    def test_confidences_bounded(self):
        returns = _mixed_returns()
        _, confs = classify_volatility_threshold(returns)
        assert all(0.0 <= c <= 1.0 for c in confs)

    def test_short_input(self):
        regimes, confs = classify_volatility_threshold([0.01] * 5)
        assert len(regimes) == 5
        assert all(r == "RANGING" for r in regimes)

    def test_output_length_matches_input(self):
        for n in [10, 50, 100, 300]:
            returns = _ranging_returns(n)
            regimes, confs = classify_volatility_threshold(returns)
            assert len(regimes) == n
            assert len(confs) == n


# ── Change-Point Detection ─────────────────────────────────────────────────


class TestChangePointDetection:
    """VR-27: Z-score change-point detection."""

    def test_detects_crash_onset(self):
        calm = _calm_returns(100, seed=1)
        crash = _crash_returns(100, seed=2)
        returns = calm + crash
        cps = detect_change_points(returns, threshold=2.0)
        # Should detect transition around index 100
        assert len(cps) >= 1
        assert any(80 <= cp <= 140 for cp in cps)

    def test_no_change_in_stable(self):
        returns = _calm_returns(200)
        cps = detect_change_points(returns, threshold=3.0)
        # Stable market should have few/no change points
        assert len(cps) <= 3

    def test_multiple_regimes(self):
        returns = _mixed_returns()
        cps = detect_change_points(returns, threshold=2.0)
        assert isinstance(cps, list)
        assert all(isinstance(cp, int) for cp in cps)

    def test_suppresses_close_duplicates(self):
        returns = _mixed_returns()
        cps = detect_change_points(returns)
        for i in range(1, len(cps)):
            assert cps[i] - cps[i - 1] > 5


# ── RegimeDetector Class ──────────────────────────────────────────────────


class TestRegimeDetector:
    """VR-27: RegimeDetector lifecycle."""

    def test_fit_basic(self):
        det = RegimeDetector()
        det.fit(_mixed_returns())
        assert det.n_observations == 240

    def test_current_regime_returns_state(self):
        det = RegimeDetector()
        det.fit(_mixed_returns())
        state = det.current_regime()
        assert state is not None
        assert isinstance(state, RegimeState)
        assert state.regime in {"TRENDING", "RANGING", "CRASH_RISK"}
        assert 0.0 <= state.confidence <= 1.0
        assert state.vol_current > 0
        assert state.vol_mean > 0

    def test_current_regime_none_short_data(self):
        det = RegimeDetector()
        det.fit([0.01] * 10)
        assert det.current_regime() is None

    def test_update_extends_history(self):
        det = RegimeDetector()
        det.fit(_ranging_returns(100))
        initial_n = det.n_observations
        label = det.update(0.01)
        assert det.n_observations == initial_n + 1
        assert label in {"TRENDING", "RANGING", "CRASH_RISK"}

    def test_update_multiple_times(self):
        det = RegimeDetector()
        det.fit(_ranging_returns(100))
        for _ in range(20):
            det.update(np.random.normal(0, 0.02))
        assert det.n_observations == 120

    def test_classify_full(self):
        det = RegimeDetector()
        det.fit(_mixed_returns())
        hist = det.classify_full()
        assert hist is not None
        assert isinstance(hist, RegimeHistory)
        assert len(hist.regimes) == 240
        assert len(hist.confidences) == 240
        assert isinstance(hist.transition_indices, list)
        assert len(hist.transition_indices) > 0
        assert isinstance(hist.regime_durations, dict)

    def test_classify_full_none_short_data(self):
        det = RegimeDetector()
        det.fit([0.01] * 10)
        assert det.classify_full() is None

    def test_regime_labels_property(self):
        det = RegimeDetector()
        det.fit(_ranging_returns(100))
        labels = det.regime_labels
        assert len(labels) == 100

    def test_reset(self):
        det = RegimeDetector()
        det.fit(_mixed_returns())
        det.reset()
        assert det.n_observations == 0
        assert det.current_regime() is None

    def test_custom_params(self):
        det = RegimeDetector(
            vol_window=30,
            return_window=15,
            crash_vol_pct=85.0,
            crash_ret_threshold=-0.01,
        )
        det.fit(_mixed_returns())
        state = det.current_regime()
        assert state is not None

    def test_features_in_state(self):
        det = RegimeDetector()
        det.fit(_mixed_returns())
        state = det.current_regime()
        assert "vol_ratio" in state.features
        assert "return_mean_10d" in state.features
        assert "skewness" in state.features

    def test_vol_percentile_in_state(self):
        det = RegimeDetector()
        det.fit(_mixed_returns())
        state = det.current_regime()
        assert 0.0 <= state.vol_percentile <= 100.0


# ── Integration with RegimeConditionalVaR ──────────────────────────────────


class TestRegimeVaRIntegration:
    """VR-27: RegimeDetector → RegimeConditionalVaR pipeline."""

    def test_detect_and_load(self):
        returns = _mixed_returns()
        current, labels = detect_and_load_regimes(returns)
        assert current in {"TRENDING", "RANGING", "CRASH_RISK"}
        assert len(labels) == len(returns)

    def test_pipeline_with_regime_conditional_var(self):
        returns = _mixed_returns()
        current, labels = detect_and_load_regimes(returns)

        rcv = RegimeConditionalVaR()
        rcv.bulk_load(returns, labels)

        # At least one regime should have data
        assert len(rcv.regimes) >= 1
        # Current regime should have data
        assert rcv.regime_count(current) > 0

    def test_bulk_load_length_matches(self):
        returns = _mixed_returns()
        _, labels = detect_and_load_regimes(returns)
        assert len(labels) == len(returns)

    def test_all_regimes_present_in_mixed(self):
        returns = _mixed_returns()
        _, labels = detect_and_load_regimes(returns)
        unique = set(labels)
        # Mixed data should produce at least 2 different regimes
        assert len(unique) >= 2

    def test_live_update_loop(self):
        """Simulate live: fit on history, update tick-by-tick."""
        rng = np.random.RandomState(99)
        history = rng.normal(0.0, 0.015, 100).tolist()

        det = RegimeDetector()
        det.fit(history)
        rcv = RegimeConditionalVaR()

        # Bulk load history
        _, hist_labels = detect_and_load_regimes(history)
        rcv.bulk_load(history, hist_labels)

        # Live ticks
        for _ in range(30):
            r = float(rng.normal(-0.01, 0.03))
            regime = det.update(r)
            rcv.record(r, regime)

        state = det.current_regime()
        assert state is not None
        assert rcv.regime_count(state.regime) > 0


# ── Edge Cases ─────────────────────────────────────────────────────────────


class TestEdgeCases:
    """VR-27: Edge case robustness."""

    def test_constant_returns(self):
        det = RegimeDetector()
        det.fit([0.001] * 100)
        state = det.current_regime()
        assert state is not None
        assert state.regime in {"TRENDING", "RANGING", "CRASH_RISK"}

    def test_zero_returns(self):
        det = RegimeDetector()
        det.fit([0.0] * 100)
        state = det.current_regime()
        assert state is not None

    def test_single_crash_event(self):
        """One big crash in otherwise calm data."""
        returns = [0.001] * 90 + [-0.15] + [0.001] * 9
        det = RegimeDetector()
        det.fit(returns)
        state = det.current_regime()
        assert state is not None

    def test_alternating_returns(self):
        returns = [0.02 if i % 2 == 0 else -0.02 for i in range(200)]
        det = RegimeDetector()
        det.fit(returns)
        state = det.current_regime()
        assert state is not None

    def test_very_high_volatility(self):
        rng = np.random.RandomState(77)
        returns = rng.normal(0, 0.10, 200).tolist()
        det = RegimeDetector()
        det.fit(returns)
        state = det.current_regime()
        assert state is not None
        assert state.vol_current > 0


# ── Regime Enum ────────────────────────────────────────────────────────────


class TestRegimeEnum:
    """VR-27: Regime enum values."""

    def test_values(self):
        assert Regime.TRENDING.value == "TRENDING"
        assert Regime.RANGING.value == "RANGING"
        assert Regime.CRASH_RISK.value == "CRASH_RISK"

    def test_string_equality(self):
        assert Regime.TRENDING == "TRENDING"
        assert Regime.CRASH_RISK == "CRASH_RISK"


# ── CLI ────────────────────────────────────────────────────────────────────


class TestCLI:
    """VR-27: CLI interface."""

    def test_text_output(self, capsys):
        from scripts.regime_detect import main

        rc = main([])
        captured = capsys.readouterr()
        assert "Regime Detection" in captured.out
        assert rc == 0

    def test_json_output(self, capsys):
        from scripts.regime_detect import main

        rc = main(["--json"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "current_regime" in data
        assert "regime_counts" in data
        assert rc == 0


# ── Sentinel ────────────────────────────────────────────────────────────────


class TestSentinel:
    """VR-27: Sentinel marker."""

    def test_sentinel_present(self):
        src = _ROOT / "super_otonom" / "risk" / "regime_detector.py"
        text = src.read_text(encoding="utf-8")
        assert "regime_detection_engine_active = True" in text

    def test_script_sentinel(self):
        src = _ROOT / "scripts" / "regime_detect.py"
        text = src.read_text(encoding="utf-8")
        assert "regime_detect_active = True" in text


# ── Audit Allowlist ─────────────────────────────────────────────────────────


class TestAuditAllowlist:
    """VR-27: var_topology_audit allowlist entries."""

    def test_test_file_in_allowlist(self):
        text = module_source_path(_PKG, "var_topology_audit").read_text(encoding="utf-8")
        assert "test_regime_detector_vr27" in text

    def test_detector_module_in_allowlist(self):
        text = module_source_path(_PKG, "var_topology_audit").read_text(encoding="utf-8")
        assert "regime_detector" in text

    def test_script_in_allowlist(self):
        text = module_source_path(_PKG, "var_topology_audit").read_text(encoding="utf-8")
        assert "regime_detect" in text
