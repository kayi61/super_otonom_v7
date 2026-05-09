"""
Faz 28 — Yüksek frekanslı sinyal motoru (tick → bar, VWAP, intraday örüntü, kuyruk/fat-tail, mikro momentum).

Girdi `tick_data` (esnek dict):
- ticks: [{price|p, ts|t|time (ms), size|v|volume?}, ...]
- veya prices / price + timestamps / ts + volumes / sizes
- Tick yoksa: close | prices | ohlcv / candles / klines (OHLCV → sentetik tick akışı)

Saf NumPy.

Çıktı standard_phase_output uyumlu; phase28 / faz28.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

import numpy as np

from super_otonom.standard_phase_output import attach_phase_alias

ScoreType = Literal["ALPHA", "RISK", "QUALITY"]
TradePermission = Literal["ALLOW", "BLOCK", "HALT"]

_EPS = 1e-12
_MIN_SAMPLES = 24
_DEFAULT_BAR_MS = 60_000
_MICRO_N_DEFAULT = 48
_TAIL_KURT_THRESHOLD = 5.5
_TAIL_EXCEED_RATE = 0.045


def _now_ms() -> int:
    return int(time.time() * 1000)


def _clamp01(x: float) -> float:
    if x != x:
        return 0.0
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else float(x)


def _normalize(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return dict(raw)


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


def _float_list(seq: Sequence[Any], min_len: int) -> Optional[np.ndarray]:
    out: List[float] = []
    for x in seq:
        try:
            fv = float(x)
            if fv == fv:
                out.append(fv)
        except (TypeError, ValueError):
            continue
    if len(out) < min_len:
        return None
    return np.asarray(out, dtype=float)


def _extract_ticks_from_dict(d: Dict[str, Any]) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    ticks = d.get("ticks") or d.get("tick_stream") or d.get("trades")
    if isinstance(ticks, list) and len(ticks) >= _MIN_SAMPLES:
        ps: List[float] = []
        ts: List[float] = []
        vs: List[float] = []
        for row in ticks:
            if not isinstance(row, dict):
                continue
            price = row.get("price") or row.get("p") or row.get("Px")
            t_raw = row.get("ts") or row.get("t") or row.get("time") or row.get("timestamp")
            v_raw = row.get("size") or row.get("volume") or row.get("v") or row.get("qty")
            try:
                p = float(price)
                t = float(t_raw) if t_raw is not None else float("nan")
                vol = float(v_raw) if v_raw is not None else 1.0
            except (TypeError, ValueError):
                continue
            if not (p == p and p > 0):
                continue
            if not (vol == vol and vol >= 0):
                vol = 1.0
            ps.append(p)
            ts.append(t)
            vs.append(max(vol, _EPS))
        if len(ps) < _MIN_SAMPLES:
            return None
        t_arr = np.asarray(ts, dtype=float)
        if bool(np.any(~np.isfinite(t_arr))) or float(np.nanmax(t_arr) - np.nanmin(t_arr)) < _EPS:
            t_arr = np.arange(len(ps), dtype=float) * 1000.0
        else:
            if float(np.max(t_arr)) < 1e11:
                t_arr = t_arr * 1000.0
        return np.asarray(ps, dtype=float), np.asarray(vs, dtype=float), t_arr

    for pk, tk in (("price", "timestamps"), ("prices", "ts"), ("mid", "times")):
        pv = d.get(pk)
        tv = d.get(tk)
        if isinstance(pv, (list, tuple)) and isinstance(tv, (list, tuple)):
            if len(pv) != len(tv) or len(pv) < _MIN_SAMPLES:
                continue
            try:
                p_arr = np.asarray([float(x) for x in pv], dtype=float)
                t_arr = np.asarray([float(x) for x in tv], dtype=float)
            except (TypeError, ValueError):
                continue
            if float(np.max(t_arr)) < 1e11:
                t_arr = t_arr * 1000.0
            vv = d.get("volumes") or d.get("sizes") or d.get("volume")
            if isinstance(vv, (list, tuple)) and len(vv) == len(p_arr):
                v_arr = np.asarray([max(float(x), _EPS) for x in vv], dtype=float)
            else:
                v_arr = np.ones(len(p_arr), dtype=float)
            return p_arr, v_arr, t_arr

    return None


def _ohlcv_closes_volumes(d: Dict[str, Any]) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    for key in ("close", "prices", "price"):
        v = d.get(key)
        if isinstance(v, (list, tuple)):
            arr = _float_list(v, _MIN_SAMPLES)
            if arr is not None:
                vols = d.get("volume") or d.get("volumes") or d.get("base_volume")
                if isinstance(vols, (list, tuple)) and len(vols) >= len(arr):
                    va = _float_list(vols[: len(arr)], len(arr))
                    if va is not None:
                        return arr, np.maximum(va, _EPS)
                return arr, np.ones(len(arr), dtype=float)

    ohlcv = d.get("ohlcv") or d.get("candles") or d.get("klines")
    if isinstance(ohlcv, list) and len(ohlcv) >= _MIN_SAMPLES:
        closes: List[float] = []
        vols: List[float] = []
        for row in ohlcv:
            if isinstance(row, (list, tuple)) and len(row) >= 5:
                try:
                    closes.append(float(row[4]))
                    vols.append(max(float(row[5]), _EPS) if len(row) > 5 else 1.0)
                except (TypeError, ValueError):
                    continue
            elif isinstance(row, dict):
                try:
                    closes.append(float(row.get("close", row.get("c", 0))))
                    vv = row.get("volume", row.get("v", 1.0))
                    vols.append(max(float(vv), _EPS))
                except (TypeError, ValueError):
                    continue
        if len(closes) >= _MIN_SAMPLES:
            return np.asarray(closes, dtype=float), np.asarray(vols[: len(closes)], dtype=float)
    return None


def _resolve_series(d: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray, np.ndarray, str]:
    """prices, volumes, timestamps_ms, source_tag."""
    ext = _extract_ticks_from_dict(d)
    if ext is not None:
        p, v, t = ext
        order = np.argsort(t)
        return p[order], v[order], t[order], "ticks"
    cv = _ohlcv_closes_volumes(d)
    if cv is None:
        z = np.zeros(0, dtype=float)
        return z, z, z, "none"
    closes, vols = cv
    ts = np.arange(len(closes), dtype=float) * float(d.get("synthetic_ts_step_ms") or 1000.0)
    return closes, vols, ts, "ohlcv"


def aggregate_ticks_to_bars(
    prices: np.ndarray,
    volumes: np.ndarray,
    timestamps_ms: np.ndarray,
    *,
    bar_window_ms: float,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Her bar: OHLC + VWAP + hacim."""
    if len(prices) == 0:
        z = np.zeros(0, dtype=float)
        return z, z, z, z, z
    bucket = np.floor(timestamps_ms / max(bar_window_ms, _EPS)).astype(np.int64)
    uniq = np.unique(bucket)
    o = np.zeros(len(uniq))
    h = np.zeros(len(uniq))
    low = np.zeros(len(uniq))
    c = np.zeros(len(uniq))
    vwap = np.zeros(len(uniq))
    vol = np.zeros(len(uniq))
    for i, b in enumerate(uniq):
        mask = bucket == b
        seg_p = prices[mask]
        seg_v = volumes[mask]
        o[i] = seg_p[0]
        h[i] = float(np.max(seg_p))
        low[i] = float(np.min(seg_p))
        c[i] = seg_p[-1]
        pv = float(np.sum(seg_p * seg_v))
        sv = float(np.sum(seg_v)) + _EPS
        vwap[i] = pv / sv
        vol[i] = sv
    return o, h, low, c, vwap


