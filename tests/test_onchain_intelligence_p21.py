"""PROMPT-2.1 — On-Chain Intelligence + alternative_data_engine (Faz 27)."""

from __future__ import annotations

import pytest
from super_otonom.signals.alternative_data_engine import analyze_alternative_data
from super_otonom.signals.onchain_intelligence import (
    ACCUMULATION,
    DISTRIBUTION,
    MVRV_FAIR,
    MVRV_OVER,
    MVRV_UNDER,
    OnchainCollector,
    analyze_holders,
    analyze_miner_metrics,
    analyze_mvrv,
    analyze_network_activity,
    analyze_onchain,
    classify_mvrv,
    parse_blockchain_stats,
    parse_coinmetrics,
)

# ── MVRV ─────────────────────────────────────────────────────────────────────


def test_classify_mvrv() -> None:
    assert classify_mvrv(4.0) == MVRV_OVER
    assert classify_mvrv(0.8) == MVRV_UNDER
    assert classify_mvrv(2.0) == MVRV_FAIR


def test_analyze_mvrv_overvalued() -> None:
    mv = analyze_mvrv(mvrv=4.0, market_price=60000, realized_price=40000)
    assert mv.valuation == MVRV_OVER
    assert mv.bias < 0  # satış riski
    assert mv.price_premium_pct == pytest.approx(0.5)


def test_analyze_mvrv_undervalued() -> None:
    mv = analyze_mvrv(mvrv=0.8)
    assert mv.valuation == MVRV_UNDER
    assert mv.bias > 0  # birikim fırsatı


def test_analyze_mvrv_computed_from_prices() -> None:
    mv = analyze_mvrv(market_price=30000, realized_price=40000)
    assert mv.mvrv == pytest.approx(0.75)
    assert mv.valuation == MVRV_UNDER


def test_analyze_mvrv_none() -> None:
    mv = analyze_mvrv()
    assert mv.mvrv is None and mv.valuation == MVRV_FAIR and mv.bias == 0.0


# ── Network activity ─────────────────────────────────────────────────────────


def test_network_activity() -> None:
    net = analyze_network_activity(
        active_addresses=1e6, tx_count=8e5, tx_volume_usd=4e9, new_address_rate=3e5
    )
    assert 0.0 < net.activity_score <= 1.0


def test_network_congestion() -> None:
    high = analyze_network_activity(active_addresses=1e6, avg_tx_fee_usd=30)
    low = analyze_network_activity(active_addresses=1e6, avg_tx_fee_usd=0.5)
    assert high.congestion > low.congestion


# ── Holders ──────────────────────────────────────────────────────────────────


def test_holders_accumulation() -> None:
    h = analyze_holders(top10_pct=0.3, holder_count_change_pct=0.03, accumulation_trend_30d=0.05)
    assert h.trend == ACCUMULATION


def test_holders_distribution() -> None:
    h = analyze_holders(holder_count_change_pct=-0.05, accumulation_trend_30d=-0.08)
    assert h.trend == DISTRIBUTION


def test_holders_concentration_risk() -> None:
    high = analyze_holders(top10_pct=0.6)
    low = analyze_holders(top10_pct=0.15)
    assert high.concentration_risk > low.concentration_risk


# ── Miner ────────────────────────────────────────────────────────────────────


def test_miner_sell_pressure() -> None:
    m = analyze_miner_metrics(miner_outflow_usd=100e6)
    assert m.miner_sell_pressure > 0.5


def test_miner_security_from_hashrate() -> None:
    up = analyze_miner_metrics(hash_rate_change_pct=0.1)
    down = analyze_miner_metrics(hash_rate_change_pct=-0.1)
    assert up.security_score > down.security_score


def test_miner_staking() -> None:
    m = analyze_miner_metrics(staking_ratio_change=0.05)
    assert m.security_score > 0.5


# ── Parsers ──────────────────────────────────────────────────────────────────


def test_parse_blockchain_stats() -> None:
    payload = {"n_tx": 800000, "estimated_transaction_volume_usd": 4e9,
               "hash_rate": 5e8, "market_price_usd": 60000}
    d = parse_blockchain_stats(payload)
    assert d["tx_count"] == 800000 and d["market_price"] == 60000


def test_parse_blockchain_invalid() -> None:
    assert parse_blockchain_stats("x") == {}
    assert parse_blockchain_stats({}) == {}


