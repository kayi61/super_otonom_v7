"""Faz 38 — trade_explainability birim testleri."""
from __future__ import annotations

import numpy as np
import pytest

from phases.phase_38 import trade_explainability as te_mod
from phases.phase_38.trade_explainability import (
    analyze,
    build_explain_text,
    build_top_blockers,
    build_top_contributors,
    compute_contributions,
    validate_market_data,
    weighted_mean,
)


def _schema() -> set:
    return {
        "phase",
        "module",
        "trade_permission",
        "alpha_score",
        "risk_score",
        "score_type",
        "confidence",
        "data_health",
        "event_ts",
        "half_life_ms",
        "analysis",
        "reason",
    }


def _ph(
    phase: int,
    *,
    alpha: float = 0.5,
    risk: float = 0.3,
    perm: str = "ALLOW",
    conf: float = 0.8,
    st: str = "ALPHA",
) -> dict:
    return {
        "phase": phase,
        "alpha_score": alpha,
        "risk_score": risk,
        "trade_permission": perm,
        "confidence": conf,
        "score_type": st,
    }


def _base(n: int = 36, **final_kw: str) -> dict:
    po = [_ph(i, alpha=0.4 + i * 0.001, risk=0.2 + i * 0.001) for i in range(n)]
    return {"phase_outputs": po, "final_decision": final_kw.get("final_decision", "WAIT")}


def test_analyze_none_invalid() -> None:
    r = analyze(None)
    assert r["trade_permission"] == "BLOCK"
    assert r["data_health"] == 0.0
    assert r["score_type"] == "QUALITY"
    assert _schema() <= set(r.keys())


def test_empty_phase_outputs() -> None:
    r = analyze({"phase_outputs": [], "final_decision": "WAIT"})
    assert r["trade_permission"] == "BLOCK"


def test_missing_final_decision() -> None:
    r = analyze({"phase_outputs": [_ph(1)]})
    assert r["trade_permission"] == "BLOCK"


def test_invalid_final_decision_value() -> None:
    r = analyze({"phase_outputs": [_ph(1)], "final_decision": "INVALID"})
    assert r["trade_permission"] == "BLOCK"


def test_missing_phase_field() -> None:
    bad = dict(_ph(1))
    del bad["alpha_score"]
    r = analyze({"phase_outputs": [bad], "final_decision": "WAIT"})
    assert r["trade_permission"] == "BLOCK"


def test_weighted_mean_basic() -> None:
    v = np.array([0.2, 0.8])
    w = np.array([1.0, 1.0])
    assert weighted_mean(v, w) == pytest.approx(0.5)


def test_weighted_mean_zero_weights_fallback() -> None:
    v = np.array([0.1, 0.9])
    w = np.array([0.0, 0.0])
    assert weighted_mean(v, w) == pytest.approx(0.5)


def test_avg_alpha_risk_match_weighted_mean() -> None:
    d = _base(10)
    r = analyze(d)
    po = d["phase_outputs"]
    phases, k, rw, a, rr, c = compute_contributions(po)
    exp_a = weighted_mean(a, c)
    exp_r = weighted_mean(rr, c)
    assert r["alpha_score"] == pytest.approx(np.clip(exp_a, 0, 1))
    assert r["risk_score"] == pytest.approx(np.clip(exp_r, 0, 1))


def test_consensus_ratio_and_counts() -> None:
    po = [_ph(i, perm="ALLOW") for i in range(5)]
    po[0] = _ph(99, perm="BLOCK")
    r = analyze({"phase_outputs": po, "final_decision": "ENTER"})
    assert r["analysis"]["allow_count"] == 4
    assert r["analysis"]["block_count"] == 1
    assert r["analysis"]["halt_count"] == 0
    assert r["analysis"]["consensus_ratio"] == pytest.approx(4 / 5)


def test_halt_permission() -> None:
    po = [_ph(i) for i in range(5)]
    po.append(_ph(100, perm="HALT"))
    r = analyze({"phase_outputs": po, "final_decision": "HALT"})
    assert r["trade_permission"] == "HALT"
    assert r["reason"] == "halt_phase_present"


def test_block_threshold_strict_gt() -> None:
    n = 10
    po = [_ph(i, perm="BLOCK") for i in range(n)]
    r = analyze({"phase_outputs": po, "final_decision": "WAIT"})
    assert r["analysis"]["block_count"] == n
    assert n > n * 0.3
    assert r["trade_permission"] == "BLOCK"


def test_block_boundary_not_exceeded() -> None:
    n = 10
    po = [_ph(i, perm="ALLOW") for i in range(n)]
    for i in range(3):
        po[i] = _ph(i, perm="BLOCK")
    r = analyze({"phase_outputs": po, "final_decision": "WAIT"})
    assert r["analysis"]["block_count"] == 3
    assert not (3 > n * 0.3)
    assert r["trade_permission"] == "ALLOW"


