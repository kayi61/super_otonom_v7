"""Maliyet + kapasite modelinin KANITI (calisan ispat, uydurma degil)."""
from __future__ import annotations

import numpy as np
import pytest
from super_otonom.research.cost_model import (
    CostParams,
    capacity_notional,
    evaluate_strategy_costs,
    format_cost_report,
    market_impact_bps,
    net_returns_after_cost,
    round_trip_cost_bps,
)


# --------------------------------------------------------------------------- #
# parametre dogrulama
# --------------------------------------------------------------------------- #
def test_params_validate_rejects_bad_values():
    CostParams().validate()  # default gecerli
    with pytest.raises(ValueError):
        CostParams(taker_bps=-1).validate()
    with pytest.raises(ValueError):
        CostParams(impact_exponent=0.0).validate()
    with pytest.raises(ValueError):
        CostParams(impact_exponent=1.5).validate()
    with pytest.raises(ValueError):
        CostParams(impact_coef=-0.1).validate()


# --------------------------------------------------------------------------- #
# market impact: monotonluk + sinir kosullari
# --------------------------------------------------------------------------- #
def test_market_impact_monotonic_and_boundaries():
    p = CostParams(impact_coef=0.5, impact_exponent=0.5)
    vol = 0.04  # %4 gunluk
    adv = 1_000_000.0
    # sifir emir -> sifir impact
    assert market_impact_bps(0.0, adv, vol, p) == 0.0
    # likidite yok -> sonsuz (durust)
    assert market_impact_bps(1000.0, 0.0, vol, p) == float("inf")
    # emir buyudukce impact artar (monoton)
    sizes = [1_000, 10_000, 100_000, 500_000]
    imp = [market_impact_bps(s, adv, vol, p) for s in sizes]
    assert all(imp[i] < imp[i + 1] for i in range(len(imp) - 1))
    # kare-kok: emiri 4x yapinca impact 2x (exponent 0.5)
    base = market_impact_bps(50_000, adv, vol, p)
    quad = market_impact_bps(200_000, adv, vol, p)
    assert quad == pytest.approx(2.0 * base, rel=1e-9)


# --------------------------------------------------------------------------- #
# round-trip maliyet: 2x ucret + 2x spread + 2x impact (+ tasima)
# --------------------------------------------------------------------------- #
def test_round_trip_cost_components():
    p = CostParams(taker_bps=5.0, maker_bps=2.0, half_spread_bps=1.0,
                   impact_coef=0.5, impact_exponent=0.5)
    vol, adv, order = 0.04, 1_000_000.0, 50_000.0
    impact = market_impact_bps(order, adv, vol, p)
    expected_taker = 2 * 5.0 + 2 * 1.0 + 2 * impact
    assert round_trip_cost_bps(order, adv, vol, p, taker=True) == pytest.approx(expected_taker)
    # maker daha ucuz
    expected_maker = 2 * 2.0 + 2 * 1.0 + 2 * impact
    assert round_trip_cost_bps(order, adv, vol, p, taker=False) == pytest.approx(expected_maker)
    # funding + borrow tasima eklenir
    p2 = CostParams(funding_bps_per_period=3.0, borrow_bps_per_day=2.0)
    base = round_trip_cost_bps(order, adv, vol, p2, taker=True)
    with_carry = round_trip_cost_bps(order, adv, vol, p2, taker=True,
                                     funding_periods=3, holding_days=2, short=True)
    assert with_carry == pytest.approx(base + 3.0 * 3 + 2.0 * 2)


def test_net_returns_after_cost():
    gross = [0.02, 0.01, -0.005]
    net = net_returns_after_cost(gross, cost_bps=50.0)  # 50 bps = 0.005
    assert net == pytest.approx(np.array([0.015, 0.005, -0.010]))


# --------------------------------------------------------------------------- #
# KAPASITE <-> MALIYET TUTARLILIK INVARIANTI (en kritik dogruluk testi)
# capacity_notional(Q) oyle bir Q dondurur ki o emirde net == net_floor olmali.
# --------------------------------------------------------------------------- #
def test_capacity_roundtrip_consistency():
    p = CostParams(taker_bps=5.0, half_spread_bps=1.0, impact_coef=0.5, impact_exponent=0.5)
    vol, adv = 0.04, 1_000_000.0
    gross_edge_bps = 40.0
    floor = 5.0
    q = capacity_notional(gross_edge_bps, adv, vol, p, taker=True, net_floor_bps=floor)
    assert q > 0
    # o emir buyuklugunde gercek net = gross - round_trip == floor olmali
    cost_at_q = round_trip_cost_bps(q, adv, vol, p, taker=True)
    net_at_q = gross_edge_bps - cost_at_q
    assert net_at_q == pytest.approx(floor, abs=1e-6)


def test_capacity_zero_when_fixed_costs_exceed_edge():
    # brut 8 bps, ama sabit maliyet 2*5+2*1 = 12 bps > 8 -> en kucuk emir bile zararli
    p = CostParams(taker_bps=5.0, half_spread_bps=1.0)
    assert capacity_notional(8.0, 1_000_000.0, 0.04, p, taker=True) == 0.0


def test_capacity_scales_with_adv():
    p = CostParams(taker_bps=5.0, half_spread_bps=1.0, impact_coef=0.5, impact_exponent=0.5)
    q_small = capacity_notional(40.0, 1_000_000.0, 0.04, p)
    q_big = capacity_notional(40.0, 10_000_000.0, 0.04, p)
    # ADV 10x -> kapasite 10x (participation sabit kalir)
    assert q_big == pytest.approx(10.0 * q_small, rel=1e-9)


def test_capacity_larger_edge_more_capacity():
    p = CostParams(taker_bps=5.0, half_spread_bps=1.0, impact_coef=0.5, impact_exponent=0.5)
    assert (capacity_notional(60.0, 1e6, 0.04, p)
            > capacity_notional(30.0, 1e6, 0.04, p) > 0)


# --------------------------------------------------------------------------- #
# ust-duzey rapor: brut pozitif ama maliyet sonrasi olabilir/olmayabilir
# --------------------------------------------------------------------------- #
def test_evaluate_strategy_costs_kills_thin_edge():
    p = CostParams(taker_bps=5.0, half_spread_bps=1.0, impact_coef=0.5, impact_exponent=0.5)
    # brut ~ +8 bps/islem ama gidis-donus sabit maliyet ~12 bps -> NET negatif -> oldur
    gross = [0.0008] * 100
    r = evaluate_strategy_costs(
        gross, order_notional=10_000, adv_notional=1_000_000, daily_vol=0.04, params=p
    )
    assert r.gross_mean_bps == pytest.approx(8.0, abs=0.1)
    assert r.net_mean_bps < 0.0
    assert r.survives is False
    assert "OLDUR" in format_cost_report("ince-edge", r)


def test_evaluate_strategy_costs_survives_fat_edge():
    p = CostParams(taker_bps=5.0, half_spread_bps=1.0, impact_coef=0.5, impact_exponent=0.5)
    gross = [0.006] * 100  # +60 bps/islem -> maliyet sonrasi pozitif kalir
    r = evaluate_strategy_costs(
        gross, order_notional=10_000, adv_notional=5_000_000, daily_vol=0.04, params=p
    )
    assert r.net_mean_bps > 0.0
    assert r.survives is True
    assert r.capacity_notional > 0.0
    assert "OK" in format_cost_report("kalin-edge", r)
