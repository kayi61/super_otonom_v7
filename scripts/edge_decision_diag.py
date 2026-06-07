"""P-1 teshis araci: bot neden islem acmiyor? Ham sinyal vs nihai karar + sebep dagilimi.

Gercek OHLCV uzerinde gercek BotEngine.tick kosturup her bar icin:
  - analizorun HAM sinyali (BUY/SELL/HOLD)
  - rejim dagilimi
  - nihai sinyal + karar sebebi
  - ham=BUY/SELL iken nihaiyi olduren sebep
toplar. 0-islem kok sebebini (sinyal yok mu, kapi mi blokluyor) ayirir.

Kullanim:
    python scripts/edge_decision_diag.py --symbol BTC/USDT --timeframe 4h --limit 400
    python scripts/edge_decision_diag.py --symbol SOL/USDT --timeframe 1h --limit 500 --json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections import Counter
from typing import Any, Dict

os.environ.setdefault("PYTHONUTF8", "1")


async def _diag(symbol: str, timeframe: str, limit: int) -> Dict[str, Any]:
    from super_otonom.analyzer import MarketAnalyzer
    from super_otonom.bot_engine import BotEngine
    from super_otonom.signals.edge_evidence import fetch_ccxt_candles

    candles = fetch_ccxt_candles(symbol, timeframe, limit)
    engine = BotEngine(10_000, paper=True, paper_fee_bps_per_side=10.0)
    analyzer = MarketAnalyzer()

    raw, final, reasons, regimes, kill = (Counter(), Counter(), Counter(), Counter(), Counter())
    min_bars, max_window = 35, 150
    for i in range(min_bars, len(candles)):
        window = candles[max(0, i - max_window + 1): i + 1]
        analysis = analyzer.analyze(symbol, window)
        analysis.setdefault("strategist", "trend")
        rs = str(analysis.get("signal", "?"))
        raw[rs] += 1
        regimes[str(analysis.get("regime") or analysis.get("market_regime") or "?")] += 1
        out = await engine.tick(symbol, analysis, window)
        fs = str(out.get("final_signal", "?"))
        final[fs] += 1
        dr = str(out.get("decision_reason", "?"))
        reasons[dr] += 1
        if rs in ("BUY", "SELL") and fs not in ("BUY", "SELL"):
            kill[dr] += 1

    n = sum(raw.values())
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "ticks": n,
        "raw_signal": dict(raw),
        "regime": dict(regimes),
        "final_signal": dict(final),
        "decision_reason_top": reasons.most_common(10),
        "wouldbe_entry_killed_by": kill.most_common(10),
        "raw_entry_fraction": round((raw.get("BUY", 0) + raw.get("SELL", 0)) / n, 4) if n else 0.0,
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="0-islem kok sebep teshisi")
    p.add_argument("--symbol", default="BTC/USDT")
    p.add_argument("--timeframe", default="4h")
    p.add_argument("--limit", type=int, default=400)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    res = asyncio.run(_diag(args.symbol, args.timeframe, args.limit))
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(f"== {res['symbol']} {res['timeframe']} | {res['ticks']} tick ==")
        print("HAM sinyal (analyzer):", res["raw_signal"], f"| giris orani={res['raw_entry_fraction']}")
        print("REJIM:", res["regime"])
        print("NIHAI sinyal:", res["final_signal"])
        print("KARAR sebebi (top):", res["decision_reason_top"])
        print("HAM=BUY/SELL iken olduren:", res["wouldbe_entry_killed_by"] or "(ham hic giris uretmedi)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
