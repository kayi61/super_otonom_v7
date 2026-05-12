"""Faz 33 — adversarial_robustness (flash, pump-dump, vol, fake breakout)."""

from __future__ import annotations

import numpy as np
from super_otonom.adversarial_robustness import (
    analyze_adversarial_robustness,
    run_adversarial_phase,
)


def _ohlcv_rows(
    o: np.ndarray, h: np.ndarray, low: np.ndarray, c: np.ndarray, v: np.ndarray
) -> list:
    return [
        [i, float(o[i]), float(h[i]), float(low[i]), float(c[i]), float(v[i])]
        for i in range(len(c))
    ]


def test_adversarial_empty_blocks_quality() -> None:
    """1. Boş veri → BLOCK, data_health 0, QUALITY."""
    a: dict = {}
    r = analyze_adversarial_robustness("BTC/USDT", {}, a, attach_to_analysis=True)

    assert r["trade_permission"] == "BLOCK"
    assert r["data_health"] == 0.0
    assert r["score_type"] == "QUALITY"
    assert r.get("empty_reason") == "no_market_data"


def test_adversarial_insufficient_bars() -> None:
    """2. Yetersiz bar (<48) → BLOCK, empty_reason."""
    np.random.seed(42)
    c = (100 * np.exp(np.cumsum(np.random.randn(40) * 0.004))).astype(float)
    r = analyze_adversarial_robustness("S/USDT", {"close": c.tolist()}, {})

    assert r["trade_permission"] == "BLOCK"
    assert r.get("empty_reason") == "insufficient_bars"


def test_adversarial_flash_crash_halts() -> None:
    """3. Flash crash → flash_crash_score >= 0.42, HALT."""
    np.random.seed(42)
    c = (100 * np.exp(np.cumsum(np.random.randn(80) * 0.003))).astype(float)
    o, h, low = c.copy(), c.copy(), c.copy()
    c[-1] = float(c[-2]) * float(np.exp(-0.095))
    low[-1] = min(float(low[-1]), float(c[-2]) * 0.88)
    r = analyze_adversarial_robustness(
        "FC/USDT",
        {"ohlcv": _ohlcv_rows(o, h, low, c, np.ones(80) * 1e6)},
        {},
        attach_to_analysis=False,
    )

    assert r["adversarial"]["flash_crash_score"] >= 0.42
    assert r["trade_permission"] == "HALT"


def test_adversarial_pump_dump_halts() -> None:
    """4. Pump & dump → pump_dump_score >= 0.42, HALT."""
    lr = np.zeros(79)
    lr[20:28] = 0.0132
    lr[28:36] = -0.0083
    lr[36:] = 0.0
    c = 100 * np.exp(np.cumsum(np.concatenate([[0], lr])))
    o = np.roll(c, 1)
    o[0] = float(c[0])
    h = np.maximum.reduce([c, o]) * 1.0005
    low = np.minimum.reduce([c, o]) * 0.9995
    v = np.ones(80) * 1e6
    v[20:36] *= 8.0
    r = analyze_adversarial_robustness(
        "PD/USDT",
        {"ohlcv": _ohlcv_rows(o, h, low, c, v)},
        {},
        attach_to_analysis=False,
    )

    assert r["adversarial"]["pump_dump_score"] >= 0.42
    assert r["adversarial"]["flash_crash_score"] < 0.42
    assert r["trade_permission"] == "HALT"


def test_adversarial_volatility_spike_blocks() -> None:
    """5. Volatility spike → volatility_spike_score >= 0.72, BLOCK (HALT tetiklenmez)."""
    np.random.seed(123)
    lr = np.zeros(79)
    lr[:67] = np.random.randn(67) * 0.001
    lr[67:] = np.random.uniform(-0.045, 0.045, 12)
    c = 100 * np.exp(np.cumsum(np.concatenate([[0], lr])))
    r = analyze_adversarial_robustness(
        "VOL/USDT",
        {"ohlcv": _ohlcv_rows(c, c, c, c, np.ones(80) * 1e6)},
        {},
        attach_to_analysis=False,
    )

    assert r["adversarial"]["volatility_spike_score"] >= 0.72
    assert r["adversarial"]["flash_crash_score"] < 0.42
    assert r["trade_permission"] == "BLOCK"


