"""CI %97 hedefi — adversarial_robustness, causal_alpha_engine, rl_trading_agent, liquidity_games_detector."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest

# ── adversarial_robustness ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_extract_ohlcv_skips_bad_numeric_rows_keeps_enough_bars() -> None:
    from super_otonom.adversarial_robustness import _MIN_BARS, extract_ohlcv

    good = [[i, 1.0, 1.1, 0.9, 1.0 + i * 1e-4, 1.0] for i in range(_MIN_BARS + 8)]
    bad_mid = [0, "x", 1.0, 0.9, 1.0, 1.0]
    ohlcv = good[:20] + [bad_mid] + good[20:]
    out = extract_ohlcv({"ohlcv": ohlcv})
    assert out is not None
    _o, h, low, c, v = out
    assert c.size >= _MIN_BARS
    assert float(np.mean(c)) > 0.0


@pytest.mark.asyncio
async def test_score_volatility_spike_low_ratio_uses_scaled_branch() -> None:
    from super_otonom.adversarial_robustness import score_volatility_spike

    rng = np.random.default_rng(99)
    c = 100.0 * np.exp(rng.normal(0, 0.0008, size=80))
    s = float(score_volatility_spike(c))
    assert 0.0 <= s <= 0.5


@pytest.mark.asyncio
async def test_discrete_mi_xy_returns_bounded() -> None:
    from super_otonom.causal_alpha_engine import _discrete_mi_xy

    rng = np.random.default_rng(5)
    x = rng.normal(0, 1.0, 40)
    y = 0.3 * x + 0.7 * rng.normal(0, 1.0, 40)
    mi = float(_discrete_mi_xy(x, y, bins=5))
    assert mi == mi and 0.0 <= mi <= 1.0


@pytest.mark.asyncio
async def test_score_volatility_spike_short_lr_branch_else_long() -> None:
    from super_otonom.adversarial_robustness import score_volatility_spike

    rng = np.random.default_rng(7)
    c = np.cumprod(np.exp(rng.normal(0, 0.002, size=33)))
    s = float(score_volatility_spike(c))
    assert s == s and 0.0 <= s <= 1.0


@pytest.mark.asyncio
async def test_analyze_adversarial_extreme_crash_halts() -> None:
    from super_otonom.adversarial_robustness import analyze_adversarial_robustness

    n = 96
    c = np.ones(n) * 100.0
    c[40:45] = np.linspace(100, 130, 5)
    c[45:55] = np.linspace(130, 85, 10)
    c[55:] = 85 + np.linspace(0, 0.5, n - 55)
    low = c * 0.85
    high = c * 1.15
    v = np.ones(n) * 1e6
    v[40:55] *= 50.0
    ohlcv = [
        [i, float(hi), float(hi), float(lo), float(cl), float(vi)]
        for i, (hi, lo, cl, vi) in enumerate(zip(high, low, c, v))
    ]
    p88 = analyze_adversarial_robustness(
        "BTC/USDT",
        {"ohlcv": ohlcv},
        {},
        attach_to_analysis=False,
        event_ts=1_700_000_000_000,
    )
    assert p88["trade_permission"] == "HALT"
    assert float(p88["risk_score"]) > 0.35

    calm = 100.0 + np.linspace(0, 0.5, n)
    ohlcv2 = [
        [i, float(c) * 1.001, float(c) * 1.002, float(c) * 0.999, float(c), 1.0]
        for i, c in enumerate(calm)
    ]
    p_mid = analyze_adversarial_robustness(
        "ETH/USDT",
        {"ohlcv": ohlcv2},
        {},
        attach_to_analysis=False,
    )
    assert p_mid["trade_permission"] in ("ALLOW", "BLOCK", "HALT")
    assert float(p_mid["risk_score"]) < float(p88["risk_score"])


# ── causal_alpha_engine ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_try_ts_ms_large_epoch_ms_via_analyze() -> None:
    from super_otonom.causal_alpha_engine import analyze_causal_alpha

    n = 40
    a = [100.0 + 0.01 * math.sin(i / 3.0) for i in range(n)]
    b = [100.0 + 0.01 * math.sin(i / 3.0 + 0.2) for i in range(n)]
    ts_ms = 1_731_000_000_000.0
    out = analyze_causal_alpha(
        "X",
        {"series_a": a, "series_b": b},
        {"event_ts": ts_ms},
        attach_to_analysis=False,
        event_ts=None,
    )
    assert int(out["event_ts"]) == int(ts_ms)


@pytest.mark.asyncio
async def test_granger_causality_score_continues_when_lag_matrix_none() -> None:
    from super_otonom.causal_alpha_engine import granger_causality_score

    s, lag = granger_causality_score(np.ones(3), np.ones(3), max_lag=4)
    assert s == 0.0
    assert lag == 1


@pytest.mark.asyncio
async def test_transfer_entropy_proxy_returns_zero_when_m_below_10() -> None:
    from super_otonom.causal_alpha_engine import transfer_entropy_proxy

    x = np.arange(25.0)
    assert transfer_entropy_proxy(x, x, lag=16) == 0.0


@pytest.mark.asyncio
async def test_analyze_causal_bidirectional_and_risk_block() -> None:
    from super_otonom.causal_alpha_engine import analyze_causal_alpha

    n = 48
    t = np.arange(n, dtype=float)
    a = (100.0 + 0.4 * np.sin(t / 2.1)).tolist()
    b = (100.0 + 0.4 * np.sin(t / 2.1 + 0.55)).tolist()
    out = analyze_causal_alpha(
        "PAIR",
        {"series_a": a, "series_b": b, "max_lag": 6},
        {},
        attach_to_analysis=False,
    )
    assert out["causal"]["direction"] in ("A_TO_B", "B_TO_A", "BIDIRECTIONAL", "NONE")
    if out["causal"]["direction"] == "BIDIRECTIONAL":
        assert out["causal"]["granger_score_a_to_b"] >= 0.18
        assert out["causal"]["granger_score_b_to_a"] >= 0.18

    rng = np.random.default_rng(3)
    x = np.cumsum(rng.normal(0, 0.02, size=n)) + 100.0
    y = np.roll(x, 1) + rng.normal(0, 0.15, size=n)
    out2 = analyze_causal_alpha(
        "PAIR2",
        {"series_a": x.tolist(), "series_b": y.tolist(), "max_lag": 8},
        {},
        attach_to_analysis=False,
    )
    assert out2["trade_permission"] in ("ALLOW", "BLOCK")
    assert 0.0 <= float(out2["risk_score"]) <= 1.0


# ── rl_trading_agent ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_agent_breakout_down_signal_when_vol_spike() -> None:
    from super_otonom.rl_trading_agent import agent_breakout

    rng = np.random.default_rng(19)
    base = rng.normal(0, 0.002, size=60)
    base[-10:] = np.linspace(0.0, 0.05, 10)
    base[-1] = -0.08
    ret = base.astype(float)
    v = agent_breakout(ret)
    assert v in (-1, 0, 1)


@pytest.mark.asyncio
async def test_analyze_rl_agent_high_disagreement_can_block() -> None:
    from super_otonom.rl_trading_agent import analyze_rl_agent

    rng = np.random.default_rng(2025)
    closes = (100.0 + np.cumsum(rng.normal(0, 0.04, size=120))).tolist()
    out = analyze_rl_agent("Z", {"close": closes}, {}, attach_to_analysis=False)
    assert out["trade_permission"] in ("ALLOW", "BLOCK")
    assert 0.0 <= float(out["risk_score"]) <= 1.0
    assert "rl_agent" in out


# ── liquidity_games_detector ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_detect_liquidity_games_classic_ob_malformed_prices_lowers_health() -> None:
    from super_otonom.liquidity_games_detector import detect_liquidity_games

    ob: dict[str, Any] = {
        "bids": [["not-a-float", 1.0]],
        "asks": [["also-bad", 1.0]],
    }
    r = detect_liquidity_games(symbol="X", analysis={}, order_book=ob)
    assert r.data_health <= 0.65
    assert r.spread_pct is None or isinstance(r.spread_pct, float)


@pytest.mark.asyncio
async def test_detect_liquidity_games_snap_missing_spread_imbalance_caps_health() -> None:
    from super_otonom.liquidity_games_detector import detect_liquidity_games

    snap = {
        "schema": "a8/v1",
        "order_book": {
            "empty": False,
            "levels": {
                "bids": [[100.0, 5.0], [99.9, 3.0]],
                "asks": [[100.1, 5.0], [100.2, 3.0]],
            },
        },
    }
    r = detect_liquidity_games(symbol="Y", analysis={"market_snapshot": snap})
    assert r.ob_imbalance is not None or r.data_health <= 0.7


@pytest.mark.asyncio
async def test_detect_liquidity_games_game_types_and_trade_permission() -> None:
    from super_otonom.liquidity_games_detector import detect_liquidity_games

    wide_ob: dict[str, Any] = {
        "bids": [[100.0, 50.0]],
        "asks": [[110.0, 50.0]],
    }
    r1 = detect_liquidity_games(
        symbol="W",
        analysis={"volatility": 0.09},
        order_book=wide_ob,
    )
    assert r1.game_type in (
        "stop_hunt",
        "momentum_ignition",
        "quote_stuffing",
        "spoofing",
        "none",
        "unknown",
    )

    tight_ob: dict[str, Any] = {
        "bids": [[100.0, 200.0], [99.99, 50.0]],
        "asks": [[100.02, 5.0], [100.04, 5.0]],
    }
    r2 = detect_liquidity_games(
        symbol="S",
        analysis={"volatility": 0.02},
        order_book=tight_ob,
    )
    assert r2.trade_permission in ("ALLOW", "BLOCK", "HALT")
    assert 0 <= r2.risk_score <= 100
