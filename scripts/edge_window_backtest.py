"""P-1 — Sayfalamalı geçmiş veri + belirli tarih aralığında edge backtest (SAHTE para).

`fetch_ccxt_candles` tek çağrı (≈1000 bar) tavanını aşar: `since`→`until` sayfalama ile
herhangi bir geçmiş dönemi (örn. bilinen bir boğa koşusu, gerçek 12 ay) çeker, sonra gerçek
`BotEngine.tick` + fee + slippage ile backtest eder. GERÇEK PARA YOK — geçmiş fiyat verisi
üzerinde "olsaydı ne olurdu" hesabı.

Ayrıca buy&hold getirisiyle kıyas + karar/sebep dağılımı verir (dürüst bağlam).

Kullanım:
    python scripts/edge_window_backtest.py --symbol BTC/USDT --timeframe 4h \
        --start 2024-01-01 --end 2024-04-01 --fee-bps 10
"""
from __future__ import annotations

import argparse
import asyncio
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List


def _to_ms(date_str: str) -> int:
    return int(
        datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000
    )


def fetch_range(symbol: str, timeframe: str, start_ms: int, end_ms: int) -> List[List[float]]:
    """Sayfalamalı OHLCV (since→until). Binance tek çağrı ≈1000 bar; döngüyle birleştirir."""
    import ccxt

    ex = ccxt.binance({"enableRateLimit": True})
    bar_ms = ex.parse_timeframe(timeframe) * 1000
    rows: List[List[float]] = []
    since = start_ms
    while since < end_ms:
        batch = ex.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
        if not batch:
            break
        rows.extend(batch)
        nxt = batch[-1][0] + bar_ms
        if nxt <= since:
            break
        since = nxt
        if len(batch) < 1000:
            break
        time.sleep(max(ex.rateLimit, 200) / 1000.0)
    return [r for r in rows if start_ms <= r[0] <= end_ms]


async def run(symbol: str, timeframe: str, start: str, end: str, fee_bps: float) -> Dict[str, Any]:
    from super_otonom.analyzer import MarketAnalyzer
    from super_otonom.backtester import build_backtest_report
    from super_otonom.bot_engine import BotEngine
    from super_otonom.exchange_async import ohlcv_to_candles

    raw_ohlcv = fetch_range(symbol, timeframe, _to_ms(start), _to_ms(end))
    candles = ohlcv_to_candles(raw_ohlcv)
    if len(candles) < 60:
        return {"error": f"yetersiz bar: {len(candles)}"}

    engine = BotEngine(
        10_000.0, paper=True, paper_fee_bps_per_side=fee_bps,
        exec_slippage_range=(0.0002, 0.0012), exec_seed=42,
    )
    analyzer = MarketAnalyzer()
    equity: List[float] = []
    raw, regime, final, reasons = Counter(), Counter(), Counter(), Counter()
    min_bars, max_window = 35, 150
    for i in range(min_bars, len(candles)):
        window = candles[max(0, i - max_window + 1): i + 1]
        analysis = analyzer.analyze(symbol, window)
        analysis.setdefault("strategist", "trend")
        raw[str(analysis.get("signal", "?"))] += 1
        regime[str(analysis.get("regime") or analysis.get("market_regime") or "?")] += 1
        out = await engine.tick(symbol, analysis, window)
        final[str(out.get("final_signal", "?"))] += 1
        reasons[str(out.get("decision_reason", "?"))] += 1
        equity.append(float(engine.equity))

    rep = build_backtest_report(
        engine, equity, 10_000.0, bars_simulated=len(equity), timeframe=timeframe
    )
    p0, p1 = float(candles[0]["close"]), float(candles[-1]["close"])
    buy_hold_pct = (p1 - p0) / p0 * 100.0
    return {
        "symbol": symbol, "timeframe": timeframe, "window": f"{start}..{end}",
        "bars": len(candles), "price_start": p0, "price_end": p1,
        "buy_hold_pct": round(buy_hold_pct, 2),
        "bot_return_pct": rep.total_return_pct, "n_trades": rep.n_trades,
        "sharpe": rep.sharpe_ratio, "max_dd_pct": rep.max_drawdown_pct,
        "raw_signal": dict(raw), "regime": dict(regime),
        "final_signal": dict(final), "reason_top": reasons.most_common(6),
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Tarih aralığında edge backtest (paper)")
    p.add_argument("--symbol", default="BTC/USDT")
    p.add_argument("--timeframe", default="4h")
    p.add_argument("--start", required=True, help="YYYY-MM-DD (UTC)")
    p.add_argument("--end", required=True, help="YYYY-MM-DD (UTC)")
    p.add_argument("--fee-bps", type=float, default=10.0)
    args = p.parse_args(argv)

    res = asyncio.run(run(args.symbol, args.timeframe, args.start, args.end, args.fee_bps))
    if "error" in res:
        print("HATA:", res["error"])
        return 1
    print(f"== {res['symbol']} {res['timeframe']} | {res['window']} | {res['bars']} bar ==")
    print(f"Fiyat: {res['price_start']:.0f} -> {res['price_end']:.0f} | BUY&HOLD: {res['buy_hold_pct']}%")
    print(f"BOT: getiri={res['bot_return_pct']}% | ISLEM={res['n_trades']} | "
          f"Sharpe={res['sharpe']} | MDD={res['max_dd_pct']}%")
    print(f"REJIM: {res['regime']}")
    print(f"HAM sinyal: {res['raw_signal']}")
    print(f"NIHAI: {res['final_signal']}")
    print(f"SEBEP(top): {res['reason_top']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
