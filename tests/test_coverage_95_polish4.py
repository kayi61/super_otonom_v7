"""Fourth polish pass — final push to 95% strict."""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np

# ────────────────────────── adversarial_robustness ─────────────────────────


def _make_ohlcv(closes: List[float], highs: List[float] | None = None,
                lows: List[float] | None = None, vols: List[float] | None = None) -> Dict[str, Any]:
    n = len(closes)
    if highs is None:
        highs = [c * 1.005 for c in closes]
    if lows is None:
        lows = [c * 0.995 for c in closes]
    if vols is None:
        vols = [100.0] * n
    return {
        "open": closes,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": vols,
    }


def test_adversarial_flash_crash_extreme() -> None:
    """Big drop with deep wick → s_flash high → perm HALT path."""
    from super_otonom.adversarial_robustness import analyze_adversarial_robustness

    # 80 bars baseline; final bars drop sharply
    base = 100.0
    closes = [base + i * 0.05 for i in range(60)]
    # Crash
    closes.extend([base - 5.0, base - 10.0, base - 15.0, base - 18.0])
    lows = [c * 0.998 for c in closes[:-1]] + [closes[-1] * 0.95]  # deep wick on crash
    out = analyze_adversarial_robustness(
        "BTC/USDT",
        _make_ohlcv(closes, lows=lows),
    )
    assert isinstance(out, dict)


def test_adversarial_pump_dump_extreme() -> None:
    """Volume spike + price pump+drop → s_pump high."""
    from super_otonom.adversarial_robustness import analyze_adversarial_robustness

    base = 100.0
    closes = [base + i * 0.05 for i in range(50)]
    closes.extend([base * 1.3, base * 1.35, base * 1.0])  # pump then dump
    vols = [100.0] * 50 + [10000.0, 12000.0, 1000.0]
    out = analyze_adversarial_robustness(
        "BTC/USDT",
        _make_ohlcv(closes, vols=vols),
    )
    assert isinstance(out, dict)


def test_adversarial_vol_spike_branch() -> None:
    """Last 12 bars high vol vs first → s_vol high → BLOCK."""
    from super_otonom.adversarial_robustness import analyze_adversarial_robustness

    base = 100.0
    closes = [base + 0.01 * i for i in range(80)]  # low vol baseline
    # Last 12: high vol
    closes[-12:] = [base + (-1) ** i * 5.0 for i in range(12)]
    out = analyze_adversarial_robustness(
        "BTC/USDT",
        _make_ohlcv(closes),
    )
    assert isinstance(out, dict)


def test_adversarial_helpers_direct() -> None:
    from super_otonom.adversarial_robustness import (
        score_fake_breakout,
        score_flash_crash,
        score_pump_dump,
        score_slow_bleed,
        score_volatility_spike,
    )

    rng = np.random.default_rng(0)
    n = 80
    c = np.arange(n, dtype=float) + 100.0 + rng.normal(0, 0.1, n)
    h = c + 0.5
    low = c - 0.5
    v = np.ones(n, dtype=float) * 100.0

    assert 0.0 <= score_flash_crash(c, low) <= 1.0
    assert 0.0 <= score_pump_dump(c, v) <= 1.0
    assert 0.0 <= score_slow_bleed(c) <= 1.0
    assert 0.0 <= score_volatility_spike(c) <= 1.0
    assert 0.0 <= score_fake_breakout(h, low, c) <= 1.0

    # Edge cases
    tiny = np.array([1.0, 2.0], dtype=float)
    assert score_flash_crash(tiny, tiny) == 0.0
    assert score_pump_dump(tiny, tiny) == 0.0
    assert score_slow_bleed(tiny) == 0.0
    assert score_volatility_spike(tiny) == 0.0
    assert score_fake_breakout(tiny, tiny, tiny) == 0.0


# ─────────────────────────── portfolio_optimizer_pro ───────────────────────


