"""Null-kontrol: permutasyon / Monte-Carlo testi ile sahte edge'i ve harness sizintisini yakala.

NEDEN: Bir backtest "edge var" diyebilir; ama bu (a) gercek bir tahmin gucu mu, yoksa
(b) sans/overfit/look-ahead sizintisi mi? Ayirmak icin: stratejiyi ZAMAN YAPISI YOK EDILMIS
(karistirilmis) veride yuzlerce kez kosturup istatistigin NULL DAGILIMINI kurariz. Gercek
sonuc ancak bu dagilimin UC KUYRUGUNDAYSA (ampirik p-deger kucuk) anlamlidir.

Bu yontem iki seyi ayni anda yakalar:
  1. SAHTE EDGE (sans): gercek istatistik null dagiliminin icinde kaliyorsa -> sans, oldur.
  2. SIZINTI (look-ahead): sizintili strateji karistirilmis veride DE yuksek skor verir
     (gelecege bakma her veride calisir) -> null dagilimi da yuksek -> gercek skor uc kuyrukta
     DEGIL -> p anlamsiz -> artefakt olarak damgalanir. Bu, en sinsi hatayi yakalar.

Edge URETMEZ. Gercek edge'i sahteden ayirir. "Masallari" eler.

Referans yaklasim: permutasyon testi / Monte-Carlo reality-check (White 2000 ruhu),
non-parametrik -> normal-dagilim varsayimina ihtiyac duymaz (t-istatistiginden daha durust).
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import numpy as np

Candle = Dict[str, Any]
# Bir stratejiyi mum listesi uzerinde kosturup TEK skaler istatistik dondurur
# (orn: net ortalama islem %, Sharpe, toplam getiri). Yuksek = daha iyi olmali.
StatFn = Callable[[List[Candle]], float]


def _col(candles: List[Candle], key: str, default: Optional[float] = None) -> np.ndarray:
    if default is not None and (not candles or key not in candles[0]):
        return np.full(len(candles), default, dtype=float)
    return np.asarray([float(c[key]) for c in candles], dtype=float)


def shuffle_bars(candles: List[Candle], rng: np.random.Generator) -> List[Candle]:
    """Bar SIRASINI rastgele karistir; her barin ic OHLC geometrisi ve hareket dagilimi
    korunur, ama ZAMAN YAPISI (autocorrelation/trend) yok edilir.

    Yontem: ilk mumu CAPA olarak sabit tut; kalan her bari (gross close-getiri g_i +
    barin KENDI close'una gore intrabar oranlari open/close, high/close, low/close) ile
    temsil et; bu demetlerin SIRASINI karistir; mutlak fiyatlari bastan kur. Boylece
    bar-getiri COKLUGU TAM KORUNUR (sorted(getiriler) ayni), sadece SIRA degisir ->
    zaman yapisi (autocorrelation/trend) silinir. Trend'e dayanan gercek edge null'da
    kaybolmali; sirayla-degismeyen bir istatistik (orn. look-ahead artefakti) ise null'da
    da AYNI kalir -> ayirt edilemez -> dogru sekilde elenir.
    """
    n = len(candles)
    if n < 3:
        return [dict(c) for c in candles]
    close = _col(candles, "close")
    open_ = _col(candles, "open")
    high = _col(candles, "high")
    low = _col(candles, "low")
    vol = _col(candles, "volume", 1.0)
    safe = np.where(close == 0.0, 1e-12, close)
    # bar i (i=1..n-1): onceki kapanisa gore gross getiri + kendi close'una gore intrabar
    g = close[1:] / safe[:-1]
    c_ref = safe[1:]
    oc, hc, lc = open_[1:] / c_ref, high[1:] / c_ref, low[1:] / c_ref
    v = vol[1:]
    order = rng.permutation(n - 1)
    g, oc, hc, lc, v = g[order], oc[order], hc[order], lc[order], v[order]
    first = dict(candles[0])
    first["timestamp"] = 0.0
    out: List[Candle] = [first]
    c_prev = float(close[0])
    for k in range(n - 1):
        c = c_prev * float(g[k])
        o = c * float(oc[k])
        h = c * float(hc[k])
        lo = c * float(lc[k])
        out.append(
            {
                "timestamp": float(k + 1),
                "open": o,
                "high": float(max(h, o, c)),
                "low": float(min(lo, o, c)),
                "close": c,
                "volume": float(v[k]),
            }
        )
        c_prev = c
    return out


def random_walk_candles(
    n: int,
    rng: np.random.Generator,
    *,
    start: float = 100.0,
    mu: float = 0.0,
    sigma: float = 0.02,
) -> List[Candle]:
    """Saf rastgele yuruyus (gercel-olcum edge yok, insa geregi). Sentetik null.

    mu=0 -> driftsiz; herhangi bir stratejinin maliyet-sonrasi beklentisi <=0 olmali.
    """
    if n < 2:
        n = 2
    rets = rng.normal(mu, sigma, n)
    close = start * np.exp(np.cumsum(rets))
    out: List[Candle] = []
    for i in range(n):
        o = float(close[i - 1]) if i > 0 else start
        c = float(close[i])
        wick = abs(rng.normal(0.0, sigma / 2.0))
        h = max(o, c) * (1.0 + wick)
        lo = min(o, c) * (1.0 - wick)
        out.append(
            {
                "timestamp": float(i),
                "open": o,
                "high": h,
                "low": lo,
                "close": c,
                "volume": 1.0,
            }
        )
    return out


def permutation_null_distribution(
    stat_fn: StatFn,
    candles: List[Candle],
    *,
    n_perm: int = 500,
    method: str = "shuffle",
    seed: int = 42,
    synth_len: Optional[int] = None,
) -> np.ndarray:
    """Null hipotezi ("edge yok") altinda istatistigin dagilimini Monte-Carlo ile kur.

    method="shuffle": gercek mumlarin bar-sirasini karistirir (zaman yapisi yok).
    method="random_walk": saf rastgele yuruyus uretir (insa geregi edge yok).
    """
    rng = np.random.default_rng(seed)
    n = len(candles)
    stats: List[float] = []
    for _ in range(n_perm):
        if method == "shuffle":
            null_c = shuffle_bars(candles, rng)
        elif method == "random_walk":
            null_c = random_walk_candles(synth_len or n, rng)
        else:
            raise ValueError(f"bilinmeyen method: {method!r} (shuffle|random_walk)")
        try:
            s = float(stat_fn(null_c))
        except Exception:
            s = float("nan")
        if np.isfinite(s):
            stats.append(s)
    return np.asarray(stats, dtype=float)


def empirical_pvalue(observed: float, null_dist: np.ndarray) -> float:
    """Tek-tarafli ampirik p-deger: null'un gercek skoru >= verme olasiligi.

    (1 + #{null >= observed}) / (1 + N)  -- add-one (yansiz, asla 0 dondurmez).
    Kucuk p (ornek <0.05) = "bu sonuc sans/sizintiyla zor aciklanir" = gercek aday.
    Buyuk p = "null bunu rahat uretir" = SAHTE/sans -> oldur.
    """
    null_dist = np.asarray(null_dist, dtype=float)
    null_dist = null_dist[np.isfinite(null_dist)]
    n = null_dist.size
    if n == 0:
        return 1.0
    ge = int(np.sum(null_dist >= observed))
    return (1.0 + ge) / (1.0 + n)


def null_control_test(
    stat_fn: StatFn,
    candles: List[Candle],
    *,
    n_perm: int = 500,
    method: str = "shuffle",
    seed: int = 42,
    alpha: float = 0.05,
    synth_len: Optional[int] = None,
) -> Dict[str, Any]:
    """NULL-KONTROL KAPISI. Bir stratejinin skorunun gercek mi sans/sizinti mi oldugunu olcer.

    Donen dict:
      observed     : stratejinin gercek veride skoru
      null_mean/std: null dagiliminin merkezi/yayilimi
      null_q95/q99 : null'un ust kuyruk esikleri (gecmek icin asilmali)
      z_vs_null    : (observed - null_mean) / null_std
      p_value      : ampirik tek-tarafli p
      n_eff        : gecerli null orneklem sayisi
      passes_null  : p < alpha  (= "null bunu kolay uretemiyor" = gercek aday)
      verdict      : 'REAL_CANDIDATE' | 'INDISTINGUISHABLE_FROM_NULL'

    DIKKAT: passes_null=True "edge var" DEMEK DEGIL; sadece "sans/sizinti ile aciklanamaz,
    bir sonraki kapiya (out-of-sample, maliyet, hold-out) aday." passes_null=False ise -> OLDUR.
    """
    try:
        observed = float(stat_fn(candles))
    except Exception as exc:  # pragma: no cover - cagiranin stat_fn'i bozuksa
        raise ValueError(f"stat_fn gercek veride basarisiz: {exc}") from exc

    null = permutation_null_distribution(
        stat_fn, candles, n_perm=n_perm, method=method, seed=seed, synth_len=synth_len
    )
    n_eff = int(null.size)
    null_mean = float(np.mean(null)) if n_eff else 0.0
    null_std = float(np.std(null, ddof=1)) if n_eff > 1 else 0.0
    p = empirical_pvalue(observed, null)
    passes = bool(np.isfinite(observed) and p < alpha)
    return {
        "observed": observed,
        "null_mean": null_mean,
        "null_std": null_std,
        "null_q95": float(np.quantile(null, 0.95)) if n_eff else 0.0,
        "null_q99": float(np.quantile(null, 0.99)) if n_eff else 0.0,
        "z_vs_null": float((observed - null_mean) / null_std) if null_std > 1e-12 else 0.0,
        "p_value": p,
        "n_eff": n_eff,
        "method": method,
        "alpha": alpha,
        "passes_null": passes,
        "verdict": "REAL_CANDIDATE" if passes else "INDISTINGUISHABLE_FROM_NULL",
    }


def format_report(name: str, res: Dict[str, Any]) -> str:
    """Insan-okur null-kontrol raporu."""
    icon = "OK" if res["passes_null"] else "X"
    lines = [
        f"== NULL-KONTROL: {name} ==",
        f"  yontem        : {res['method']}  (n_eff={res['n_eff']})",
        f"  gercek skor   : {res['observed']:+.6f}",
        f"  null ortalama : {res['null_mean']:+.6f}  (std {res['null_std']:.6f})",
        f"  null q95/q99  : {res['null_q95']:+.6f} / {res['null_q99']:+.6f}",
        f"  z vs null     : {res['z_vs_null']:+.2f}",
        f"  ampirik p     : {res['p_value']:.4f}  (alpha {res['alpha']})",
        f"  >>> [{icon}] {res['verdict']}"
        + (
            "  (sans/sizinti ile aciklanamaz -> bir sonraki kapiya aday)"
            if res["passes_null"]
            else "  (null bunu kolay uretir -> SAHTE/sans, OLDUR)"
        ),
    ]
    return "\n".join(lines)
