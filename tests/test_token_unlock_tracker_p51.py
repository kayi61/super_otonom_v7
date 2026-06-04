"""PROMPT-5.1 — Token Unlock & Vesting Tracker + Faz 23/27 entegrasyonu."""

from __future__ import annotations

import json

import pytest
from super_otonom.signals.alternative_data_engine import analyze_alternative_data
from super_otonom.signals.news_event_intelligence import analyze_news_event
from super_otonom.signals.token_unlock_tracker import (
    CLIFF,
    ECOSYSTEM,
    LINEAR,
    TEAM,
    UnlockCollector,
    analyze_token_unlock,
    analyze_unlock_data,
    backtest_unlock_impact,
    event_severity,
    normalize_event,
    parse_dune,
    parse_token_unlocks_app,
)

NOW = 1_000_000_000_000.0
_DAY = 86_400_000.0


def _ev(days: float, pct: float, utype: str = "cliff", cat: str = "team") -> dict:
    return {"date_ms": NOW + days * _DAY, "pct_of_circulating": pct, "unlock_type": utype, "category": cat}


# ── 1) Event + severity ──────────────────────────────────────────────────────


def test_event_severity_cliff_gt_linear() -> None:
    cliff = event_severity(0.06, CLIFF, TEAM)
    linear = event_severity(0.06, LINEAR, ECOSYSTEM)
    assert cliff > linear
    assert 0.0 < linear < cliff <= 1.0


def test_event_severity_scales_with_pct() -> None:
    assert event_severity(0.08, CLIFF, TEAM) > event_severity(0.01, CLIFF, TEAM)


def test_normalize_event_pct_percent_form() -> None:
    e = normalize_event(_ev(5, 5.0), circulating_supply=None, now_ms=NOW)  # 5 → 0.05
    assert e is not None and e.pct_of_circulating == pytest.approx(0.05)


def test_normalize_event_from_amount() -> None:
    raw = {"date_ms": NOW + 5 * _DAY, "amount": 1000, "unlock_type": "cliff", "category": "team"}
    e = normalize_event(raw, circulating_supply=20000, now_ms=NOW)
    assert e is not None and e.pct_of_circulating == pytest.approx(0.05)
    assert e.days_until == pytest.approx(5.0)


def test_normalize_event_invalid() -> None:
    assert normalize_event({"pct_of_circulating": 0.05}, circulating_supply=None, now_ms=NOW) is None
    assert normalize_event("nope", circulating_supply=None, now_ms=NOW) is None


# ── 2/4) Birleşik sinyal + otomatik risk ayarı ───────────────────────────────


def test_high_sell_pressure_7d_blocks_and_shrinks() -> None:
    sig = analyze_token_unlock([_ev(3, 0.06)], now_ms=NOW)
    assert sig is not None
    assert sig.high_sell_pressure is True
    assert sig.risk_score >= 0.6
    assert sig.position_size_multiplier == 0.5
    assert sig.trade_permission == "BLOCK"
    assert sig.alpha_bias < 0


def test_unlock_day_blocks() -> None:
    sig = analyze_token_unlock([_ev(0.5, 0.03)], now_ms=NOW)
    assert sig.trade_permission == "BLOCK"
    assert sig.next_unlock_days == pytest.approx(0.5)


def test_urgent_whale_inflow_halts() -> None:
    sig = analyze_token_unlock([_ev(5, 0.06)], whale_exchange_inflow_usd=6_000_000, now_ms=NOW)
    assert sig.urgent is True
    assert sig.trade_permission == "HALT"
    assert sig.position_size_multiplier <= 0.4
    assert any("ACİL" in r or "whale" in r.lower() for r in sig.reasons)


def test_far_unlock_low_risk_allows() -> None:
    sig = analyze_token_unlock([_ev(200, 0.06)], now_ms=NOW)
    assert sig.trade_permission == "ALLOW"
    assert sig.position_size_multiplier == 1.0
    assert sig.high_sell_pressure is False
    assert sig.risk_score < 0.4


def test_windows_aggregate() -> None:
    sig = analyze_token_unlock([_ev(3, 0.03), _ev(20, 0.04), _ev(80, 0.05)], now_ms=NOW)
    assert sig.window_7d.count == 1
    assert sig.window_30d.count == 2
    assert sig.window_90d.count == 3
    assert sig.window_30d.total_pct == pytest.approx(0.07)


def test_cliff_reason_present() -> None:
    sig = analyze_token_unlock([_ev(10, 0.04, "cliff", "investor")], now_ms=NOW)
    assert any("Cliff" in r for r in sig.reasons)


def test_empty_returns_none() -> None:
    assert analyze_token_unlock([], now_ms=NOW) is None


# ── 3) Geçmiş davranış backtest ──────────────────────────────────────────────


def test_backtest_unlock_impact_dump() -> None:
    hist = [
        {"post_move_pct": -0.10, "team_sold": True},
        {"post_move_pct": -0.06, "team_sold": True},
        {"price_before": 100, "price_after": 92, "team_sold": False},
    ]
    stats = backtest_unlock_impact(hist)
    assert stats.sample_size == 3
    assert stats.avg_post_move_pct < 0
    assert stats.sold_rate == pytest.approx(2 / 3)
    assert stats.worst_drawdown_pct < 0


def test_history_dump_raises_risk() -> None:
    hist = [{"post_move_pct": -0.08}, {"post_move_pct": -0.06}]
    no_hist = analyze_token_unlock([_ev(40, 0.02)], now_ms=NOW)
    with_hist = analyze_token_unlock([_ev(40, 0.02)], history=hist, now_ms=NOW)
    assert with_hist.risk_score > no_hist.risk_score
    assert with_hist.alpha_bias < no_hist.alpha_bias


