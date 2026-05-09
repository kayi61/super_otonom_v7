"""Faz 35 — meta_learning_engine (CUSUM, MAML proxy, rollback, sürüm)."""
from __future__ import annotations

import ast
import time
from pathlib import Path

import numpy as np

from super_otonom.meta_learning_engine import analyze_meta_learning, run_meta_learning_phase


def test_meta_empty_blocks_quality() -> None:
    """1. Boş veri → BLOCK, data_health 0, QUALITY."""
    a: dict = {}
    r = analyze_meta_learning("BTC/USDT", {}, a, attach_to_analysis=True)

    assert r["trade_permission"] == "BLOCK"
    assert r["data_health"] == 0.0
    assert r["score_type"] == "QUALITY"
    assert r.get("empty_reason") == "no_meta_data"


def test_meta_insufficient_series() -> None:
    """2. Yetersiz seri (<24 nokta) → BLOCK, empty_reason."""
    np.random.seed(42)
    short = np.abs(np.random.randn(18) * 0.05).tolist()
    r = analyze_meta_learning("S/USDT", {"loss_series": short}, {})

    assert r["trade_permission"] == "BLOCK"
    assert r.get("empty_reason") == "insufficient_series"


def test_meta_cusum_drift_blocks() -> None:
    """3. CUSUM drift → cusum_drift_detected True, BLOCK."""
    loss = np.concatenate([np.ones(40, dtype=float) * 0.2, np.ones(40, dtype=float) * 0.78])
    r = analyze_meta_learning(
        "DR/USDT",
        {"loss_series": loss.tolist(), "deployed_at_ms": time.time() * 1000},
        {},
        attach_to_analysis=False,
    )

    assert r["meta_learning"]["cusum_drift_detected"] is True
    assert r["trade_permission"] == "BLOCK"


def test_meta_rollback_blocks() -> None:
    """4. Rollback tetiklenir → rollback_triggered True, BLOCK."""
    loss = np.concatenate([np.ones(56, dtype=float) * 0.21, np.ones(24, dtype=float) * 0.94])
    r = analyze_meta_learning(
        "RB/USDT",
        {
            "loss_series": loss.tolist(),
            "deployed_at_ms": time.time() * 1000,
            "previous_model_version": "v7-stable",
        },
        {},
        attach_to_analysis=False,
    )

    assert r["meta_learning"]["rollback_triggered"] is True
    assert r["trade_permission"] == "BLOCK"
    assert r["meta_learning"]["effective_model_version"] == "v7-stable"


def test_meta_stale_version_low_data_health() -> None:
    """5. Eski sürüm → version_stale_score yüksek, data_health düşük."""
    np.random.seed(42)
    loss = np.abs(np.random.randn(80) * 0.05 + 0.2).tolist()
    fresh_ms = time.time() * 1000
    stale_ms = fresh_ms - 35 * 24 * 3600 * 1000

    r_fresh = analyze_meta_learning(
        "ST/USDT",
        {"loss_series": loss, "model_version": "v3", "deployed_at_ms": fresh_ms},
        {},
        attach_to_analysis=False,
    )
    r_stale = analyze_meta_learning(
        "ST/USDT",
        {"loss_series": loss, "model_version": "v3", "deployed_at_ms": stale_ms},
        {},
        attach_to_analysis=False,
    )

    assert r_stale["meta_learning"]["version_stale_score"] >= 0.85
    assert r_stale["data_health"] < r_fresh["data_health"]


def test_meta_maml_gain_in_unit_interval() -> None:
    """6. MAML adaptasyon kazancı [0,1]."""
    np.random.seed(42)
    loss = np.abs(np.random.randn(80) * 0.05 + 0.2).tolist()
    r = analyze_meta_learning("M/USDT", {"loss_series": loss, "deployed_at_ms": time.time() * 1000}, {})

    g = r["meta_learning"]["maml_adaptation_gain"]
    assert isinstance(g, float)
    assert 0.0 <= g <= 1.0


def test_meta_online_degradation_raises_risk() -> None:
    """7. Online degradasyon (yüksek degradation skoru) → risk artar (API float)."""
    np.random.seed(42)
    stable = np.abs(np.random.randn(80) * 0.05 + 0.2)
    degraded = np.concatenate([np.ones(56, dtype=float) * 0.21, np.ones(24, dtype=float) * 0.94])

    r_s = analyze_meta_learning(
        "OK/USDT",
        {"loss_series": stable.tolist(), "deployed_at_ms": time.time() * 1000},
        {},
        attach_to_analysis=False,
    )
    r_d = analyze_meta_learning(
        "BAD/USDT",
        {"loss_series": degraded.tolist(), "deployed_at_ms": time.time() * 1000},
        {},
        attach_to_analysis=False,
    )

    assert r_d["meta_learning"]["online_degradation"] >= 0.62
    assert r_d["risk_score"] > r_s["risk_score"]


def test_meta_normal_series_allow_confident() -> None:
    """8. Normal seri → ALLOW, güven göreceli olarak yüksek."""
    np.random.seed(42)
    loss = np.abs(np.random.randn(80) * 0.05 + 0.2).tolist()
    r = analyze_meta_learning(
        "N/USDT",
        {"loss_series": loss, "deployed_at_ms": time.time() * 1000},
        {},
        attach_to_analysis=False,
    )

    assert r["trade_permission"] == "ALLOW"
    assert r["confidence"] >= 0.55


def test_meta_phase35_faz35_attached() -> None:
    """9. analysis['phase35'] ve analysis['faz35'] aynı payload."""
    a: dict = {}
    np.random.seed(42)
    loss = np.abs(np.random.randn(80) * 0.05 + 0.2).tolist()
    analyze_meta_learning("PH/USDT", {"loss_series": loss, "deployed_at_ms": time.time() * 1000}, a)

    assert "phase35" in a and "faz35" in a
    assert a["phase35"] is a["faz35"]
    assert a["phase35"]["phase"] == "35"


def test_run_meta_learning_phase_writes_analysis() -> None:
    """10. run_meta_learning_phase çalışır ve phase35 yazar."""
    a: dict = {}
    np.random.seed(42)
    loss = np.abs(np.random.randn(80) * 0.05 + 0.2).tolist()
    r = run_meta_learning_phase(
        "RUN/USDT",
        {"loss_series": loss, "deployed_at_ms": time.time() * 1000},
        a,
    )

    assert r["source"] == "meta_learning_engine"
    assert a.get("phase35") is r


def test_meta_engine_no_torch_sklearn_import() -> None:
    """Kaynak dosyada torch / sklearn import edilmesin."""
    import super_otonom.meta_learning_engine as mod

    tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
    banned_roots = {"torch", "sklearn"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                assert root not in banned_roots
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            assert root not in banned_roots
