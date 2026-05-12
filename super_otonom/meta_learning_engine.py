"""
Faz 35 — Meta-öğrenme motoru (MAML-benzeri proxy, CUSUM drift, sürüm / rollback, online izleme).

Girdi `meta_data` (esnek dict):
- loss_series | val_loss | errors | residuals — meta-loss veya hata izi (tercihen düşük = iyi)
- veya predictions + targets (aynı uzunluk)
- active_model_version | model_version — aktif sürüm kimliği (string/int)
- previous_model_version — rollback adayı
- deployed_at_ms | version_timestamp_ms — sürüm yaşı için zaman damgası (ms)
- online_window — son N bar takibi (varsayılan 24)

Saf NumPy; PyTorch / sklearn yok.

Özel kurallar:
- CUSUM drift → güven düşer, trade_permission BLOCK
- Rollback tetiklenirse → BLOCK
- Eski (stale) sürüm → data_health düşer

Çıktı Faz 16–33 ile uyumlu; phase35 / faz35.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Literal, Optional, Tuple

import numpy as np

from super_otonom.standard_phase_output import attach_phase_alias

ScoreType = Literal["ALPHA", "RISK", "QUALITY"]
TradePermission = Literal["ALLOW", "BLOCK", "HALT"]

_EPS = 1e-12
_MIN_SERIES = 24


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


def _list_float(seq: Any, min_len: int) -> Optional[np.ndarray]:
    if not isinstance(seq, (list, tuple)) or len(seq) < min_len:
        return None
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


def extract_metric_series(d: Dict[str, Any]) -> Tuple[Optional[np.ndarray], bool]:
    """
    Meta iz döndürür ve `lower_is_better` bayrağı.
    Önce loss/error; yoksa |pred-target| üretilir.
    """
    for key in ("loss_series", "val_loss", "errors", "residuals", "train_loss"):
        arr = _list_float(d.get(key), _MIN_SERIES)
        if arr is not None:
            return arr, True

    pred = _list_float(d.get("predictions"), _MIN_SERIES)
    tgt = _list_float(d.get("targets"), _MIN_SERIES)
    if pred is not None and tgt is not None:
        n = min(pred.size, tgt.size)
        if n >= _MIN_SERIES:
            return np.abs(pred[:n] - tgt[:n]), True

    for key in ("accuracy_series", "sharpe_window", "score_series"):
        arr = _list_float(d.get(key), _MIN_SERIES)
        if arr is not None:
            return arr, False

    return None, True


def cusum_two_sided(
    x: np.ndarray,
    *,
    baseline_frac: float = 0.45,
    slack: float = 0.33,
    threshold: float = 7.0,
) -> Tuple[float, bool]:
    """
    Standartlaştırılmış iki yönlü CUSUM; drift gücü [0,1] ve eşik ihlali.
    Referans: ilk `baseline_frac` dilimin ortalama/std'si.
    """
    if x.size < _MIN_SERIES:
        return 0.0, False
    cut = max(4, int(x.size * baseline_frac))
    ref = x[:cut]
    mu = float(np.mean(ref))
    sd = float(np.std(ref))
    if sd < _EPS:
        sd = 1.0
    gp = 0.0
    gm = 0.0
    peak = 0.0
    for i in range(cut, x.size):
        z = (float(x[i]) - mu) / sd
        gp = max(0.0, gp + z - slack)
        gm = max(0.0, gm - z - slack)
        peak = max(peak, gp, gm)
    # Güç metrik: alarm eşidine yaklaşma (tepe == threshold → ~0.45); alarm zirvesi ayrı bayrak
    drift_strength = _clamp01(peak / max(threshold * 1.35, _EPS))
    drift_hit = peak > threshold
    return drift_strength, drift_hit


def maml_style_adaptation_gain(y: np.ndarray) -> float:
    """
    Few-shot iç döngü proxy: destek alt kümesinde ridge güncelleme → sorgu MSE kazancı.
    """
    if y.size < 12:
        return 0.0
    n = int(y.size)
    t = np.arange(n, dtype=float)
    X = np.column_stack([np.ones(n), t / max(n - 1, 1), np.sin(2 * np.pi * t / max(8.0, n / 3))])
    k_support = max(5, min(n // 4, 18))
    idx_s = np.arange(0, k_support)
    idx_q = np.arange(k_support, n)
    if idx_q.size < 4:
        idx_q = np.arange(max(0, n - k_support), n)
        idx_s = np.arange(0, max(k_support, n - idx_q.size))

    lam = 1e-2
    ident = np.eye(X.shape[1])
    inner_w = np.linalg.solve(X[idx_s].T @ X[idx_s] + lam * ident, X[idx_s].T @ y[idx_s])
    pred_q = X[idx_q] @ inner_w
    mse_inner = float(np.mean((pred_q - y[idx_q]) ** 2))

    outer_w = np.linalg.solve(X.T @ X + lam * ident, X.T @ y)
    pred_all = X[idx_q] @ outer_w
    mse_outer = float(np.mean((pred_all - y[idx_q]) ** 2))

    gain = (mse_outer - mse_inner) / max(mse_outer, _EPS)
    return float(_clamp01(0.5 + 0.5 * gain))


def online_performance_proxy(
    y: np.ndarray,
    window: int,
    lower_is_better: bool,
) -> Tuple[float, float]:
    """
    Son `window` vs önceki dilim: göreceli performans ve düşüş oranı [0,1].
    """
    w = max(6, min(window, y.size // 2))
    if y.size < w + 4:
        return 0.5, 0.0
    recent = y[-w:]
    past = y[-2 * w : -w] if y.size >= 2 * w else y[:-w]
    r_mu = float(np.mean(recent))
    p_mu = float(np.mean(past))
    if lower_is_better:
        # düşük loss daha iyi — son dönem yüksediyse kötüleşme
        degrade = _clamp01((r_mu - p_mu) / (abs(p_mu) + 0.05))
        perf_idx = _clamp01(1.0 - _clamp01(r_mu / (p_mu + _EPS)))
    else:
        degrade = _clamp01((p_mu - r_mu) / (abs(p_mu) + 0.05))
        perf_idx = _clamp01(r_mu / (p_mu + _EPS))
    return perf_idx, degrade


def version_staleness(d: Dict[str, Any], now_ms: int) -> Tuple[str, float, float]:
    """Aktif sürüm kimliği, [0,1] stale skoru, saat cinsinden yaş."""
    ver = d.get("active_model_version")
    if ver is None:
        ver = d.get("model_version")
    label = str(ver) if ver is not None else "unknown"

    ts_ms = d.get("deployed_at_ms")
    if ts_ms is None:
        ts_ms = d.get("version_timestamp_ms")
    age_h = 48.0
    stale_unknown = False
    try:
        if ts_ms is not None:
            age_h = max(0.0, (float(now_ms) - float(ts_ms)) / 3_600_000.0)
        else:
            stale_unknown = True
    except (TypeError, ValueError):
        age_h = 96.0
        stale_unknown = True

    stale = _clamp01(age_h / (24.0 * 21.0))
    if stale_unknown:
        stale = max(stale, 0.34)
    m = re.search(r"(\d+)", label)
    if m is not None and int(m.group(1)) <= 1 and age_h > 72:
        stale = max(stale, 0.55)

    return label, stale, age_h


def analyze_meta_learning(
    symbol: str,
    meta_data: Any,
    analysis: Optional[Dict[str, Any]] = None,
    *,
    attach_to_analysis: bool = True,
    half_life_ms: int = 46_000,
    event_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Meta-öğrenme özeti; `analysis['phase35']` / `['faz35']` yazar.
    """
    _ = symbol
    a = analysis if analysis is not None else {}
    ts = int(event_ts) if event_ts is not None else _try_ts_ms(a)
    clock_ms = _now_ms()
    d = _normalize(meta_data)

    if not d:
        payload = _empty_phase35(ts, half_life_ms, "no_meta_data")
        if attach_to_analysis:
            attach_phase_alias(a, "35", payload)
        return payload

    series, lower_is_better = extract_metric_series(d)
    if series is None:
        payload = _empty_phase35(ts, half_life_ms, "insufficient_series")
        if attach_to_analysis:
            attach_phase_alias(a, "35", payload)
        return payload

    cusum_score, drift_hit = cusum_two_sided(series)
    adapt_gain = maml_style_adaptation_gain(series)

    win = int(d.get("online_window") or d.get("performance_window") or 24)
    perf_idx, degrade = online_performance_proxy(series, win, lower_is_better)

    active_ver, stale_score, age_h = version_staleness(d, clock_ms)
    prev_ver = d.get("previous_model_version") or d.get("rollback_version")

    rollback_trigger = bool(drift_hit or degrade > 0.62 or (cusum_score >= 0.85 and degrade > 0.35))
    effective_ver = str(prev_ver) if rollback_trigger and prev_ver is not None else str(active_ver)

    risk_01 = _clamp01(
        0.28 * cusum_score
        + 0.26 * degrade
        + 0.22 * stale_score
        + 0.14 * (1.0 - adapt_gain)
        + 0.10 * float(rollback_trigger)
    )

    alpha_01 = _clamp01(
        0.42 * adapt_gain
        + 0.28 * perf_idx
        + 0.18 * (1.0 - cusum_score)
        + 0.12 * (1.0 - stale_score)
    )
    alpha_01 = _clamp01(alpha_01 * (0.55 if rollback_trigger else 1.0))

    conf_base = _clamp01(
        0.26 + 0.34 * (1.0 - cusum_score) + 0.22 * adapt_gain + 0.18 * (1.0 - degrade)
    )
    conf = _clamp01(conf_base * (0.42 if drift_hit else 1.0) * (0.50 if rollback_trigger else 1.0))

    dh_base = _clamp01(0.28 + 0.38 * (1.0 - stale_score) + 0.34 * (1.0 - cusum_score * 0.85))
    dh = _clamp01(dh_base * (0.55 if stale_score > 0.72 else 1.0))

    perm: TradePermission = "ALLOW"
    if rollback_trigger:
        perm = "BLOCK"
    elif drift_hit:
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
        "phase": "35",
        "source": "meta_learning_engine",
        "meta_learning": {
            "cusum_drift_score": float(cusum_score),
            "cusum_drift_detected": bool(drift_hit),
            "maml_adaptation_gain": float(adapt_gain),
            "online_performance_index": float(perf_idx),
            "online_degradation": float(degrade),
            "active_model_version": str(active_ver),
            "effective_model_version": str(effective_ver),
            "previous_model_version": prev_ver if prev_ver is not None else None,
            "rollback_triggered": bool(rollback_trigger),
            "version_age_hours": float(age_h),
            "version_stale_score": float(stale_score),
            "series_length": int(series.size),
            "lower_is_better_metric": bool(lower_is_better),
        },
    }

    if attach_to_analysis:
        attach_phase_alias(a, "35", payload)

    return payload


def run_meta_learning_phase(
    symbol: str,
    meta_data: Any,
    analysis: Optional[Dict[str, Any]] = None,
    *,
    attach_to_analysis: bool = True,
    half_life_ms: int = 46_000,
    event_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """Pipeline girişi — `analyze_meta_learning` ile aynı."""
    return analyze_meta_learning(
        symbol,
        meta_data,
        analysis,
        attach_to_analysis=attach_to_analysis,
        half_life_ms=half_life_ms,
        event_ts=event_ts,
    )


def _empty_phase35(ts: int, half_life_ms: int, reason: str) -> Dict[str, Any]:
    return {
        "trade_permission": "BLOCK",
        "alpha_score": 0.0,
        "risk_score": 1.0,
        "confidence": 0.0,
        "data_health": 0.0,
        "event_ts": float(ts),
        "half_life_ms": int(half_life_ms),
        "score_type": "QUALITY",
        "phase": "35",
        "source": "meta_learning_engine",
        "empty_reason": reason,
        "meta_learning": {},
    }
