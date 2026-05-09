"""Faz 32 — transformer_intelligence (NumPy dikkat, torch yok)."""
from __future__ import annotations

import ast
from pathlib import Path

import numpy as np

from super_otonom.transformer_intelligence import (
    analyze_transformer_intelligence,
    run_transformer_phase,
)


def test_transformer_empty_blocks_quality() -> None:
    """1. Boş veri → BLOCK, data_health 0, QUALITY."""
    a: dict = {}
    r = analyze_transformer_intelligence("BTC/USDT", {}, a, attach_to_analysis=True)

    assert r["trade_permission"] == "BLOCK"
    assert r["data_health"] == 0.0
    assert r["score_type"] == "QUALITY"
    assert r.get("empty_reason") == "no_price_data"


def test_transformer_short_series_blocks() -> None:
    """2. Çok kısa seri (<36 bar) → BLOCK, empty_reason."""
    np.random.seed(42)
    short = (100 * np.exp(np.cumsum(np.random.randn(20) * 0.01))).tolist()
    r = analyze_transformer_intelligence("S/USDT", {"close": short}, {})

    assert r["trade_permission"] == "BLOCK"
    assert r.get("empty_reason") == "insufficient_bars"


def test_transformer_strong_up_trend() -> None:
    """3. Güçlü UP trend → direction UP, yüksek alpha_score."""
    np.random.seed(42)
    ret = 0.02 + np.random.randn(80) * 0.0015
    px = 100 * np.exp(np.cumsum(ret))
    r = analyze_transformer_intelligence("UP/USDT", {"close": px.tolist()}, {}, attach_to_analysis=False)

    assert r["transformer"]["direction"] == "UP"
    assert r["alpha_score"] >= 0.55


def test_transformer_strong_down_trend_high_risk() -> None:
    """4. Güçlü DOWN trend → direction DOWN, yüksek risk_score."""
    np.random.seed(42)
    ret = -0.018 + np.random.randn(80) * 0.0015
    px = 100 * np.exp(np.cumsum(ret))
    r = analyze_transformer_intelligence("DN/USDT", {"close": px.tolist()}, {}, attach_to_analysis=False)

    assert r["transformer"]["direction"] == "DOWN"
    assert r["risk_score"] >= 0.75


def test_transformer_flat_attention_low_confidence() -> None:
    """5. Düz seri (özdeş patch gömüleri) → attention_uniformity yüksek, confidence düşük."""
    np.random.seed(42)
    ret = np.ones(80, dtype=float) * 0.008
    px = 100 * np.exp(np.cumsum(ret))
    r = analyze_transformer_intelligence("FL/USDT", {"close": px.tolist()}, {}, attach_to_analysis=False)

    np.random.seed(42)
    ret_u = 0.022 + np.random.randn(80) * 0.001
    px_u = 100 * np.exp(np.cumsum(ret_u))
    r_up = analyze_transformer_intelligence("CMP/USDT", {"close": px_u.tolist()}, {}, attach_to_analysis=False)

    assert r["transformer"]["attention_uniformity"] >= 0.95
    assert r["confidence"] <= 0.22
    assert r["confidence"] < r_up["confidence"]


def test_transformer_dict_core_fields() -> None:
    """6. transformer dict: direction, direction_score, attention_uniformity."""
    np.random.seed(42)
    px = (100 * np.exp(np.cumsum(np.random.randn(80) * 0.01))).tolist()
    r = analyze_transformer_intelligence("K/USDT", {"close": px}, {})

    t = r["transformer"]
    assert "direction" in t and t["direction"] in ("UP", "DOWN", "NEUTRAL")
    assert "direction_score" in t and isinstance(t["direction_score"], float)
    assert "attention_uniformity" in t and isinstance(t["attention_uniformity"], float)


def test_transformer_phase32_faz32_attached() -> None:
    """7. analysis['phase32'] ve analysis['faz32'] aynı payload."""
    a: dict = {}
    np.random.seed(42)
    px = (100 * np.exp(np.cumsum(np.random.randn(80) * 0.01))).tolist()
    analyze_transformer_intelligence("PH/USDT", {"close": px}, a)

    assert "phase32" in a and "faz32" in a
    assert a["phase32"] is a["faz32"]
    assert a["phase32"]["phase"] == "32"


def test_run_transformer_phase_writes_analysis() -> None:
    """8. run_transformer_phase çalışır ve phase32 yazar."""
    a: dict = {}
    np.random.seed(42)
    px = (100 * np.exp(np.cumsum(np.random.randn(80) * 0.01))).tolist()
    r = run_transformer_phase("RUN/USDT", {"close": px}, a)

    assert r["source"] == "transformer_intelligence"
    assert a.get("phase32") is r


def test_transformer_module_has_no_torch_import() -> None:
    """Kaynak dosyada torch import edilmesin."""
    import super_otonom.transformer_intelligence as ti

    path = Path(ti.__file__).resolve()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] != "torch"
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] != "torch"