def _session_fraction(timestamps_ms: np.ndarray) -> np.ndarray:
    t0 = float(np.min(timestamps_ms))
    t1 = float(np.max(timestamps_ms))
    span = max(t1 - t0, _EPS)
    return (timestamps_ms - t0) / span


def _intraday_pattern_scores(timestamps_ms: np.ndarray, prices: np.ndarray) -> Tuple[float, float, float, float]:
    """Açılış / öğle / kapanış bölgelerinde ortalama tick getirisi (normalize)."""
    if len(prices) < 3:
        return 0.0, 0.0, 0.0, 0.0
    ret = np.diff(prices) / np.maximum(prices[:-1], _EPS)
    frac = _session_fraction(timestamps_ms)
    fr = frac[1:]
    open_m = float(np.mean(ret[fr < 0.15])) if np.any(fr < 0.15) else 0.0
    lunch_m = float(np.mean(ret[(fr >= 0.35) & (fr <= 0.65)])) if np.any((fr >= 0.35) & (fr <= 0.65)) else 0.0
    close_m = float(np.mean(ret[fr > 0.85])) if np.any(fr > 0.85) else 0.0
    zones = np.array([open_m, lunch_m, close_m], dtype=float)
    spread = float(np.max(zones) - np.min(zones))
    patt_strength = _clamp01(abs(spread) * 80.0)
    return open_m, lunch_m, close_m, patt_strength


