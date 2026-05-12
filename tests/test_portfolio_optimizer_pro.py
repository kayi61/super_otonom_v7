"""Faz 29 — portfolio_optimizer_pro (Black–Litterman, ERC, 5-faktör, Sharpe)."""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest
import super_otonom.portfolio_optimizer_pro as po_mod
from super_otonom.portfolio_optimizer_pro import (
    analyze_portfolio_optimizer,
    erc_weights,
    run_portfolio_optimizer_phase,
)


def _five_asset_equal_vol_returns(seed: int = 42) -> dict:
    """Normal portföy: 5 varlık, eş vol, deterministik (ALLOW örüntüsü)."""
    np.random.seed(seed)
    n = 40
    syms = ["A", "B", "C", "D", "E"]
    return {s: (0.0004 + np.random.randn(n) * 0.003).tolist() for s in syms}


def test_po_empty_blocks_quality() -> None:
    """1. Boş veri → BLOCK, data_health 0, QUALITY."""
    a: dict = {}
    r = analyze_portfolio_optimizer("X/USDT", {}, a, attach_to_analysis=True)

    assert r["trade_permission"] == "BLOCK"
    assert r["data_health"] == 0.0
    assert r["score_type"] == "QUALITY"
    assert r.get("empty_reason") == "no_portfolio_data"


@pytest.mark.parametrize(
    "portfolio_data",
    [
        pytest.param(
            {"asset_returns": {"A": (0.0001 * np.arange(40)).tolist()}}, id="single_asset"
        ),
        pytest.param({"asset_returns": {"A": [0.001] * 30, "B": [0.001] * 30}}, id="short_series"),
    ],
)
def test_po_single_or_insufficient_blocks(portfolio_data: dict) -> None:
    """2. Tek varlık / yetersiz gözlem → BLOCK, empty_reason (insufficient)."""
    r = analyze_portfolio_optimizer("S/USDT", portfolio_data, {})
    assert r["trade_permission"] == "BLOCK"
    er = r.get("empty_reason", "")
    assert "insufficient" in er


def test_po_normal_portfolio_allow_optimal_sum() -> None:
    """3. Normal portföy → ALLOW, optimal_weights toplamı ≈ 1.0."""
    np.random.seed(42)
    ar = _five_asset_equal_vol_returns(42)
    r = analyze_portfolio_optimizer(
        "OK/USDT",
        {"asset_returns": ar, "sharpe_erc_blend": 0.45},
        {},
        attach_to_analysis=False,
    )
    assert r["trade_permission"] == "ALLOW"
    ow = r["portfolio_optimizer"]["optimal_weights"]
    s = sum(ow.values())
    assert abs(s - 1.0) < 1e-6


def test_po_negative_sharpe_blocks() -> None:
    """4. Negatif Sharpe → BLOCK."""
    np.random.seed(43)
    n = 40
    syms = ["A", "B", "C", "D", "E"]
    ar = {s: (-0.001 + np.random.randn(n) * 0.003).tolist() for s in syms}
    r = analyze_portfolio_optimizer(
        "NEG/USDT",
        {"asset_returns": ar, "sharpe_erc_blend": 0.45},
        {},
        attach_to_analysis=False,
    )
    assert r["portfolio_optimizer"]["portfolio_sharpe_ratio"] < 0
    assert r["trade_permission"] == "BLOCK"


def test_po_concentration_over_40_blocks() -> None:
    """5. Konsantrasyon > %40 (tek varlık baskın) → BLOCK."""
    np.random.seed(50)
    n = 40
    ar = {
        "A": (0.003 + np.random.randn(n) * 0.001).tolist(),
        "B": (-0.0005 + np.random.randn(n) * 0.004).tolist(),
    }
    r = analyze_portfolio_optimizer(
        "CONC/USDT",
        {"asset_returns": ar, "sharpe_erc_blend": 0.55},
        {},
        attach_to_analysis=False,
    )
    assert r["portfolio_optimizer"]["max_single_asset_weight"] > 0.40
    assert r["trade_permission"] == "BLOCK"


