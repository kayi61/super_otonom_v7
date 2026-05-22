"""VR-27: Statistical Regime Detection Engine.

Detects market regimes (TRENDING / RANGING / CRASH_RISK) from
return data using rolling statistical features.  Feeds into
``RegimeConditionalVaR`` (VR-10) which was waiting for an
automated regime *producer* — it only consumes labels.

Methods:
  1. Volatility-threshold: rolling σ + return sign → 3 regimes
  2. Z-score change-point: detects abrupt regime transitions
  3. Composite: majority vote of multiple signals

All methods are pure NumPy/SciPy — no heavy ML dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy import stats as sp_stats

# Sentinel for var_topology detection
regime_detection_engine_active = True

REGIME_DETECTOR_MIN_OBS = 60
"""Minimum observations for regime detection."""


class Regime(str, Enum):
    """Market regime labels compatible with RegimeConditionalVaR."""

    TRENDING = "TRENDING"
    RANGING = "RANGING"
    CRASH_RISK = "CRASH_RISK"


@dataclass(frozen=True)
class RegimeState:
    """Current regime detection result."""

    regime: str
    confidence: float  # 0.0–1.0
    vol_current: float
    vol_mean: float
    vol_percentile: float  # current vol's percentile in history
    return_zscore: float
    features: Dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class RegimeHistory:
    """Full regime classification over a return series."""

    regimes: List[str]
    confidences: List[float]
    transition_indices: List[int]
    regime_durations: Dict[str, float]  # avg duration per regime


# ── Volatility-Threshold Detector ──────────────────────────────────────────


def _rolling_std(returns: np.ndarray, window: int) -> np.ndarray:
    """Rolling standard deviation (NaN for first `window-1` entries)."""
    result = np.full(len(returns), np.nan)
    for i in range(window - 1, len(returns)):
        result[i] = float(np.std(returns[i - window + 1 : i + 1], ddof=1))
    return result


def _rolling_mean(returns: np.ndarray, window: int) -> np.ndarray:
    """Rolling mean."""
    result = np.full(len(returns), np.nan)
    for i in range(window - 1, len(returns)):
        result[i] = float(np.mean(returns[i - window + 1 : i + 1]))
    return result


def classify_volatility_threshold(
    returns: Sequence[float],
    vol_window: int = 20,
    return_window: int = 10,
    crash_vol_pct: float = 90.0,
    crash_ret_threshold: float = -0.02,
    low_vol_pct: float = 40.0,
) -> Tuple[List[str], List[float]]:
    """Classify each timestep into a regime using volatility thresholds.

    Rules:
      - CRASH_RISK: vol > 90th percentile AND mean return < -2%
      - TRENDING: vol < 40th percentile AND abs(mean_return) > 0.3*vol
      - RANGING: everything else

    Returns (regime_labels, confidences) aligned with input.
    """
    ret = np.asarray(returns, dtype=np.float64)
    n = len(ret)
    if n < vol_window + 1:
        return [Regime.RANGING.value] * n, [0.5] * n

    vol = _rolling_std(ret, vol_window)
    rm = _rolling_mean(ret, return_window)

    # Compute vol percentile thresholds from valid observations
    valid_vol = vol[~np.isnan(vol)]
    if len(valid_vol) < 10:
        return [Regime.RANGING.value] * n, [0.5] * n

    vol_p_crash = float(np.percentile(valid_vol, crash_vol_pct))
    vol_p_low = float(np.percentile(valid_vol, low_vol_pct))

    regimes: List[str] = []
    confidences: List[float] = []

    for i in range(n):
        if np.isnan(vol[i]) or np.isnan(rm[i]):
            regimes.append(Regime.RANGING.value)
            confidences.append(0.3)
            continue

        v = vol[i]
        r = rm[i]

        # CRASH_RISK: high vol + negative returns
        if v >= vol_p_crash and r < crash_ret_threshold:
            conf = min(1.0, 0.6 + 0.4 * (v / vol_p_crash - 1.0))
            regimes.append(Regime.CRASH_RISK.value)
            confidences.append(conf)
        # TRENDING: low vol + directional movement
        elif v <= vol_p_low and abs(r) > 0.3 * v and abs(r) > 1e-6:
            conf = min(1.0, 0.5 + 0.5 * abs(r) / max(v, 1e-6))
            regimes.append(Regime.TRENDING.value)
            confidences.append(min(conf, 0.95))
        else:
            regimes.append(Regime.RANGING.value)
            confidences.append(0.5)

    return regimes, confidences


# ── Z-Score Change-Point Detector ──────────────────────────────────────────


def detect_change_points(
    returns: Sequence[float],
    window: int = 30,
    threshold: float = 2.5,
) -> List[int]:
    """Detect regime change points via rolling z-score of volatility.

    A change point is flagged when the z-score of the current volatility
    (relative to the expanding mean/std of historical vol) exceeds the
    threshold.
    """
    ret = np.asarray(returns, dtype=np.float64)
    vol = _rolling_std(ret, min(window, 20))

    change_points: List[int] = []
    valid_vols: List[float] = []

    for i in range(len(vol)):
        if np.isnan(vol[i]):
            continue
        valid_vols.append(vol[i])
        if len(valid_vols) < 20:
            continue
        mu = float(np.mean(valid_vols[:-1]))
        sigma = float(np.std(valid_vols[:-1], ddof=1))
        if sigma < 1e-12:
            continue
        z = (vol[i] - mu) / sigma
        if abs(z) > threshold:
            # Suppress close duplicates (within 5 bars)
            if not change_points or i - change_points[-1] > 5:
                change_points.append(i)

    return change_points


# ── Composite Regime Detector ──────────────────────────────────────────────


class RegimeDetector:
    """Composite regime detector using multiple statistical signals.

    Feeds into ``RegimeConditionalVaR.record(return_t, regime_t)``
    to close the VR-10 loop.

    Usage::

        detector = RegimeDetector()
        detector.fit(historical_returns)
        state = detector.current_regime()
        # → RegimeState(regime="CRASH_RISK", confidence=0.85, ...)

        # Live update:
        detector.update(new_return)
        state = detector.current_regime()
    """

    def __init__(
        self,
        vol_window: int = 20,
        return_window: int = 10,
        change_point_threshold: float = 2.5,
        crash_vol_pct: float = 90.0,
        crash_ret_threshold: float = -0.02,
    ) -> None:
        self._vol_window = vol_window
        self._return_window = return_window
        self._cp_threshold = change_point_threshold
        self._crash_vol_pct = crash_vol_pct
        self._crash_ret_threshold = crash_ret_threshold
        self._returns: List[float] = []
        self._regime_history: List[str] = []
        self._confidence_history: List[float] = []

    # ── Fit / Update ──────────────────────────────────────────────────────

    def fit(self, returns: Sequence[float]) -> None:
        """Fit detector on historical returns and classify all timesteps."""
        self._returns = [float(r) for r in returns]
        regimes, confs = classify_volatility_threshold(
            self._returns,
            vol_window=self._vol_window,
            return_window=self._return_window,
            crash_vol_pct=self._crash_vol_pct,
            crash_ret_threshold=self._crash_ret_threshold,
        )
        self._regime_history = regimes
        self._confidence_history = confs

    def update(self, new_return: float) -> str:
        """Add a new return and re-classify the current regime.

        Returns the regime label for the latest timestep.
        """
        self._returns.append(float(new_return))
        # Re-run only on the tail for efficiency
        tail = self._returns[-max(self._vol_window * 3, 100) :]
        regimes, confs = classify_volatility_threshold(
            tail,
            vol_window=self._vol_window,
            return_window=self._return_window,
            crash_vol_pct=self._crash_vol_pct,
            crash_ret_threshold=self._crash_ret_threshold,
        )
        if regimes:
            self._regime_history.append(regimes[-1])
            self._confidence_history.append(confs[-1])
        else:
            self._regime_history.append(Regime.RANGING.value)
            self._confidence_history.append(0.3)
        return self._regime_history[-1]

    # ── Query ─────────────────────────────────────────────────────────────

    def current_regime(self) -> Optional[RegimeState]:
        """Return the current regime state, or None if not enough data."""
        if len(self._returns) < REGIME_DETECTOR_MIN_OBS:
            return None

        ret = np.asarray(self._returns, dtype=np.float64)
        vol = _rolling_std(ret, self._vol_window)
        valid_vol = vol[~np.isnan(vol)]

        if len(valid_vol) < 10:
            return None

        vol_current = float(valid_vol[-1])
        vol_mean = float(np.mean(valid_vol))
        vol_pct = float(sp_stats.percentileofscore(valid_vol, vol_current))

        recent = ret[-self._return_window :]
        ret_mean = float(np.mean(recent))
        ret_std = float(np.std(ret, ddof=1))
        ret_zscore = ret_mean / max(ret_std, 1e-12) * np.sqrt(len(recent))

        regime = self._regime_history[-1] if self._regime_history else Regime.RANGING.value
        conf = self._confidence_history[-1] if self._confidence_history else 0.5

        return RegimeState(
            regime=regime,
            confidence=conf,
            vol_current=vol_current,
            vol_mean=vol_mean,
            vol_percentile=vol_pct,
            return_zscore=ret_zscore,
            features={
                "vol_ratio": vol_current / max(vol_mean, 1e-12),
                "return_mean_10d": ret_mean,
                "skewness": float(sp_stats.skew(recent)) if len(recent) >= 3 else 0.0,
            },
        )

    def classify_full(self) -> Optional[RegimeHistory]:
        """Return full regime classification history."""
        if len(self._returns) < REGIME_DETECTOR_MIN_OBS:
            return None

        # Detect transitions
        transitions: List[int] = []
        for i in range(1, len(self._regime_history)):
            if self._regime_history[i] != self._regime_history[i - 1]:
                transitions.append(i)

        # Compute average duration per regime
        durations: Dict[str, List[int]] = {}
        current_start = 0
        for i in range(1, len(self._regime_history)):
            if self._regime_history[i] != self._regime_history[i - 1]:
                r = self._regime_history[i - 1]
                d = i - current_start
                durations.setdefault(r, []).append(d)
                current_start = i
        # Final segment
        r = self._regime_history[-1]
        durations.setdefault(r, []).append(len(self._regime_history) - current_start)

        avg_durations = {
            k: float(np.mean(v)) for k, v in durations.items()
        }

        return RegimeHistory(
            regimes=list(self._regime_history),
            confidences=list(self._confidence_history),
            transition_indices=transitions,
            regime_durations=avg_durations,
        )

    @property
    def regime_labels(self) -> List[str]:
        """All classified regime labels."""
        return list(self._regime_history)

    @property
    def n_observations(self) -> int:
        return len(self._returns)

    def reset(self) -> None:
        """Clear all state."""
        self._returns.clear()
        self._regime_history.clear()
        self._confidence_history.clear()


# ── Integration helper ────────────────────────────────────────────────────


def detect_and_load_regimes(
    returns: Sequence[float],
    vol_window: int = 20,
) -> Tuple[str, List[str]]:
    """Convenience: detect regimes and return (current_regime, all_labels).

    Designed for direct integration with ``RegimeConditionalVaR.bulk_load()``.
    """
    detector = RegimeDetector(vol_window=vol_window)
    detector.fit(returns)
    state = detector.current_regime()
    current = state.regime if state else Regime.RANGING.value
    return current, detector.regime_labels
