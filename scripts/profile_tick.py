#!/usr/bin/env python
"""Tick döngüsü profilleme aracı (PROMPT-10).

``BotEngine.tick`` sıcak yolunu cProfile ile profiller. ``--dry-run`` modunda
gerçek borsa/ağ olmadan, paper modda sentetik mum verisiyle N tick çalıştırır.

Örnekler::

    python scripts/profile_tick.py --dry-run                 # 200 tick, top 30
    python scripts/profile_tick.py --dry-run --ticks 500 --sort tottime
    python scripts/profile_tick.py --dry-run --json          # makine-okur özet

py-spy ile canlı örnekleme (opsiyonel, ayrı kurulum)::

    py-spy record -o tick.svg -- python scripts/profile_tick.py --dry-run --ticks 2000
"""

from __future__ import annotations

import argparse
import asyncio
import cProfile
import json
import sys
import time
from typing import Any, Dict, List


def _synthetic_candles(n: int = 60) -> List[Dict[str, float]]:
    """Deterministik, gerçekçi mum serisi (ağ yok)."""
    out: List[Dict[str, float]] = []
    price = 100.0
    for i in range(n):
        price *= 1.0 + (0.002 if i % 3 == 0 else -0.0015)
        out.append(
            {
                "open": price * 0.999,
                "high": price * 1.004,
                "low": price * 0.996,
                "close": price,
                "volume": 1_000.0 + i * 5.0,
            }
        )
    return out


def _synthetic_analysis(i: int) -> Dict[str, Any]:
    sig = "BUY" if i % 5 == 0 else ("SELL" if i % 7 == 0 else "HOLD")
    return {
        "signal": sig,
        "volatility": 0.01,
        "regime": "TRENDING" if i % 2 == 0 else "RANGING",
        "hurst": 0.55,
        "confidence": 0.6,
        "ob_safe_size": 500.0,
    }


async def _run_ticks(ticks: int) -> Dict[str, Any]:
    """Paper BotEngine üzerinde N sentetik tick çalıştırır; latency istatistiği döndürür."""
    from super_otonom.bot_engine import BotEngine
    from super_otonom.profiling import TickLatencyTracker

    engine = BotEngine(10_000.0, paper=True)
    candles = _synthetic_candles(60)
    tracker = TickLatencyTracker(maxlen=max(64, ticks))

    for i in range(ticks):
        t0 = time.perf_counter()
        try:
            await engine.tick("BTC/USDT", _synthetic_analysis(i), candles)
        except Exception as exc:  # dry-run sağlamlığı
            print(f"[warn] tick {i} hata: {exc}", file=sys.stderr)
        tracker.record((time.perf_counter() - t0) * 1000.0)

    # engine'in kendi tracker'ı da varsa onu da raporla
    eng_stats = getattr(getattr(engine, "_latency_tracker", None), "stats", lambda: {})()
    return {"driver": tracker.stats(), "engine": eng_stats}


def _profile(ticks: int, sort: str, limit: int) -> Dict[str, Any]:
    from super_otonom.profiling import format_profile

    pr = cProfile.Profile()
    pr.enable()
    stats = asyncio.run(_run_ticks(ticks))
    pr.disable()
    table = format_profile(pr, sort=sort, limit=limit)
    return {"ticks": ticks, "latency": stats, "profile_table": table}


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="BotEngine tick profiling (cProfile).")
    p.add_argument("--dry-run", action="store_true", help="Paper mod, sentetik veri (ağ yok)")
    p.add_argument("--ticks", type=int, default=200, help="Çalıştırılacak tick sayısı")
    p.add_argument("--sort", default="cumulative", help="pstats sıralama anahtarı")
    p.add_argument("--limit", type=int, default=30, help="Gösterilecek satır sayısı")
    p.add_argument("--json", action="store_true", help="Makine-okur özet (profil tablosu hariç)")
    args = p.parse_args(argv)

    if not args.dry_run:
        print(
            "Yalnızca --dry-run destekleniyor (canlı borsa profili güvenli değil). "
            "Kullanım: python scripts/profile_tick.py --dry-run",
            file=sys.stderr,
        )
        return 2

    result = _profile(max(1, args.ticks), args.sort, max(1, args.limit))

    if args.json:
        print(json.dumps({"ticks": result["ticks"], "latency": result["latency"]}, indent=2))
    else:
        print(f"=== tick profiling — {result['ticks']} tick (dry-run) ===")
        print("latency:", json.dumps(result["latency"], ensure_ascii=False))
        print()
        print(result["profile_table"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
