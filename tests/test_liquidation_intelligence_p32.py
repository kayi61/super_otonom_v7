"""PROMPT-3.2 — Liquidation Intelligence + derivatives_intel (Faz 18) entegrasyonu."""

from __future__ import annotations

import pytest
from super_otonom.derivatives_intel import analyze_derivatives_intel
from super_otonom.signals.liquidation_intelligence import (
    BACKWARDATION,
    CONTANGO,
    FLAT_STRUCTURE,
    OI_LONG_CAPITULATION,
    OI_NEUTRAL,
    OI_SHORT_BUILDUP,
    OI_SHORT_COVERING,
    OI_TREND_STRENGTHENING,
    analyze_basis,
    analyze_liquidation_map,
    analyze_long_short,
    analyze_market_structure,
    analyze_oi,
    classify_oi_regime,
    parse_liquidation_levels,
    velocities_from_history,
)

_HOUR = 3_600_000


# ── OI rejim ──────────────────────────────────────────────────────────────────


def test_oi_regimes() -> None:
    assert classify_oi_regime(0.02, 0.01) == OI_TREND_STRENGTHENING
    assert classify_oi_regime(0.02, -0.01) == OI_SHORT_BUILDUP
    assert classify_oi_regime(-0.02, -0.01) == OI_LONG_CAPITULATION
    assert classify_oi_regime(-0.02, 0.01) == OI_SHORT_COVERING


def test_oi_neutral_small_change() -> None:
    assert classify_oi_regime(0.001, 0.0001) == OI_NEUTRAL  # eşik altı


def test_analyze_oi_squeeze_and_props() -> None:
    oi = analyze_oi(0.02, -0.01, velocity_1h=0.01, velocity_24h=0.05)
    assert oi.regime == OI_SHORT_BUILDUP
    assert oi.squeeze_risk is True
    assert oi.is_bullish is False
    assert oi.velocity_1h == 0.01

    bull = analyze_oi(0.03, 0.02)
    assert bull.is_bullish is True and bull.squeeze_risk is False


# ── Liquidation map ──────────────────────────────────────────────────────────


def test_parse_liquidation_levels() -> None:
    levels = [
        {"price": 102, "notional_usd": 150e6, "side": "short"},
        {"price": 98, "size": 50e6, "side": "long"},
        {"bad": "row"},
    ]
    cl = parse_liquidation_levels(levels, 100.0)
    assert len(cl) == 2
    assert cl[0].distance_pct == pytest.approx(0.02)
    assert cl[0].side == "short"


def test_parse_liquidation_invalid() -> None:
    assert parse_liquidation_levels("x", 100.0) == []
    assert parse_liquidation_levels([], 100.0) == []
    assert parse_liquidation_levels([{"price": 100, "size": 1e6}], 0.0) == []


def test_liquidation_magnet_near_big_cluster() -> None:
    levels = [{"price": 101.5, "notional_usd": 150e6}]  # %1.5, > $100M
    lm = analyze_liquidation_map(levels, 100.0)
    assert lm.has_magnet is True
    assert lm.magnet_target == 101.5
    assert lm.magnet_distance_pct == pytest.approx(0.015)


def test_liquidation_no_magnet_when_small() -> None:
    levels = [{"price": 101.5, "notional_usd": 50e6}]  # < $100M
    lm = analyze_liquidation_map(levels, 100.0)
    assert lm.has_magnet is False


def test_liquidation_no_magnet_when_far() -> None:
    levels = [{"price": 110.0, "notional_usd": 150e6}]  # %10 > MAGNET_MAX_DIST
    lm = analyze_liquidation_map(levels, 100.0)
    assert lm.has_magnet is False


def test_liquidation_cascade_risk() -> None:
    levels = [{"price": 100.5, "notional_usd": 200e6}]  # %0.5 < %2 → cascade
    lm = analyze_liquidation_map(levels, 100.0)
    assert lm.cascade_risk == pytest.approx(1.0)  # 200M / (100M*2) = 1.0
    assert lm.total_near_usd == pytest.approx(200e6)


# ── Long/Short ───────────────────────────────────────────────────────────────


def test_long_short_crowded_long() -> None:
    # ratio 4.0 → long %80 > %70 → crowded long
    ls = analyze_long_short(global_ratio=4.0)
    assert ls.crowded_side == "long"
    assert ls.long_pct == pytest.approx(0.8)
    assert ls.is_crowded is True


def test_long_short_crowded_short() -> None:
    ls = analyze_long_short(global_ratio=0.25)  # long %20 → short %80
    assert ls.crowded_side == "short"
    assert ls.is_crowded is True


def test_long_short_not_crowded() -> None:
    ls = analyze_long_short(global_ratio=1.2)  # long %54.5
    assert ls.is_crowded is False


def test_long_short_divergence() -> None:
    # top trader long (3.0≥1), global short (0.8<1) → divergence
    ls = analyze_long_short(top_trader_ratio=3.0, global_ratio=0.8)
    assert ls.retail_whale_divergence is True
    ls2 = analyze_long_short(top_trader_ratio=2.0, global_ratio=1.5)
    assert ls2.divergence is False


def test_long_short_explicit_long_pct() -> None:
    ls = analyze_long_short(long_pct=0.75)
    assert ls.crowded_side == "long" and ls.is_crowded is True


def test_long_short_none() -> None:
    ls = analyze_long_short()
    assert ls.long_pct is None and ls.crowded_side == "none"


# ── Basis ────────────────────────────────────────────────────────────────────


