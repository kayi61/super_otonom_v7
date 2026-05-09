"""Faz 28 — hft_signal_engine (tick/OHLCV, VWAP, fat-tail, mikro momentum)."""
from __future__ import annotations

import ast
from pathlib import Path

import numpy as np

import super_otonom.hft_signal_engine as hft_mod
from super_otonom.hft_signal_engine import analyze_hft_signal, run_hft_signal_phase


def test_hft_empty_blocks_quality() -> None:
    """1. Boş veri → BLOCK, data_health 0, QUALITY."""
    a: dict = {}
    r = analyze_hft_signal("X/USDT", {}, a, attach_to_analysis=True)

    assert r["trade_permission"] == "BLOCK"
    assert r["data_health"] == 0.0
    assert r["score_type"] == "QUALITY"
    assert r.get("empty_reason") == "no_hft_data"


def test_hft_ohlcv_fallback_fills_phase28() -> None:
    """2. OHLCV yedek → phase28 doluyor."""
    np.random.seed(42)
    n = 80
    closes = (100 * np.exp(np.cumsum(np.random.randn(n) * 0.002))).tolist()
    a: dict = {}
    r = analyze_hft_signal("OHLC/USDT", {"close": closes}, a, attach_to_analysis=True)

    assert r["hft_signal"]["data_source"] == "ohlcv"
    assert r["phase"] == "28"
    assert "phase28" in a and a["phase28"] is r


def test_hft_fat_tail_blocks() -> None:
    """3. Fat tail → fat_tail_detected True, BLOCK."""
    np.random.seed(42)
    base = np.random.randn(90) * 0.0008
    base = np.concatenate([base, np.array([0.06, -0.055, 0.052, -0.048, 0.05])])
    prices = 100 * np.exp(np.cumsum(np.concatenate([[0], base])))
    ticks = [{"price": float(prices[i]), "ts": float(i * 80), "size": 1.0} for i in range(len(prices))]
    r = analyze_hft_signal("FT/USDT", {"ticks": ticks}, {}, attach_to_analysis=False)

    assert r["hft_signal"]["queue_tail_risk"]["fat_tail_detected"] is True
    assert r["trade_permission"] == "BLOCK"


def test_hft_high_vwap_deviation_raises_risk() -> None:
    """4. Yüksek VWAP sapması → vwap_deviation_score yüksek, risk_score artar."""
    np.random.seed(42)
    n = 200
    walk = np.cumsum(np.random.randn(n) * 0.02)
    p_smooth = 100 + walk
    ticks_low = [{"price": float(p_smooth[i]), "ts": float(i * 100), "size": 1.0} for i in range(n)]
    r_low = analyze_hft_signal("V1/USDT", {"ticks": ticks_low}, {}, attach_to_analysis=False)

    p_spike = p_smooth.copy()
    p_spike[-1] = float(p_spike[-2]) * 1.18
    ticks_high = [{"price": float(p_spike[i]), "ts": float(i * 100), "size": 1.0} for i in range(n)]
    r_high = analyze_hft_signal("V2/USDT", {"ticks": ticks_high}, {}, attach_to_analysis=False)

    assert r_high["hft_signal"]["vwap_deviation_score"] > r_low["hft_signal"]["vwap_deviation_score"]
    assert r_high["risk_score"] > r_low["risk_score"]


def test_hft_strong_micro_momentum_high_alpha() -> None:
    """5. Güçlü mikro momentum → alpha_score yüksek (kıyaslı)."""
    np.random.seed(42)
    n = 120
    flat = 100 + np.random.randn(n) * 0.01
    ticks_flat = [{"price": float(flat[i]), "ts": float(i * 50), "size": 1.0} for i in range(n)]
    r_flat = analyze_hft_signal("M1/USDT", {"ticks": ticks_flat, "micro_N": 32}, {}, attach_to_analysis=False)

    trend = 100 + np.arange(n, dtype=float) * 0.08
    ticks_trend = [{"price": float(trend[i]), "ts": float(i * 50), "size": 1.0} for i in range(n)]
    r_trend = analyze_hft_signal("M2/USDT", {"ticks": ticks_trend, "micro_N": 32}, {}, attach_to_analysis=False)

    assert r_trend["alpha_score"] > r_flat["alpha_score"]
    assert r_trend["hft_signal"]["micro_momentum_heat"] > 0.65


def test_hft_force_halt() -> None:
    """6. force_halt True → HALT."""
    np.random.seed(42)
    n = 80
    p = (100 * np.exp(np.cumsum(np.random.randn(n) * 0.001))).tolist()
    r = analyze_hft_signal(
        "H/USDT",
        {"close": p, "force_halt": True},
        {},
        attach_to_analysis=False,
    )
    assert r["trade_permission"] == "HALT"


def test_hft_signal_dict_keys() -> None:
    """7. hft_signal: VWAP, fat-tail, tail score, mikro ısı anahtarları."""
    np.random.seed(42)
    n = 100
    p = (100 * np.exp(np.cumsum(np.random.randn(n) * 0.002))).tolist()
    r = analyze_hft_signal("K/USDT", {"close": p}, {}, attach_to_analysis=False)
    h = r["hft_signal"]
    q = h["queue_tail_risk"]

    assert "vwap_deviation_score" in h
    assert "fat_tail_detected" in q
    assert "tail_exceedance_score" in q
    assert "micro_momentum_heat" in h


def test_hft_phase28_faz28_attached() -> None:
    """8. analysis['phase28'] ve analysis['faz28'] dolu ve aynı nesne."""
    a: dict = {}
    np.random.seed(42)
    closes = (100 * np.exp(np.cumsum(np.random.randn(80) * 0.002))).tolist()
    analyze_hft_signal("PH/USDT", {"close": closes}, a)

    assert "phase28" in a and "faz28" in a
    assert a["phase28"] is a["faz28"]
    assert a["phase28"]["phase"] == "28"


def test_run_hft_signal_phase_writes_analysis() -> None:
    """9. run_hft_signal_phase çalışır ve phase28 yazar."""
    a: dict = {}
    np.random.seed(42)
    closes = (100 * np.exp(np.cumsum(np.random.randn(80) * 0.002))).tolist()
    r = run_hft_signal_phase("RUN/USDT", {"close": closes}, a)

    assert r["source"] == "hft_signal_engine"
    assert a.get("phase28") is r


def test_hft_no_math_import() -> None:
    """10. math import yok (saf NumPy + stdlib)."""
    tree = ast.parse(Path(hft_mod.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] != "math"
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            assert root != "math"