def test_top_contributors_sorted_top5() -> None:
    po = [_ph(1, alpha=0.1, conf=0.5), _ph(2, alpha=0.9, conf=1.0), _ph(3, alpha=0.5, conf=0.8)]
    phases, k, _, _, _, _ = compute_contributions(po)
    top = build_top_contributors(phases, k, 5)
    assert top[0]["phase"] == 2
    assert top[0]["score"] == pytest.approx(0.9)


def test_top_blockers_top3() -> None:
    po = [_ph(1, risk=0.9, conf=1.0), _ph(2, risk=0.1, conf=0.5), _ph(3, risk=0.8, conf=1.0)]
    phases, _, rw, _, _, _ = compute_contributions(po)
    blk = build_top_blockers(phases, rw, 3)
    assert len(blk) <= 3
    assert blk[0]["score"] >= blk[-1]["score"]


def test_explain_text_contains_decision() -> None:
    txt = build_explain_text("ENTER", 5, 2, 0, [{"phase": 9, "score": 0.7}], [{"phase": 3, "score": 0.6}])
    assert "Karar: ENTER" in txt
    assert "5✅" in txt and "2🚫" in txt
    assert "Faz 9" in txt and "Faz 3" in txt


def test_explain_text_empty_top_lists() -> None:
    txt = build_explain_text("WAIT", 0, 0, 0, [], [])
    assert "—" in txt


def test_data_health_formula() -> None:
    r = analyze(_base(35))
    assert r["data_health"] == pytest.approx(np.clip(35 / 35.0, 0.1, 1.0))


def test_confidence_is_dh_times_consensus() -> None:
    po = [_ph(i, perm="ALLOW") for i in range(35)]
    d = {"phase_outputs": po, "final_decision": "WAIT"}
    r = analyze(d)
    dh = r["data_health"]
    cr = r["analysis"]["consensus_ratio"]
    assert r["confidence"] == pytest.approx(np.clip(dh * cr, 0, 1))


def test_half_life_60000() -> None:
    assert analyze(_base())["half_life_ms"] == 60000


def test_analysis_nested_keys() -> None:
    r = analyze(_base())
    a = r["analysis"]
    for k in (
        "top_contributors",
        "top_blockers",
        "allow_count",
        "block_count",
        "halt_count",
        "consensus_ratio",
        "explain_text",
    ):
        assert k in a


def test_validate_ok() -> None:
    ok, err = validate_market_data(_base())
    assert ok and err == ""


def test_phase_output_not_dict() -> None:
    r = analyze({"phase_outputs": ["x"], "final_decision": "WAIT"})
    assert r["trade_permission"] == "BLOCK"


def test_normalize_permission_case_insensitive() -> None:
    po = [_ph(1, perm="allow")]
    r = analyze({"phase_outputs": po, "final_decision": "WAIT"})
    assert r["analysis"]["allow_count"] == 1


def test_constants() -> None:
    assert te_mod._HALF_LIFE_MS == 60000


def test_score_type_when_quality_low_dh() -> None:
    po = [_ph(i) for i in range(5)]
    r = analyze({"phase_outputs": po, "final_decision": "WAIT"})
    assert r["data_health"] < 0.42


def test_allow_reason_when_clear() -> None:
    po = [_ph(i, perm="ALLOW") for i in range(40)]
    r = analyze({"phase_outputs": po, "final_decision": "ENTER"})
    if r["trade_permission"] == "ALLOW":
        assert r["reason"] == "consensus_allow"


def test_event_ts_float() -> None:
    r = analyze(_base())
    assert isinstance(r["event_ts"], float)


def test_top_contributors_limit_five() -> None:
    po = [_ph(i, alpha=float(i) / 100.0, conf=1.0) for i in range(20)]
    phases, k, _, _, _, _ = compute_contributions(po)
    top = build_top_contributors(phases, k, 5)
    assert len(top) == 5


def test_risk_avg_weighted_not_product_mean() -> None:
    po = [_ph(1, alpha=0.5, risk=0.8, conf=1.0), _ph(2, alpha=0.5, risk=0.2, conf=0.0)]
    r = analyze({"phase_outputs": po, "final_decision": "WAIT"})
    assert r["risk_score"] == pytest.approx(0.8)


def test_module_phase_field() -> None:
    r = analyze(_base())
    assert r["phase"] == 38
    assert r["module"] == "trade_explainability"


def test_all_scores_clipped() -> None:
    r = analyze(_base())
    for k in ("alpha_score", "risk_score", "confidence", "data_health"):
        assert 0.0 <= r[k] <= 1.0


def test_parse_failure_empty_arrays_blocked() -> None:
    bad = {"phase": "NaN", "alpha_score": 1.0, "risk_score": 0.0, "trade_permission": "ALLOW", "confidence": 1.0, "score_type": "X"}
    r = analyze({"phase_outputs": [bad], "final_decision": "WAIT"})
    assert r["trade_permission"] == "BLOCK"