def _micro_momentum(prices: np.ndarray, n: int) -> float:
    if len(prices) < 2:
        return 0.5
    r = np.diff(prices)
    k = min(max(1, n), len(r))
    tail = r[-k:]
    heat = float(np.mean(np.sign(tail)))
    return _clamp01(0.5 + 0.5 * heat)


def _excess_kurtosis(x: np.ndarray) -> float:
    x = np.asarray(x, dtype=float)
    if len(x) < 8:
        return 0.0
    m = float(np.mean(x))
    v = float(np.var(x)) + _EPS
    m4 = float(np.mean((x - m) ** 4))
    return m4 / (v * v) - 3.0


def _fat_tail_metrics(returns: np.ndarray) -> Tuple[bool, float, float]:
    """Fat tail: yüksek ekser kurtosis veya aşırı uç oranı."""
    if len(returns) < 12:
        return False, 0.0, 0.0
    xs = _excess_kurtosis(returns)
    sig = float(np.std(returns)) + _EPS
    mu = float(np.mean(returns))
    z = np.abs(returns - mu) / sig
    exceed = float(np.mean(z > 3.0))
    tail_prob = _clamp01(max(exceed / max(_TAIL_EXCEED_RATE, _EPS), xs / max(_TAIL_KURT_THRESHOLD, _EPS)) * 0.45)
    fat = bool(xs > _TAIL_KURT_THRESHOLD or exceed > _TAIL_EXCEED_RATE)
    return fat, xs, tail_prob


def _empty_phase28(ts: int, half_life_ms: int, reason: str) -> Dict[str, Any]:
    return {
        "trade_permission": "BLOCK",
        "alpha_score": 0.0,
        "risk_score": 1.0,
        "confidence": 0.0,
        "data_health": 0.0,
        "event_ts": float(ts),
        "half_life_ms": int(half_life_ms),
        "score_type": "QUALITY",
        "phase": "28",
        "source": "hft_signal_engine",
        "empty_reason": reason,
        "hft_signal": {},
    }


