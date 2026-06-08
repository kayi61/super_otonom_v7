"""NULL-KONTROL KAPISI — gercek strateji + gercek veri uzerinde (EP-0).

Bir stratejinin "edge"i gercek tahmin gucu mu, yoksa sans/sizinti artefakti mi?
Stratejiyi ZAMAN YAPISI YOK EDILMIS (bar-sirasi karistirilmis) veride yuzlerce kez
kosturup net-ortalama-islem istatistiginin NULL DAGILIMINI kurar; gercek sonuc bu
dagilimin uc kuyrugunda DEGILSE -> sans/sizinti -> OLDUR.

GERCEK PARA YOK — gecmis OHLCV. Edge URETMEZ; sahteyi eler.

Kullanim:
    python scripts/edge_null_control.py --signal donchian --signal-param 20 \
        --symbol BTC/USDT --tf 4h --start 2022-01-01 --end 2024-12-01 --n-perm 300
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edge_validate import _to_ms, collect_trades, fetch_range, make_signal  # noqa: E402
from super_otonom.research.null_control import (  # noqa: E402
    format_report,
    null_control_test,
)


def make_stat_fn(symbol: str, signal: str, param: int, fee: float, slip: float):
    """stat_fn(candles) -> net ortalama islem getirisi (yuksek = daha iyi). <2 islem -> 0."""

    def stat(candles: List[Dict[str, Any]]) -> float:
        sig = make_signal(signal, symbol, param)  # her cagride taze (analyzer state tutar)
        pnls, _bh = collect_trades(symbol, candles, sig, fee, slip)
        if len(pnls) < 2:
            return 0.0
        return float(np.mean(pnls))

    return stat


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Null-kontrol kapisi (permutasyon testi)")
    p.add_argument("--signal", default="donchian",
                   choices=["analyzer", "momentum", "donchian", "ema_cross"])
    p.add_argument("--signal-param", type=int, default=0)
    p.add_argument("--symbol", default="BTC/USDT")
    p.add_argument("--tf", default="4h")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--fee", type=float, default=0.001)
    p.add_argument("--slip", type=float, default=0.0005)
    p.add_argument("--n-perm", type=int, default=300)
    p.add_argument("--alpha", type=float, default=0.05)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args(argv)

    print(f"Veri cekiliyor: {args.symbol} {args.tf} {args.start}..{args.end} ...")
    candles = fetch_range(args.symbol, args.tf, _to_ms(args.start), _to_ms(args.end))
    if len(candles) < 100:
        print(f"YETERSIZ VERI: {len(candles)} mum (>=100 gerekli)")
        return 1
    print(f"  {len(candles)} mum.  Null dagilimi kuruluyor (n_perm={args.n_perm}) ...")

    stat_fn = make_stat_fn(args.symbol, args.signal, args.signal_param, args.fee, args.slip)
    res = null_control_test(
        stat_fn, candles, n_perm=args.n_perm, method="shuffle",
        seed=args.seed, alpha=args.alpha,
    )
    name = f"{args.signal}({args.signal_param or '-'}) {args.symbol} {args.tf}"
    print()
    print(format_report(name, res))
    print()
    if res["passes_null"]:
        print(">>> Null'u gecti: SANS/SIZINTI ile aciklanamaz. Bir sonraki kapiya "
              "(out-of-sample CPCV + maliyet + hold-out) aday. 'Kazandi' DEGIL.")
    else:
        print(">>> Null'u GECEMEDI: skor karistirilmis veriden ayirt edilemiyor "
              "(sans veya sizinti). Bu sinyali OLDUR.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