def test_parse_coinmetrics() -> None:
    payload = {"data": [
        {"AdrActCnt": 500000, "TxCnt": 700000, "CapMVRVCur": 2.3, "PriceUSD": 55000},
        {"AdrActCnt": 600000, "TxCnt": 800000, "CapMVRVCur": 2.5, "PriceUSD": 60000},
    ]}
    d = parse_coinmetrics(payload)
    assert d["active_addresses"] == 600000  # son satır
    assert d["mvrv"] == 2.5


def test_parse_coinmetrics_invalid() -> None:
    assert parse_coinmetrics("x") == {}
    assert parse_coinmetrics({"data": []}) == {}


# ── Combined ─────────────────────────────────────────────────────────────────


def test_analyze_onchain_combined() -> None:
    sig = analyze_onchain(
        network=analyze_network_activity(active_addresses=1e6, tx_count=8e5),
        holders=analyze_holders(holder_count_change_pct=0.03, accumulation_trend_30d=0.05),
        miner=analyze_miner_metrics(hash_rate_change_pct=0.05),
        mvrv=analyze_mvrv(mvrv=0.8),
    )
    assert sig.adoption_score > 0
    assert sig.alpha_bias > 0  # accumulation + undervalued MVRV
    d = sig.to_dict()
    assert d["mvrv_valuation"] == MVRV_UNDER
    assert d["holder_trend"] == ACCUMULATION


def test_analyze_onchain_overvalued_bearish() -> None:
    sig = analyze_onchain(mvrv=analyze_mvrv(mvrv=4.5))
    assert sig.alpha_bias < 0
    assert sig.risk_score > 0
    assert any("aşırı değerli" in r for r in sig.reasons)


def test_analyze_onchain_empty() -> None:
    sig = analyze_onchain()
    assert sig.alpha_bias == 0.0 and sig.adoption_score == 0.0


# ── Collector ────────────────────────────────────────────────────────────────


def test_collector_blockchain_stats() -> None:
    import json
    payload = {"n_tx": 700000, "market_price_usd": 50000}
    col = OnchainCollector(http_get=lambda u, t: json.dumps(payload))
    d = col.fetch_blockchain_stats()
    assert d["tx_count"] == 700000


def test_collector_none_graceful() -> None:
    col = OnchainCollector(http_get=lambda u, t: None)
    assert col.fetch_blockchain_stats() == {}


# ── alternative_data_engine (Faz 27) entegrasyonu ────────────────────────────


def test_faz27_onchain_fields() -> None:
    data = {"onchain": {
        "active_addresses": 1e6, "tx_count": 8e5, "avg_tx_fee_usd": 2,
        "top10_pct": 0.4, "holder_count_change_pct": 0.03, "accumulation_trend_30d": 0.05,
        "miner_outflow_usd": 10e6, "hash_rate_change_pct": 0.05,
        "mvrv": 0.85, "market_price": 30000, "realized_price": 35000,
    }}
    out = analyze_alternative_data("BTCUSDT", data, {"signal": "BUY"})
    oc = out["alternative_data"]["onchain"]
    assert oc["mvrv_valuation"] == MVRV_UNDER
    assert oc["holder_trend"] == ACCUMULATION
    assert "network_activity_score" in oc


def test_faz27_onchain_overvalued_raises_risk() -> None:
    data = {"onchain": {"mvrv": 4.5, "market_price": 70000, "realized_price": 40000}}
    out = analyze_alternative_data("BTCUSDT", data, {"signal": "BUY"})
    assert out["alternative_data"]["onchain"]["mvrv_valuation"] == MVRV_OVER
    assert out["risk_score"] > 0.3


def test_faz27_onchain_coexists_with_options() -> None:
    data = {
        "onchain": {"mvrv": 0.8},
        "options_flow": {"put_call_ratio": 1.5},
    }
    out = analyze_alternative_data("BTCUSDT", data, {"signal": "BUY"})
    assert "onchain" in out["alternative_data"]
    assert "options_flow_deep" in out["alternative_data"]


def test_faz27_backward_compat() -> None:
    out = analyze_alternative_data("BTCUSDT", {"developer": {"commits_30d": 50}}, {"signal": "BUY"})
    assert "onchain" not in out["alternative_data"]


def test_faz27_onchain_flat_keys() -> None:
    # onchain alt dict olmadan düz anahtarlar da çalışır
    out = analyze_alternative_data("BTCUSDT", {"mvrv": 0.8, "active_addresses": 1e6}, {"signal": "BUY"})
    assert "onchain" in out["alternative_data"]