def analyze_hft_signal(
    symbol: str,
    tick_data: Any,
    analysis: Optional[Dict[str, Any]] = None,
    *,
    attach_to_analysis: bool = True,
    half_life_ms: int = 42_000,
    event_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Tick veya OHLCV üzerinden HFT sinyal özeti; `analysis['phase28']` / `['faz28']` yazar.
    """
    _ = symbol
    a = analysis if analysis is not None else {}
    ts = int(event_ts) if event_ts is not None else _try_ts_ms(a)
    d = _normalize(tick_data)

    if not d:
        payload = _empty_phase28(ts, half_life_ms, "no_hft_data")
        if attach_to_analysis:
            attach_phase_alias(a, "28", payload)
        return payload

    prices, volumes, timestamps_ms, source = _resolve_series(d)
    if len(prices) < _MIN_SAMPLES or source == "none":
        payload = _empty_phase28(ts, half_life_ms, "insufficient_ticks")
        if attach_to_analysis:
            attach_phase_alias(a, "28", payload)
        return payload

    bar_ms = float(d.get("bar_window_ms") or d.get("bar_ms") or _DEFAULT_BAR_MS)
    if source == "ohlcv" and d.get("bar_window_ms") is None:
        bar_ms = max(float(len(prices)) * 500.0, _DEFAULT_BAR_MS)

    o, h, lo, c_bar, vwap_bars = aggregate_ticks_to_bars(prices, volumes, timestamps_ms, bar_window_ms=bar_ms)

    cum_pv = np.cumsum(prices * volumes)
    cum_v = np.cumsum(volumes) + _EPS
    vwap_path = cum_pv / cum_v
    last_px = float(prices[-1])
    vwap_now = float(vwap_path[-1])
    vwap_dev = abs(last_px - vwap_now) / max(vwap_now, _EPS)
    vwap_dev_risk = _clamp01(min(vwap_dev * 35.0, 1.0))

    tick_ret = np.diff(prices) / np.maximum(prices[:-1], _EPS)
    bar_ret = np.diff(c_bar) / np.maximum(c_bar[:-1], _EPS) if len(c_bar) > 2 else tick_ret
    ret_use = bar_ret if len(bar_ret) >= 8 else tick_ret

    fat_tail, xs_kurt, tail_prob = _fat_tail_metrics(ret_use)

    open_e, lunch_e, close_e, patt_risk = _intraday_pattern_scores(timestamps_ms, prices)

    micro_n = int(d.get("micro_N") or _MICRO_N_DEFAULT)
    micro_heat = _micro_momentum(prices, micro_n)

    patt_risk_c = _clamp01(patt_risk * 0.85)
    tail_risk = _clamp01(0.55 * tail_prob + 0.45 * _clamp01(xs_kurt / 12.0))

    risk_01 = _clamp01(
        0.30 * vwap_dev_risk
        + 0.22 * patt_risk_c
        + 0.28 * tail_risk
        + 0.12 * _clamp01(float(np.std(tick_ret)) * 45.0)
        + 0.08 * float(fat_tail)
    )
    if vwap_dev_risk > 0.78:
        risk_01 = _clamp01(max(risk_01, 0.74))
    if fat_tail:
        risk_01 = _clamp01(max(risk_01, 0.82))

    alpha_raw = (
        0.38 * micro_heat
        + 0.22 * (1.0 - vwap_dev_risk)
        + 0.18 * _clamp01(abs(open_e - close_e) * 120.0)
        + 0.14 * (1.0 - patt_risk_c)
        + 0.08 * _clamp01(1.0 - tail_risk)
    )
    if micro_heat > 0.72 or micro_heat < 0.28:
        alpha_raw = _clamp01(alpha_raw * 1.12 + 0.06)

    alpha_01 = _clamp01(alpha_raw)
    if fat_tail:
        alpha_01 = _clamp01(alpha_01 * 0.28)

    conf = _clamp01(
        0.26
        + 0.34 * (1.0 - vwap_dev_risk)
        + 0.22 * (1.0 - patt_risk_c)
        + 0.18 * (1.0 - tail_risk)
    )

    n_eff = len(prices)
    dh = _clamp01(
        0.22
        + 0.28 * min(1.0, n_eff / 2000.0)
        + 0.28 * (1.0 - vwap_dev_risk * 0.5)
        + 0.22 * (1.0 - tail_risk)
    )

    perm: TradePermission = "ALLOW"
    if d.get("force_halt") is True:
        perm = "HALT"
    elif fat_tail:
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
        "phase": "28",
        "source": "hft_signal_engine",
        "hft_signal": {
            "data_source": source,
            "tick_count": int(len(prices)),
            "bar_window_ms": float(bar_ms),
            "bar_count": int(len(c_bar)),
            "vwap_deviation_abs": float(vwap_dev),
            "vwap_deviation_score": float(vwap_dev_risk),
            "micro_momentum_score": float(micro_heat),
            "micro_momentum_heat": float(micro_heat),
            "micro_N": int(min(micro_n, max(len(prices) - 1, 1))),
            "intraday_pattern": {
                "open_effect": float(open_e),
                "lunch_effect": float(lunch_e),
                "close_effect": float(close_e),
                "pattern_dispersion_score": float(patt_risk),
            },
            "queue_tail_risk": {
                "fat_tail_detected": bool(fat_tail),
                "excess_kurtosis": float(xs_kurt),
                "tail_exceedance_score": float(tail_prob),
            },
            "aggregated_last_bar": {
                "open": float(o[-1]) if len(o) else last_px,
                "high": float(h[-1]) if len(h) else last_px,
                "low": float(lo[-1]) if len(lo) else last_px,
                "close": float(c_bar[-1]) if len(c_bar) else last_px,
                "vwap": float(vwap_bars[-1]) if len(vwap_bars) else vwap_now,
            },
        },
    }

    if attach_to_analysis:
        attach_phase_alias(a, "28", payload)

    return payload


def run_hft_signal_phase(
    symbol: str,
    tick_data: Any,
    analysis: Optional[Dict[str, Any]] = None,
    *,
    attach_to_analysis: bool = True,
    half_life_ms: int = 42_000,
    event_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """Pipeline girişi — `analyze_hft_signal` ile aynı."""
    return analyze_hft_signal(
        symbol,
        tick_data,
        analysis,
        attach_to_analysis=attach_to_analysis,
        half_life_ms=half_life_ms,
        event_ts=event_ts,
    )