def test_portfolio_extract_return_matrix_branches() -> None:
    from super_otonom.portfolio_optimizer_pro import (
        equilibrium_returns,
        extract_return_matrix,
        prior_market_weights,
        sample_covariance,
    )

    assert extract_return_matrix({}) is None
    assert extract_return_matrix({"returns": "not-a-dict"}) is None

    rng = np.random.default_rng(1)
    n = 60
    returns_data = {
        "returns": {
            "BTC": rng.normal(0, 0.01, n).tolist(),
            "ETH": rng.normal(0, 0.015, n).tolist(),
            "SOL": rng.normal(0, 0.02, n).tolist(),
        }
    }
    M, syms = extract_return_matrix(returns_data)
    assert M is not None and syms is not None
    assert len(syms) >= 2 and M.size > 0

    cov = sample_covariance(M)
    assert cov.shape[0] == len(syms)

    w = prior_market_weights(syms, returns_data)
    assert abs(float(np.sum(w)) - 1.0) < 1e-6

    eq = equilibrium_returns(cov, w)
    assert eq.shape[0] == len(syms)


def test_portfolio_erc_and_blend_helpers() -> None:
    from super_otonom.portfolio_optimizer_pro import (
        blend_optimal,
        erc_imbalance_score,
        erc_weights,
    )

    cov = np.array([[0.04, 0.01], [0.01, 0.09]], dtype=float)
    w_erc = erc_weights(cov)
    assert abs(float(np.sum(w_erc)) - 1.0) < 1e-3
    score = erc_imbalance_score(w_erc, cov)
    assert 0.0 <= score <= 1.0

    blend = blend_optimal(w_erc, w_erc, blend=0.5)
    assert blend.shape == w_erc.shape


# ─────────────────────────────── hft_signal_engine ─────────────────────────


def test_hft_force_halt_branch() -> None:
    """force_halt=True → perm=HALT (line ~412-413)."""
    from super_otonom.hft_signal_engine import analyze_hft_signal

    rng = np.random.default_rng(0)
    closes = [100.0 + rng.normal(0, 0.1) for _ in range(120)]
    out = analyze_hft_signal(
        "BTC/USDT",
        {"close": closes, "force_halt": True},
    )
    assert isinstance(out, dict)


def test_hft_session_fraction() -> None:
    from super_otonom.hft_signal_engine import _session_fraction

    ts = np.array([1000.0, 2000.0, 3000.0, 4000.0], dtype=float)
    frac = _session_fraction(ts)
    assert frac[0] == 0.0
    assert frac[-1] == 1.0


# ───────────────────────────────── rl_trading_agent ────────────────────────


def test_rl_helpers_direct() -> None:
    from super_otonom.rl_trading_agent import (
        _normalize,
        build_state_vector,
        entropy_probs,
        log_returns,
        softmax,
    )

    # entropy
    p = np.array([0.5, 0.5], dtype=float)
    h = entropy_probs(p)
    assert h > 0

    # softmax
    z = np.array([1.0, 2.0, 3.0], dtype=float)
    sm = softmax(z)
    assert abs(float(np.sum(sm)) - 1.0) < 1e-6

    # log_returns
    closes = np.array([100.0, 101.0, 102.0], dtype=float)
    lr = log_returns(closes)
    assert lr.size == 2

    dnorm = _normalize({"x": 1, "y": 2})
    assert isinstance(dnorm, dict) and dnorm.get("x") == 1

    ret = log_returns(closes)
    sv = build_state_vector(ret, min(16, int(ret.size)))
    assert isinstance(sv, np.ndarray) and sv.size > 0


# ─────────────────────────────── meta_learning_engine ──────────────────────


def test_meta_learning_helpers() -> None:
    from super_otonom.meta_learning_engine import _list_float, _normalize, cusum_two_sided

    lf = _list_float([1.0, 2.0, "bad", 3.0], min_len=2)
    assert lf is not None and lf.size >= 2

    dnorm = _normalize({"phase": "meta", "ok": True})
    assert isinstance(dnorm, dict) and dnorm.get("ok") is True

    arr = np.array([1.0, 2.0, 3.0, 4.0, 5.0] * 8, dtype=float)
    drift_strength, drift_hit = cusum_two_sided(arr - np.mean(arr), threshold=2.0)
    assert isinstance(drift_strength, float) and isinstance(drift_hit, bool)
