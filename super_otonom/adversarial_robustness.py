"""
Faz 33 — Karşıt / manipülasyon dayanıklılığı (flash crash, pump-dump, slow bleed, vol spike, fake breakout).

Girdi `market_data` (esnek dict):
- ohlcv | candles | klines: [[ts,o,h,l,c,v], ...]
- veya close + high + low (+ open, volume) eş uzunlukta diziler

Her senaryo [0,1] skor üretir. Özet risk ve alpha bu skorlardan türetilir.

Özel kurallar:
- Flash crash skoru yüksek → HALT
- Pump & dump skoru yüksek → HALT
- Volatility spike şiddetli → BLOCK
- Fake breakout → alpha düşür + BLOCK
- Slow bleed → risk artırır (doğrudan HALT/BLOCK tetiklemez)

Çıktı Faz 16–32 ile uyumlu; phase33 / faz33.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Literal, Optional, Tuple

import numpy as np

from super_otonom.standard_phase_output import attach_phase_alias

ScoreType = Literal["ALPHA", "RISK", "QUALITY"]
TradePermission = Literal["ALLOW", "BLOCK", "HALT"]

_EPS = 1e-12
_MIN_BARS = 48


def _now_ms() -> int:
    return int(time.time() * 1000)


def _clamp01(x: float) -> float:
    if x != x:
        return 0.0
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else float(x)


def _try_ts_ms(analysis: Dict[str, Any]) -> int:
    v = analysis.get("event_ts") or analysis.get("candle_ts")
    try:
        if v is None:
            return _now_ms()
        fv = float(v)
        if fv < 1e11:
            return int(fv * 1000.0)
        return int(fv)
    except (TypeError, ValueError):
        return _now_ms()


def _pick_score_type(data_health: float, risk_01: float) -> ScoreType:
    if data_health < 0.42:
        return "QUALITY"
    if risk_01 >= 0.72:
        return "RISK"
    return "ALPHA"


def _normalize(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return dict(raw)


def _series_from_dict(d: Dict[str, Any], key: str) -> Optional[np.ndarray]:
    v = d.get(key)
    if not isinstance(v, (list, tuple)) or len(v) < _MIN_BARS:
        return None
    out: List[float] = []
    for x in v:
        try:
            fv = float(x)
            if fv == fv and fv > 0:
                out.append(fv)
        except (TypeError, ValueError):
            continue
    if len(out) < _MIN_BARS:
        return None
    return np.asarray(out, dtype=float)


def extract_ohlcv(d: Dict[str, Any]) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]]:
    """OHLCV dizileri; eksikse close üzerinden sentez."""
    ohlcv = d.get("ohlcv") or d.get("candles") or d.get("klines")
    if isinstance(ohlcv, list) and len(ohlcv) >= _MIN_BARS:
        o_arr: List[float] = []
        h_arr: List[float] = []
        l_arr: List[float] = []
        c_arr: List[float] = []
        v_arr: List[float] = []
        for row in ohlcv:
            if isinstance(row, (list, tuple)) and len(row) >= 5:
                try:
                    o_arr.append(float(row[1]))
                    h_arr.append(float(row[2]))
                    l_arr.append(float(row[3]))
                    c_arr.append(float(row[4]))
                    v_arr.append(float(row[5]) if len(row) > 5 else 0.0)
                except (TypeError, ValueError):
                    continue
        if len(c_arr) >= _MIN_BARS:
            return (
                np.asarray(o_arr, dtype=float),
                np.asarray(h_arr, dtype=float),
                np.asarray(l_arr, dtype=float),
                np.asarray(c_arr, dtype=float),
                np.asarray(v_arr, dtype=float),
            )

    c = _series_from_dict(d, "close")
    if c is None:
        c = _series_from_dict(d, "prices")
    if c is None:
        c = _series_from_dict(d, "price")
    if c is None:
        return None
    h = _series_from_dict(d, "high")
    l = _series_from_dict(d, "low")
    o = _series_from_dict(d, "open")
    if h is None:
        h = c.copy()
    if l is None:
        l = c.copy()
    if o is None:
        o = np.roll(c, 1)
        o[0] = c[0]
    vol = _series_from_dict(d, "volume")
    if vol is None:
        vol = np.zeros_like(c)
    n = min(len(c), len(h), len(l), len(o), len(vol))
    return o[:n], h[:n], l[:n], c[:n], vol[:n]


def score_flash_crash(c: np.ndarray, l: np.ndarray) -> float:
    """Tek/çok barlı ani düşüş (wick ve kapanış)."""
    if c.size < 8:
        return 0.0
    prev = np.roll(c, 1)
    prev[0] = c[0]
    bar_ret = np.log(np.maximum(c / np.maximum(prev, _EPS), _EPS))
    worst_bar = float(np.min(bar_ret))
    # Düşük vs önceki kapanış (intrabar çöküş)
    wick_to_prev = np.log(np.maximum(l / np.maximum(prev, _EPS), _EPS))
    worst_wick = float(np.min(wick_to_prev[1:]))
    tail = min(worst_bar, worst_wick)
    # kümülatif 3 bar düşüş
    if c.size >= 4:
        r3 = np.log(c[-1] / np.maximum(c[-4], _EPS))
        tail = min(tail, float(r3))
    if tail >= -0.025:
        return 0.0
    return _clamp01((-tail - 0.025) / 0.14)


def score_pump_dump(c: np.ndarray, v: np.ndarray) -> float:
    """Hızlı yükseliş + sonrasında keskin düşüş (veya tepe sonrası çöküş)."""
    if c.size < 24:
        return 0.0
    lr = np.diff(np.log(np.maximum(c, _EPS)))
    n = lr.size
    best = 0.0
    for w in (5, 8, 12):
        for i in range(w, n - w):
            pump = float(np.sum(lr[i - w : i]))
            dump = float(np.sum(lr[i : i + w]))
            vol_ratio = 1.0
            if v.size == c.size:
                num_v = v[i - w : i]
                den_v = v[max(0, i - 3 * w) : max(0, i - w)]
                if num_v.size and den_v.size:
                    vr = float(np.mean(num_v) / (np.mean(den_v) + _EPS))
                    vol_ratio = _clamp01((vr - 1.0) / 3.0 + 0.5)
            if pump > 0.04 and dump < -0.035:
                cand = _clamp01((pump / 0.22) * 0.55 + (abs(dump) / 0.18) * 0.45) * (0.75 + 0.25 * vol_ratio)
                best = max(best, cand)
    peak_i = int(np.argmax(c[-36:])) + max(0, c.size - 36)
    pk = float(c[peak_i])
    trail_min = float(np.min(c[peak_i:]))
    dd_from_peak = (trail_min - pk) / max(pk, _EPS)
    if dd_from_peak < -0.06 and peak_i < c.size - 3:
        rise = float(pk / max(float(np.min(c[max(0, peak_i - 15) : peak_i])), _EPS) - 1.0)
        drop_score = _clamp01(abs(dd_from_peak) / 0.18)
        rise_score = _clamp01(rise / 0.25)
        best = max(best, 0.5 * drop_score + 0.5 * rise_score)
    return float(best)


def score_slow_bleed(c: np.ndarray) -> float:
    """Yavaş erozyon: belirgin negatif eğim, düşük tek-bar şok."""
    if c.size < 32:
        return 0.0
    w = c[-40:]
    x = np.arange(w.size, dtype=float)
    slope, _ = np.polyfit(x, w, 1)
    mean_c = float(np.mean(w))
    rel_slope = float(-slope / max(mean_c, _EPS))
    lr = np.diff(np.log(np.maximum(c[-40:], _EPS)))
    shock = float(np.min(lr)) if lr.size else 0.0
    # Şiddetli flash değilse bleed daha güvenilir
    shock_pen = _clamp01(1.0 + shock / 0.08) if shock < -0.02 else 1.0
    bleed = _clamp01(rel_slope * 120.0) * (0.55 + 0.45 * shock_pen)
    if rel_slope <= 0:
        bleed *= 0.35
    return float(bleed)


def score_volatility_spike(c: np.ndarray) -> float:
    """Kısa vadeli realized vol / uzun vadeli tabana oranı."""
    lr = np.diff(np.log(np.maximum(c, _EPS)))
    if lr.size < 30:
        return 0.0
    short = lr[-12:] if lr.size >= 12 else lr[-6:]
    if lr.size > 36:
        long = lr[:-12]
    else:
        mid = max(8, lr.size // 2)
        long = lr[:mid]
    if long.size < 8:
        long = lr[: max(8, lr.size - short.size)]
    if long.size < 4:
        return 0.0
    s_s = float(np.std(short))
    s_l = float(np.std(long))
    ratio = s_s / (s_l + _EPS)
    if ratio <= 1.15:
        return _clamp01((ratio - 1.0) / 0.15 * 0.35)
    return _clamp01((ratio - 1.15) / 1.85)


def score_fake_breakout(h: np.ndarray, l: np.ndarray, c: np.ndarray) -> float:
    """Direnç üstü fitil / teğet sonra kapanışın geri dönmesi."""
    if c.size < 35:
        return 0.0
    look = 28
    hb = h[-1]
    resist = float(np.max(c[-look:-4]))
    prev_high = float(np.max(h[-look:-2]))
    poke = hb > resist * 1.001 and hb > prev_high * 1.0005
    fail_close = float(c[-1]) < resist * 1.0005 or float(c[-1]) < float(c[-2])
    upper_wick = hb > max(float(c[-1]), float(l[-1])) * 1.0002
    if poke and (fail_close or upper_wick):
        depth = (hb - float(c[-1])) / max(hb, _EPS)
        return _clamp01(0.45 + 0.55 * _clamp01(depth / 0.05))
    # Son 5 barda sahte kırılım
    for j in range(1, min(6, c.size - look)):
        resist2 = float(np.max(c[-look - j : -4 - j]))
        if float(h[-j]) > resist2 * 1.002 and float(c[-j]) < resist2:
            return max(0.35, _clamp01(0.4 + 0.02 * j))
    return 0.0


def analyze_adversarial_robustness(
    symbol: str,
    market_data: Any,
    analysis: Optional[Dict[str, Any]] = None,
    *,
    attach_to_analysis: bool = True,
    half_life_ms: int = 48_000,
    event_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Karşıt senaryo özeti; `analysis['phase33']` / `['faz33']` yazar.
    """
    _ = symbol
    a = analysis if analysis is not None else {}
    ts = int(event_ts) if event_ts is not None else _try_ts_ms(a)
    d = _normalize(market_data)

    if not d:
        payload = _empty_phase33(ts, half_life_ms, "no_market_data")
        if attach_to_analysis:
            attach_phase_alias(a, "33", payload)
        return payload

    ohlc = extract_ohlcv(d)
    if ohlc is None:
        payload = _empty_phase33(ts, half_life_ms, "insufficient_bars")
        if attach_to_analysis:
            attach_phase_alias(a, "33", payload)
        return payload

    _o, h, l, c, v = ohlc
    if c.size < _MIN_BARS:
        payload = _empty_phase33(ts, half_life_ms, "insufficient_bars")
        if attach_to_analysis:
            attach_phase_alias(a, "33", payload)
        return payload

    s_flash = score_flash_crash(c, l)
    s_pump = score_pump_dump(c, v)
    s_bleed = score_slow_bleed(c)
    s_vol = score_volatility_spike(c)
    s_fake = score_fake_breakout(h, l, c)

    # Risk: slow bleed ağırlıklı; vol ve yapısal senaryolar
    risk_01 = _clamp01(
        0.22 * s_flash
        + 0.22 * s_pump
        + 0.20 * s_bleed
        + 0.22 * s_vol
        + 0.14 * s_fake
    )
    risk_01 = _clamp01(risk_01 + 0.12 * s_bleed)

    # Alpha: fake breakout ve yüksek yapısal risk ile düşer
    alpha_base = _clamp01(0.55 * (1.0 - s_flash) * (1.0 - s_pump) + 0.45 * (1.0 - s_vol * 0.85))
    alpha_01 = _clamp01(alpha_base * (1.0 - 0.55 * s_fake) * (1.0 - 0.25 * s_bleed))

    hist_ok = c.size >= 64
    conf = _clamp01(0.22 + 0.38 * (1.0 - s_vol * 0.7) * (1.0 - s_fake * 0.5) + 0.18 * (1.0 if hist_ok else 0.4))
    dh = _clamp01(0.26 + 0.30 * (1.0 - s_flash) * (1.0 - s_pump) + 0.24 * (1.0 - s_fake) + 0.20 * (1.0 if hist_ok else 0.35))

    perm: TradePermission = "ALLOW"
    if s_flash >= 0.42:
        perm = "HALT"
    elif s_pump >= 0.42:
        perm = "HALT"
    elif s_vol >= 0.72:
        perm = "BLOCK"
    elif s_fake >= 0.38:
        perm = "BLOCK"
    elif risk_01 >= 0.88:
        perm = "BLOCK"
    elif risk_01 >= 0.72:
        perm = "BLOCK"

    st = _pick_score_type(dh, risk_01)

    payload: Dict[str, Any] = {
        "trade_permission": perm,
        "alpha_score": float(alpha_01),
        "risk_score": float(risk_01),
        "confidence": float(conf),
        "data_health": float(dh),
        "event_ts": float(ts),
        "half_life_ms": int(half_life_ms),
        "score_type": st,
        "phase": "33",
        "source": "adversarial_robustness",
        "adversarial": {
            "flash_crash_score": float(s_flash),
            "pump_dump_score": float(s_pump),
            "slow_bleed_score": float(s_bleed),
            "volatility_spike_score": float(s_vol),
            "fake_breakout_score": float(s_fake),
            "bars": int(c.size),
        },
    }

    if attach_to_analysis:
        attach_phase_alias(a, "33", payload)

    return payload


def run_adversarial_phase(
    symbol: str,
    market_data: Any,
    analysis: Optional[Dict[str, Any]] = None,
    *,
    attach_to_analysis: bool = True,
    half_life_ms: int = 48_000,
    event_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """Pipeline girişi — `analyze_adversarial_robustness` ile aynı."""
    return analyze_adversarial_robustness(
        symbol,
        market_data,
        analysis,
        attach_to_analysis=attach_to_analysis,
        half_life_ms=half_life_ms,
        event_ts=event_ts,
    )


def _empty_phase33(ts: int, half_life_ms: int, reason: str) -> Dict[str, Any]:
    return {
        "trade_permission": "BLOCK",
        "alpha_score": 0.0,
        "risk_score": 1.0,
        "confidence": 0.0,
        "data_health": 0.0,
        "event_ts": float(ts),
        "half_life_ms": int(half_life_ms),
        "score_type": "QUALITY",
        "phase": "33",
        "source": "adversarial_robustness",
        "empty_reason": reason,
        "adversarial": {},
    }
