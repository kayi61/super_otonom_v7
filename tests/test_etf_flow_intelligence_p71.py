"""PROMPT-7.1 — ETF Flow Tracker + Faz 17 entegrasyonu testleri (ağsız)."""

from __future__ import annotations

import json

import pytest
from super_otonom.signals.etf_flow_intelligence import (
    DEMAND_STRONG,
    NEUTRAL,
    ROTATION,
    SELLING_PRESSURE,
    VOLUME_SPIKE,
    EtfFlow,
    EtfFlowTracker,
    classify_asset,
    compute_etf_net_flow_usd,
    detect_rotation,
    inflow_streak,
    parse_farside,
    parse_sosovalue,
    run_etf_flow_phase,
)

# ── classify_asset ────────────────────────────────────────────────────────────


def test_classify_asset() -> None:
    assert classify_asset("GBTC") == "BTC"
    assert classify_asset("ibit") == "BTC"
    assert classify_asset("ETHA") == "ETH"
    assert classify_asset("ETHE") == "ETH"
    assert classify_asset("UNKNOWN") is None


# ── parse_sosovalue ───────────────────────────────────────────────────────────


def test_parse_sosovalue() -> None:
    payload = {"data": [
        {"ticker": "IBIT", "net_flow_usd": 300e6, "aum_usd": 20e9, "volume_usd": 1e9},
        {"ticker": "GBTC", "net_flow_usd": -100e6, "aum_usd": 15e9},
    ]}
    flows = parse_sosovalue(payload)
    assert len(flows) == 2
    assert flows[0].ticker == "IBIT" and flows[0].asset == "BTC"
    assert flows[0].net_flow_usd == pytest.approx(300e6)


def test_parse_sosovalue_skips_unknown_ticker() -> None:
    payload = {"data": [{"ticker": "SPY", "net_flow_usd": 100e6}]}  # ETF değil
    assert parse_sosovalue(payload) == []


def test_parse_sosovalue_explicit_asset() -> None:
    payload = {"data": [{"ticker": "NEWETF", "asset": "BTC", "net_flow_usd": 50e6}]}
    flows = parse_sosovalue(payload)
    assert len(flows) == 1 and flows[0].asset == "BTC"


def test_parse_sosovalue_invalid() -> None:
    assert parse_sosovalue("x") == []
    assert parse_sosovalue({"data": None}) == []
    assert parse_sosovalue({"data": [{"ticker": "IBIT"}]}) == []  # net_flow yok


def test_parse_sosovalue_string() -> None:
    payload = json.dumps({"data": [{"ticker": "FBTC", "net_flow_usd": 10e6}]})
    assert len(parse_sosovalue(payload)) == 1


# ── parse_farside ─────────────────────────────────────────────────────────────


def test_parse_farside_million_unit() -> None:
    payload = {"asset": "BTC", "flow_unit": "M", "rows": [{"ticker": "IBIT", "flow": 300}]}
    flows = parse_farside(payload)
    assert flows[0].net_flow_usd == pytest.approx(300e6)  # 300M


def test_parse_farside_list() -> None:
    flows = parse_farside([{"ticker": "ETHA", "flow": 5e6}])
    assert flows[0].asset == "ETH"


def test_parse_farside_invalid() -> None:
    assert parse_farside("x") == []
    assert parse_farside({"rows": "bad"}) == []


# ── Helpers ───────────────────────────────────────────────────────────────────


def test_compute_net_flow() -> None:
    flows = [EtfFlow("IBIT", "BTC", 300e6), EtfFlow("GBTC", "BTC", -100e6)]
    assert compute_etf_net_flow_usd(flows) == pytest.approx(200e6)


def test_inflow_streak() -> None:
    assert inflow_streak([1, 1, 1, 1, 1]) == 5
    assert inflow_streak([1, 1, -1]) == 0       # son gün outflow
    assert inflow_streak([-1, 1, 1]) == 2
    assert inflow_streak([]) == 0


def test_detect_rotation() -> None:
    flows = [EtfFlow("GBTC", "BTC", -100e6), EtfFlow("IBIT", "BTC", 300e6)]
    assert detect_rotation(flows) is True


def test_detect_no_rotation_all_inflow() -> None:
    flows = [EtfFlow("GBTC", "BTC", 50e6), EtfFlow("IBIT", "BTC", 300e6)]
    assert detect_rotation(flows) is False


# ── analyze: 4 sinyal kuralı ─────────────────────────────────────────────────


def test_analyze_strong_demand() -> None:
    trk = EtfFlowTracker(inflow_streak_days=5)
    flows = [EtfFlow("IBIT", "BTC", 300e6)]
    sig = trk.analyze(flows, asset="BTC", daily_net_flow_history=[1, 1, 1, 1, 1, 1])
    assert sig.signal == DEMAND_STRONG
    assert sig.inflow_streak_days == 6
    assert sig.alpha_bias > 0


def test_analyze_selling_pressure() -> None:
    trk = EtfFlowTracker()
    flows = [EtfFlow("IBIT", "BTC", -50e6), EtfFlow("FBTC", "BTC", -30e6)]
    sig = trk.analyze(flows, asset="BTC")
    assert sig.signal == SELLING_PRESSURE
    assert sig.alpha_bias < 0


def test_analyze_rotation() -> None:
    trk = EtfFlowTracker()
    flows = [EtfFlow("GBTC", "BTC", -100e6), EtfFlow("IBIT", "BTC", 300e6)]
    sig = trk.analyze(flows, asset="BTC")
    assert sig.signal == ROTATION
    assert sig.alpha_bias == 0.0


