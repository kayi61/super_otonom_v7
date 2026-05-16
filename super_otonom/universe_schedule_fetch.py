"""
Binance spot USDT evreni — point-in-time takvim verisi çekimi (ccxt).

Her sembol için günlük mumdan ``active_from_ms`` / ``active_until_ms`` üretir.
Delist adayları: hâlâ kline dönen çiftler → son mum zamanı ``active_until``;
aktif çiftler → ``active_until_ms: null``.

Çıktı: ``data/universe_schedule_binance.json`` (+ meta JSON).
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

log = logging.getLogger("super_otonom.universe_schedule_fetch")

_REPO = Path(__file__).resolve().parents[1]
_DEFAULT_OUT = _REPO / "data" / "universe_schedule_binance.json"
_DEFAULT_META = _REPO / "data" / "universe_schedule_binance.meta.json"

# Bilinen delist / yeniden listelenme adayları (kline hâlâ dönebilir veya hata verir)
_DELIST_CANDIDATES: Tuple[str, ...] = (
    "LUNC/USDT",
    "FTT/USDT",
    "OCEAN/USDT",
    "XEM/USDT",
    "WAVES/USDT",
    "OMG/USDT",
)

_DEFAULT_CORE: Tuple[str, ...] = (
    "BTC/USDT",
    "ETH/USDT",
    "BNB/USDT",
    "SOL/USDT",
    "XRP/USDT",
)


def _make_exchange():
    import ccxt

    return ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "spot"}})


def _top_usdt_symbols(ex: Any, top_n: int) -> List[str]:
    markets = ex.load_markets()
    usdt = [
        s
        for s, m in markets.items()
        if m.get("quote") == "USDT"
        and m.get("spot")
        and m.get("active", True)
        and "/USDT" in s
    ]
    scored: List[Tuple[str, float]] = []
    for sym in usdt[: min(len(usdt), top_n * 3)]:
        try:
            t = ex.fetch_ticker(sym)
            scored.append((sym, float(t.get("quoteVolume") or 0.0)))
        except Exception:
            continue
    scored.sort(key=lambda x: x[1], reverse=True)
    return [s for s, _ in scored[:top_n]]


def _ohlcv_window_ms(
    ex: Any, symbol: str, timeframe: str = "1d"
) -> Optional[Tuple[float, float, int]]:
    """(first_ts_ms, last_ts_ms, bar_count) veya None."""
    try:
        # Son mumlar
        tail = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=1000)
        if not tail:
            return None
        first_ts = float(tail[0][0])
        last_ts = float(tail[-1][0])
        # Daha eski başlangıç (mümkünse)
        since = int(time.time() * 1000) - 365 * 24 * 3600 * 1000 * 8
        head = ex.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=3)
        if head:
            first_ts = min(first_ts, float(head[0][0]))
        return first_ts, last_ts, len(tail)
    except Exception as exc:
        log.warning("%s: ohlcv failed: %s", symbol, exc)
        return None


def fetch_schedule_entries(
    symbols: Sequence[str],
    *,
    timeframe: str = "1d",
    mark_active_open: bool = True,
) -> List[Dict[str, Any]]:
    ex = _make_exchange()
    ex.load_markets()
    rows: List[Dict[str, Any]] = []
    markets = ex.markets or {}

    for sym in symbols:
        win = _ohlcv_window_ms(ex, sym, timeframe=timeframe)
        if win is None:
            rows.append(
                {
                    "symbol": sym,
                    "active_from_ms": None,
                    "active_until_ms": None,
                    "status": "no_data",
                    "market_active": bool(markets.get(sym, {}).get("active", False)),
                }
            )
            continue
        first_ts, last_ts, n_bars = win
        m = markets.get(sym, {})
        active = bool(m.get("active", False))
        entry: Dict[str, Any] = {
            "symbol": sym,
            "active_from_ms": first_ts,
            "active_until_ms": None if (mark_active_open and active) else last_ts,
            "status": "active" if active else "delisted_or_inactive",
            "market_active": active,
            "ohlcv_bars_sampled": n_bars,
            "last_bar_ms": last_ts,
        }
        rows.append(entry)
        time.sleep(ex.rateLimit / 1000.0 if ex.rateLimit else 0.2)
    return rows


def entries_to_schedule(entries: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Yalnızca veri olan semboller — edge_evidence / backtest_universe formatı."""
    out: List[Dict[str, Any]] = []
    for e in entries:
        if e.get("active_from_ms") is None:
            continue
        row = {
            "symbol": e["symbol"],
            "active_from_ms": e["active_from_ms"],
        }
        if e.get("active_until_ms") is not None:
            row["active_until_ms"] = e["active_until_ms"]
        out.append(row)
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="Binance USDT evren takvimi verisi çek (ccxt).")
    p.add_argument("--symbols", default="", help="Virgülle semboller; boşsa çekirdek+top.")
    p.add_argument("--top-n", type=int, default=8, help="Hacim üst N aktif USDT (symbols boşsa).")
    p.add_argument("--include-delist", action="store_true", default=True)
    p.add_argument("--no-delist", action="store_true", help="Delist adaylarını atla.")
    p.add_argument("--timeframe", default="1d")
    p.add_argument("--out", default=str(_DEFAULT_OUT))
    p.add_argument("--meta-out", default=str(_DEFAULT_META))
    p.add_argument("--json", action="store_true", help="Takvimi stdout'a yaz.")
    args = p.parse_args(list(argv) if argv is not None else None)

    if str(args.symbols).strip():
        from super_otonom.backtest_universe import parse_symbol_list

        symbols = parse_symbol_list(args.symbols)
    else:
        ex = _make_exchange()
        top = _top_usdt_symbols(ex, int(args.top_n))
        symbols = list(dict.fromkeys([*_DEFAULT_CORE, *top]))
    if not args.no_delist and args.include_delist:
        symbols = list(dict.fromkeys([*symbols, *_DELIST_CANDIDATES]))

    log.info("Fetching OHLCV windows for %d symbols...", len(symbols))
    entries = fetch_schedule_entries(symbols, timeframe=str(args.timeframe))
    schedule = entries_to_schedule(entries)
    if len(schedule) < 2:
        log.error("Yetersiz sembol verisi (schedule < 2).")
        return 1

    out_path = Path(args.out)
    meta_path = Path(args.meta_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(schedule, indent=2), encoding="utf-8")

    meta = {
        "fetched_at_unix": int(time.time()),
        "source": "ccxt.binance.spot",
        "timeframe": args.timeframe,
        "symbol_count": len(schedule),
        "symbols": [r["symbol"] for r in schedule],
        "entries_full": entries,
        "disclaimer": (
            "Takvim günlük OHLCV penceresinden türetildi; resmi delist duyuru tarihi değildir. "
            "Kurumsal survivorship kontrolü için delist tarihlerini harici kaynakla doğrulayın."
        ),
    }
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    log.info("Wrote schedule (%d symbols) -> %s", len(schedule), out_path)
    log.info("Meta -> %s", meta_path)
    if args.json:
        print(json.dumps(schedule, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
