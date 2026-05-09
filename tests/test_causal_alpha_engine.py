"""Faz 31 — causal_alpha_engine (Granger proxy, transfer entropy, sahte korelasyon)."""
from __future__ import annotations

import numpy as np

from super_otonom.causal_alpha_engine import analyze_causal_alpha, run_causal_alpha_phase


def test_causal_empty_blocks_quality() -> None:
    """1. Boş veri → BLOCK, data_health 0, QUALITY."""
    a: dict = {}
    r = analyze_causal_alpha("BTC/USDT", {}, a, attach_to_analysis=True)

    assert r["trade_permission"] == "BLOCK"
    assert r["data_health"] == 0.0
    assert r["score_type"] == "QUALITY"
    assert r.get("empty_reason") == "no_causal_data"


def test_causal_strong_a_to_b_allow_high_alpha() -> None:
    """2. Güçlü nedensellik (A→B) → yüksek alpha_score, ALLOW."""
    np.random.seed(42)
    n = 90
    ra = np.random.randn(n) * 0.012
    rb = np.zeros(n)
    rb[2:] = ra[:-2] + np.random.randn(n - 2) * 0.0004

    px = 100 * np.exp(np.cumsum(ra))
    py = 100 * np.exp(np.cumsum(rb))
    d = {"series_a": px.tolist(), "series_b": py.tolist()}
    r = analyze_causal_alpha("PAIR/USDT", d, {}, attach_to_analysis=False)

    assert r["trade_permission"] == "ALLOW"
    assert r["alpha_score"] >= 0.35
    c = r["causal"]
    assert c["direction"] == "A_TO_B"
    assert c["granger_ab"] > c["granger_ba"]


def test_causal_spurious_high_corr_blocks() -> None:
    """3. Sahte korelasyon (yüksek corr, düşük Granger) → BLOCK."""
    np.random.seed(42)
    n = 90
    ra = np.random.randn(n) * 0.02
    rb = ra.copy()
    px = 100 * np.exp(np.cumsum(ra))
    py = 100 * np.exp(np.cumsum(rb))
    d = {"series_a": px.tolist(), "series_b": py.tolist()}
    r = analyze_causal_alpha("SPUR/USDT", d, {}, attach_to_analysis=False)

    assert abs(r["causal"]["sample_correlation"]) >= 0.78
    assert r["causal"]["spurious_flag"] is True
    assert r["trade_permission"] == "BLOCK"


def test_causal_short_series_blocks_with_reason() -> None:
    """4. Çok kısa seri → BLOCK, empty_reason."""
    np.random.seed(42)
    short = np.random.randn(12).tolist()
    r = analyze_causal_alpha("SHORT/USDT", {"series_a": short, "series_b": short}, {})

    assert r["trade_permission"] == "BLOCK"
    assert r["empty_reason"] == "insufficient_series"


def test_causal_low_transfer_entropy_lowers_alpha() -> None:
    """5. Transfer entropy düşük → alpha_score (bağımsız seriye göre) daha düşük."""
    np.random.seed(42)
    n = 90

    ra_lead = np.random.randn(n) * 0.012
    rb_lead = np.zeros(n)
    rb_lead[2:] = ra_lead[:-2] + np.random.randn(n - 2) * 0.0004
    px_lead = 100 * np.exp(np.cumsum(ra_lead))
    py_lead = 100 * np.exp(np.cumsum(rb_lead))
    r_lead = analyze_causal_alpha(
        "LEAD/USDT",
        {"series_a": px_lead.tolist(), "series_b": py_lead.tolist()},
        {},
        attach_to_analysis=False,
    )

    ra_ind = np.random.randn(n) * 0.012
    rb_ind = np.random.randn(n) * 0.012
    px_ind = 100 * np.exp(np.cumsum(ra_ind))
    py_ind = 100 * np.exp(np.cumsum(rb_ind))
    r_ind = analyze_causal_alpha(
        "IND/USDT",
        {"series_a": px_ind.tolist(), "series_b": py_ind.tolist()},
        {},
        attach_to_analysis=False,
    )

    assert r_ind["causal"]["transfer_entropy_max"] < r_lead["causal"]["transfer_entropy_max"]
    assert r_ind["alpha_score"] < r_lead["alpha_score"]


def test_causal_phase31_faz31_attached() -> None:
    """6. analysis['phase31'] ve analysis['faz31'] aynı payload."""
    a: dict = {}
    np.random.seed(42)
    n = 40
    x = np.cumsum(np.random.randn(n)) + 100
    analyze_causal_alpha("PH/USDT", {"series_a": x.tolist(), "series_b": x.tolist()}, a)

    assert "phase31" in a and "faz31" in a
    assert a["phase31"] is a["faz31"]
    assert a["phase31"]["phase"] == "31"


def test_run_causal_alpha_phase_runs() -> None:
    """7. run_causal_alpha_phase çalışır ve phase31 yazar."""
    a: dict = {}
    np.random.seed(42)
    n = 40
    x = np.cumsum(np.random.randn(n)) + 100
    r = run_causal_alpha_phase("RUN/USDT", {"series_a": x.tolist(), "series_b": x.tolist()}, a)

    assert r["source"] == "causal_alpha_engine"
    assert a.get("phase31") is r


def test_causal_dict_key_fields() -> None:
    """8. causal dict: granger_ab, granger_ba, te_ab, spurious_flag."""
    np.random.seed(42)
    n = 60
    ra = np.random.randn(n) * 0.01
    rb = np.roll(ra, 1) + np.random.randn(n) * 0.001
    px = 100 * np.exp(np.cumsum(ra))
    py = 100 * np.exp(np.cumsum(rb))
    r = analyze_causal_alpha("KEYS/USDT", {"series_a": px.tolist(), "series_b": py.tolist()}, {})

    c = r["causal"]
    assert "granger_ab" in c and isinstance(c["granger_ab"], float)
    assert "granger_ba" in c and isinstance(c["granger_ba"], float)
    assert "te_ab" in c and isinstance(c["te_ab"], float)
    assert "spurious_flag" in c and isinstance(c["spurious_flag"], bool)