def test_analyze_volume_spike() -> None:
    trk = EtfFlowTracker(volume_spike_mult=2.0)
    flows = [EtfFlow("IBIT", "BTC", 10e6, volume_usd=500e6)]
    sig = trk.analyze(flows, asset="BTC", avg_volume_usd=100e6)  # 500M >= 100M*2
    assert sig.signal == VOLUME_SPIKE
    assert any("volume spike" in r for r in sig.reasons)


def test_analyze_grayscale_discount() -> None:
    trk = EtfFlowTracker()
    flows = [EtfFlow("IBIT", "BTC", 50e6)]
    sig = trk.analyze(flows, asset="BTC", grayscale_premium_pct=-0.10)
    assert any("discount" in r.lower() for r in sig.reasons)


def test_analyze_neutral() -> None:
    trk = EtfFlowTracker()
    sig = trk.analyze([EtfFlow("IBIT", "BTC", 0.0)], asset="BTC")
    assert sig.signal == NEUTRAL


def test_analyze_eth_filter() -> None:
    trk = EtfFlowTracker()
    flows = [EtfFlow("IBIT", "BTC", 300e6), EtfFlow("ETHA", "ETH", 50e6)]
    sig = trk.analyze(flows, asset="ETH")
    assert sig.total_net_flow_usd == pytest.approx(50e6)  # sadece ETH
    assert "ETHA" in sig.per_etf and "IBIT" not in sig.per_etf


# ── Fetch / collect ───────────────────────────────────────────────────────────


def test_collect_no_url_empty(monkeypatch) -> None:
    monkeypatch.delenv("SOSOVALUE_API_URL", raising=False)
    monkeypatch.delenv("FARSIDE_API_URL", raising=False)
    trk = EtfFlowTracker(http_get=lambda u, t: "should-not-call")
    assert trk.collect() == []


def test_collect_with_injected(monkeypatch) -> None:
    monkeypatch.setenv("SOSOVALUE_API_URL", "http://x")
    payload = {"data": [{"ticker": "IBIT", "net_flow_usd": 100e6}]}
    trk = EtfFlowTracker(http_get=lambda u, t: json.dumps(payload))
    assert len(trk.collect()) >= 1


# ── should_update / update / Faz 17 ──────────────────────────────────────────


def test_should_update() -> None:
    trk = EtfFlowTracker(update_interval_sec=3600)
    assert trk.should_update(now_ms=10**13) is True
    trk._last_update_ms = 10**13
    assert trk.should_update(now_ms=10**13 + 1_000_000) is False  # <1h
    assert trk.should_update(now_ms=10**13 + 3_700_000) is True


def test_update_faz17_data(monkeypatch) -> None:
    monkeypatch.setenv("SOSOVALUE_API_URL", "http://x")
    payload = {"data": [{"ticker": "IBIT", "net_flow_usd": 300e6}]}
    trk = EtfFlowTracker(http_get=lambda u, t: json.dumps(payload))
    data = trk.update(asset="BTC", daily_net_flow_history=[1, 1, 1, 1, 1, 1])
    assert data["etf_net_flow_usd"] == pytest.approx(300e6)
    assert data["etf_signal"] == DEMAND_STRONG


def test_run_etf_flow_phase_faz17(monkeypatch) -> None:
    monkeypatch.setenv("SOSOVALUE_API_URL", "http://x")
    payload = {"data": [{"ticker": "IBIT", "net_flow_usd": 300e6}]}
    trk = EtfFlowTracker(http_get=lambda u, t: json.dumps(payload))
    out = run_etf_flow_phase("BTCUSDT", trk, {}, daily_net_flow_history=[1, 1, 1, 1, 1])
    assert {"alpha_score", "risk_score", "trade_permission"}.issubset(out.keys())
    assert out["trade_permission"] in ("ALLOW", "BLOCK", "HALT")
    assert out["phase"] == "17"


def test_run_phase_empty(monkeypatch) -> None:
    monkeypatch.delenv("SOSOVALUE_API_URL", raising=False)
    monkeypatch.delenv("FARSIDE_API_URL", raising=False)
    trk = EtfFlowTracker(http_get=lambda u, t: None)
    out = run_etf_flow_phase("BTCUSDT", trk, {})
    assert out["trade_permission"] in ("ALLOW", "BLOCK", "HALT")


# ── Dispatch ─────────────────────────────────────────────────────────────────


class _FakeAlertManager:
    def __init__(self) -> None:
        self.events = []

    def system(self, event: str, detail: str = "", level: str = "INFO") -> None:
        self.events.append((event, detail, level))


def test_dispatch_selling(monkeypatch) -> None:
    monkeypatch.setenv("SOSOVALUE_API_URL", "http://x")
    payload = {"data": [{"ticker": "IBIT", "net_flow_usd": -50e6}]}
    am = _FakeAlertManager()
    trk = EtfFlowTracker(http_get=lambda u, t: json.dumps(payload), alert_manager=am)
    trk.update(asset="BTC")
    assert any(e[0] == "ETF_INSTITUTIONAL_SELLING" for e in am.events)


def test_dispatch_none_and_bad() -> None:
    from super_otonom.signals.etf_flow_intelligence import EtfFlowSignal
    sig = EtfFlowSignal("BTC", -50e6, 0, {}, 0, SELLING_PRESSURE, None, None, -0.5, ["x"])
    EtfFlowTracker()._dispatch(sig)  # None alert_manager → no raise
    EtfFlowTracker(alert_manager=object())._dispatch(sig)  # no raise


def test_env_config(monkeypatch) -> None:
    monkeypatch.setenv("ETF_INFLOW_STREAK_DAYS", "7")
    monkeypatch.setenv("ETF_VOLUME_SPIKE_MULT", "3")
    trk = EtfFlowTracker()
    assert trk.inflow_streak_days == 7
    assert trk.volume_spike_mult == 3.0
