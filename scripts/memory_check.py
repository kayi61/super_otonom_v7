#!/usr/bin/env python
"""Bellek sızıntısı tespiti — tracemalloc snapshot karşılaştırma (PROMPT-10).

Paper modda BotEngine üzerinde bir ısınma (warmup) turundan sonra N tick
çalıştırır; öncesi/sonrası ``tracemalloc`` snapshot'larını karşılaştırır. Sabit
durumda RSS ve izlenen tahsis büyümesi eşik altında kalmalıdır.

Örnekler::

    python scripts/memory_check.py --ticks 500
    python scripts/memory_check.py --ticks 1000 --warmup 100 --threshold-mb 25 --json

Çıkış kodu: tahsis büyümesi ``--threshold-mb`` üstündeyse 1 (CI'da sızıntı kapısı),
aksi halde 0.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

# Doğrudan çalıştırmada (python scripts/memory_check.py) repo kökünü path'e ekle.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.profile_tick import _synthetic_analysis, _synthetic_candles  # noqa: E402


async def _drive(ticks: int, warmup: int) -> Dict[str, Any]:
    from super_otonom.bot_engine import BotEngine
    from super_otonom.profiling import (
        diff_snapshots,
        start_tracemalloc,
        stop_tracemalloc,
        take_memory_snapshot,
    )

    engine = BotEngine(10_000.0, paper=True)
    candles = _synthetic_candles(60)

    async def _ticks(n: int) -> None:
        for i in range(n):
            try:
                await engine.tick("BTC/USDT", _synthetic_analysis(i), candles)
            except Exception as exc:
                print(f"[warn] tick {i} hata: {exc}", file=sys.stderr)

    started = start_tracemalloc(nframe=5)
    # Isınma: lazy init / cache'ler dolsun, sabit duruma gelelim.
    await _ticks(warmup)
    before = take_memory_snapshot("before")
    await _ticks(ticks)
    after = take_memory_snapshot("after")
    rss_delta, top = diff_snapshots(before, after, top=12)
    traced_delta = after.traced_current - before.traced_current
    if started:
        stop_tracemalloc()

    return {
        "ticks": ticks,
        "warmup": warmup,
        "rss_before": before.rss,
        "rss_after": after.rss,
        "rss_delta_bytes": rss_delta,
        "traced_delta_bytes": traced_delta,
        "traced_peak_bytes": after.traced_peak,
        "top_growth": top,
    }


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="tracemalloc tabanlı tick bellek kontrolü.")
    p.add_argument("--ticks", type=int, default=500, help="Ölçüm turu tick sayısı")
    p.add_argument("--warmup", type=int, default=50, help="Isınma tick sayısı (snapshot öncesi)")
    p.add_argument(
        "--threshold-mb",
        type=float,
        default=30.0,
        help="İzlenen tahsis büyümesi bu MB'ı aşarsa exit 1",
    )
    p.add_argument("--json", action="store_true", help="Makine-okur JSON çıktı")
    args = p.parse_args(argv)

    res = asyncio.run(_drive(max(1, args.ticks), max(0, args.warmup)))
    traced_mb = res["traced_delta_bytes"] / (1024 * 1024)
    rss_mb = res["rss_delta_bytes"] / (1024 * 1024)
    leak = traced_mb > args.threshold_mb
    res["traced_delta_mb"] = round(traced_mb, 3)
    res["rss_delta_mb"] = round(rss_mb, 3)
    res["threshold_mb"] = args.threshold_mb
    res["leak_suspected"] = leak

    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print(f"=== memory check — {res['ticks']} tick (warmup {res['warmup']}) ===")
        print(f"RSS delta:    {rss_mb:+.2f} MB")
        print(f"traced delta: {traced_mb:+.2f} MB (peak {res['traced_peak_bytes'] / 1e6:.1f} MB)")
        print(f"threshold:    {args.threshold_mb:.1f} MB → {'LEAK?' if leak else 'OK'}")
        if res["top_growth"]:
            print("\nEn çok büyüyen tahsis satırları:")
            for line in res["top_growth"]:
                print(f"  {line}")
    return 1 if leak else 0


if __name__ == "__main__":
    raise SystemExit(main())
