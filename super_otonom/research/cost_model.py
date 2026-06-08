"""Maliyet + kapasite modeli (EP-0) — gercekci islem maliyeti ve edge'in dayanikliligi.

NEDEN: Bir backtest'in "brut" getirisi YALANDIR — gercek dunyada her islem ucret, spread
ve (buyukse) market-impact oder. Ayrica bir edge SONSUZ sermaye almaz: emir buyudukce
fiyati kendin itersin (impact), edge erir. Bu modul ikisini de olcer:
  1. round_trip_cost_bps: bir gidis-donus islemin TOPLAM maliyeti (bps).
  2. capacity_notional: brut edge'i tuketmeden konabilecek MAKS emir buyuklugu.

Maliyet bilesenleri (literatur-temelli, uydurma degil):
  - Ucret: maker/taker (bps), her dolum.
  - Spread: bid-ask yarisi (piyasayi gecme maliyeti).
  - Market impact: KARE-KOK yasasi (Almgren-Chriss / BARRA ampirik):
        impact_bps = eta * sigma_gunluk_bps * (emir_notional / ADV_notional) ** exponent
    Emir gunluk hacmin buyuyen bir oranina cikinca fiyati itersin.
  - Funding (perp tasima) + borrow (short).

DURUST CAVEAT (en kritik): `impact_coef` (eta) AMPIRIKTIR. Gercek edge dogrulamasinda
GERCEK dolum verisiyle kalibre edilmeli. Buradaki default (0.5) literaturden bir O(1)
placeholder'dir; en buyuk belirsizlik kaynagidir. Capacity tahminleri bu katsayiya
DOGRUDAN baglidir -> kalibre edilene kadar tahmindir, kesinlik DEGIL.

GERCEK PARA YOK. Edge URETMEZ; brut sayilarin yalanini soyup gercek-net ve siniri gosterir.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

_BPS = 1.0e4  # 1 = 10_000 bps


@dataclass(frozen=True)
class CostParams:
    """Islem maliyeti parametreleri. Default'lar Binance-futures civari + KONSERVATIF
    placeholder; gercek dogrulamada borsaya/sembole gore kalibre et."""

    taker_bps: float = 5.0          # taker ucreti, dolum basina (Binance futures ~5)
    maker_bps: float = 2.0          # maker ucreti, dolum basina
    half_spread_bps: float = 1.0    # bid-ask yarisi (piyasayi gecme)
    impact_coef: float = 0.5        # eta — AMPIRIK, kalibre edilmeli (en buyuk belirsizlik)
    impact_exponent: float = 0.5    # kare-kok yasasi (literaturde 0.5..0.6)
    funding_bps_per_period: float = 0.0   # perp funding/period (8h), isaret disaridan
    borrow_bps_per_day: float = 0.0       # short borrow gunluk

    def validate(self) -> None:
        if self.taker_bps < 0 or self.maker_bps < 0 or self.half_spread_bps < 0:
            raise ValueError("ucret/spread negatif olamaz")
        if self.impact_coef < 0:
            raise ValueError("impact_coef negatif olamaz")
        if not (0.0 < self.impact_exponent <= 1.0):
            raise ValueError("impact_exponent (0, 1] araliginda olmali")
        if self.borrow_bps_per_day < 0:
            raise ValueError("borrow negatif olamaz")


def market_impact_bps(
    order_notional: float,
    adv_notional: float,
    daily_vol: float,
    params: CostParams,
) -> float:
    """Kare-kok market impact (bps). Emir buyudukce / likidite azaldikca artar.

    order_notional : emrin dolar buyuklugu
    adv_notional   : ortalama GUNLUK dolar hacmi (ayni birim)
    daily_vol      : gunluk getiri std'si (kesir, orn 0.04 = %4)
    Likidite yoksa (ADV<=0) -> sonsuz impact (durust: bilinmeyen likidite = guvenli degil).
    """
    if order_notional <= 0:
        return 0.0
    if adv_notional <= 0:
        return float("inf")
    participation = order_notional / adv_notional
    vol_bps = daily_vol * _BPS
    return params.impact_coef * vol_bps * (participation ** params.impact_exponent)


def round_trip_cost_bps(
    order_notional: float,
    adv_notional: float,
    daily_vol: float,
    params: CostParams,
    *,
    taker: bool = True,
    funding_periods: float = 0.0,
    holding_days: float = 0.0,
    short: bool = False,
) -> float:
    """Bir GIDIS-DONUS islemin (gir + cik = 2 dolum) toplam maliyeti, bps.

    = 2*ucret + 2*spread_yarisi + 2*impact  (+ funding + borrow tasima).
    """
    fee = params.taker_bps if taker else params.maker_bps
    impact = market_impact_bps(order_notional, adv_notional, daily_vol, params)
    cost = 2.0 * fee + 2.0 * params.half_spread_bps + 2.0 * impact
    cost += abs(params.funding_bps_per_period) * max(0.0, funding_periods)  # taasima (konservatif)
    if short:
        cost += params.borrow_bps_per_day * max(0.0, holding_days)
    return cost


def net_returns_after_cost(
    gross_returns: Sequence[float],
    cost_bps: float,
) -> np.ndarray:
    """Her islemin BRUT getirisinden gidis-donus maliyetini (bps) dus -> NET getiri (kesir)."""
    g = np.asarray(gross_returns, dtype=float)
    return g - (cost_bps / _BPS)


def capacity_notional(
    gross_edge_bps: float,
    adv_notional: float,
    daily_vol: float,
    params: CostParams,
    *,
    taker: bool = True,
    net_floor_bps: float = 0.0,
    funding_periods: float = 0.0,
    holding_days: float = 0.0,
    short: bool = False,
) -> float:
    """Brut edge'i (islem basina bps) `net_floor_bps`'in altina dusurmeden konabilecek
    MAKS emir buyuklugu (notional). Impact denklemini ters cozer.

    fixed = 2*ucret + 2*spread (+ funding + borrow);  impact icin kalan butce =
    gross - fixed - floor.  Butce<=0 ise sabit maliyetler bile edge'i yiyor -> kapasite 0.
    """
    fee = params.taker_bps if taker else params.maker_bps
    fixed = 2.0 * fee + 2.0 * params.half_spread_bps
    fixed += abs(params.funding_bps_per_period) * max(0.0, funding_periods)
    if short:
        fixed += params.borrow_bps_per_day * max(0.0, holding_days)
    budget = gross_edge_bps - fixed - net_floor_bps  # 2*impact icin kalan
    if budget <= 0.0:
        return 0.0
    if adv_notional <= 0:
        return 0.0
    vol_bps = daily_vol * _BPS
    if vol_bps <= 0 or params.impact_coef <= 0:
        return float("inf")  # impactsiz model -> sinirsiz (gercekci degil, ucariyi belirt)
    base = budget / (2.0 * params.impact_coef * vol_bps)  # = participation^exponent
    participation = base ** (1.0 / params.impact_exponent)
    return adv_notional * participation


@dataclass(frozen=True)
class CostReport:
    gross_mean_bps: float
    cost_bps: float
    net_mean_bps: float
    n_trades: int
    order_notional: float
    adv_notional: float
    capacity_notional: float
    impact_bps: float

    @property
    def survives(self) -> bool:
        return self.net_mean_bps > 0.0


def evaluate_strategy_costs(
    gross_returns: Sequence[float],
    *,
    order_notional: float,
    adv_notional: float,
    daily_vol: float,
    params: CostParams,
    taker: bool = True,
    net_floor_bps: float = 0.0,
) -> CostReport:
    """Bir stratejinin brut islem getirilerini alip GERCEK-NET edge + kapasiteyi hesapla."""
    g = np.asarray(gross_returns, dtype=float)
    gross_mean_bps = float(np.mean(g) * _BPS) if g.size else 0.0
    cost = round_trip_cost_bps(order_notional, adv_notional, daily_vol, params, taker=taker)
    impact = market_impact_bps(order_notional, adv_notional, daily_vol, params)
    cap = capacity_notional(
        gross_mean_bps, adv_notional, daily_vol, params,
        taker=taker, net_floor_bps=net_floor_bps,
    )
    return CostReport(
        gross_mean_bps=gross_mean_bps,
        cost_bps=cost,
        net_mean_bps=gross_mean_bps - cost,
        n_trades=int(g.size),
        order_notional=order_notional,
        adv_notional=adv_notional,
        capacity_notional=cap,
        impact_bps=impact,
    )


def format_cost_report(name: str, r: CostReport) -> str:
    icon = "OK" if r.survives else "X"
    cap = "sinirsiz" if r.capacity_notional == float("inf") else f"${r.capacity_notional:,.0f}"
    return "\n".join(
        [
            f"== MALIYET + KAPASITE: {name} ==",
            f"  islem sayisi   : {r.n_trades}",
            f"  emir buyuklugu : ${r.order_notional:,.0f}   ADV: ${r.adv_notional:,.0f}",
            f"  brut edge      : {r.gross_mean_bps:+.2f} bps/islem",
            f"  maliyet (g-d)  : {r.cost_bps:.2f} bps  (impact {r.impact_bps:.2f} bps)",
            f"  NET edge       : {r.net_mean_bps:+.2f} bps/islem",
            f"  kapasite (net>0): {cap}",
            f"  >>> [{icon}] " + ("maliyet sonrasi POZITIF (sonraki kapiya aday)"
                                  if r.survives else "maliyet sonrasi <=0 -> OLDUR"),
        ]
    )
