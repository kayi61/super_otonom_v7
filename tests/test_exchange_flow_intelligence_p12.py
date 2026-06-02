"""PROMPT-1.2 — Exchange Flow Intelligence + Faz 17 entegrasyonu testleri (ağsız)."""

from __future__ import annotations

import json

import pytest
from super_otonom.signals.exchange_flow_intelligence import (
    BEARISH,
    BULLISH,
    NEUTRAL,
    ExchangeFlow,
    ExchangeFlowIntelligence,
    ReservePoint,
    StablecoinEvent,
    net_exchange_flow_usd,
    parse_cryptoquant_flow,
    parse_glassnode_reserve,
    parse_stablecoin_mint,
    per_exchange_netflow,
    reserve_trend_7d,
    run_exchange_flow_phase,
    stablecoin_net_mint_usd,
)

_ZERO = "0x0000000000000000000000000000000000000000"
_USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
_DAY = 86_400_000


# ── parse_cryptoquant_flow ────────────────────────────────────────────────────


def test_parse_cryptoquant_nested() -> None:
    payload = {
        "result": {
            "data": [
                {"exchange": "Binance", "symbol": "BTC", "inflow_usd": 10e6, "outflow_usd": 4e6, "timestamp": 1700000000},
            ]
        }
    }
    flows = parse_cryptoquant_flow(payload)
    assert len(flows) == 1
    assert flows[0].exchange == "binance"
    assert flows[0].netflow_usd == pytest.approx(6e6)


def test_parse_cryptoquant_flat() -> None:
    payload = {"data": [{"exchange": "coinbase", "asset": "ETH", "inflow": 5e6, "outflow": 8e6}]}
    flows = parse_cryptoquant_flow(payload)
    assert len(flows) == 1
    assert flows[0].netflow_usd == pytest.approx(-3e6)


def test_parse_cryptoquant_invalid() -> None:
    assert parse_cryptoquant_flow("nope") == []
    assert parse_cryptoquant_flow(None) == []
    assert parse_cryptoquant_flow({"data": None}) == []
    assert parse_cryptoquant_flow({"data": [{"inflow": 0, "outflow": 0}]}) == []


def test_parse_cryptoquant_string() -> None:
    payload = json.dumps({"data": [{"exchange": "bybit", "symbol": "BTC", "inflow_usd": 1e6, "outflow_usd": 0}]})
    assert len(parse_cryptoquant_flow(payload)) == 1


# ── parse_glassnode_reserve ───────────────────────────────────────────────────


def test_parse_glassnode_reserve_sorted() -> None:
    payload = [{"t": 200, "v": 950}, {"t": 100, "v": 1000}]
    pts = parse_glassnode_reserve(payload, asset="btc")
    assert [p.ts_ms for p in pts] == sorted(p.ts_ms for p in pts)
    assert pts[0].asset == "BTC"


def test_parse_glassnode_invalid() -> None:
    assert parse_glassnode_reserve("x") == []
    assert parse_glassnode_reserve({"not": "list"}) == []
    assert parse_glassnode_reserve([{"v": 0}]) == []


# ── parse_stablecoin_mint ─────────────────────────────────────────────────────


def test_parse_mint_from_zero() -> None:
    payload = {
        "result": [
            {"from": _ZERO, "to": "0xabc", "value": str(600 * 10**6 * 10**6),
             "contractAddress": _USDT, "timeStamp": "1700000000"}
        ]
    }
    ev = parse_stablecoin_mint(payload)
    assert len(ev) == 1
    assert ev[0].kind == "mint" and ev[0].asset == "USDT"
    assert ev[0].amount_usd == pytest.approx(600e6)


def test_parse_burn_to_zero() -> None:
    payload = {
        "result": [
            {"from": "0xabc", "to": _ZERO, "value": str(100 * 10**6 * 10**6),
             "contractAddress": _USDT, "timeStamp": "1"}
        ]
    }
    ev = parse_stablecoin_mint(payload)
    assert ev[0].kind == "burn"


def test_parse_mint_skips_normal_transfer() -> None:
    payload = {"result": [{"from": "0xa", "to": "0xb", "value": "1000000", "contractAddress": _USDT}]}
    assert parse_stablecoin_mint(payload) == []


def test_parse_mint_unknown_contract_uses_symbol() -> None:
    payload = {
        "result": [
            {"from": _ZERO, "to": "0xabc", "value": str(10 * 10**18), "tokenDecimal": "18",
             "tokenSymbol": "dai", "contractAddress": "0xunknown"}
        ]
    }
    ev = parse_stablecoin_mint(payload, price_usd=1.0)
    assert ev[0].asset == "DAI" and ev[0].amount_usd == pytest.approx(10.0)


def test_parse_mint_invalid() -> None:
    assert parse_stablecoin_mint("x") == []
    assert parse_stablecoin_mint({"result": "bad"}) == []


# ── Sinyal yardımcıları ──────────────────────────────────────────────────────


def test_reserve_trend_decline() -> None:
    pts = [ReservePoint("BTC", 1000, ts_ms=0), ReservePoint("BTC", 900, ts_ms=7 * _DAY)]
    assert reserve_trend_7d(pts) == pytest.approx(-0.10)


