"""
Faz 31 — Nedensel alpha motoru (Granger proxy, transfer entropy proxy, sahte korelasyon).

Girdi `causal_data` (esnek dict):
- series_a / series_b veya price_a / price_b veya leader / follower — eş uzunlukta sayı dizileri
- use_log_returns: varsayılan True (fiyat seviyesi ise log-getiriye çevrilir)
- max_lag: Granger ve gecikme taraması için üst sınır (varsayılan 6)

Çıktı Faz 16–25 ile uyumlu; phase31 / faz31.

Özel kurallar:
- Güçlü nedensellik + düşük gecikme → yüksek alpha_score
- Sahte korelasyon → confidence düşük, trade_permission BLOCK
- Transfer entropy düşükse alpha düşürülür (bloke etmez tek başına)
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

import numpy as np

from super_otonom.standard_phase_output import attach_phase_alias

ScoreType = Literal["ALPHA", "RISK", "QUALITY"]
TradePermission = Literal["ALLOW", "BLOCK", "HALT"]

_EPS = 1e-12
_MIN_POINTS = 28


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


def _normalize_causal(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return dict(raw)


def _as_float_series(seq: Any) -> List[float]:
    if not isinstance(seq, (list, tuple)) or len(seq) < 3:
        return []
    out: List[float] = []
    for v in seq:
        try:
            x = float(v)
            if x == x:
                out.append(x)
        except (TypeError, ValueError):
            continue
    return out


def _extract_ab_series(d: Dict[str, Any]) -> Tuple[List[float], List[float]]:
    """İki seriyi çıkar; anahtar adları esnek."""
    keys_a = ("series_a", "price_a", "leader", "a", "primary", "x")
    keys_b = ("series_b", "price_b", "follower", "b", "secondary", "y")
    a = None
    b = None
    for k in keys_a:
        if k in d and d[k] is not None:
            a = _as_float_series(d[k])
            if a:
                break
    for k in keys_b:
        if k in d and d[k] is not None:
            b = _as_float_series(d[k])
            if b:
                break
    if not a or not b:
        return [], []
    n = min(len(a), len(b))
    return a[:n], b[:n]


def _to_log_returns(levels: Sequence[float]) -> np.ndarray:
    xs = np.asarray(levels, dtype=float)
    if xs.size < 3:
        return np.array([])
    r = np.diff(np.log(np.maximum(xs, _EPS)))
    return r.astype(float)


def _prepare_returns(a: List[float], b: List[float], d: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray]:
    use_lr = d.get("use_log_returns")
    if use_lr is False:
        ra = np.diff(np.asarray(a, dtype=float))
        rb = np.diff(np.asarray(b, dtype=float))
    else:
        ra = _to_log_returns(a)
        rb = _to_log_returns(b)
    n = min(ra.size, rb.size)
    if n < 8:
        return np.array([]), np.array([])
    return ra[:n].copy(), rb[:n].copy()


def _ols_rss(y: np.ndarray, X: np.ndarray) -> Tuple[float, int]:
    """RSS ve serbestlik derecesi (satır sayısı − sütun sayısı)."""
    if X.size == 0 or y.size == 0:
        return float("inf"), 0
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    rss = float(np.dot(resid, resid))
    dof = max(1, int(y.shape[0] - X.shape[1]))
    return rss, dof


def granger_f_stat(y: np.ndarray, own_lags: np.ndarray, cross_lags: np.ndarray) -> float:
    """
    Basit F istatistiği: cross_lags katsayıları sıfır mı?
    own_lags: [1, y_{t-1}, ...]; cross_lags: [x_{t-1}, ...].
    """
    if y.size < 12 or own_lags.shape[0] != cross_lags.shape[0]:
        return 0.0
    n = y.shape[0]
    X_r = own_lags
    X_u = np.hstack([own_lags, cross_lags])
    rss_r, dof_r = _ols_rss(y, X_r)
    rss_u, _dof_u = _ols_rss(y, X_u)
    k = cross_lags.shape[1]
    if rss_u <= _EPS or k <= 0:
        return 0.0
    num = max(0.0, (rss_r - rss_u) / k)
    den = rss_u / max(1, n - X_u.shape[1])
    if den <= _EPS:
        return 0.0
    return float(num / den)


def _build_lag_matrix(series: np.ndarray, L: int) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """series[t] için satır: [1, s_{t-1}, ..., s_{t-L}]; hedef y vektörü."""
    n = series.size
    if n <= L + 2:
        return None
    rows = []
    y_vec = []
    for t in range(L, n):
        row = [1.0]
        for ell in range(1, L + 1):
            row.append(float(series[t - ell]))
        rows.append(row)
        y_vec.append(float(series[t]))
    return np.asarray(rows, dtype=float), np.asarray(y_vec, dtype=float)


def granger_causality_score(
    cause: np.ndarray,
    effect: np.ndarray,
    *,
    max_lag: int = 6,
) -> Tuple[float, int]:
    """
    cause → effect için Granger tarzı F skorlarının normalize edilmiş maksimumu ve en iyi gecikme.
    Skor ~ [0,1].
    """
    L_max = max(1, min(max_lag, 8, cause.size // 4))
    best_f = 0.0
    best_lag = 1
    for L in range(1, L_max + 1):
        Xy = _build_lag_matrix(effect, L)
        Xx = _build_lag_matrix(cause, L)
        if Xy is None or Xx is None:
            continue
        X_own, y = Xy
        X_c_full, _ = Xx
        m = min(X_own.shape[0], X_c_full.shape[0])
        if m < 10:
            continue
        X_own = X_own[-m:]
        y = y[-m:]
        X_c = X_c_full[-m:, 1:]  # intercept yok; çapraz gecikmeler
        own_part = X_own
        f = granger_f_stat(y, own_part, X_c)
        if f > best_f:
            best_f = f
            best_lag = L
    # F dağılımı yerine monoton sıkıştırma (deterministik)
    score = float(_clamp01(best_f / (best_f + 4.5)))
    return score, int(best_lag)


def _pearson_corr(a: np.ndarray, b: np.ndarray) -> float:
    if a.size < 5 or a.size != b.size:
        return 0.0
    if float(np.std(a)) < _EPS or float(np.std(b)) < _EPS:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def _discrete_mi_xy(x: np.ndarray, y: np.ndarray, bins: int = 5) -> float:
    """Diskret karşılıklı bilgi (transfer entropy proxy bileşeni); nat → [0,1]."""
    if x.size != y.size or x.size < 12:
        return 0.0
    H, _, _ = np.histogram2d(x, y, bins=bins)
    joint = H.astype(float)
    s = float(np.sum(joint))
    if s <= _EPS:
        return 0.0
    joint /= s
    px = np.sum(joint, axis=1)
    py = np.sum(joint, axis=0)
    mi = 0.0
    bi, bj = joint.shape
    for i in range(bi):
        for j in range(bj):
            p = joint[i, j]
            if p <= _EPS:
                continue
            px_i = max(_EPS, px[i])
            py_j = max(_EPS, py[j])
            mi += p * math.log(p / (px_i * py_j) + _EPS)
    cap = math.log(bins * bins + _EPS)
    return float(_clamp01(mi / cap if cap > _EPS else 0.0))


def transfer_entropy_proxy(cause: np.ndarray, effect: np.ndarray, lag: int) -> float:
    """
    TE için MI(cause[t-lag], effect[t]) — yön A→B bilgi akışı proxy [0,1].
    """
    if lag < 1 or cause.size != effect.size:
        return 0.0
    if cause.size <= lag + 5:
        return 0.0
    xc = cause[:-lag].copy()
    ye = effect[lag:].copy()
    m = min(xc.size, ye.size)
    if m < 10:
        return 0.0
    return _discrete_mi_xy(xc[-m:], ye[-m:])


def spurious_correlation_score(
    ra: np.ndarray,
    rb: np.ndarray,
    granger_ab: float,
    granger_ba: float,
) -> Tuple[bool, float]:
    """
    Yüksek korelasyon + zayıf çift yönlü Granger → sahte ilişki şüphesi.
    Dönüş: (bayrak, [0,1] şiddet).
    """
    c = abs(_pearson_corr(ra, rb))
    gmax = max(granger_ab, granger_ba)
    # Korelasyon yüksek ama nedensellik yoksa sahte
    spurious = c >= 0.78 and gmax < 0.28
    # Şiddet: korelasyon faz, nedensellik az
    intensity = _clamp01((c - 0.5) * 1.4) * _clamp01(1.0 - gmax)
    if spurious:
        intensity = max(intensity, 0.55)
    return bool(spurious), float(intensity)


def analyze_causal_alpha(
    symbol: str,
    causal_data: Any,
    analysis: Optional[Dict[str, Any]] = None,
    *,
    attach_to_analysis: bool = True,
    half_life_ms: int = 52_000,
    event_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Nedensel alpha özeti; `analysis['phase31']` / `['faz31']` yazar.
    """
    _ = symbol
    a = analysis if analysis is not None else {}
    ts = int(event_ts) if event_ts is not None else _try_ts_ms(a)
    d = _normalize_causal(causal_data)

    if not d:
        payload = _empty_phase31(ts, half_life_ms, "no_causal_data")
        if attach_to_analysis:
            attach_phase_alias(a, "31", payload)
        return payload

    raw_a, raw_b = _extract_ab_series(d)
    if len(raw_a) < _MIN_POINTS or len(raw_b) < _MIN_POINTS:
        payload = _empty_phase31(ts, half_life_ms, "insufficient_series")
        if attach_to_analysis:
            attach_phase_alias(a, "31", payload)
        return payload

    ra, rb = _prepare_returns(raw_a, raw_b, d)
    if ra.size < 12:
        payload = _empty_phase31(ts, half_life_ms, "returns_too_short")
        if attach_to_analysis:
            attach_phase_alias(a, "31", payload)
        return payload

    max_lag_in = int(d.get("max_lag") or 6)
    g_ab, lag_ab = granger_causality_score(ra, rb, max_lag=max_lag_in)
    g_ba, lag_ba = granger_causality_score(rb, ra, max_lag=max_lag_in)

    best_lag = lag_ab if g_ab >= g_ba else lag_ba
    te_ab = transfer_entropy_proxy(ra, rb, max(1, lag_ab))
    te_ba = transfer_entropy_proxy(rb, ra, max(1, lag_ba))
    te_max = max(te_ab, te_ba)

    spurious, sp_score = spurious_correlation_score(ra, rb, g_ab, g_ba)

    if g_ab >= g_ba + 0.04:
        direction: Literal["A_TO_B", "B_TO_A", "BIDIRECTIONAL", "NONE"] = "A_TO_B"
    elif g_ba >= g_ab + 0.04:
        direction = "B_TO_A"
    elif g_ab >= 0.18 and g_ba >= 0.18:
        direction = "BIDIRECTIONAL"
    else:
        direction = "NONE"

    g_main = max(g_ab, g_ba)
    lag_eff = float(min(best_lag, 24))
    lag_bonus = 1.0 / (1.0 + 0.18 * lag_eff)
    te_factor = _clamp01(0.55 * te_max + 0.45 * min(te_ab, te_ba))

    base_alpha = _clamp01(
        0.38 * g_main
        + 0.28 * te_factor
        + 0.22 * lag_bonus * g_main
        + 0.12 * (1.0 - sp_score)
    )
    # Transfer entropy düşükse alpha düşür
    alpha_01 = _clamp01(base_alpha * (0.35 + 0.65 * te_factor))

    risk_01 = _clamp01(
        0.30 * (1.0 - g_main)
        + 0.28 * sp_score
        + 0.22 * (1.0 - te_factor)
        + 0.20 * _clamp01(lag_eff / 18.0)
    )

    hist_ok = ra.size >= _MIN_POINTS
    conf_base = _clamp01(0.26 + 0.42 * (1.0 if hist_ok else 0.4) + 0.18 * g_main + 0.14 * te_factor)
    conf = _clamp01(conf_base * (0.38 if spurious else 1.0))

    dh = _clamp01(
        0.28
        + 0.32 * (1.0 if hist_ok else 0.35)
        + 0.22 * (1.0 - sp_score)
        + 0.18 * te_factor
    )

    perm: TradePermission = "ALLOW"
    if spurious:
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
        "phase": "31",
        "source": "causal_alpha_engine",
        "causal": {
            "granger_score_a_to_b": float(g_ab),
            "granger_score_b_to_a": float(g_ba),
            "granger_ab": float(g_ab),
            "granger_ba": float(g_ba),
            "best_lag_a_to_b": int(lag_ab),
            "best_lag_b_to_a": int(lag_ba),
            "transfer_entropy_a_to_b": float(te_ab),
            "transfer_entropy_b_to_a": float(te_ba),
            "te_ab": float(te_ab),
            "transfer_entropy_max": float(te_max),
            "direction": direction,
            "spurious_correlation": bool(spurious),
            "spurious_flag": bool(spurious),
            "spurious_score": float(sp_score),
            "sample_correlation": float(_pearson_corr(ra, rb)),
            "bars_available": int(ra.size),
        },
    }

    if attach_to_analysis:
        attach_phase_alias(a, "31", payload)

    return payload


def run_causal_alpha_phase(
    symbol: str,
    causal_data: Any,
    analysis: Optional[Dict[str, Any]] = None,
    *,
    attach_to_analysis: bool = True,
    half_life_ms: int = 52_000,
    event_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """Pipeline girişi — `analyze_causal_alpha` ile aynı."""
    return analyze_causal_alpha(
        symbol,
        causal_data,
        analysis,
        attach_to_analysis=attach_to_analysis,
        half_life_ms=half_life_ms,
        event_ts=event_ts,
    )


def _empty_phase31(ts: int, half_life_ms: int, reason: str) -> Dict[str, Any]:
    return {
        "trade_permission": "BLOCK",
        "alpha_score": 0.0,
        "risk_score": 1.0,
        "confidence": 0.0,
        "data_health": 0.0,
        "event_ts": float(ts),
        "half_life_ms": int(half_life_ms),
        "score_type": "QUALITY",
        "phase": "31",
        "source": "causal_alpha_engine",
        "empty_reason": reason,
        "causal": {},
    }
