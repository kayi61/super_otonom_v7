"""VR-27: Regime Detection CLI.

Runs the regime detector on synthetic or live data and reports
the current market regime classification.

Exit codes:
  0  — detection completed successfully
  1  — error during detection
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

regime_detect_active = True

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from super_otonom.risk.regime_detector import (
    RegimeDetector,
    detect_change_points,
)


def _generate_demo_data(seed: int = 42) -> list[float]:
    """Generate mixed-regime demo data."""
    rng = np.random.RandomState(seed)
    calm = rng.normal(0.002, 0.005, 80).tolist()
    ranging = rng.normal(0.0, 0.015, 60).tolist()
    crash = rng.normal(-0.03, 0.06, 40).tolist()
    recovery = rng.normal(0.003, 0.008, 60).tolist()
    return calm + ranging + crash + recovery


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Regime detection (VR-27).")
    p.add_argument("--json", action="store_true", help="JSON output")
    p.add_argument("--seed", type=int, default=42, help="Random seed for demo data")
    args = p.parse_args(list(argv) if argv is not None else None)

    try:
        returns = _generate_demo_data(args.seed)
        detector = RegimeDetector()
        detector.fit(returns)

        state = detector.current_regime()
        hist = detector.classify_full()
        change_points = detect_change_points(returns)

        if state is None:
            print("ERROR: Insufficient data for regime detection")
            return 1

        # Count regimes
        regime_counts = {}
        if hist:
            for r in hist.regimes:
                regime_counts[r] = regime_counts.get(r, 0) + 1

        if args.json:
            payload = {
                "current_regime": state.regime,
                "confidence": round(state.confidence, 4),
                "vol_current": round(state.vol_current, 6),
                "vol_mean": round(state.vol_mean, 6),
                "vol_percentile": round(state.vol_percentile, 2),
                "return_zscore": round(state.return_zscore, 4),
                "regime_counts": regime_counts,
                "change_points": change_points,
                "n_observations": detector.n_observations,
                "features": {k: round(v, 6) for k, v in state.features.items()},
            }
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print("Regime Detection Report (VR-27)")
            print("=" * 45)
            print(f"Observations: {detector.n_observations}")
            print(f"Current regime: {state.regime}")
            print(f"Confidence: {state.confidence:.1%}")
            print(f"Volatility: {state.vol_current:.4%} (mean: {state.vol_mean:.4%})")
            print(f"Vol percentile: {state.vol_percentile:.1f}%")
            print(f"Return z-score: {state.return_zscore:.2f}")
            print()
            print("Regime distribution:")
            for regime, count in sorted(regime_counts.items()):
                pct = count / sum(regime_counts.values()) * 100
                print(f"  {regime}: {count} ({pct:.1f}%)")
            print()
            print(f"Change points detected: {len(change_points)}")
            if change_points:
                print(f"  Indices: {change_points}")

        return 0

    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
