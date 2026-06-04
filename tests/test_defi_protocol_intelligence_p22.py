"""PROMPT-2.2 — DeFi Protocol Intelligence (standalone modül testleri)."""

from __future__ import annotations

import json

import pytest
from super_otonom.signals.defi_protocol_intelligence import (
    DefiCollector,
    analyze_bridge,
    analyze_defi,
    analyze_defi_data,
    analyze_dex,
    analyze_lending,
    analyze_tvl,
    parse_defillama_chains,
    parse_defillama_protocol,
)

# ── 1) TVL ───────────────────────────────────────────────────────────────────


def test_tvl_growth_bias_positive() -> None:
    t = analyze_tvl(tvl_change_pct=0.2)
    assert t.bias > 0 and t.exploit_alert is False


def test_tvl_sudden_drop_exploit_alert() -> None:
    t = analyze_tvl(tvl_change_pct=-0.30)
    assert t.exploit_alert is True
    assert t.bias < 0 and t.risk >= 0.7


def test_tvl_from_absolute() -> None:
    t = analyze_tvl(protocol_tvl=80, protocol_tvl_prev=100)
    assert t.change_pct == pytest.approx(-0.2)
    assert t.exploit_alert is True


def test_tvl_fdv_overvalued() -> None:
    t = analyze_tvl(tvl_usd=5e6, fdv_usd=1e9)  # ratio 0.005 < 0.10
    assert t.overvalued is True


def test_tvl_dominant_chain() -> None:
    t = analyze_tvl(chain_tvl_flows={"ethereum": -5e8, "solana": 4e8, "arbitrum": 1e8})
    assert t.dominant_chain == "solana"


# ── 2) DEX ───────────────────────────────────────────────────────────────────


def test_dex_whale_swaps_counted() -> None:
    d = analyze_dex(large_swaps=[
        {"amount_usd": 2_000_000, "side": "buy"},
        {"amount_usd": 500_000, "side": "sell"},  # < $1M → sayılmaz
        {"amount_usd": 1_500_000, "side": "buy"},
    ])
    assert d.large_swap_count == 2
    assert d.whale_activity > 0
    assert d.bias > 0  # net alış


def test_dex_new_pool_signal() -> None:
    d = analyze_dex(new_pools=3)
    assert d.new_pool_signal is True


def test_dex_liquidity_drain_risk() -> None:
    d = analyze_dex(pool_depth_change_pct=-0.4)
    assert d.risk >= 0.3


# ── 3) Lending ───────────────────────────────────────────────────────────────


def test_lending_rate_spike() -> None:
    le = analyze_lending(borrow_rate=0.15, borrow_rate_prev=0.08)  # +87%
    assert le.rate_spike is True
    assert le.volatility_expectation > 0


def test_lending_high_utilization() -> None:
    le = analyze_lending(utilization_rate=0.85)
    assert le.high_utilization is True


def test_lending_utilization_percent_form() -> None:
    le = analyze_lending(utilization_rate=88)  # 88 → 0.88
    assert le.high_utilization is True


def test_lending_cascade_risk() -> None:
    le = analyze_lending(liquidation_proximity=0.9)
    assert le.cascade_risk >= 0.6 and le.risk >= 0.6


def test_lending_stablecoin_stress() -> None:
    le = analyze_lending(stablecoin_borrow_rate_change=0.8)
    assert le.stablecoin_stress is True and le.volatility_expectation >= 0.6


# ── 4) Bridge ────────────────────────────────────────────────────────────────


def test_bridge_dominant_inflow() -> None:
    b = analyze_bridge(bridge_flows={"solana": 6e8, "ethereum": -2e8})
    assert b.dominant_inflow_chain == "solana"
    assert b.bias > 0


def test_bridge_exploit_risk() -> None:
    b = analyze_bridge(bridge_flows={"x": 1e8}, bridge_exploit_history=0.8)
    assert b.exploit_risk == pytest.approx(0.8)


# ── Birleşik sinyal ──────────────────────────────────────────────────────────


def test_analyze_defi_chain_rotation() -> None:
    sig = analyze_defi(
        tvl=analyze_tvl(chain_tvl_flows={"solana": 5e8, "ethereum": -5e8}, tvl_change_pct=0.1),
        bridge=analyze_bridge(bridge_flows={"solana": 4e8}),
    )
    assert sig is not None
    assert sig.chain_rotation == "solana"
    assert sig.alpha_bias > 0
    assert any("yoğunlaş" in r for r in sig.reasons)


def test_analyze_defi_exploit_alert_dominates() -> None:
    sig = analyze_defi(tvl=analyze_tvl(tvl_change_pct=-0.4))
    assert sig.exploit_alert is True
    assert sig.risk_score >= 0.85
    assert sig.alpha_bias < 0


def test_analyze_defi_cascade_risk() -> None:
    sig = analyze_defi(lending=analyze_lending(liquidation_proximity=0.9))
    assert sig.cascade_risk >= 0.6
    assert any("cascade" in r for r in sig.reasons)


def test_analyze_defi_whale_reason() -> None:
    sig = analyze_defi(dex=analyze_dex(large_swaps=[{"amount_usd": 3e6, "side": "buy"}]))
    assert any("whale swap" in r for r in sig.reasons)


def test_analyze_defi_empty_none() -> None:
    assert analyze_defi() is None


# ── Köprü (analyze_defi_data) ────────────────────────────────────────────────


def test_defi_data_nested() -> None:
    data = {"defi": {
        "tvl": {"tvl_change_pct": 0.15, "chain_tvl_flows": {"solana": 5e8}},
        "lending": {"utilization_rate": 0.9},
        "bridge": {"bridge_flows": {"solana": 4e8}},
    }}
    sig = analyze_defi_data(data)
    assert sig is not None
    assert sig.chain_rotation == "solana"
    assert sig.lending.high_utilization is True


def test_defi_data_flat() -> None:
    sig = analyze_defi_data({"tvl_change_pct": -0.3, "borrow_rate": 0.2, "borrow_rate_prev": 0.1})
    assert sig is not None and sig.exploit_alert is True


def test_defi_data_empty_none() -> None:
    assert analyze_defi_data({}) is None
    assert analyze_defi_data("nope") is None


# ── Parser + Collector ───────────────────────────────────────────────────────


def test_parse_defillama_protocol() -> None:
    payload = {"currentChainTvls": {"Ethereum": 1e9, "Arbitrum": 4e8}}
    out = parse_defillama_protocol(json.dumps(payload))
    assert out["tvl"] == pytest.approx(1.4e9)
    assert out["chain_tvls"]["Ethereum"] == 1e9


def test_parse_defillama_chains() -> None:
    payload = [{"name": "Ethereum", "tvl": 5e10}, {"name": "Solana", "tvl": 8e9}]
    out = parse_defillama_chains(json.dumps(payload))
    assert out["Ethereum"] == 5e10 and out["Solana"] == 8e9


def test_parsers_garbage() -> None:
    assert parse_defillama_protocol("not json") == {}
    assert parse_defillama_chains({"not": "list"}) == {}


def test_collector_protocol() -> None:
    payload = json.dumps({"currentChainTvls": {"Ethereum": 2e9}})
    col = DefiCollector(http_get=lambda u, t: payload)
    out = col.fetch_protocol("aave")
    assert out["tvl"] == pytest.approx(2e9)


def test_collector_none_graceful() -> None:
    col = DefiCollector(http_get=lambda u, t: None)
    assert col.fetch_protocol("x") == {}
    assert col.fetch_chains() == {}
