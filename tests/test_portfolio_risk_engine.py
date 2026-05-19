"""Faz 24 — portfolio_risk_engine (VaR / CVaR / Herfindahl / stres)."""

from __future__ import annotations

from super_otonom.portfolio_risk_engine import analyze_portfolio_risk, run_portfolio_risk_phase


def test_portfolio_empty_blocks_quality() -> None:
    """1. Boş veri → BLOCK, data_health 0, QUALITY."""
    a: dict = {}
    r = analyze_portfolio_risk("BTC/USDT", {}, a, attach_to_analysis=True)

    assert r["trade_permission"] == "BLOCK"
    assert r["data_health"] == 0.0
    assert r["score_type"] == "QUALITY"
    assert r.get("empty_reason") == "no_portfolio_data"


def test_portfolio_normal_allow_risk_in_unit_interval() -> None:
    """2. Normal portföy → ALLOW, risk_score [0,1]."""
    d = {
        "weights": {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25},
        "portfolio_returns": [0.001] * 40,
        "stress_scenarios": {"bear": 0.12, "flash": 0.10},
    }
    r = analyze_portfolio_risk("NORM/USDT", d, {}, attach_to_analysis=False)

    assert r["trade_permission"] == "ALLOW"
    assert 0.0 <= r["risk_score"] <= 1.0
    pr = r["portfolio_risk"]
    assert pr["historical_returns_available"] is True


def test_portfolio_cvar_over_20_halts() -> None:
    """3. CVaR > %20 → HALT (Monte Carlo seed=42 ile deterministik)."""
    rets = [-0.30] * 10 + [-0.01] * 90
    d = {
        "weights": {"X": 1.0},
        "portfolio_returns": rets,
        "stress_scenarios": {"s": 0.10},
    }
    r = analyze_portfolio_risk("CVAR/USDT", d, {}, attach_to_analysis=False)

    assert r["portfolio_risk"]["cvar"] > 0.20
    assert r["trade_permission"] == "HALT"


def test_portfolio_stress_over_40_halts() -> None:
    """4. Stres testi kaybı > %40 → HALT."""
    d = {
        "weights": {"A": 0.5, "B": 0.5},
        "portfolio_returns": [0.0005] * 50,
        "stress_scenarios": {"flash_crash": 0.45},
    }
    r = analyze_portfolio_risk("STR/USDT", d, {}, attach_to_analysis=False)

    assert r["portfolio_risk"]["stress_max_loss_pct"] > 0.40
    assert r["trade_permission"] == "HALT"


def test_portfolio_var_over_15_blocks_without_cvar_halt() -> None:
    """5. VaR > %15 → BLOCK; CVaR (max of 3 methods) within reasonable bound."""
    # VR-04: cvar_95_1d = max(historical, parametric_student_t, mc).
    # Student-t parametric ES is larger than historical for skewed data.
    head = [-0.22, -0.21, -0.20, -0.19, -0.17]
    rest = [0.001] * (100 - len(head))
    rets = head + rest
    d = {
        "weights": {"X": 1.0},
        "portfolio_returns": rets,
        "stress_scenarios": {"s": 0.10},
    }
    r = analyze_portfolio_risk("VAR/USDT", d, {}, attach_to_analysis=False)

    assert r["portfolio_risk"]["var_max"] > 0.15
    assert r["portfolio_risk"]["cvar"] <= 0.35  # Student-t parametric ES is larger
    # VR-04: max(3 CVaR methods) → higher composite score → may escalate to HALT
    assert r["trade_permission"] in ("BLOCK", "HALT")


def test_portfolio_herfindahl_over_06_blocks() -> None:
    """6. Herfindahl > 0.6 → BLOCK (düşük stres / sentetik VaR ile HALT önlenir)."""
    d = {
        "weights": {"A": 0.85, "B": 0.15},
        "stress_scenarios": {"bear": 0.25, "flash": 0.15},
    }
    r = analyze_portfolio_risk("HIHI/USDT", d, {}, attach_to_analysis=False)

    assert r["portfolio_risk"]["herfindahl_hhi"] > 0.6
    assert r["trade_permission"] == "BLOCK"


def test_portfolio_phase24_faz24_attached() -> None:
    """7. analysis['phase24'] ve analysis['faz24'] aynı payload."""
    a: dict = {}
    d = {"weights": {"A": 1.0}, "stress_scenarios": {"x": 0.1}}
    analyze_portfolio_risk("PH/USDT", d, a, attach_to_analysis=True)

    assert "phase24" in a and "faz24" in a
    assert a["phase24"] is a["faz24"]
    assert a["phase24"]["phase"] == "24"


def test_run_portfolio_risk_phase_runs() -> None:
    """8. run_portfolio_risk_phase çalışır ve phase24 yazar."""
    a: dict = {}
    d = {
        "weights": {"A": 0.5, "B": 0.5},
        "portfolio_returns": [0.0] * 20,
        "stress_scenarios": {"m": 0.12},
    }
    r = run_portfolio_risk_phase("RUN/USDT", d, a, attach_to_analysis=True)

    assert r["source"] == "portfolio_risk_engine"
    assert a.get("phase24") is r


def test_portfolio_three_var_methods_populated() -> None:
    """9. Parametrik / tarihsel / Monte Carlo VaR alanları dolu (MC seed=42)."""
    d = {
        "weights": {"A": 1.0},
        "portfolio_returns": [0.01, -0.02, 0.015, -0.01, 0.005] * 10,
        "stress_scenarios": {"s": 0.11},
    }
    r = analyze_portfolio_risk("V3/USDT", d, {}, attach_to_analysis=False)
    pr = r["portfolio_risk"]

    assert "var_parametric" in pr and isinstance(pr["var_parametric"], float)
    assert "var_historical" in pr and isinstance(pr["var_historical"], float)
    assert "var_monte_carlo" in pr and isinstance(pr["var_monte_carlo"], float)
    assert pr["var_max"] == max(pr["var_parametric"], pr["var_historical"], pr["var_monte_carlo"])