def test_adversarial_fake_breakout_blocks() -> None:
    """6. Fake breakout → fake_breakout_score >= 0.38, BLOCK."""
    np.random.seed(42)
    lr = np.random.randn(79) * 0.002
    c = 100 * np.exp(np.cumsum(np.concatenate([[0], lr])))
    o = np.roll(c, 1)
    o[0] = float(c[0])
    h = np.maximum(o, c) * 1.0003
    low = np.minimum(o, c) * 0.9997
    resist = float(np.max(c[-28:-4]))
    h[-1] = max(float(h[-1]), resist * 1.008)
    c[-1] = resist * 0.998
    low[-1] = min(float(low[-1]), float(c[-1]) * 0.999)
    r = analyze_adversarial_robustness(
        "FK/USDT",
        {"ohlcv": _ohlcv_rows(o, h, low, c, np.ones(80) * 1e6)},
        {},
        attach_to_analysis=False,
    )

    assert r["adversarial"]["fake_breakout_score"] >= 0.38
    assert r["trade_permission"] == "BLOCK"


def test_adversarial_normal_market_allow_low_scores() -> None:
    """7. Normal piyasa → ALLOW; yapısal skorlar düşük."""
    np.random.seed(42)
    lr = np.random.randn(79) * 0.002
    c = 100 * np.exp(np.cumsum(np.concatenate([[0], lr])))
    r = analyze_adversarial_robustness(
        "OK/USDT",
        {"ohlcv": _ohlcv_rows(c, c, c, c, np.ones(80) * 1e6)},
        {},
        attach_to_analysis=False,
    )

    adv = r["adversarial"]
    assert r["trade_permission"] == "ALLOW"
    assert adv["flash_crash_score"] < 0.15
    assert adv["pump_dump_score"] < 0.15
    assert adv["slow_bleed_score"] < 0.15
    assert adv["volatility_spike_score"] < 0.15
    assert adv["fake_breakout_score"] < 0.15


def test_adversarial_dict_scores_present() -> None:
    """8. adversarial dict ana skor alanları."""
    np.random.seed(42)
    c = (100 * np.exp(np.cumsum(np.random.randn(80) * 0.002))).astype(float)
    r = analyze_adversarial_robustness("K/USDT", {"close": c.tolist()}, {})

    adv = r["adversarial"]
    for key in (
        "flash_crash_score",
        "pump_dump_score",
        "slow_bleed_score",
        "volatility_spike_score",
        "fake_breakout_score",
    ):
        assert key in adv
        assert isinstance(adv[key], float)


def test_adversarial_phase33_faz33_attached() -> None:
    """9. analysis['phase33'] ve analysis['faz33'] aynı payload."""
    a: dict = {}
    np.random.seed(42)
    c = (100 * np.exp(np.cumsum(np.random.randn(80) * 0.002))).astype(float)
    analyze_adversarial_robustness("PH/USDT", {"close": c.tolist()}, a)

    assert "phase33" in a and "faz33" in a
    assert a["phase33"] is a["faz33"]
    assert a["phase33"]["phase"] == "33"


def test_run_adversarial_phase_writes_analysis() -> None:
    """10. run_adversarial_phase çalışır ve phase33 yazar."""
    a: dict = {}
    np.random.seed(42)
    c = (100 * np.exp(np.cumsum(np.random.randn(80) * 0.002))).astype(float)
    r = run_adversarial_phase("RUN/USDT", {"close": c.tolist()}, a)

    assert r["source"] == "adversarial_robustness"
    assert a.get("phase33") is r
