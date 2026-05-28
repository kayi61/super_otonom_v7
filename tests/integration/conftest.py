"""Integration test fixtures — shared across all integration test modules."""

from __future__ import annotations

import random
from typing import Any, Dict, List

import numpy as np
import pytest


@pytest.fixture()
def synthetic_returns() -> List[float]:
    """120 realistic crypto daily returns (mean ~0, vol ~3%)."""
    rng = random.Random(42)
    return [rng.gauss(0.0005, 0.03) for _ in range(120)]


@pytest.fixture()
def synthetic_returns_500() -> List[float]:
    """500 returns for EVT/FHS thresholds."""
    rng = random.Random(123)
    return [rng.gauss(0.0002, 0.025) for _ in range(500)]


@pytest.fixture()
def base_analysis() -> Dict[str, Any]:
    """Minimal analysis dict for phase pipeline."""
    return {
        "signal": "BUY",
        "close": 50000.0,
        "open": 49800.0,
        "high": 50200.0,
        "low": 49500.0,
        "volume": 1500.0,
        "rsi": 55.0,
        "macd": 50.0,
        "atr": 500.0,
        "ema_short": 50100.0,
        "ema_long": 49900.0,
        "bb_upper": 51000.0,
        "bb_lower": 49000.0,
        "adx": 28.0,
        "obv": 100000.0,
    }


@pytest.fixture()
def multi_asset_returns() -> Dict[str, List[float]]:
    """Per-asset return series for decomposition tests."""
    rng = np.random.RandomState(42)
    return {
        "BTC/USDT": rng.normal(0.0005, 0.03, 120).tolist(),
        "ETH/USDT": rng.normal(0.0003, 0.04, 120).tolist(),
        "SOL/USDT": rng.normal(0.0001, 0.05, 120).tolist(),
    }


@pytest.fixture()
def portfolio_weights() -> Dict[str, float]:
    return {"BTC/USDT": 0.5, "ETH/USDT": 0.3, "SOL/USDT": 0.2}
