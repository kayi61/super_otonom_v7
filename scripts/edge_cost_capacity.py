"""MALIYET + KAPASITE KAPISI — gercek strateji + gercek veri (EP-0).

Bir stratejinin BRUT islem getirilerini alir; gercekci ucret+spread+market-impact dusurur;
GERCEK-NET edge'i ve KAPASITEYI (net'i sifirlamadan konabilecek maks emir) raporlar.
ADV ve gunluk volatilite GERCEK mum verisinden tahmin edilir.

DURUST CAVEAT: impact_coef (eta) ampiriktir; gercek dolum verisiyle kalibre edilene kadar
kapasite tahmindir. Brut sayinin yalanini soyup net-gercegi gosterir.

GERCEK PARA YOK.

Kullanim:
    python scripts/edge_cost_capacity.py --signal donchian --signal-param 20 \
        --symbol BTC/USDT --tf 4h --start 2022-01-01 --end 2024-12-01 \
        --order-notional 10000 --taker-bps 5 --impact-coef 0.5
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edge_validate import _to_ms, collect_trades, fetch_range, make_signal  # noqa: E402
from super_otonom.research.cost_model import (  # noqa: E402
    CostParams,
    evaluate_strategy_costs,
    format_cost_report,
)

_TF_SECONDS = {"m": 60, "h": 3600, "d": 86400, "w": 604800}


def bars_per_day(tf: str) -> float:
    unit = tf[-1].lower()
    num = float(tf[:-1])
    sec = num * _TF_SECONDS.get(unit, 3600)
    return 86400.0 / sec if sec > 0 else 6.0


def estimate_adv_notional(candles, bpd: float) -> float:
    """Ortalama GUNLUK dolar hacmi ~ mean(bar notional) * bar/gun."""
    notional = [float(c["volume"]) * float(c["close"]) for c in candles if c.get("volume")]
    if not notional:
        return 0.0
    return float(np.mean(notional)) * bpd


def estimate_daily_vol(candles, bpd: float) -> float:
    closes = np.asarray([float(c["close"]) for c in candles], dtype=float)
    if closes.size < 3:
        return 0.0
    rets = np.diff(closes) / closes[:-1]
    return float(np.std(rets, ddof=1)) * np.sqrt(bpd)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Maliyet + kapasite kapisi")
    p.add_argument("--signal", default="donchian",
                   choices=["analyzer", "momentum", "donchian", "ema_cross"])
    p.add_argument("--signal-param", type=int, default=0)
    p.add_argument("--symbol", default="BTC/USDT")
    p.add_argument("--tf", default="4h")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--order-notional", type=float, default=10_000.0)
    p.add_argument("--taker-bps", type=float, default=5.0)
    p.add_argument("--maker-bps", type=float, default=2.0)
    p.add_argument("--half-spread-bps", type=float, default=1.0)
    p.add_argument("--impact-coef", type=float, default=0.5)
    p.add_argument("--impact-exponent", type=float, default=0.5)
    p.add_argument("--net-floor-bps", type=float, default=0.0)
    args = p.parse_args(argv)

    print(f"Veri cekiliyor: {args.symbol} {args.tf} {args.start}..{args.end} ...")
    candles = fetch_range(args.symbol, args.tf, _to_ms(args.start), _to_ms(args.end))
    if len(candles) < 100:
        print(f"YETERSIZ VERI: {len(candles)} mum (>=100 gerekli)")
        return 1

    bpd = bars_per_day(args.tf)
    adv = estimate_adv_notional(candles, bpd)
    vol = estimate_daily_vol(candles, bpd)

    # BRUT islem getirileri (ucret/slip = 0 -> maliyeti model ekleyecek)
    sig = make_signal(args.signal, args.symbol, args.signal_param)
    gross, _bh = collect_trades(args.symbol, candles, sig, fee=0.0, slip=0.0)
    if len(gross) < 5:
        print(f"YETERSIZ ISLEM: {len(gross)} (>=5 gerekli)")
        return 1

    params = CostParams(
        taker_bps=args.taker_bps, maker_bps=args.maker_bps,
        half_spread_bps=args.half_spread_bps, impact_coef=args.impact_coef,
        impact_exponent=args.impact_exponent,
    )
    params.validate()
    report = evaluate_strategy_costs(
        gross, order_notional=args.order_notional, adv_notional=adv,
        daily_vol=vol, params=params, net_floor_bps=args.net_floor_bps,
    )

    name = f"{args.signal}({args.signal_param or '-'}) {args.symbol} {args.tf}"
    print(f"  {len(candles)} mum | ADV~${adv:,.0f}/gun | gunluk vol~{vol*100:.2f}% | "
          f"bar/gun={bpd:.1f}")
    print()
    print(format_cost_report(name, report))
    print()
    print("NOT: impact_coef AMPIRIK — gercek dolumla kalibre edilene dek kapasite TAHMIN. "
          "Net edge maliyet sonrasi <=0 ise sinyal OLUR (brut yalandi).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