def test_basis_contango() -> None:
    ba = analyze_basis(spot=100, perp_price=101)
    assert ba.structure == CONTANGO
    assert ba.basis_pct == pytest.approx(0.01)


def test_basis_backwardation() -> None:
    ba = analyze_basis(spot=100, perp_price=99)
    assert ba.structure == BACKWARDATION


def test_basis_flat() -> None:
    ba = analyze_basis(spot=100, perp_price=100.02)  # %0.02 < flat_eps
    assert ba.structure == FLAT_STRUCTURE


def test_basis_term_spread_and_opportunity() -> None:
    ba = analyze_basis(spot=100, perp_price=100.5, quarterly_price=102)
    assert ba.perp_basis_pct == pytest.approx(0.005)
    assert ba.quarterly_basis_pct == pytest.approx(0.02)
    assert ba.term_spread_pct == pytest.approx(0.015)
    assert ba.basis_trade_opportunity is True  # term spread 1.5% > 1%


def test_basis_no_spot() -> None:
    ba = analyze_basis(perp_price=101)
    assert ba.basis_pct is None and ba.structure == FLAT_STRUCTURE


# ── velocities ───────────────────────────────────────────────────────────────


def test_velocities_from_history() -> None:
    hist = [(0, 1000.0), (1 * _HOUR, 1010.0), (4 * _HOUR, 1040.0), (24 * _HOUR, 1200.0)]
    v = velocities_from_history(hist, now_ms=24 * _HOUR)
    assert v["24h"] == pytest.approx(0.20)   # (1200-1000)/1000
    assert v["1h"] is not None and v["4h"] is not None


def test_velocities_empty() -> None:
    v = velocities_from_history([])
    assert v == {"1h": None, "4h": None, "24h": None}


# ── analyze_market_structure ─────────────────────────────────────────────────


def test_market_structure_combined() -> None:
    ms = analyze_market_structure(
        oi=analyze_oi(0.02, -0.01),  # short_buildup
        liquidation=analyze_liquidation_map([{"price": 100.5, "notional_usd": 200e6}], 100.0),
        long_short=analyze_long_short(global_ratio=5.0),  # crowded long
        basis=analyze_basis(spot=100, perp_price=100.5, quarterly_price=102),
    )
    assert ms.risk_score >= 0.5
    assert ms.alpha_bias <= 0  # short_buildup + crowded long → bearish
    assert len(ms.reasons) >= 2
    d = ms.to_dict()
    assert d["oi_regime"] == OI_SHORT_BUILDUP
    assert d["liq_cascade_risk"] >= 0.5
    assert d["ls_is_crowded"] is True
    assert d["basis_structure"] == CONTANGO


def test_market_structure_empty() -> None:
    ms = analyze_market_structure()
    assert ms.alpha_bias == 0.0 and ms.risk_score == 0.0


# ── derivatives_intel (Faz 18) entegrasyonu ──────────────────────────────────


def test_faz18_market_structure_fields() -> None:
    data = {
        "open_interest": 1_050_000, "open_interest_prev": 1_000_000,  # +5%
        "price_change_pct": -0.02,
        "liquidation_levels": [{"price": 101.5, "notional_usd": 150e6, "side": "short"}],
        "spot_price": 100.0, "perp_price": 100.5, "quarterly_price": 102.0,
        "top_trader_ls_ratio": 3.0, "global_ls_ratio": 0.8,
    }
    out = analyze_derivatives_intel("BTCUSDT", data, {"signal": "BUY"})
    ms = out["derivatives"]["market_structure"]
    assert ms["oi_regime"] == OI_SHORT_BUILDUP
    assert ms["oi_squeeze_risk"] is True
    assert ms["liq_magnet_target"] == 101.5
    assert ms["ls_divergence"] is True
    assert ms["basis_structure"] == CONTANGO
    assert ms["basis_trade_opportunity"] is True


def test_faz18_cascade_risk_blocks() -> None:
    data = {
        "open_interest": 1_050_000, "open_interest_prev": 1_000_000,
        "price_change_pct": -0.02,
        "liquidation_levels": [{"price": 100.3, "notional_usd": 400e6}],  # cascade 1.0
        "spot_price": 100.0,
    }
    out = analyze_derivatives_intel("BTCUSDT", data, {"signal": "BUY"})
    assert out["trade_permission"] == "BLOCK"
    assert out["derivatives"]["market_structure"]["liq_cascade_risk"] == pytest.approx(1.0)


def test_faz18_backward_compat_no_market_data() -> None:
    out = analyze_derivatives_intel("BTCUSDT", {"funding_rate": 0.0001}, {"signal": "BUY"})
    assert "market_structure" not in out["derivatives"]


def test_faz18_oi_velocity_from_history() -> None:
    data = {
        "open_interest": 1_200_000, "open_interest_prev": 1_000_000,
        "price_change_pct": 0.03,
        "oi_history": [[0, 1000000], [24 * _HOUR, 1200000]],
        "spot_price": 100.0,
    }
    out = analyze_derivatives_intel("BTCUSDT", data, {"signal": "BUY"})
    ms = out["derivatives"]["market_structure"]
    assert ms["oi_regime"] == OI_TREND_STRENGTHENING
    assert ms["oi_velocity"]["24h"] == pytest.approx(0.20)


def test_faz18_graceful_bad_liq() -> None:
    data = {"open_interest": 1e6, "price_change_pct": 0.01, "liquidation_levels": "bad", "spot_price": 100.0}
    out = analyze_derivatives_intel("BTCUSDT", data, {"signal": "BUY"})
    assert out["trade_permission"] in ("ALLOW", "BLOCK", "HALT")