def test_backtest_empty() -> None:
    s = backtest_unlock_impact([])
    assert s.sample_size == 0 and s.avg_post_move_pct == 0.0


# ── Parser'lar ───────────────────────────────────────────────────────────────


def test_parse_token_unlocks_app() -> None:
    payload = {"unlocks": [
        {"timestamp": NOW, "percentOfCirculating": 5.0, "type": "cliff", "category": "team"},
    ]}
    out = parse_token_unlocks_app(json.dumps(payload))
    assert len(out) == 1 and out[0]["pct_of_circulating"] == 5.0
    sig = analyze_token_unlock(out, now_ms=NOW - _DAY)  # unlock 1 gün sonra
    assert sig is not None


def test_parse_dune() -> None:
    payload = {"result": {"rows": [
        {"unlock_date_ms": NOW, "unlock_pct": 0.06, "unlock_type": "linear", "category": "ecosystem"},
    ]}}
    out = parse_dune(json.dumps(payload))
    assert len(out) == 1 and out[0]["pct_of_circulating"] == 0.06


def test_parsers_garbage() -> None:
    assert parse_token_unlocks_app("not json") == []
    assert parse_dune({"no_result": 1}) == []


# ── Collector ────────────────────────────────────────────────────────────────


def test_collector_no_env(monkeypatch) -> None:
    monkeypatch.delenv("TOKEN_UNLOCKS_API_URL", raising=False)
    monkeypatch.delenv("DUNE_API_KEY", raising=False)
    col = UnlockCollector(http_get=lambda u, t: "{}")
    assert col.fetch_token_unlocks("BTC/USDT") == []
    assert col.fetch_dune("123") == []


def test_collector_token_unlocks_parses(monkeypatch) -> None:
    monkeypatch.setenv("TOKEN_UNLOCKS_API_URL", "https://example.com/api")
    payload = json.dumps({"unlocks": [{"timestamp": NOW, "percentOfCirculating": 3.0}]})
    col = UnlockCollector(http_get=lambda u, t: payload)
    out = col.fetch_token_unlocks("ARB/USDT")
    assert len(out) == 1


# ── Köprü (analyze_unlock_data) ──────────────────────────────────────────────


def test_analyze_unlock_data_block() -> None:
    data = {"token_unlock": {"schedule": [_ev(3, 0.06)], "now_ms": NOW, "whale_exchange_inflow_usd": 6e6}}
    sig = analyze_unlock_data(data)
    assert sig is not None and sig.urgent is True


def test_analyze_unlock_data_flat_schedule() -> None:
    data = {"unlock_schedule": [_ev(3, 0.06)], "now_ms": NOW}
    sig = analyze_unlock_data(data)
    assert sig is not None and sig.high_sell_pressure is True


def test_analyze_unlock_data_empty() -> None:
    assert analyze_unlock_data({}) is None
    assert analyze_unlock_data("nope") is None


# ── Faz 23 (news_event_intelligence) entegrasyonu ────────────────────────────


def test_faz23_unlock_block_and_block_perm() -> None:
    news = {
        "headline": "Project X large token unlock scheduled",
        "token_unlock": {"schedule": [_ev(3, 0.06)], "now_ms": NOW},
    }
    r = analyze_news_event("X/USDT", news, {}, attach_to_analysis=False)
    assert "unlock_tracker" in r["news"]
    assert r["news"]["unlock_tracker"]["high_sell_pressure"] is True
    assert r["trade_permission"] == "BLOCK"


def test_faz23_unlock_urgent_halts() -> None:
    news = {
        "headline": "token unlock soon",
        "token_unlock": {"schedule": [_ev(4, 0.06)], "now_ms": NOW, "whale_exchange_inflow_usd": 7e6},
    }
    r = analyze_news_event("X/USDT", news, {}, attach_to_analysis=False)
    assert r["trade_permission"] == "HALT"


def test_faz23_backward_compat_no_unlock() -> None:
    news = {"headline": "Bitcoin ETF sees record inflows", "sentiment_score": 0.6}
    r = analyze_news_event("BTC/USDT", news, {}, attach_to_analysis=False)
    assert "unlock_tracker" not in r["news"]


# ── Faz 27 (alternative_data_engine) entegrasyonu ────────────────────────────


def test_faz27_unlock_block_attached() -> None:
    alt = {"token_unlock": {"schedule": [_ev(3, 0.06)], "now_ms": NOW}}
    out = analyze_alternative_data("ARB/USDT", alt, {"signal": "BUY"})
    assert "unlock" in out["alternative_data"]
    assert out["alternative_data"]["unlock"]["high_sell_pressure"] is True
    assert out["risk_score"] >= 0.5
    assert out["trade_permission"] == "BLOCK"


def test_faz27_unlock_lowers_alpha() -> None:
    base = analyze_alternative_data("ARB/USDT", {"adoption": {"active_users": 1e6}}, {"signal": "BUY"})
    unlocked = analyze_alternative_data(
        "ARB/USDT",
        {"adoption": {"active_users": 1e6}, "token_unlock": {"schedule": [_ev(2, 0.07)], "now_ms": NOW}},
        {"signal": "BUY"},
    )
    assert unlocked["alpha_score"] <= base["alpha_score"]
    assert unlocked["risk_score"] >= base["risk_score"]


def test_faz27_backward_compat_no_unlock() -> None:
    out = analyze_alternative_data("BTC/USDT", {"developer": {"commits_30d": 50}}, {"signal": "BUY"})
    assert "unlock" not in out["alternative_data"]
