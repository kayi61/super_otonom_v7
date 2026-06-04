"""PROMPT-6.2 — Stablecoin Dominance & Flow + macro (Faz 6.1) entegrasyonu."""

from __future__ import annotations

import json

import pytest
from super_otonom.signals.macro_event_intelligence import analyze_macro_data
from super_otonom.signals.stablecoin_intelligence import (
    BEARISH,
    BULLISH,
    RISK_OFF,
    StablecoinCollector,
    analyze_depeg,
    analyze_dominance,
    analyze_market_cap,
    analyze_mint_burn,
    analyze_stablecoin,
    analyze_stablecoin_data,
    parse_coingecko_stablecoins,
)

# ── 1) Market cap ────────────────────────────────────────────────────────────


def test_mcap_growth_bullish() -> None:
    bias, reasons = analyze_market_cap(mcap_change_pct=0.05)
    assert bias > 0 and any("yeni para" in r for r in reasons)


def test_mcap_drop_bearish() -> None:
    bias, _ = analyze_market_cap(total_mcap=95, total_mcap_prev=100)
    assert bias < 0


# ── 2) Dominance ─────────────────────────────────────────────────────────────


def test_dominance_up_bearish() -> None:
    bias, reasons = analyze_dominance(dominance_change_pct=0.02)
    assert bias < 0 and any("cash'e dönüyor" in r for r in reasons)


def test_dominance_down_bullish() -> None:
    bias, reasons = analyze_dominance(dominance_change_pct=-0.02)
    assert bias > 0 and any("crypto'ya geçiş" in r for r in reasons)


# ── 3) Mint / Burn ───────────────────────────────────────────────────────────


def test_usdt_big_mint() -> None:
    mb = analyze_mint_burn(usdt_mint_usd=300_000_000)
    assert mb.big_mint is True and mb.bias > 0


def test_usdt_big_burn() -> None:
    mb = analyze_mint_burn(usdt_burn_usd=400_000_000)
    assert mb.big_burn is True and mb.bias < 0


def test_usdc_institutional() -> None:
    mb = analyze_mint_burn(usdc_mint_usd=150_000_000)
    assert mb.institutional_inflow is True and mb.bias > 0


def test_small_mint_not_big() -> None:
    mb = analyze_mint_burn(usdt_mint_usd=50_000_000)
    assert mb.big_mint is False


# ── 4) Depeg ─────────────────────────────────────────────────────────────────


def test_depeg_alarm_from_price() -> None:
    dp = analyze_depeg(usdt_price=0.99)  # %1 sapma > %0.5
    assert dp.alarm is True and dp.risk >= 0.6


def test_depeg_no_alarm() -> None:
    dp = analyze_depeg(usdt_price=0.999)  # %0.1 < %0.5
    assert dp.alarm is False


def test_depeg_swap_spike() -> None:
    dp = analyze_depeg(swap_volume_spike=True)
    assert dp.swap_volume_spike is True and dp.risk >= 0.5


# ── Birleşik sinyal ──────────────────────────────────────────────────────────


def test_stablecoin_bullish_mint() -> None:
    sig = analyze_stablecoin(mcap_change_pct=0.04, usdt_mint_usd=300_000_000)
    assert sig is not None
    assert sig.environment == BULLISH
    assert sig.stablecoin_mint is True


def test_stablecoin_bearish_dominance() -> None:
    sig = analyze_stablecoin(dominance_change_pct=0.03, mcap_change_pct=-0.02)
    assert sig.environment == BEARISH
    assert sig.bias < 0


def test_stablecoin_depeg_risk_off() -> None:
    sig = analyze_stablecoin(usdt_price=0.97, swap_volume_spike=True)
    assert sig.environment == RISK_OFF
    assert sig.depeg_alarm is True
    assert sig.risk_score >= 0.6


def test_stablecoin_empty_none() -> None:
    assert analyze_stablecoin() is None


def test_stablecoin_data_bridge() -> None:
    sig = analyze_stablecoin_data({"stablecoin": {"mcap_change_pct": 0.05, "usdc_mint_usd": 2e8}})
    assert sig is not None and sig.environment == BULLISH


def test_stablecoin_data_flat() -> None:
    sig = analyze_stablecoin_data({"usdt_price": 0.985})
    assert sig is not None and sig.depeg_alarm is True


def test_stablecoin_data_empty_none() -> None:
    assert analyze_stablecoin_data({}) is None
    assert analyze_stablecoin_data("nope") is None


# ── Parser + Collector ───────────────────────────────────────────────────────


def test_parse_coingecko() -> None:
    payload = [{"market_cap": 1.1e11}, {"market_cap": 3.2e10}, {"market_cap": 5e9}]
    out = parse_coingecko_stablecoins(json.dumps(payload))
    assert out["total_mcap"] == pytest.approx(1.47e11)


def test_collector_total_mcap() -> None:
    payload = json.dumps([{"market_cap": 1e11}])
    col = StablecoinCollector(http_get=lambda u, t: payload)
    assert col.fetch_total_mcap() == pytest.approx(1e11)


def test_collector_none_graceful() -> None:
    col = StablecoinCollector(http_get=lambda u, t: None)
    assert col.fetch_total_mcap() is None


# ── macro_event_intelligence (Faz 6.1) entegrasyonu ──────────────────────────


def test_macro_stablecoin_mint_exposed() -> None:
    """Büyük USDT mint → macro_signal.stablecoin_mint (10.1 STRONG_BUY beslemesi)."""
    sig = analyze_macro_data({"stablecoin": {"usdt_mint_usd": 3e8, "mcap_change_pct": 0.04}})
    assert sig is not None
    assert sig.stablecoin_mint is True
    assert sig.to_dict()["stablecoin_mint"] is True


def test_macro_stablecoin_folds_bias() -> None:
    """Stablecoin bias makro bias'ı etkiler (dominance ↓ → bullish katkı)."""
    base = analyze_macro_data({"fed_stance": "neutral", "vix": 18})
    withsc = analyze_macro_data({"fed_stance": "neutral", "vix": 18, "dominance_change_pct": -0.03,
                                 "mcap_change_pct": 0.05})
    assert withsc.bias >= base.bias


def test_macro_stablecoin_only_activates() -> None:
    sig = analyze_macro_data({"mcap_change_pct": 0.05})
    assert sig is not None
    assert "stablecoin" in sig.to_dict()


def test_macro_backward_compat_no_stablecoin() -> None:
    sig = analyze_macro_data({"fed_stance": "dovish", "dxy_trend": "down", "m2_trend": "up"})
    assert sig is not None
    assert sig.stablecoin_mint is False
    assert sig.environment == BULLISH  # eski 6.1 davranışı korunur
