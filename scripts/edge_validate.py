"""P-1 VALIDASYON HARNESS — strateji-bagimsiz, overfit-onleyici, istatistiksel.

Amac: bir stratejinin (sinyal fonksiyonu) GERCEK edge'i olup olmadigini, kendimizi
in-sample sayilarla kandirmadan olcmek. Cok sembol + uzun gecmis + tum rejimler
uzerinde calistirir, TUM islemleri havuzlar, fee/slippage sonrasi:
  - islem sayisi, ortalama islem %, t-istatistigi (mean/std*sqrt(n)) -> anlamlilik
  - kazanma orani, toplam getiri, Sharpe, buy&hold kiyasi
Verdikt: VALIDATED / NO_EDGE / NOT_SIGNIFICANT / INSUFFICIENT.

KURAL: pozitif beklenti yalnizca t>=2 (≈%95 guven) + yeterli islem + buy&hold'a kiyasla
anlamliysa "VALIDATED (tentative)". Aksi halde sistem kazanan DEGILDIR.

Sinyal pluggable: varsayilan = mevcut MarketAnalyzer. Yeni stratejiler ayni sinava sokulur.
GERCEK PARA YOK — gecmis veride hesap.

Kullanim:
    python scripts/edge_validate.py --symbols BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT \
        --timeframe 4h --start 2023-01-01 --end 2024-12-01 --fee-bps 10
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List

import numpy as np


def _to_ms(d: str) -> int:
    return int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


def fetch_range(symbol: str, tf: str, start_ms: int, end_ms: int) -> List[Dict[str, Any]]:
    import ccxt
    from super_otonom.exchange_async import ohlcv_to_candles

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
    return ohlcv_to_candles([r for r in rows if start_ms <= r[0] <= end_ms])


def analyzer_signal(symbol: str) -> Callable[[List[Dict[str, Any]]], str]:
    from super_otonom.analysis.analyzer import MarketAnalyzer

    az = MarketAnalyzer()

    def f(window: List[Dict[str, Any]]) -> str:
        a = az.analyze(symbol, window)
        a.setdefault("strategist", "trend")
        return str(a.get("signal", "HOLD"))

    return f


# ── Klasik baseline sinyalleri (on-kayitli, overfit DEGIL — R&D referansi) ──

def momentum_signal(n: int = 30):
    """Fiyat N bar oncesinden yuksekse long; dususe gecince cik. Klasik momentum."""
    def f(window: List[Dict[str, Any]]) -> str:
        if len(window) <= n:
            return "HOLD"
        now = float(window[-1]["close"])
        past = float(window[-1 - n]["close"])
        return "BUY" if now > past else "SELL"
    return f


def donchian_signal(n: int = 20):
    """Donchian kirilimi: N-bar yuksegini asarsa long, N-bar dusugunu kirarsa cik."""
    def f(window: List[Dict[str, Any]]) -> str:
        if len(window) <= n + 1:
            return "HOLD"
        highs = [float(c["high"]) for c in window[-n - 1:-1]]
        lows = [float(c["low"]) for c in window[-n - 1:-1]]
        px = float(window[-1]["close"])
        if px > max(highs):
            return "BUY"
        if px < min(lows):
            return "SELL"
        return "HOLD"
    return f


def ema_cross_signal(fast: int = 12, slow: int = 26):
    """EMA hizli > yavas -> long; asagi kesince cik."""
    def _ema(vals, span):
        k = 2.0 / (span + 1)
        e = vals[0]
        for v in vals[1:]:
            e = v * k + e * (1 - k)
        return e
    def f(window: List[Dict[str, Any]]) -> str:
        if len(window) <= slow:
            return "HOLD"
        closes = [float(c["close"]) for c in window]
        return "BUY" if _ema(closes, fast) > _ema(closes, slow) else "SELL"
    return f


def make_signal(name: str, symbol: str, param: int = 0):
    if name == "analyzer":
        return analyzer_signal(symbol)
    if name == "momentum":
        return momentum_signal(param or 30)
    if name == "donchian":
        return donchian_signal(param or 20)
    if name == "ema_cross":
        return ema_cross_signal()
    raise ValueError(f"bilinmeyen sinyal: {name}")


def collect_trades(symbol: str, candles: List[Dict[str, Any]], signal_fn, fee: float, slip: float):
    """Long/flat: BUY->gir, SELL->cik. Net (fee+slip sonrasi) islem getirileri listesi."""
    pnls: List[float] = []
    pos = False
    entry = 0.0
    min_bars, max_window = 35, 150
    for i in range(min_bars, len(candles)):
        w = candles[max(0, i - max_window + 1): i + 1]
        sig = signal_fn(w)
        px = float(w[-1]["close"])
        if not pos and sig == "BUY":
            entry = px * (1 + slip)
            pos = True
        elif pos and sig == "SELL":
            xpx = px * (1 - slip)
            pnls.append((xpx / entry) * (1 - fee) * (1 - fee) - 1.0)
            pos = False
    if pos:
        xpx = float(candles[-1]["close"]) * (1 - slip)
        pnls.append((xpx / entry) * (1 - fee) * (1 - fee) - 1.0)
    bh = float(candles[-1]["close"]) / float(candles[min_bars]["close"]) - 1.0
    return pnls, bh


def verdict(n: int, mean: float, t_stat: float, beats_bh: bool) -> str:
    if n < 30:
        return f"INSUFFICIENT (n={n} < 30 islem — istatistik icin yetersiz)"
    if mean <= 0:
        return "NO_EDGE (ortalama islem <= 0 — negatif/sifir beklenti)"
    if t_stat < 2.0:
        return f"NOT_SIGNIFICANT (t={t_stat:.2f} < 2.0 — pozitif ama sansa baglanabilir)"
    if not beats_bh:
        return f"WEAK (t={t_stat:.2f} pozitif ama buy&hold'u gecemiyor)"
    return f"VALIDATED-tentative (t={t_stat:.2f} >= 2.0, pozitif, B&H ustu)"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Edge validasyon harness (overfit-onleyici)")
    p.add_argument("--symbols", default="BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT")
    p.add_argument("--timeframe", default="4h")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--fee-bps", type=float, default=10.0)
    p.add_argument("--slip-bps", type=float, default=5.0)
    p.add_argument("--signal", default="analyzer",
                   choices=("analyzer", "momentum", "donchian", "ema_cross"))
    p.add_argument("--signal-param", type=int, default=0, help="donchian/momentum N (0=varsayilan)")
    args = p.parse_args(argv)

    fee, slip = args.fee_bps / 10000.0, args.slip_bps / 10000.0
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    s_ms, e_ms = _to_ms(args.start), _to_ms(args.end)

    all_pnls: List[float] = []
    bh_list: List[float] = []
    per_sym = []
    for sym in symbols:
        candles = fetch_range(sym, args.timeframe, s_ms, e_ms)
        if len(candles) < 100:
            print(f"  {sym}: yetersiz bar ({len(candles)}) — atlandi")
            continue
        pnls, bh = collect_trades(sym, candles, make_signal(args.signal, sym, args.signal_param), fee, slip)
        all_pnls.extend(pnls)
        bh_list.append(bh)
        comp = float(np.prod([1 + x for x in pnls]) - 1.0) if pnls else 0.0
        per_sym.append((sym, len(candles), len(pnls), comp * 100, bh * 100))

    arr = np.asarray(all_pnls, dtype=float)
    n = arr.size
    mean = float(arr.mean()) if n else 0.0
    std = float(arr.std(ddof=1)) if n > 1 else 0.0
    t_stat = (mean / std * np.sqrt(n)) if std > 1e-12 and n > 1 else 0.0
    win = float((arr > 0).mean()) if n else 0.0
    bh_avg = float(np.mean(bh_list)) * 100 if bh_list else 0.0
    # strateji ortalama bilesik getirisi (semboller arasi)
    strat_avg = float(np.mean([c for _, _, _, c, _ in per_sym])) if per_sym else 0.0
    beats_bh = strat_avg > bh_avg

    print(f"== EDGE VALIDASYON | {args.timeframe} | {args.start}..{args.end} | fee={args.fee_bps}bps slip={args.slip_bps}bps ==")
    for sym, bars, nt, comp, bh in per_sym:
        print(f"  {sym:10s} bar={bars:5d} islem={nt:3d} strateji={comp:+7.1f}% buy&hold={bh:+7.1f}%")
    print("-" * 70)
    print(f"HAVUZ: islem={n} | ort.islem={mean*100:+.3f}% | std={std*100:.3f}% | "
          f"t-stat={t_stat:.2f} | kazanma={win:.2f}")
    print(f"Strateji ort.getiri={strat_avg:+.1f}%  vs  Buy&Hold ort.={bh_avg:+.1f}%")
    print(f"\n>>> VERDIKT: {verdict(n, mean, t_stat, beats_bh)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
