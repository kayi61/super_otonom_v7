"""Faz 46 — production_deployment_engine birim testleri."""

from __future__ import annotations

import pytest
from phases.phase_46.production_deployment_engine import (
    analyze,
    deployment_score,
    is_transition_valid,
    validate_market_data,
)


def _schema_keys() -> set:
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


def _base_market_data() -> dict:
    return {
        "deployment_state": "SHADOW",
        "current_position": "WAIT",
        "requested_position": "ENTER",
        "cooldown_remaining_ms": 0.0,
        "human_approval_required": False,
        "human_approved": False,
        "paper_sharpe": 1.5,
        "shadow_sharpe": 1.2,
        "uptime_hours": 48.0,
    }


class TestValidation:
    def test_none_invalid(self) -> None:
        ok, err = validate_market_data(None)
        assert not ok
        assert "missing" in err or "invalid" in err

    def test_missing_field(self) -> None:
        d = _base_market_data()
        del d["deployment_state"]
        ok, err = validate_market_data(d)
        assert not ok
        assert "deployment_state" in err

    def test_valid_data(self) -> None:
        ok, err = validate_market_data(_base_market_data())
        assert ok
        assert err == ""

    def test_non_numeric_sharpe(self) -> None:
        d = _base_market_data()
        d["paper_sharpe"] = "abc"
        ok, err = validate_market_data(d)
        assert not ok
        assert "numeric" in err


class TestDeploymentScore:
    def test_paper(self) -> None:
        score, ok = deployment_score("PAPER")
        assert ok
        assert score == pytest.approx(0.3)

    def test_shadow(self) -> None:
        score, ok = deployment_score("SHADOW")
        assert ok
        assert score == pytest.approx(0.6)

    def test_live(self) -> None:
        score, ok = deployment_score("LIVE")
        assert ok
        assert score == pytest.approx(1.0)

    def test_invalid(self) -> None:
        score, ok = deployment_score("UNKNOWN")
        assert not ok
        assert score == 0.0


class TestTransitionValid:
    def test_wait_to_enter(self) -> None:
        assert is_transition_valid("WAIT", "ENTER")

    def test_enter_to_exit_blocked(self) -> None:
        assert not is_transition_valid("ENTER", "EXIT")

    def test_enter_to_hedge(self) -> None:
        assert is_transition_valid("ENTER", "HEDGE")

    def test_halt_to_wait(self) -> None:
        assert is_transition_valid("HALT", "WAIT")

    def test_invalid_source(self) -> None:
        assert not is_transition_valid("NONEXIST", "WAIT")


class TestAnalyze:
    def test_none_blocked(self) -> None:
        r = analyze(None)
        assert r["trade_permission"] == "BLOCK"
        assert r["phase"] == 46
        assert _schema_keys() <= set(r.keys())

    def test_valid_allow(self) -> None:
        r = analyze(_base_market_data())
        assert r["trade_permission"] == "ALLOW"
        assert 0.0 <= r["alpha_score"] <= 1.0
        assert 0.0 <= r["risk_score"] <= 1.0

    def test_cooldown_blocks(self) -> None:
        d = _base_market_data()
        d["cooldown_remaining_ms"] = 5000.0
        r = analyze(d)
        assert r["trade_permission"] == "BLOCK"
        assert r["reason"] == "cooldown_active"

    def test_live_requires_approval(self) -> None:
        d = _base_market_data()
        d["deployment_state"] = "LIVE"
        d["human_approved"] = False
        r = analyze(d)
        assert r["trade_permission"] == "BLOCK"
        assert "approval" in r["reason"]

    def test_live_approved(self) -> None:
        d = _base_market_data()
        d["deployment_state"] = "LIVE"
        d["human_approved"] = True
        r = analyze(d)
        assert r["trade_permission"] == "ALLOW"

    def test_halt_requested(self) -> None:
        d = _base_market_data()
        d["requested_position"] = "HALT"
        r = analyze(d)
        assert r["trade_permission"] == "HALT"
        assert r["reason"] == "halt_requested"

    def test_invalid_transition_blocks(self) -> None:
        d = _base_market_data()
        d["current_position"] = "ENTER"
        d["requested_position"] = "EXIT"
        r = analyze(d)
        assert r["trade_permission"] == "BLOCK"
        assert "transition" in r["reason"]

    def test_low_paper_sharpe_increases_risk(self) -> None:
        d = _base_market_data()
        d["paper_sharpe"] = 0.1
        r = analyze(d)
        assert r["risk_score"] > 0.3

    def test_schema_complete(self) -> None:
        r = analyze(_base_market_data())
        assert _schema_keys() <= set(r.keys())
        assert isinstance(r["analysis"], dict)