def test_reserve_trend_insufficient() -> None:
    assert reserve_trend_7d([]) == 0.0
    assert reserve_trend_7d([ReservePoint("BTC", 1000, ts_ms=0)]) == 0.0


def test_net_and_per_exchange() -> None:
    flows = [
        ExchangeFlow("binance", "BTC", 10e6, 4e6),
        ExchangeFlow("coinbase", "ETH", 2e6, 7e6),
    ]
    assert net_exchange_flow_usd(flows) == pytest.approx(6e6 - 5e6)
    pe = per_exchange_netflow(flows)
    assert pe["binance"] == pytest.approx(6e6) and pe["coinbase"] == pytest.approx(-5e6)


def test_stablecoin_net_mint() -> None:
    ev = [StablecoinEvent("USDT", 500e6, "mint"), StablecoinEvent("USDC", 200e6, "burn")]
    assert stablecoin_net_mint_usd(ev) == pytest.approx(300e6)


# ── analyze: 4 sinyal kuralı ─────────────────────────────────────────────────


def test_analyze_bullish_reserve_and_mint() -> None:
    eng = ExchangeFlowIntelligence()
    flows = [ExchangeFlow("binance", "BTC", 10e6, 60e6)]  # net outflow
    reserves = {"BTC": [ReservePoint("BTC", 1000e6, ts_ms=0), ReservePoint("BTC", 950e6, ts_ms=7 * _DAY)]}
    stable = [StablecoinEvent("USDT", 600e6, "mint")]
    sig = eng.analyze(flows, reserves, stable)
    assert sig.direction == BULLISH
    assert sig.institutional_flow_usd > 0
    assert any("rezerv" in r for r in sig.reasons)
    assert any("mint" in r for r in sig.reasons)


def test_analyze_bearish_btc_inflow_stable_outflow() -> None:
    eng = ExchangeFlowIntelligence(btc_inflow_alert_usd=100e6)
    flows = [
        ExchangeFlow("binance", "BTC", 200e6, 10e6),   # +190M BTC inflow
        ExchangeFlow("binance", "USDT", 5e6, 50e6),    # -45M stable outflow
    ]
    sig = eng.analyze(flows, {}, [])
    assert sig.direction == BEARISH
    assert sig.institutional_flow_usd < 0
    assert any("satış" in r for r in sig.reasons)


def test_analyze_neutral() -> None:
    eng = ExchangeFlowIntelligence()
    flows = [ExchangeFlow("binance", "BTC", 1e6, 1e6)]  # net 0
    sig = eng.analyze(flows, {}, [])
    assert sig.direction == NEUTRAL


def test_analyze_stablecoin_inflow_bullish() -> None:
    eng = ExchangeFlowIntelligence(stable_inflow_alert_usd=100e6)
    flows = [ExchangeFlow("coinbase", "USDC", 150e6, 10e6)]  # +140M stable inflow
    sig = eng.analyze(flows, {}, [])
    assert any("alım hazırlığı" in r for r in sig.reasons)


def test_analyze_big_mint_alert() -> None:
    eng = ExchangeFlowIntelligence(stable_mint_alert_usd=500e6)
    sig = eng.analyze([], {}, [StablecoinEvent("USDT", 600e6, "mint")])
    assert sig.direction == BULLISH
    assert sig.stablecoin_net_mint_usd == pytest.approx(600e6)


def test_institutional_flow_formula() -> None:
    eng = ExchangeFlowIntelligence()
    flows = [ExchangeFlow("binance", "BTC", 0, 50e6)]  # net -50M
    stable = [StablecoinEvent("USDT", 600e6, "mint")]
    sig = eng.analyze(flows, {}, stable)
    # institutional = net_mint - net_flow = 600 - (-50) = 650
    assert sig.institutional_flow_usd == pytest.approx(650e6)


# ── Fetch (mock'lanabilir) ───────────────────────────────────────────────────


def test_fetch_no_api_key_empty(monkeypatch) -> None:
    monkeypatch.delenv("CRYPTOQUANT_API_KEY", raising=False)
    monkeypatch.delenv("CRYPTOQUANT_API_URL", raising=False)
    eng = ExchangeFlowIntelligence(http_get=lambda u, t: "should-not-call")
    assert eng._fetch_cryptoquant() == []


def test_fetch_with_injected_http(monkeypatch) -> None:
    monkeypatch.setenv("CRYPTOQUANT_API_KEY", "k")
    monkeypatch.setenv("CRYPTOQUANT_API_URL", "http://x")
    payload = {"data": [{"exchange": "binance", "symbol": "BTC", "inflow_usd": 1e6, "outflow_usd": 0}]}
    eng = ExchangeFlowIntelligence(http_get=lambda u, t: json.dumps(payload))
    assert len(eng._fetch_cryptoquant()) == 1


