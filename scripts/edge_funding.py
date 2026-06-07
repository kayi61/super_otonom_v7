"""P-1 TESHIS: funding rate'in YON tahmin gucu var mi? (acimasiz, istatistiksel)

Hipotez (taksonomi): asiri pozitif funding (kalabalik long) -> ters donus (dusus);
asiri negatif funding (kalabalik short) -> yukari squeeze. Yani funding ile ILERI getiri
NEGATIF korelasyonlu olmali. Bunu olceriz:
  - funding (8h) ile ileri 8h/24h getiri korelasyonu
  - asiri funding decile'larinda ortalama ileri getiri + t-istatistigi
Cok sembol havuzu. Anlamli ters-donus yoksa -> funding yon-edge'i yok.

GERCEK PARA YOK — gecmis funding+fiyat verisi.

Kullanim:
    python scripts/edge_funding.py --symbols BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT \
        --start 2022-01-01 --end 2024-12-01
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone
from typing import Dict, List, Tuple

import numpy as np


def _to_ms(d: str) -> int:
    return int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


def _perp(sym: str) -> str:
    return sym if ":" in sym else f"{sym}:{sym.split('/')[1]}"


def fetch_funding(ex, sym: str, start_ms: int, end_ms: int) -> List[Tuple[int, float]]:
    out: List[Tuple[int, float]] = []
    since = start_ms
    while since < end_ms:
        batch = ex.fetch_funding_rate_history(_perp(sym), since=since, limit=1000)
        if not batch:
            break
        for r in batch:
            ts = int(r["timestamp"])
            if start_ms <= ts <= end_ms:
                out.append((ts, float(r["fundingRate"])))
        nxt = int(batch[-1]["timestamp"]) + 1
        if nxt <= since:
            break
        since = nxt
        if len(batch) < 1000:
            break
        time.sleep(max(ex.rateLimit, 200) / 1000.0)
    return out


def fetch_price_map(ex, sym: str, start_ms: int, end_ms: int) -> Dict[int, float]:
    """8h close map (funding ile ayni periyot)."""
    pm: Dict[int, float] = {}
    bar = ex.parse_timeframe("8h") * 1000
    since = start_ms
    while since < end_ms:
        batch = ex.fetch_ohlcv(_perp(sym), "8h", since=since, limit=1000)
        if not batch:
            break
        for r in batch:
            pm[int(r[0])] = float(r[4])
        nxt = int(batch[-1][0]) + bar
        if nxt <= since:
            break
        since = nxt
        if len(batch) < 1000:
            break
        time.sleep(max(ex.rateLimit, 200) / 1000.0)
    return pm


def analyze(symbols: List[str], start_ms: int, end_ms: int):
    import ccxt

    ex = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "future"}})
    bar8 = ex.parse_timeframe("8h") * 1000
    all_fund: List[float] = []
    all_fwd8: List[float] = []
    all_fwd24: List[float] = []
    per_sym = []
    for sym in symbols:
        fund = fetch_funding(ex, sym, start_ms, end_ms)
        pm = fetch_price_map(ex, sym, start_ms, end_ms)
        f, f8, f24 = [], [], []
        for ts, fr in fund:
            # funding ts'yi 8h grid'e hizala
            base = ts - (ts % bar8)
            p0 = pm.get(base)
            p8 = pm.get(base + bar8)
            p24 = pm.get(base + 3 * bar8)
            if p0 and p8 and p0 > 0:
                f.append(fr)
                f8.append(p8 / p0 - 1.0)
                f24.append((p24 / p0 - 1.0) if p24 else float("nan"))
        if len(f) < 50:
            print(f"  {sym}: yetersiz funding ({len(f)}) — atlandi")
            continue
        all_fund += f
        all_fwd8 += f8
        all_fwd24 += [x for x in f24]
        corr = float(np.corrcoef(f, f8)[0, 1]) if len(f) > 2 else 0.0
        # HASAT: delta-notr (long spot + short perp) short bacak funding'i TOPLAR (pozitifte alir).
        harvest_gross = float(np.prod([1.0 + x for x in f]) - 1.0) * 100.0
        days = (len(f) * 8.0) / 24.0
        harvest_apr = harvest_gross * (365.0 / days) if days > 0 else 0.0
        per_sym.append((sym, len(f), corr, harvest_gross, harvest_apr))

    fa = np.asarray(all_fund)
    r8 = np.asarray(all_fwd8)
    n = fa.size
    corr8 = float(np.corrcoef(fa, r8)[0, 1]) if n > 2 else 0.0

    # Asiri funding decile'lari: tepe %10 (kalabalik long) -> ileri getiri negatif mi?
    hi = np.quantile(fa, 0.9)
    lo = np.quantile(fa, 0.1)
    hi_ret = r8[fa >= hi]
    lo_ret = r8[fa <= lo]

    def _t(x):
        x = x[~np.isnan(x)]
        if x.size < 2:
            return 0.0, 0.0, 0
        m = float(x.mean())
        s = float(x.std(ddof=1))
        return m, (m / s * np.sqrt(x.size)) if s > 1e-12 else 0.0, x.size

    hi_m, hi_t, hi_n = _t(hi_ret)
    lo_m, lo_t, lo_n = _t(lo_ret)
    return n, corr8, per_sym, (hi, hi_m, hi_t, hi_n), (lo, lo_m, lo_t, lo_n)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Funding yon-edge teshisi")
    p.add_argument("--symbols", default="BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    args = p.parse_args(argv)
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    n, corr8, per_sym, hi, lo = analyze(symbols, _to_ms(args.start), _to_ms(args.end))

    print(f"== FUNDING YON-EDGE + HASAT | {args.start}..{args.end} | {n} funding noktasi ==")
    h_aprs = []
    for sym, cnt, corr, h_gross, h_apr in per_sym:
        h_aprs.append(h_apr)
        print(f"  {sym:10s} n={cnt:5d} corr(funding,ileri8h)={corr:+.3f} | HASAT brut={h_gross:+.1f}% (~{h_apr:+.1f}%/yil)")
    print(f"  -> HASAT ort ~{(sum(h_aprs)/len(h_aprs)) if h_aprs else 0:+.1f}%/yil (delta-notr, BRUT; islem/borc/risk maliyeti HARIC)")
    print("-" * 64)
    print(f"HAVUZ corr(funding, ileri 8h getiri) = {corr8:+.4f}  (mean-reversion icin NEGATIF beklenir)")
    print(f"ASIRI POZITIF funding (tepe %10, >={hi[0]:+.4f}): ileri8h ort={hi[1]*100:+.3f}% t={hi[2]:+.2f} n={hi[3]}")
    print("  -> mean-reversion icin bu NEGATIF + anlamli (t<=-2) olmali")
    print(f"ASIRI NEGATIF funding (dip %10, <={lo[0]:+.4f}): ileri8h ort={lo[1]*100:+.3f}% t={lo[2]:+.2f} n={lo[3]}")
    print("  -> squeeze icin bu POZITIF + anlamli (t>=2) olmali")

    edge = (hi[2] <= -2.0 and hi[1] < 0) or (lo[2] >= 2.0 and lo[1] > 0)
    print(f"\n>>> VERDIKT: {'SINYAL VAR (anlamli ters-donus) — strateji testine deger' if edge else 'YON-EDGE YOK (anlamli ters-donus bulunamadi)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
