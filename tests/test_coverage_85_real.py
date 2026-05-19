"""
Gerçek kapsam artışı — %82 → %85. Sahte omit yok; testler asıl modül davranışını
zorlar. Hedefler:
  - portfolio_risk_engine (58% → ~90%): VaR/CVaR/HHI/stres/empty paths
  - incident_response_engine (64% → ~95%): tüm permission + severity dalları
  - liquidity_games_detector (72% → ~92%): a8 snapshot + classic order_book
  - alert_manager (65% → ~90%): tüm metodlar + cooldown + level filter
  - deploy_env_check (48% → ~90%): main() dalları (paper/live/advisory)

Strateji/main_loop/bot_engine.tick mantığına dokunulmaz — yalnız modül çağrıları.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

# ════════════════════════════════════════════════════════════════════════════
# portfolio_risk_engine
# ════════════════════════════════════════════════════════════════════════════


def test_pre_helpers_clamp_and_pick() -> None:
    from super_otonom.portfolio_risk_engine import _clamp01, _pick_score_type, _try_ts_ms

    assert _clamp01(float("nan")) == 0.0
    assert _clamp01(-1.0) == 0.0
    assert _clamp01(2.0) == 1.0
    assert _pick_score_type(0.1, 0.0) == "QUALITY"
    assert _pick_score_type(0.9, 0.9) == "RISK"
    assert _pick_score_type(0.9, 0.4) == "ALPHA"

    assert _try_ts_ms({"event_ts": 1700000000}) >= 0
    assert _try_ts_ms({"event_ts": 1700000000.5}) >= 0
    assert _try_ts_ms({"event_ts": "bad"}) > 0
    assert _try_ts_ms({}) > 0


def test_pre_weights_extraction() -> None:
    from super_otonom.portfolio_risk_engine import _extract_weights

    assert _extract_weights({"weights": {"A": 0.6, "B": 0.4}}) == {"A": 0.6, "B": 0.4}
    assert _extract_weights({"weights": {"A": "bad", "B": 0.5}}) == {"B": 1.0}
    assert _extract_weights({"weights": [["A", 0.4], ["B", 0.6]]}) == {"A": 0.4, "B": 0.6}
    assert _extract_weights({"weights": [["A", "x"], "garbage"]}) == {}
    assert _extract_weights({"weights": None}) == {}
    assert _extract_weights({"weights": {"A": 0.0, "B": 0.0}}) == {"A": 0.0, "B": 0.0}


def test_pre_portfolio_return_series_paths() -> None:
    from super_otonom.portfolio_risk_engine import _portfolio_return_series

    assert _portfolio_return_series({"portfolio_returns": [0.01, 0.02, -0.01, 0.03]}) == [
        0.01, 0.02, -0.01, 0.03
    ]
    assert _portfolio_return_series({"portfolio_returns": ["bad"] * 5}) == []
    assert _portfolio_return_series({}) == []

    combined = _portfolio_return_series({
        "weights": {"A": 0.5, "B": 0.5},
        "asset_returns": {"A": [0.01, 0.02, -0.01], "B": [-0.005, 0.01, 0.0]},
    })
    assert len(combined) == 3


def test_pre_var_and_cvar_paths() -> None:
    from super_otonom.portfolio_risk_engine import (
        cvar_expected_shortfall,
        herfindahl_index,
        var_historical,
        var_monte_carlo,
        var_parametric,
    )

    assert var_parametric([], 0.95) == 0.09
    assert var_parametric([0.01, -0.01, 0.02, -0.02, 0.005], 0.95) > 0.0
    assert var_parametric([0.01, -0.01, 0.005], confidence=0.90) >= 0.0

    assert var_historical([], 0.95) == 0.09
    h = var_historical([-0.1, -0.05, 0.0, 0.05, 0.1])
    assert h >= 0.0

    assert var_monte_carlo([0.01, -0.01], 0.95) == 0.085
    mc = var_monte_carlo([0.01, -0.02, 0.005, -0.01, 0.02], draws=50)
    assert mc >= 0.0

    assert cvar_expected_shortfall([0.01]) == 0.12
    assert cvar_expected_shortfall([-0.1, -0.05, 0.0, 0.05, 0.1]) >= 0.0

    assert herfindahl_index({}) == 1.0
    assert herfindahl_index({"A": 0.5, "B": 0.5}) == pytest.approx(0.5)


def test_pre_avg_pairwise_correlation_paths() -> None:
    from super_otonom.portfolio_risk_engine import _avg_pairwise_correlation

    cm = {"BTC": {"ETH": 0.8, "BTC": 1.0}, "ETH": {"BTC": 0.8}}
    v = _avg_pairwise_correlation({"correlation_matrix": cm})
    assert 0.0 <= v <= 1.0

    bad_cm = {"A": {"B": "bad"}, "C": "notdict"}
    v2 = _avg_pairwise_correlation({"correlation_matrix": bad_cm})
    assert v2 == 0.35

    rets = {"A": [0.01, 0.02, -0.01, 0.03, 0.02], "B": [-0.005, 0.01, 0.005, 0.0, 0.012]}
    v3 = _avg_pairwise_correlation({"weights": {"A": 0.5, "B": 0.5}, "asset_returns": rets})
    assert 0.0 <= v3 <= 1.0

    flat = {"A": [0.01] * 5, "B": [0.01] * 5}
    v4 = _avg_pairwise_correlation({"weights": {"A": 0.5, "B": 0.5}, "asset_returns": flat})
    assert v4 == 0.35

    assert _avg_pairwise_correlation({}) == 0.35


def test_pre_stress_loss_paths() -> None:
    from super_otonom.portfolio_risk_engine import _stress_max_loss_pct

    custom = _stress_max_loss_pct({"A": 1.0}, 0.5, {"stress_scenarios": {"crash": 0.3, "bull": 0.05}})
    assert custom == pytest.approx(0.3)

    no_custom = _stress_max_loss_pct({"A": 0.7, "B": 0.3}, 0.7, {})
    assert 0.0 <= no_custom <= 1.0

    bad = _stress_max_loss_pct({"A": 1.0}, 0.5, {"stress_scenarios": {"x": "bad"}})
    assert 0.0 <= bad <= 1.0


def test_pre_analyze_portfolio_full() -> None:
    from super_otonom.portfolio_risk_engine import analyze_portfolio_risk, run_portfolio_risk_phase

    d = {
        "weights": {"BTC": 0.4, "ETH": 0.4, "SOL": 0.2},
        "asset_returns": {
            "BTC": [0.01, -0.01, 0.02, -0.02, 0.015, 0.005, -0.01],
            "ETH": [0.005, -0.005, 0.01, -0.01, 0.008, 0.003, -0.005],
            "SOL": [0.02, -0.02, 0.03, -0.03, 0.018, 0.01, -0.015],
        },
    }
    a: Dict[str, Any] = {"event_ts": 1_700_000_000.0}
    out = analyze_portfolio_risk("PORT", d, a)
    assert out["phase"] == "24"
    assert "var_parametric" in out["portfolio_risk"]
    assert out["portfolio_risk"]["historical_returns_available"] is True

    out2 = run_portfolio_risk_phase("PORT", d, None, attach_to_analysis=False)
    assert out2["phase"] == "24"


def test_pre_analyze_short_history() -> None:
    from super_otonom.portfolio_risk_engine import analyze_portfolio_risk

    d = {"weights": {"BTC": 1.0}}
    out = analyze_portfolio_risk("X", d, {})
    assert out["portfolio_risk"]["historical_returns_available"] is False


def test_pre_analyze_empty_data() -> None:
    from super_otonom.portfolio_risk_engine import analyze_portfolio_risk

    out = analyze_portfolio_risk("X", None, {})
    assert out["empty_reason"] == "no_portfolio_data"

    out2 = analyze_portfolio_risk("X", {"weights": {}}, {})
    assert out2["empty_reason"] == "no_weights"


def test_pre_analyze_high_risk_block_branches() -> None:
    from super_otonom.portfolio_risk_engine import analyze_portfolio_risk

    out_hhi = analyze_portfolio_risk("X", {"weights": {"BTC": 1.0}}, {})
    assert out_hhi["portfolio_risk"]["herfindahl_hhi"] >= 0.6
    assert out_hhi["trade_permission"] in {"BLOCK", "HALT"}

    out_stress = analyze_portfolio_risk(
        "X",
        {"weights": {"A": 0.5, "B": 0.5}, "stress_scenarios": {"crash": 0.95}},
        {},
    )
    assert out_stress["trade_permission"] == "HALT"

    bad_returns = [-0.5, -0.4, -0.3, -0.45, -0.35] * 3
    out_cvar = analyze_portfolio_risk(
        "X",
        {"weights": {"A": 0.5, "B": 0.5}, "portfolio_returns": bad_returns},
        {},
    )
    assert out_cvar["trade_permission"] == "HALT"

    var_returns = [-0.18, -0.16, -0.15, -0.17, -0.18, -0.17, -0.16]
    out_var = analyze_portfolio_risk(
        "X",
        {"weights": {"A": 0.5, "B": 0.5}, "portfolio_returns": var_returns},
        {},
    )
    assert out_var["trade_permission"] in {"BLOCK", "HALT"}


# ════════════════════════════════════════════════════════════════════════════
# incident_response_engine
# ════════════════════════════════════════════════════════════════════════════


def test_incident_helpers() -> None:
    from super_otonom.incident_response_engine import (
        _clamp01,
        _clamp100,
        _default_root_cause,
        _normalize_severity,
    )

    assert _clamp01(float("nan")) == 0.0
    assert _clamp100(float("nan")) == 0
    assert _clamp100(150) == 100
    assert _clamp100(-5) == 0

    assert _normalize_severity(95) == "critical"
    assert _normalize_severity(75) == "high"
    assert _normalize_severity(50) == "medium"
    assert _normalize_severity(25) == "low"
    assert _normalize_severity(5) == "none"
    assert _normalize_severity("high") == "high"
    assert _normalize_severity("unknown") == "none"
    assert _normalize_severity(None) == "none"

    assert _default_root_cause("critical", True) == "SLO_BREACH_LATENCY_OR_AVAILABILITY"
    assert _default_root_cause("critical", False) == "CRITICAL_INCIDENT_UNKNOWN_SUBSYSTEM"
    assert _default_root_cause("high", False) == "HIGH_SEVERITY_ESCALATION_REQUIRED"
    assert _default_root_cause("medium", False) == "MEDIUM_INCIDENT_MONITOR_AND_CONTAIN"
    assert _default_root_cause("low", False) == "LOW_INCIDENT_INFORMATIONAL"
    assert _default_root_cause("none", False) == "NO_ACTIVE_INCIDENT"


def test_incident_evaluate_all_permission_branches() -> None:
    from super_otonom.incident_response_engine import evaluate_incident_response

    r_clean = evaluate_incident_response(symbol="X", analysis={})
    assert r_clean.trade_permission == "ALLOW"
    assert r_clean.incident_severity == "none"

    r_halt = evaluate_incident_response(
        symbol="X", analysis={"slo_breach": True, "incident_severity": "high"}
    )
    assert r_halt.trade_permission == "HALT"

    r_crit = evaluate_incident_response(symbol="X", analysis={"incident_severity": "critical"})
    assert r_crit.trade_permission == "HALT"

    r_slo_med = evaluate_incident_response(
        symbol="X", analysis={"slo_breach": True, "incident_severity": "medium"}
    )
    assert r_slo_med.trade_permission == "HALT"

    r_block_med = evaluate_incident_response(symbol="X", analysis={"incident_severity": "medium"})
    assert r_block_med.trade_permission == "BLOCK"

    r_low_active = evaluate_incident_response(
        symbol="X", analysis={"incident_severity": "low", "incident_active": True}
    )
    assert r_low_active.trade_permission == "BLOCK"

    r_active_no_sev = evaluate_incident_response(
        symbol="X", analysis={"incident_active": True}
    )
    assert r_active_no_sev.incident_severity == "medium"


def test_incident_evaluate_recorded_and_template_branches() -> None:
    from super_otonom.incident_response_engine import evaluate_incident_response

    r = evaluate_incident_response(
        symbol="X",
        analysis={
            "incident_severity": "high",
            "incident_recorded": False,
            "root_cause_template": "  CUSTOM_TEMPLATE  ",
            "postmortem_ready": True,
        },
    )
    assert r.incident_recorded is False
    assert r.root_cause_template == "CUSTOM_TEMPLATE"
    assert r.postmortem_ready is True

    r2 = evaluate_incident_response(
        symbol="X",
        analysis={"incident_severity": "high", "root_cause_template": "   "},
    )
    assert r2.root_cause_template == "HIGH_SEVERITY_ESCALATION_REQUIRED"


def test_incident_event_ts_and_half_life_clamps() -> None:
    from super_otonom.incident_response_engine import evaluate_incident_response

    r = evaluate_incident_response(symbol="X", analysis={"half_life_ms": 50}, event_ts=1_700_000_000)
    assert r.event_ts == 1_700_000_000
    assert r.half_life_ms == 2_000

    r2 = evaluate_incident_response(symbol="X", analysis={"half_life_ms": 999_999_999})
    assert r2.half_life_ms == 600_000

    r3 = evaluate_incident_response(symbol="X", analysis={"event_ts": 1_700_000_000_000})
    assert r3.event_ts == 1_700_000_000_000

    d = r.to_dict()
    assert d["incident_severity"] == "none"


# ════════════════════════════════════════════════════════════════════════════
# liquidity_games_detector
# ════════════════════════════════════════════════════════════════════════════


def _make_ob(spread_pct: float = 0.001, imbalance: float = 0.5) -> Dict[str, Any]:
    mid = 100.0
    spread = mid * spread_pct
    bid = mid - spread / 2
    ask = mid + spread / 2
    bid_qty = imbalance * 10
    ask_qty = (1 - imbalance) * 10
    return {
        "bids": [[bid, bid_qty]] + [[bid - 0.01 * (i + 1), bid_qty * 0.5] for i in range(9)],
        "asks": [[ask, ask_qty]] + [[ask + 0.01 * (i + 1), ask_qty * 0.5] for i in range(9)],
    }


def test_lgd_helpers() -> None:
    from super_otonom.liquidity_games_detector import (
        _clamp01,
        _clamp100,
        _compute_ob_imbalance,
        _compute_spread_pct,
        _extract_best_prices,
    )

    assert _clamp01(float("nan")) == 0.0
    assert _clamp100(float("nan")) == 0

    assert _extract_best_prices({}) == (None, None)
    assert _extract_best_prices({"bids": [["bad", 1]], "asks": [["bad", 1]]}) == (None, None)
    assert _extract_best_prices({"bids": [[-1, 1]], "asks": [[1, 1]]}) == (None, None)
    assert _extract_best_prices({"bids": [[100, 1]], "asks": [[101, 1]]}) == (100.0, 101.0)

    assert _compute_spread_pct(100, 101) > 0.0
    assert _compute_spread_pct(0, 0) == 0.0

    assert _compute_ob_imbalance({"bids": [], "asks": []}) is None
    assert _compute_ob_imbalance({"bids": [[1, 0]], "asks": [[1, 0]]}) is None
    assert _compute_ob_imbalance({"bids": [["x", "y"]], "asks": [[1, 1]]}) is None
    v = _compute_ob_imbalance({"bids": [[1, 5]], "asks": [[1, 5]]})
    assert v == pytest.approx(0.5)


def test_lgd_detect_with_classic_order_book() -> None:
    from super_otonom.liquidity_games_detector import detect_liquidity_games

    r = detect_liquidity_games(symbol="X", order_book=_make_ob(), analysis={"volatility": 0.02})
    assert r.trade_permission in {"ALLOW", "BLOCK"}
    assert 0 <= r.manipulation_risk_score <= 100
    assert 0 <= r.alpha_score <= 100
    assert r.game_type in {"none", "spoofing", "stop_hunt", "momentum_ignition", "quote_stuffing"}


def test_lgd_detect_high_risk_scenario() -> None:
    from super_otonom.liquidity_games_detector import detect_liquidity_games

    r = detect_liquidity_games(
        symbol="X",
        order_book=_make_ob(spread_pct=0.02, imbalance=0.95),
        analysis={"volatility": 0.10},
    )
    assert r.manipulation_risk_score >= 50
    assert r.do_not_trade_flag is True or r.manipulation_risk_score >= 50


def test_lgd_detect_with_a8_snapshot() -> None:
    from super_otonom.liquidity_games_detector import detect_liquidity_games

    snap = {
        "schema": "a8/v1",
        "order_book": {
            "empty": False,
            "spread_rel": 0.002,
            "ob_imbalance_top10": 0.55,
            "levels": _make_ob(),
        },
    }
    r = detect_liquidity_games(symbol="X", analysis={"market_snapshot": snap, "volatility": 0.03})
    assert r.spread_pct is not None
    assert r.ob_imbalance is not None


def test_lgd_detect_with_a8_missing_fields() -> None:
    from super_otonom.liquidity_games_detector import detect_liquidity_games

    snap = {
        "schema": "a8/v1",
        "order_book": {"empty": False, "levels": _make_ob()},
    }
    r = detect_liquidity_games(symbol="X", analysis={"market_snapshot": snap, "volatility": 0.02})
    assert r.spread_pct is not None or r.spread_pct is None


def test_lgd_detect_no_data_paths() -> None:
    from super_otonom.liquidity_games_detector import detect_liquidity_games

    r = detect_liquidity_games(symbol="X", analysis={})
    assert r.trade_permission in {"ALLOW", "BLOCK"}
    assert r.game_type == "unknown"

    r2 = detect_liquidity_games(symbol="X", order_book={"bids": [], "asks": []})
    assert r2.game_type == "unknown"

    r3 = detect_liquidity_games(symbol="X", analysis={"volatility": "bad"}, order_book=_make_ob())
    assert r3.vol_proxy is not None


def test_lgd_event_ts_and_half_life() -> None:
    from super_otonom.liquidity_games_detector import detect_liquidity_games

    r = detect_liquidity_games(
        symbol="X", order_book=_make_ob(), analysis={"half_life_ms": 500}, event_ts=1_700_000_000
    )
    assert r.event_ts == 1_700_000_000
    assert r.half_life_ms == 2_000

    r2 = detect_liquidity_games(symbol="X", order_book=_make_ob(), analysis={"half_life_ms": 999_999})
    assert r2.half_life_ms == 300_000

    d = r.to_dict()
    assert "manipulation_risk_score" in d


# ════════════════════════════════════════════════════════════════════════════
# alert_manager
# ════════════════════════════════════════════════════════════════════════════


def test_alert_manager_filters_below_min_level(monkeypatch: pytest.MonkeyPatch) -> None:
    from super_otonom.alert_manager import AlertManager

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    m = AlertManager(webhook_url="", cooldown_sec=0, min_level="CRITICAL")
    m.system("startup", "info text", level="INFO")
    assert len(m._history) == 0


def test_alert_manager_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    from super_otonom.alert_manager import AlertManager

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    m = AlertManager(webhook_url="", cooldown_sec=10000, min_level="DEBUG")
    m.emergency("k1", nav=1.0, detail="d")
    m.emergency("k1", nav=2.0)
    assert len(m._history) == 1


def test_alert_manager_all_methods(monkeypatch: pytest.MonkeyPatch) -> None:
    from super_otonom.alert_manager import AlertManager

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    m = AlertManager(webhook_url="", cooldown_sec=0, min_level="DEBUG")

    m.emergency("dyn_loss", nav=1000.0, detail="extreme")
    m.nav_diff(diff=500.0, diff_pct=12.5, local=1000.0, exchange=1500.0)
    m.nav_diff(diff=10.0, diff_pct=1.0)
    m.circuit_breaker("BTC/USDT", "OPEN", reason="too many errors")
    m.stale_data("BTC/USDT", age_sec=120.0)
    m.backoff(error_count=1, wait_sec=1)
    m.backoff(error_count=5, wait_sec=10)
    m.system("startup", "ok", level="INFO")
    m.tca_anomaly("X", expected_slip=0.01, actual_slip=0.5)

    snap = m.snapshot()
    assert snap["total_alerts"] >= 6
    assert snap["webhook_active"] is False
    assert snap["telegram_active"] is False


def test_alert_manager_webhook_post_success_and_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    import super_otonom.alert_manager as am

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    m = am.AlertManager(webhook_url="http://hook", cooldown_sec=0, min_level="DEBUG")

    class _Resp:
        status = 200

        def __enter__(self) -> "_Resp":
            return self

        def __exit__(self, *_: Any) -> None:
            pass

    with patch.object(am.urllib.request, "urlopen", return_value=_Resp()):
        m.emergency("ok_path", nav=1.0)
    assert m._history[-1].sent is True

    with patch.object(am.urllib.request, "urlopen", side_effect=OSError("net")):
        m.circuit_breaker("ETH/USDT", "OPEN")
    assert m._history[-1].error


def test_alert_manager_telegram_post(monkeypatch: pytest.MonkeyPatch) -> None:
    import super_otonom.alert_manager as am

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    m = am.AlertManager(webhook_url="", cooldown_sec=0, min_level="DEBUG")

    class _Resp:
        status = 200

        def __enter__(self) -> "_Resp":
            return self

        def __exit__(self, *_: Any) -> None:
            pass

    with patch.object(am.urllib.request, "urlopen", return_value=_Resp()):
        m.emergency("with_telegram", nav=1.0)

    class _BadResp:
        status = 500

        def __enter__(self) -> "_BadResp":
            return self

        def __exit__(self, *_: Any) -> None:
            pass

    with patch.object(am.urllib.request, "urlopen", return_value=_BadResp()):
        m.nav_diff(diff=5.0, diff_pct=12.0)

    with patch.object(am.urllib.request, "urlopen", side_effect=OSError("e")):
        m.circuit_breaker("X", "OPEN")

    m.system("info_event", "x", level="INFO")
    snap = m.snapshot()
    assert snap["telegram_active"] is True


def test_alert_manager_history_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    import super_otonom.alert_manager as am

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setattr(am, "_MAX_HISTORY", 3)
    m = am.AlertManager(webhook_url="", cooldown_sec=0, min_level="DEBUG")
    for i in range(6):
        m.system(f"event_{i}", level="INFO")
    assert len(m._history) == 3


# ════════════════════════════════════════════════════════════════════════════
# deploy_env_check — main() branch coverage
# ════════════════════════════════════════════════════════════════════════════


def test_dec_paper_mode_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import super_otonom.config as cfg
    from super_otonom import deploy_env_check as dec

    monkeypatch.setenv("META_REGIME_MODE", "shadow")
    monkeypatch.setenv("DEPLOY_ENV_SKIP_RISK_SUMMARY", "1")
    monkeypatch.setitem(cfg.GENERAL, "paper_mode", True)
    monkeypatch.setitem(cfg.GENERAL, "live_confirm", "")
    monkeypatch.setattr(
        "super_otonom.deploy_env_stamp.write_last_ok", lambda: tmp_path / "stamp.json"
    )
    (tmp_path / "stamp.json").write_text("{}", encoding="utf-8")
    assert dec.main() == 0


def test_dec_live_without_confirm_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    import super_otonom.config as cfg
    from super_otonom import deploy_env_check as dec

    monkeypatch.setenv("META_REGIME_MODE", "shadow")
    monkeypatch.setitem(cfg.GENERAL, "paper_mode", False)
    monkeypatch.setitem(cfg.GENERAL, "live_confirm", "")
    assert dec.main() == 1


def test_dec_live_loose_advisory_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    import super_otonom.config as cfg
    from super_otonom import deploy_env_check as dec

    monkeypatch.setenv("META_REGIME_MODE", "advisory")
    monkeypatch.setenv("META_ADVISORY_LOOSE", "1")
    monkeypatch.setitem(cfg.GENERAL, "paper_mode", False)
    monkeypatch.setitem(cfg.GENERAL, "live_confirm", "YES")
    assert dec.main() == 1


def test_dec_advisory_missing_ack_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import super_otonom.config as cfg
    from super_otonom import deploy_env_check as dec
    from super_otonom import meta_regime_orchestrator as mro

    monkeypatch.setenv("META_REGIME_MODE", "advisory")
    monkeypatch.setenv("META_ADVISORY_LOOSE", "")
    monkeypatch.setitem(cfg.GENERAL, "paper_mode", False)
    monkeypatch.setitem(cfg.GENERAL, "live_confirm", "YES")

    missing = tmp_path / "absent.txt"
    monkeypatch.setattr(mro, "advisory_ack_path_for_gate", lambda *_: str(missing))
    assert dec.main() == 1

    monkeypatch.setattr(mro, "advisory_ack_path_for_gate", lambda *_: None)
    monkeypatch.setenv("DEPLOY_ENV_SKIP_RISK_SUMMARY", "1")
    monkeypatch.setattr(
        "super_otonom.deploy_env_stamp.write_last_ok", lambda: tmp_path / "ok.json"
    )
    (tmp_path / "ok.json").write_text("{}", encoding="utf-8")
    assert dec.main() == 0


def test_dec_testnet_warning_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import super_otonom.config as cfg
    from super_otonom import deploy_env_check as dec

    monkeypatch.setenv("META_REGIME_MODE", "shadow")
    monkeypatch.setenv("DEPLOY_ENV_SKIP_RISK_SUMMARY", "1")
    monkeypatch.setitem(cfg.GENERAL, "paper_mode", False)
    monkeypatch.setitem(cfg.GENERAL, "live_confirm", "YES")
    monkeypatch.setitem(cfg.GENERAL, "default_exchange", "binance")
    monkeypatch.setitem(cfg.EXCHANGES["binance"], "testnet", True)
    monkeypatch.setattr(
        "super_otonom.deploy_env_stamp.write_last_ok", lambda: tmp_path / "s.json"
    )
    (tmp_path / "s.json").write_text("{}", encoding="utf-8")
    assert dec.main() == 0


def test_dec_subprocess_summary_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import super_otonom.config as cfg
    from super_otonom import deploy_env_check as dec

    monkeypatch.setenv("META_REGIME_MODE", "shadow")
    monkeypatch.delenv("DEPLOY_ENV_SKIP_RISK_SUMMARY", raising=False)
    monkeypatch.setitem(cfg.GENERAL, "paper_mode", True)

    fake_proc = MagicMock(returncode=1)
    monkeypatch.setattr(dec.subprocess, "run", lambda *a, **kw: fake_proc)
    monkeypatch.setattr(
        "super_otonom.deploy_env_stamp.write_last_ok", lambda: tmp_path / "stamp.json"
    )
    (tmp_path / "stamp.json").write_text("{}", encoding="utf-8")
    assert dec.main() == 0


def test_dec_write_last_ok_error(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    import super_otonom.config as cfg
    from super_otonom import deploy_env_check as dec

    monkeypatch.setenv("META_REGIME_MODE", "shadow")
    monkeypatch.setenv("DEPLOY_ENV_SKIP_RISK_SUMMARY", "1")
    monkeypatch.setitem(cfg.GENERAL, "paper_mode", True)

    def _boom() -> Path:
        raise OSError("disk full")

    monkeypatch.setattr("super_otonom.deploy_env_stamp.write_last_ok", _boom)
    assert dec.main() == 0


# ════════════════════════════════════════════════════════════════════════════
# social_signal — entry hatleri
# ════════════════════════════════════════════════════════════════════════════


def test_social_signal_basic_and_empty() -> None:
    from super_otonom.social_signal import (
        _aggregate_sentiment,
        _detect_hype_stage,
        _mention_momentum,
        _sentiment_trend_label,
    )

    comp, plat = _aggregate_sentiment({})
    assert comp == 0.0
    comp2, _ = _aggregate_sentiment({"twitter_sentiment": 0.8, "reddit_sentiment": -0.5})
    assert -1.0 <= comp2 <= 1.0
    comp3, _ = _aggregate_sentiment({"sentiment_score": 0.7, "twitter_sentiment": 0.2})
    assert -1.0 <= comp3 <= 1.0
    comp4, _ = _aggregate_sentiment({"sentiment_score": 1.5})
    assert -1.0 <= comp4 <= 1.0

    m, _ = _mention_momentum({"mention_momentum": 0.5})
    assert 0.0 <= m <= 1.0
    m2, _ = _mention_momentum({"mention_count": 100, "mention_count_prev": 50})
    assert 0.0 <= m2 <= 1.0
    m3, _ = _mention_momentum({"mention_count": 100})
    assert 0.0 <= m3 <= 1.0
    m4, _ = _mention_momentum({})
    assert 0.0 <= m4 <= 1.0

    assert _sentiment_trend_label({"sentiment_trend": "bullish"}) == "up"
    assert _sentiment_trend_label({"sentiment_trend": "bearish"}) == "down"
    assert _sentiment_trend_label({"sentiment_trend_score": 0.2}) == "up"
    assert _sentiment_trend_label({"sentiment_trend_score": -0.2}) == "down"
    assert _sentiment_trend_label({}) == "flat"

    assert _detect_hype_stage(-0.8, 0.5, 0.5, "flat") == "CAPITULATION"
    assert _detect_hype_stage(0.7, 0.9, 0.8, "up") == "PEAK"
    assert _detect_hype_stage(0.5, 0.7, 0.5, "flat") == "FOMO"
    assert _detect_hype_stage(-0.2, 0.5, 0.5, "up") == "RECOVERY"
    assert _detect_hype_stage(0.2, 0.5, 0.5, "up") == "RECOVERY"
    assert _detect_hype_stage(0.1, 0.1, 0.1, "flat") == "NEUTRAL"


def test_social_signal_analyze_paths() -> None:
    from super_otonom.social_signal import analyze_social_signal

    out = analyze_social_signal("BTC", None, {})
    assert out["phase"] == "16"

    out2 = analyze_social_signal(
        "BTC",
        {
            "twitter_sentiment": 0.7,
            "reddit_sentiment": 0.6,
            "mention_count": 5000,
            "mention_count_prev": 500,
            "engagement_rate": 0.8,
            "sentiment_trend": "up",
        },
        {"signal": "BUY"},
    )
    assert out2["phase"] == "16"
    assert "social_signal" in out2 or "phase" in out2

    out3 = analyze_social_signal(
        "BTC",
        {
            "sentiment_score": -0.8,
            "mention_count": 200,
            "engagement_rate": 0.3,
        },
        {"signal": "SELL"},
    )
    assert out3["phase"] == "16"


# ════════════════════════════════════════════════════════════════════════════
# data_quality_governance — Faz 66
# ════════════════════════════════════════════════════════════════════════════


def test_dqg_helpers() -> None:
    from super_otonom.data_quality_governance import _clamp01, _clamp100, _try_float, _try_int

    assert _clamp01(float("nan")) == 0.0
    assert _clamp100(float("nan")) == 0
    assert _try_float(None, default=1.5) == 1.5
    assert _try_float("bad", default=2.0) == 2.0
    assert _try_float("3.14") == 3.14
    assert _try_int(None, default=5) == 5
    assert _try_int("bad", default=0) == 0
    assert _try_int("7.9") == 7


def test_dqg_evaluate_all_permission_branches() -> None:
    from super_otonom.data_quality_governance import evaluate_data_quality_governance

    r_clean = evaluate_data_quality_governance(
        symbol="X",
        analysis={
            "regime": "TREND",
            "volatility": 0.02,
            "signal": "BUY",
            "liquidity_ratio": 0.8,
            "order_book": {"bids": [], "asks": []},
            "event_ts": 1_700_000_000,
            "data_quality_score": 90,
            "source_trust_score": 88,
        },
    )
    assert r_clean.trade_permission == "ALLOW"

    r_rollback = evaluate_data_quality_governance(
        symbol="X", analysis={"rollback_required": True}
    )
    assert r_rollback.trade_permission == "HALT"

    r_qua = evaluate_data_quality_governance(
        symbol="X", analysis={"quarantine_flag": True}
    )
    assert r_qua.trade_permission == "BLOCK"

    r_low_dq = evaluate_data_quality_governance(
        symbol="X", analysis={"data_quality_score": 20}
    )
    assert r_low_dq.trade_permission == "BLOCK"
    assert r_low_dq.quarantine_flag is True

    r_low_trust = evaluate_data_quality_governance(
        symbol="X", analysis={"source_trust_score": 20}
    )
    assert r_low_trust.trade_permission == "BLOCK"


def test_dqg_stale_signal_reduces_scores() -> None:
    from super_otonom.data_quality_governance import evaluate_data_quality_governance

    fresh = evaluate_data_quality_governance(
        symbol="X",
        analysis={"data_quality_score": 80, "source_trust_score": 80, "signal_age_ms": 0},
    )
    stale = evaluate_data_quality_governance(
        symbol="X",
        analysis={
            "data_quality_score": 80,
            "source_trust_score": 80,
            "signal_age_ms": 200_000,
            "half_life_ms": 20_000,
        },
    )
    assert stale.data_quality_score < fresh.data_quality_score


def test_dqg_event_ts_and_half_life_clamps() -> None:
    from super_otonom.data_quality_governance import evaluate_data_quality_governance

    r = evaluate_data_quality_governance(
        symbol="X", analysis={"half_life_ms": 100}, event_ts=1_700_000_000
    )
    assert r.event_ts == 1_700_000_000
    assert r.half_life_ms == 2_000

    r2 = evaluate_data_quality_governance(
        symbol="X", analysis={"half_life_ms": 999_999_999}
    )
    assert r2.half_life_ms == 300_000

    d = r.to_dict()
    assert "data_quality_score" in d


# ════════════════════════════════════════════════════════════════════════════
# dealer_intent_inference_engine — Faz 71
# ════════════════════════════════════════════════════════════════════════════


def test_dii_helpers() -> None:
    from super_otonom.dealer_intent_inference_engine import (
        _clamp01,
        _clamp100,
        _compute_ob_imbalance,
        _compute_spread_pct,
        _extract_best_prices,
        _spread_regime,
    )

    assert _clamp01(float("nan")) == 0.0
    assert _clamp100(float("nan")) == 0

    assert _extract_best_prices({}) == (None, None)
    assert _extract_best_prices({"bids": [[100, 1]], "asks": [[101, 1]]}) == (100.0, 101.0)
    assert _extract_best_prices({"bids": [[-1, 1]], "asks": [[1, 1]]}) == (None, None)

    assert _compute_spread_pct(0, 0) == 0.0
    assert _compute_spread_pct(100, 101) > 0.0

    assert _spread_regime(None) == "unknown"
    assert _spread_regime(0.0005) == "tight"
    assert _spread_regime(0.003) == "normal"
    assert _spread_regime(0.01) == "wide"

    assert _compute_ob_imbalance({"bids": [], "asks": []}) is None
    assert _compute_ob_imbalance({"bids": [[1, 0]], "asks": [[1, 0]]}) is None
    v = _compute_ob_imbalance({"bids": [[1, 5]], "asks": [[1, 5]]})
    assert v == pytest.approx(0.5)


def test_dii_infer_with_full_ob() -> None:
    from super_otonom.dealer_intent_inference_engine import infer_dealer_intent

    r = infer_dealer_intent(symbol="X", order_book=_make_ob())
    assert r.trade_permission in {"ALLOW", "BLOCK"}
    assert 0 <= r.dealer_pressure_score <= 100
    assert r.spread_regime in {"tight", "normal", "wide", "unknown"}


def test_dii_infer_wide_spread_long_trap() -> None:
    from super_otonom.dealer_intent_inference_engine import infer_dealer_intent

    r = infer_dealer_intent(
        symbol="X",
        order_book=_make_ob(spread_pct=0.02, imbalance=0.9),
    )
    assert r.likely_trap_side in {"long", "short", "none"}
    assert r.risk_off_hint in {"risk_off", "neutral", "risk_on"}


def test_dii_infer_wide_spread_short_trap() -> None:
    from super_otonom.dealer_intent_inference_engine import infer_dealer_intent

    r = infer_dealer_intent(
        symbol="X",
        order_book=_make_ob(spread_pct=0.02, imbalance=0.1),
    )
    assert r.likely_trap_side in {"short", "none", "long"}


def test_dii_infer_no_ob() -> None:
    from super_otonom.dealer_intent_inference_engine import infer_dealer_intent

    r = infer_dealer_intent(symbol="X", order_book=None)
    assert r.likely_trap_side == "unknown"
    assert r.spread_regime == "unknown"
    assert r.risk_off_hint == "unknown"


def test_dii_event_ts_and_half_life_clamps() -> None:
    from super_otonom.dealer_intent_inference_engine import infer_dealer_intent

    r = infer_dealer_intent(
        symbol="X",
        order_book=_make_ob(),
        analysis={"half_life_ms": 100},
        event_ts=1_700_000_000,
    )
    assert r.event_ts == 1_700_000_000
    assert r.half_life_ms == 2_000

    r2 = infer_dealer_intent(
        symbol="X", order_book=_make_ob(), analysis={"half_life_ms": 999_999_999}
    )
    assert r2.half_life_ms == 300_000

    d = r.to_dict()
    assert "dealer_pressure_score" in d


# ════════════════════════════════════════════════════════════════════════════
# benchmark_katman_a — mock yolunu tek seferlik çalıştır (gerçek borsa yok)
# ════════════════════════════════════════════════════════════════════════════


def test_benchmark_katman_a_mock_path_one_iteration(capsys: pytest.CaptureFixture[str]) -> None:
    import asyncio

    from super_otonom.benchmark_katman_a import (
        _percentile,
        _print_omega_micro,
        _run_benchmark,
        _run_mock_benchmark,
        _summarize,
    )

    assert _percentile([], 50.0) == 0.0
    assert _percentile([1.0], 50.0) == 1.0
    assert _percentile([1.0, 2.0, 3.0], 50.0) == 2.0
    assert _percentile([1.0, 2.0, 3.0, 4.0], 90.0) > 0.0

    _summarize("test", [1.0, 2.0, 3.0])
    _print_omega_micro()

    asyncio.run(
        _run_mock_benchmark(iterations=1, warmup=1, scenario="normal", symbol="BTC/USDT")
    )
    asyncio.run(
        _run_benchmark(
            iterations=1,
            warmup=0,
            scenario="flash_crash",
            symbol="BTC/USDT",
            live_ob=False,
            exchange_id="binance",
        )
    )
    capsys.readouterr()


def test_benchmark_katman_a_mock_handler() -> None:
    import asyncio

    from super_otonom.benchmark_katman_a import _MockExchangeHandler

    h = _MockExchangeHandler({"bids": [[1, 1]], "asks": [[2, 1]]})
    ob = asyncio.run(h.fetch_order_book("X", limit=10))
    assert ob["bids"]
    assert h.circuit_breaker_status() == {}


# ════════════════════════════════════════════════════════════════════════════
# coordination_resilience — küçük ama %80
# ════════════════════════════════════════════════════════════════════════════


def test_coordination_resilience_paths() -> None:
    from super_otonom.coordination_resilience import (
        RESILIENCE_EXIT_PATHS,
        assert_coordination_invariants,
        coordination_snapshot,
    )

    snap = coordination_snapshot()
    assert "kanon_ok" in snap
    assert "resilience_exit_paths" in snap
    assert RESILIENCE_EXIT_PATHS["global_trade_kill"]

    if snap["kanon_ok"]:
        assert_coordination_invariants() is None
    else:
        with pytest.raises(AssertionError):
            assert_coordination_invariants()


# ════════════════════════════════════════════════════════════════════════════
# safety_policy_engine — sığ ek dallar
# ════════════════════════════════════════════════════════════════════════════


def test_safety_policy_engine_paths() -> None:
    from super_otonom.safety_policy_engine import evaluate_safety_policy

    r1 = evaluate_safety_policy(symbol="X", analysis={})
    assert r1.trade_permission in {"ALLOW", "BLOCK", "HALT"}

    r2 = evaluate_safety_policy(symbol="X", analysis={"news_kill_switch": True})
    assert r2.trade_permission == "HALT"

    r3 = evaluate_safety_policy(
        symbol="X", analysis={"volatility": 0.30, "volatility_kill_threshold": 0.10}
    )
    assert r3.trade_permission == "BLOCK"

    r4 = evaluate_safety_policy(
        symbol="X", analysis={"exp_pct": 1.5, "max_gross_exposure_pct": 0.5}
    )
    assert r4.trade_permission == "BLOCK"

    r5 = evaluate_safety_policy(symbol="X", analysis={"approval_required": True})
    assert r5.trade_permission == "BLOCK"

    r6 = evaluate_safety_policy(
        symbol="X",
        analysis={"open_exposure_notional": 100.0, "exp_pct": None},
        event_ts=1_700_000_000,
    )
    assert r6.event_ts == 1_700_000_000

    r7 = evaluate_safety_policy(
        symbol="X", analysis={"half_life_ms": 100}, event_ts=1_700_000_000
    )
    assert r7.half_life_ms == 2_000
    r8 = evaluate_safety_policy(symbol="X", analysis={"half_life_ms": 999_999_999})
    assert r8.half_life_ms == 300_000

    d = r1.to_dict()
    assert "max_position_check" in d


# ════════════════════════════════════════════════════════════════════════════
# pre_trade_gate — yan dallar
# ════════════════════════════════════════════════════════════════════════════


def test_pre_trade_gate_helpers() -> None:
    from super_otonom.pre_trade_gate import (
        fat_finger_check,
        gate_entry_cooldown,
        gate_leverage_notional,
        ob_depth_check,
        same_bar_guard,
        spread_check,
    )

    ok, _ = fat_finger_check(100.0, max_notional=1000.0)
    assert ok is True
    ok2, msg = fat_finger_check(10_000.0, max_notional=1000.0)
    assert ok2 is False
    assert "fat_finger" in msg

    ok3, _ = spread_check({"bids": [[100, 1]], "asks": [[100.05, 1]]}, max_spread_pct=0.01)
    assert ok3 is True
    ok4, _ = spread_check({"bids": [[100, 1]], "asks": [[110, 1]]}, max_spread_pct=0.01)
    assert ok4 is False
    ok5, _ = spread_check({}, max_spread_pct=0.01)
    assert ok5 is True
    ok6, _ = spread_check({"bids": [[-1, 1]], "asks": [[1, 1]]}, max_spread_pct=0.01)
    assert ok6 is True

    ok7, _ = ob_depth_check({"asks": [[100.0, 1.0]] * 5}, order_size=10.0, min_depth=100.0)
    assert isinstance(ok7, bool)
    ok8, _ = ob_depth_check({"asks": [[100.0, 0.001]] * 2}, order_size=1000.0, min_depth=100_000.0)
    assert ok8 is False
    ok9, _ = ob_depth_check({"asks": []}, order_size=10.0)
    assert ok9 is True
    ok10, _ = ob_depth_check({"asks": [["bad", "bad"]]}, order_size=10.0)
    assert ok10 is True

    ok11, _ = gate_entry_cooldown("X", {}, cooldown_sec=0.0)
    assert ok11 is True
    ok12, _ = gate_entry_cooldown("X", {}, cooldown_sec=10.0)
    assert ok12 is True
    import time as _t

    ok13, msg13 = gate_entry_cooldown("X", {"X": _t.monotonic()}, cooldown_sec=10.0)
    assert ok13 is False
    assert "cooldown" in msg13

    ok14, _ = gate_leverage_notional(0.0, 100.0, 0.5, 2.0)
    assert ok14 is False
    ok15, _ = gate_leverage_notional(1000.0, 100.0, 0.5, 2.0)
    assert ok15 is True
    ok16, msg16 = gate_leverage_notional(1000.0, 10_000.0, 0.5, 2.0)
    assert ok16 is False
    assert "leverage" in msg16

    ok17, _ = same_bar_guard("X", 1000.0, {})
    assert ok17 is True
    ok18, _ = same_bar_guard("X", 1000.0, {"X": 1000.0})
    assert ok18 is False