def test_fetch_http_none_graceful(monkeypatch) -> None:
    monkeypatch.setenv("CRYPTOQUANT_API_KEY", "k")
    monkeypatch.setenv("CRYPTOQUANT_API_URL", "http://x")
    eng = ExchangeFlowIntelligence(http_get=lambda u, t: None)
    assert eng._fetch_cryptoquant() == []


# ── Alert sistemi ─────────────────────────────────────────────────────────────


def test_alert_stable_mint() -> None:
    eng = ExchangeFlowIntelligence(stable_mint_alert_usd=500e6)
    sig = eng.analyze([], {}, [StablecoinEvent("USDT", 600e6, "mint")])
    alerts = eng.detect_alerts(sig, [StablecoinEvent("USDT", 600e6, "mint")])
    assert "STABLE_MINT" in alerts


def test_alert_exchange_inflow_surge() -> None:
    eng = ExchangeFlowIntelligence(btc_inflow_alert_usd=100e6)
    flows = [ExchangeFlow("binance", "BTC", 200e6, 10e6)]
    sig = eng.analyze(flows, {}, [])
    assert "EXCHANGE_INFLOW_SURGE" in eng.detect_alerts(sig, [])


def test_alert_sell_pressure() -> None:
    eng = ExchangeFlowIntelligence(btc_inflow_alert_usd=100e6)
    flows = [ExchangeFlow("binance", "BTC", 300e6, 10e6), ExchangeFlow("binance", "USDT", 0, 50e6)]
    sig = eng.analyze(flows, {}, [])
    assert "SELL_PRESSURE" in eng.detect_alerts(sig, [])


# ── Dispatch ─────────────────────────────────────────────────────────────────


class _FakeAlertManager:
    def __init__(self) -> None:
        self.events = []

    def system(self, event: str, detail: str = "", level: str = "INFO") -> None:
        self.events.append((event, detail, level))


def test_dispatch(monkeypatch) -> None:
    am = _FakeAlertManager()
    eng = ExchangeFlowIntelligence(alert_manager=am)
    eng._dispatch_alerts(["STABLE_MINT", "ACCUMULATION"])
    assert ("FLOW_STABLE_MINT", "STABLE_MINT", "WARNING") in am.events
    assert ("FLOW_ACCUMULATION", "ACCUMULATION", "INFO") in am.events


def test_dispatch_none_and_bad() -> None:
    ExchangeFlowIntelligence()._dispatch_alerts(["X"])  # alert_manager None → no raise
    ExchangeFlowIntelligence(alert_manager=object())._dispatch_alerts(["X"])  # no raise


# ── should_update / update / Faz 17 ──────────────────────────────────────────


def test_should_update() -> None:
    eng = ExchangeFlowIntelligence(update_interval_sec=300)
    assert eng.should_update(now_ms=10**13) is True
    eng._last_update_ms = 10**13
    assert eng.should_update(now_ms=10**13 + 100_000) is False
    assert eng.should_update(now_ms=10**13 + 301_000) is True


def test_update_produces_faz17_data(monkeypatch) -> None:
    monkeypatch.setenv("CRYPTOQUANT_API_KEY", "k")
    monkeypatch.setenv("CRYPTOQUANT_API_URL", "http://x")
    payload = {"data": [{"exchange": "binance", "symbol": "BTC", "inflow_usd": 0, "outflow_usd": 50e6}]}
    eng = ExchangeFlowIntelligence(http_get=lambda u, t: json.dumps(payload))
    data = eng.update()
    assert "institutional_flow_usd" in data
    assert "exchange_netflow_usd" in data
    assert data["exchange_netflow_usd"] == pytest.approx(-50e6)


def test_run_exchange_flow_phase_faz17(monkeypatch) -> None:
    monkeypatch.setenv("CRYPTOQUANT_API_KEY", "k")
    monkeypatch.setenv("CRYPTOQUANT_API_URL", "http://x")
    payload = {"data": [{"exchange": "binance", "symbol": "BTC", "inflow_usd": 0, "outflow_usd": 80e6}]}
    eng = ExchangeFlowIntelligence(http_get=lambda u, t: json.dumps(payload))
    out = run_exchange_flow_phase("BTCUSDT", eng, {})
    assert {"alpha_score", "risk_score", "trade_permission"}.issubset(out.keys())
    assert out["trade_permission"] in ("ALLOW", "BLOCK", "HALT")
    assert out["phase"] == "17"


def test_run_phase_empty_feed(monkeypatch) -> None:
    monkeypatch.delenv("CRYPTOQUANT_API_KEY", raising=False)
    eng = ExchangeFlowIntelligence(http_get=lambda u, t: None)
    out = run_exchange_flow_phase("BTCUSDT", eng, {})
    assert out["trade_permission"] in ("ALLOW", "BLOCK", "HALT")


def test_env_config(monkeypatch) -> None:
    monkeypatch.setenv("STABLE_MINT_ALERT_USD", "750000000")
    monkeypatch.setenv("BTC_INFLOW_ALERT_USD", "200000000")
    eng = ExchangeFlowIntelligence()
    assert eng.stable_mint_alert_usd == 750_000_000.0
    assert eng.btc_inflow_alert_usd == 200_000_000.0
