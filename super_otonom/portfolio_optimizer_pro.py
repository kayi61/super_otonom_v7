"""
Faz 29 — Profesyonel portföy optimizasyonu (Black–Litterman, Risk Parity, 5-faktör, Sharpe).

Girdi `portfolio_data` (esnek dict):
- asset_returns: {"SYM": [r1,r2,...], ...} — eş uzunlukta getiri serileri (zorunlu)
- weights veya market_cap_weights: önsel piyasa ağırlıkları (yoksa eşit)
- bl_views: opsiyonel { "P": K×N liste, "Q": K uzunluk, "Omega": K×K veya K uzunluk (köşegen) }
- book_to_market, market_cap, price_series: faktör proxy'leri (opsiyonel)

Saf NumPy; scipy / cvxpy yok.

Çıktı Faz 16–30 ile uyumlu; phase29 / faz29.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Literal, Optional, Tuple

import numpy as np

from super_otonom.standard_phase_output import attach_phase_alias

ScoreType = Literal["ALPHA", "RISK", "QUALITY"]
TradePermission = Literal["ALLOW", "BLOCK", "HALT"]

_EPS = 1e-12
_MIN_T = 36
_MIN_N = 2
_TAU = 0.05
_DELTA = 2.8
_RIDGE = 1e-8


def _now_ms() -> int:
    return int(time.time() * 1000)


def _clamp01(x: float) -> float:
    if x != x:
        return 0.0
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else float(x)


def _clip01_arr(a: np.ndarray) -> np.ndarray:
    return np.clip(a.astype(float), 0.0, 1.0)


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


def _extract_weights_map(d: Dict[str, Any]) -> Dict[str, float]:
    w = d.get("weights") or d.get("market_cap_weights")
    out: Dict[str, float] = {}
    if isinstance(w, dict):
        for k, v in w.items():
            try:
                out[str(k)] = float(v)
            except (TypeError, ValueError):
                continue
    elif isinstance(w, list):
        for row in w:
            if isinstance(row, (list, tuple)) and len(row) >= 2:
                try:
                    out[str(row[0])] = float(row[1])
                except (TypeError, ValueError):
                    continue
    s = sum(abs(v) for v in out.values())
    if s > _EPS:
        return {k: abs(v) / s for k, v in out.items()}
    return {}


def extract_return_matrix(d: Dict[str, Any]) -> Optional[Tuple[np.ndarray, List[str]]]:
    """Sütunlar varlık, satırlar zaman."""
    ar = d.get("asset_returns") or d.get("returns_by_symbol") or d.get("returns")
    if not isinstance(ar, dict):
        return None
    syms = sorted([s for s in ar if isinstance(ar[s], list) and len(ar[s]) >= _MIN_T])
    if len(syms) < _MIN_N:
        return None
    tmin = min(len(ar[s]) for s in syms)
    if tmin < _MIN_T:
        return None
    mat = np.zeros((tmin, len(syms)), dtype=float)
    for j, s in enumerate(syms):
        mat[:, j] = np.asarray([float(x) for x in ar[s][:tmin]], dtype=float)
    return mat, syms


def sample_covariance(R: np.ndarray) -> np.ndarray:
    z = R - np.mean(R, axis=0, keepdims=True)
    n = max(R.shape[0] - 1, 1)
    cov = (z.T @ z) / float(n)
    tr = float(np.trace(cov))
    rid = _RIDGE * (tr / max(R.shape[1], 1) + 1.0)
    return cov + rid * np.eye(R.shape[1])


def prior_market_weights(syms: List[str], d: Dict[str, Any]) -> np.ndarray:
    wm = _extract_weights_map(d)
    n = len(syms)
    w = np.ones(n, dtype=float) / float(n)
    if wm:
        vec = np.array([wm.get(s, 0.0) for s in syms], dtype=float)
        if np.sum(vec) > _EPS:
            w = vec / np.sum(vec)
    return w


def equilibrium_returns(Sigma: np.ndarray, w_mkt: np.ndarray) -> np.ndarray:
    """Önsel denge getiri (CAPM/δ Σ w)."""
    sw = Sigma @ w_mkt
    denom = float(w_mkt @ sw) + _EPS
    scale = _DELTA / denom
    return scale * sw


def black_litterman_posterior(
    Sigma: np.ndarray,
    pi: np.ndarray,
    *,
    tau: float,
    P: Optional[np.ndarray],
    Q: Optional[np.ndarray],
    Omega: Optional[np.ndarray],
) -> Tuple[np.ndarray, float]:
    """
    μ_BL. Görüş yoksa π döner. Omega büyükse belirsizlik skoru yüksek [0,1].
    """
    n = Sigma.shape[0]
    if P is None or Q is None or P.size == 0 or Q.size == 0:
        return pi.copy(), 0.0

    ridge = _RIDGE * np.eye(n)
    ts = tau * Sigma + ridge
    try:
        inv_ts = np.linalg.inv(ts)
    except np.linalg.LinAlgError:
        inv_ts = np.linalg.pinv(ts)

    K = P.shape[0]
    if Omega is None:
        Om = np.eye(K) * (0.0005 + _RIDGE)
    elif Omega.ndim == 1:
        Om = np.diag(np.maximum(Omega, _RIDGE))
    else:
        Om = Omega + _RIDGE * np.eye(K)

    try:
        inv_Om = np.linalg.inv(Om)
    except np.linalg.LinAlgError:
        inv_Om = np.linalg.pinv(Om)

    M = inv_ts + P.T @ inv_Om @ P
    b = inv_ts @ pi + P.T @ inv_Om @ Q.reshape(-1)
    try:
        mu = np.linalg.solve(M, b)
    except np.linalg.LinAlgError:
        mu = np.linalg.lstsq(M, b, rcond=None)[0]

    # Belirsizlik: Ω / ||Q|| yüksek oran
    qn = float(np.linalg.norm(Q)) + _EPS
    tr_o = float(np.trace(Om))
    uncertain = _clamp01(tr_o / (tr_o + qn * 12.0))

    return mu.astype(float), uncertain


def erc_weights(Sigma: np.ndarray, *, max_iter: int = 120, tol: float = 1e-9) -> np.ndarray:
    """Equal Risk Contribution — çoklayıcı güncelleme (Spinu tarzı basitleştirilmiş)."""
    n = Sigma.shape[0]
    w = np.ones(n, dtype=float) / float(n)
    for _ in range(max_iter):
        Sw = Sigma @ w
        sig_p = math.sqrt(max(float(w @ Sw), _EPS))
        beta = Sw / max(sig_p, _EPS)
        inv_b = 1.0 / np.maximum(beta, 1e-12)
        w_new = inv_b / np.sum(inv_b)
        if float(np.max(np.abs(w_new - w))) < tol:
            break
        w = w_new
    return w


def erc_imbalance_score(w: np.ndarray, Sigma: np.ndarray) -> float:
    """Risk katkıları ne kadar eşit değil [0,1]."""
    var_p = float(w @ Sigma @ w)
    if var_p <= _EPS:
        return 1.0
    rc = w * (Sigma @ w) / var_p
    target = 1.0 / len(w)
    dev = float(np.std(rc / max(target, _EPS)))
    return _clamp01(dev * 2.5)


def max_sharpe_weights(mu: np.ndarray, Sigma: np.ndarray) -> np.ndarray:
    """Uzun pozisyonlu Sharpe maksimizasyonu — projeksiyon simpleks."""
    n = len(mu)
    Sig = Sigma + _RIDGE * np.eye(n)
    try:
        invs = np.linalg.inv(Sig)
    except np.linalg.LinAlgError:
        invs = np.linalg.pinv(Sig)
    raw = invs @ mu.reshape(-1)
    raw = np.maximum(raw, 0.0)
    s = float(np.sum(raw))
    if s <= _EPS:
        return np.ones(n, dtype=float) / float(n)
    return raw / s


def blend_optimal(w_bl: np.ndarray, w_erc: np.ndarray, blend: float = 0.55) -> np.ndarray:
    x = blend * w_bl + (1.0 - blend) * w_erc
    x = np.maximum(x, 0.0)
    sx = float(np.sum(x))
    return x / max(sx, _EPS)


def five_factor_scores(R: np.ndarray, syms: List[str], d: Dict[str, Any]) -> Tuple[np.ndarray, float]:
    """
    Varlık başına [0,1] birleşik faktör skoru ve portföy ortalaması.
    momentum, value, quality, low_vol, size
    """
    t, n = R.shape
    mom = np.mean(R[-min(20, t) :, :], axis=0) / (np.std(R, axis=0) + _EPS)
    mom_n = _clip01_arr(0.5 + 0.5 * np.tanh(mom * 4.0))

    vol = np.std(R, axis=0) + _EPS
    low_vol = _clip01_arr(1.0 - np.tanh(vol * 35.0))
    qual = low_vol

    bm = d.get("book_to_market") or d.get("bm")
    if isinstance(bm, dict):
        val_raw = np.array([float(bm.get(s, 0.5)) for s in syms], dtype=float)
        val_n = _clip01_arr((val_raw - np.min(val_raw)) / (np.ptp(val_raw) + _EPS))
    else:
        cum = np.cumsum(np.log1p(np.maximum(R, -0.99)), axis=0)
        slope = cum[-1, :] / float(max(t, 1))
        val_n = _clip01_arr(0.5 - 0.5 * np.tanh(slope * 8.0))

    mc = d.get("market_cap") or d.get("size_proxy")
    if isinstance(mc, dict):
        sz_raw = np.array([float(mc.get(s, 1.0)) for s in syms], dtype=float)
        sz_n = _clip01_arr(1.0 - (sz_raw - np.min(sz_raw)) / (np.ptp(sz_raw) + _EPS))
    else:
        lev = np.mean(np.abs(R), axis=0)
        sz_n = _clip01_arr(1.0 - np.tanh(lev * 25.0))

    w_f = np.array([0.26, 0.22, 0.18, 0.18, 0.16], dtype=float)
    stack = np.column_stack([mom_n, val_n, qual, low_vol, sz_n])
    comb = np.sum(stack * w_f, axis=1)
    alpha_mean = float(np.mean(comb))
    return comb.astype(float), alpha_mean


def portfolio_sharpe(R: np.ndarray, w: np.ndarray) -> float:
    x = R @ w.reshape(-1)
    mu = float(np.mean(x))
    sig = float(np.std(x)) + _EPS
    return mu / sig


def analyze_portfolio_optimizer(
    symbol: str,
    portfolio_data: Any,
    analysis: Optional[Dict[str, Any]] = None,
    *,
    attach_to_analysis: bool = True,
    half_life_ms: int = 54_000,
    event_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Portföy optimizasyon özeti; `analysis['phase29']` / `['faz29']` yazar.
    """
    _ = symbol
    a = analysis if analysis is not None else {}
    ts = int(event_ts) if event_ts is not None else _try_ts_ms(a)
    d = _normalize(portfolio_data)

    if not d:
        payload = _empty_phase29(ts, half_life_ms, "no_portfolio_data")
        if attach_to_analysis:
            attach_phase_alias(a, "29", payload)
        return payload

    ext = extract_return_matrix(d)
    if ext is None:
        payload = _empty_phase29(ts, half_life_ms, "insufficient_series")
        if attach_to_analysis:
            attach_phase_alias(a, "29", payload)
        return payload

    R, syms = ext
    Sigma = sample_covariance(R)
    w_mkt = prior_market_weights(syms, d)
    pi = equilibrium_returns(Sigma, w_mkt)

    P = Q = Om = None
    bv = d.get("bl_views") or d.get("black_litterman_views")
    if isinstance(bv, dict):
        if isinstance(bv.get("P"), (list, tuple)):
            P = np.asarray(bv["P"], dtype=float)
        if isinstance(bv.get("Q"), (list, tuple)):
            Q = np.asarray(bv["Q"], dtype=float).reshape(-1)
        if isinstance(bv.get("Omega"), (list, tuple)):
            Om = np.asarray(bv["Omega"], dtype=float)

    try:
        mu_bl, view_uncertain = black_litterman_posterior(Sigma, pi, tau=_TAU, P=P, Q=Q, Omega=Om)
    except (ValueError, np.linalg.LinAlgError):
        mu_bl, view_uncertain = pi.copy(), 0.35

    w_sh = max_sharpe_weights(mu_bl, Sigma)
    w_erc = erc_weights(Sigma)
    lam_blend = float(d.get("sharpe_erc_blend") or 0.55)
    w_opt = blend_optimal(w_sh, w_erc, blend=_clamp01(lam_blend))

    sharpe = portfolio_sharpe(R, w_opt)
    max_w = float(np.max(w_opt))
    _, alpha_bar = five_factor_scores(R, syms, d)
    imb = erc_imbalance_score(w_opt, Sigma)

    neg_sh = _clamp01(-min(float(sharpe), 0.0) * 12.0)
    conc = _clamp01(max(0.0, max_w - 0.40) * 6.0)
    risk_01 = _clamp01(
        0.28 * neg_sh
        + 0.24 * imb
        + 0.22 * conc
        + 0.18 * view_uncertain
        + 0.08 * float(max_w > 0.40)
    )
    if sharpe < 0:
        risk_01 = _clamp01(max(risk_01, 0.78))
    if max_w > 0.40:
        risk_01 = _clamp01(max(risk_01, 0.72))

    alpha_01 = _clamp01(
        0.42 * alpha_bar + 0.28 * _clamp01(max(sharpe, 0.0) * 3.5) + 0.18 * (1.0 - imb) + 0.12 * (1.0 - max_w)
    )
    if sharpe < 0:
        alpha_01 = _clamp01(alpha_01 * 0.35)

    conf_base = _clamp01(0.24 + 0.38 * (1.0 - view_uncertain) + 0.22 * (1.0 - imb) + 0.16 * _clamp01(max(sharpe, 0.0) * 3.0))
    conf = _clamp01(conf_base * (0.45 + 0.55 * (1.0 - view_uncertain)))

    dh = _clamp01(0.28 + 0.32 * (1.0 - view_uncertain) + 0.22 * (1.0 - imb) + 0.18 * min(1.0, R.shape[0] / 120.0))

    perm: TradePermission = "ALLOW"
    if sharpe < 0:
        perm = "BLOCK"
    elif max_w > 0.40:
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
        "phase": "29",
        "source": "portfolio_optimizer_pro",
        "portfolio_optimizer": {
            "symbols": syms,
            "optimal_weights": {syms[i]: float(w_opt[i]) for i in range(len(syms))},
            "posterior_expected_returns": {syms[i]: float(mu_bl[i]) for i in range(len(syms))},
            "prior_equilibrium_returns": {syms[i]: float(pi[i]) for i in range(len(syms))},
            "erc_weights": {syms[i]: float(w_erc[i]) for i in range(len(syms))},
            "max_sharpe_weights": {syms[i]: float(w_sh[i]) for i in range(len(syms))},
            "portfolio_sharpe_ratio": float(sharpe),
            "max_single_asset_weight": float(max_w),
            "risk_parity_imbalance": float(imb),
            "black_litterman_view_uncertainty": float(view_uncertain),
            "bars": int(R.shape[0]),
            "assets": int(R.shape[1]),
        },
    }

    if attach_to_analysis:
        attach_phase_alias(a, "29", payload)

    return payload


def run_portfolio_optimizer_phase(
    symbol: str,
    portfolio_data: Any,
    analysis: Optional[Dict[str, Any]] = None,
    *,
    attach_to_analysis: bool = True,
    half_life_ms: int = 54_000,
    event_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """Pipeline girişi — `analyze_portfolio_optimizer` ile aynı."""
    return analyze_portfolio_optimizer(
        symbol,
        portfolio_data,
        analysis,
        attach_to_analysis=attach_to_analysis,
        half_life_ms=half_life_ms,
        event_ts=event_ts,
    )


def _empty_phase29(ts: int, half_life_ms: int, reason: str) -> Dict[str, Any]:
    return {
        "trade_permission": "BLOCK",
        "alpha_score": 0.0,
        "risk_score": 1.0,
        "confidence": 0.0,
        "data_health": 0.0,
        "event_ts": float(ts),
        "half_life_ms": int(half_life_ms),
        "score_type": "QUALITY",
        "phase": "29",
        "source": "portfolio_optimizer_pro",
        "empty_reason": reason,
        "portfolio_optimizer": {},
    }
