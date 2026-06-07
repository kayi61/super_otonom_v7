"""P-1 TESHIS: ham analizor sinyalinin edge'i (kapi yigini BAYPAS, fee+slippage dahil).

Soru: bot'un gate yigini her seyi bloklamadan ONCE, stratejinin ham yon sinyali
(MarketAnalyzer BUY/SELL) fee sonrasi para kazandiriyor mu? Long/flat trend-takip:
BUY -> long gir, SELL -> cik. Her giris/cikista fee (bps/taraf) + slippage.

In-sample + out-of-sample iki pencere. Edge yoksa gate cerrahisi gereksiz (dürüst dur).
GERCEK PARA YOK — gecmis veride hesap.

Kullanim:
    python scripts/edge_raw_signal.py --symbol BTC/USDT --timeframe 4h \
        --start 2024-01-01 --end 2024-04-01 --fee-bps 10
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

import numpy as np


def _to_ms(d: str) -> int:
    return int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


def fetch_range(symbol: str, tf: str, start_ms: int, end_ms: int) -> List[List[float]]:
    import ccxt

    ex = ccxt.binance({"enableRateLimit": True})
    bar = ex.parse_timeframe(tf) * 1000
    rows: List[List[float]] = []
    since = start_ms
    while since < end_ms:
        batch = ex.fetch_ohlcv(symbol, tf, since=since, limit=1000)
        if not batch:
            break
        rows.extend(batch)
        nxt = batch[-1][0] + bar
        if nxt <= since:
            break
        since = nxt
        if len(batch) < 1000:
            break
        time.sleep(max(ex.rateLimit, 200) / 1000.0)
    return [r for r in rows if start_ms <= r[0] <= end_ms]


def simulate(symbol: str, candles: List[Dict[str, Any]], fee_bps: float, slip_bps: float) -> Dict[str, Any]:
    from super_otonom.analysis.analyzer import MarketAnalyzer

    fee = fee_bps / 10000.0
    slip = slip_bps / 10000.0
    analyzer = MarketAnalyzer()
    cash, pos, entry = 10_000.0, 0.0, 0.0
    eqc: List[float] = []
    pnls: List[float] = []
    n_buy = n_sell = 0
    min_bars, max_window = 35, 150
    for i in range(min_bars, len(candles)):
        w = candles[max(0, i - max_window + 1): i + 1]
        a = analyzer.analyze(symbol, w)
        a.setdefault("strategist", "trend")
        sig = str(a.get("signal", "HOLD"))
        px = float(w[-1]["close"])
        if pos == 0.0 and sig == "BUY":
            n_buy += 1
            epx = px * (1 + slip)
            pos = (cash / epx) * (1 - fee)
            entry = epx
            cash = 0.0
        elif pos > 0.0 and sig == "SELL":
            n_sell += 1
            xpx = px * (1 - slip)
            proceeds = pos * xpx * (1 - fee)
            pnls.append((xpx - entry) / entry)
            cash = proceeds
            pos = 0.0
        eqc.append(cash + pos * px)
    # son barda acik pozisyonu kapat
    if pos > 0.0:
        xpx = float(candles[-1]["close"]) * (1 - slip)
        pnls.append((xpx - entry) / entry)
        cash = pos * xpx * (1 - fee)
        pos = 0.0
    eq = np.asarray(eqc + [cash], dtype=float)
    total_ret = (cash - 10_000.0) / 10_000.0 * 100.0
    rets = np.diff(eq) / (eq[:-1] + 1e-9)
    sharpe = float(np.mean(rets) / (np.std(rets) + 1e-12) * np.sqrt(6 * 365)) if rets.size > 2 else 0.0
    peak = np.maximum.accumulate(eq)
    mdd = float(np.max((peak - eq) / (peak + 1e-9)) * 100.0)
    wins = [p for p in pnls if p > 0]
    p0, p1 = float(candles[0]["close"]), float(candles[-1]["close"])
    return {
        "bars": len(candles), "buy_hold_pct": round((p1 - p0) / p0 * 100, 2),
        "net_return_pct": round(total_ret, 2), "n_trades": len(pnls),
        "win_rate": round(len(wins) / len(pnls), 3) if pnls else 0.0,
        "avg_trade_pct": round(float(np.mean(pnls) * 100), 3) if pnls else 0.0,
        "sharpe": round(sharpe, 2), "max_dd_pct": round(mdd, 2),
        "n_buy_signals": n_buy, "n_sell_exits": n_sell,
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Ham sinyal edge teshisi (gate baypas)")
    p.add_argument("--symbol", default="BTC/USDT")
    p.add_argument("--timeframe", default="4h")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--fee-bps", type=float, default=10.0)
    p.add_argument("--slip-bps", type=float, default=5.0)
    args = p.parse_args(argv)
    raw = fetch_range(args.symbol, args.timeframe, _to_ms(args.start), _to_ms(args.end))
    from super_otonom.exchange_async import ohlcv_to_candles

    candles = ohlcv_to_candles(raw)
    if len(candles) < 60:
        print(f"HATA: yetersiz bar ({len(candles)})")
        return 1
    r = simulate(args.symbol, candles, args.fee_bps, args.slip_bps)
    print(f"== {args.symbol} {args.timeframe} | {args.start}..{args.end} | {r['bars']} bar ==")
    print(f"BUY&HOLD: {r['buy_hold_pct']}%  |  fee={args.fee_bps}bps/taraf slip={args.slip_bps}bps")
    print(f"HAM SINYAL STRATEJISI: net getiri={r['net_return_pct']}% | islem={r['n_trades']} | "
          f"kazanma={r['win_rate']} | ort.islem={r['avg_trade_pct']}% | Sharpe={r['sharpe']} | MDD={r['max_dd_pct']}%")
    print(f"(sinyal: {r['n_buy_signals']} giris, {r['n_sell_exits']} cikis)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