def test_po_black_litterman_posterior_mu_changes() -> None:
    """6. Black–Litterman view → posterior_expected_returns (bl μ) değişir."""
    np.random.seed(42)
    ar = _five_asset_equal_vol_returns(42)
    base = analyze_portfolio_optimizer(
        "BL/USDT",
        {"asset_returns": ar, "sharpe_erc_blend": 0.45},
        {},
        attach_to_analysis=False,
    )
    bl_views = {
        "P": [[1, 0, 0, 0, 0]],
        "Q": [0.0005],
        "Omega": [[(0.0001) ** 2]],
    }
    with_views = analyze_portfolio_optimizer(
        "BL/USDT",
        {"asset_returns": ar, "sharpe_erc_blend": 0.45, "bl_views": bl_views},
        {},
        attach_to_analysis=False,
    )
    b_mu = base["portfolio_optimizer"]["posterior_expected_returns"]
    v_mu = with_views["portfolio_optimizer"]["posterior_expected_returns"]
    diff = np.sqrt(sum((b_mu[s] - v_mu[s]) ** 2 for s in b_mu))
    assert diff > 1e-6


def test_po_erc_weights_equal_risk_contribution() -> None:
    """7. ERC ağırlıkları — diyagonal Σ'da risk katkıları eşit (≈1/n)."""
    n_assets = 5
    sigma = np.eye(n_assets, dtype=float) * 2e-4
    w = erc_weights(sigma)
    var_p = float(w @ sigma @ w)
    rc = w * (sigma @ w) / var_p
    target = 1.0 / float(n_assets)
    assert np.allclose(w, np.full(n_assets, target), atol=1e-5)
    assert np.allclose(rc, np.full(n_assets, target), atol=1e-5)


def test_po_alpha_score_zero_one() -> None:
    """8. Alpha skoru (5-faktör birleşimi) 0–1 aralığında."""
    np.random.seed(42)
    ar = _five_asset_equal_vol_returns(42)
    r = analyze_portfolio_optimizer(
        "AL/USDT",
        {"asset_returns": ar, "sharpe_erc_blend": 0.45},
        {},
        attach_to_analysis=False,
    )
    a = r["alpha_score"]
    assert 0.0 <= a <= 1.0

    empty = analyze_portfolio_optimizer("E/USDT", {}, {}, attach_to_analysis=False)
    assert empty["alpha_score"] == 0.0


def test_po_phase29_faz29_attached() -> None:
    """9. analysis['phase29'] ve analysis['faz29'] dolu ve aynı nesne."""
    a: dict = {}
    np.random.seed(42)
    ar = _five_asset_equal_vol_returns(42)
    analyze_portfolio_optimizer("PH/USDT", {"asset_returns": ar}, a)

    assert "phase29" in a and "faz29" in a
    assert a["phase29"] is a["faz29"]
    assert a["phase29"]["phase"] == "29"


def test_run_portfolio_optimizer_phase_writes_analysis() -> None:
    """10. run_portfolio_optimizer_phase çalışır ve phase29 yazar."""
    a: dict = {}
    np.random.seed(42)
    ar = _five_asset_equal_vol_returns(42)
    r = run_portfolio_optimizer_phase("RUN/USDT", {"asset_returns": ar}, a)

    assert r["source"] == "portfolio_optimizer_pro"
    assert a.get("phase29") is r


def test_po_no_scipy_cvxpy_imports() -> None:
    """11. scipy / cvxpy import yok (saf NumPy)."""
    tree = ast.parse(Path(po_mod.__file__).read_text(encoding="utf-8"))
    banned_roots = ("scipy", "cvxpy")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                assert root not in banned_roots
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            assert root not in banned_roots
