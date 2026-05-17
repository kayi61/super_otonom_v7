"""
Faz 24 — Portföy risk motoru (VaR / CVaR / Herfindahl / stres / korelasyon).

Girdi `portfolio_data` (esnek dict):
- weights: {"SYM": w, ...} veya weights_list [[sym,w],...] (toplam ~1)
- portfolio_returns: günlük (veya bar) portföy getiri serisi [float, ...]
- asset_returns: {"SYM": [r1,r2,...], ...} — portfolio_returns yoksa birleştirilir
- correlation_matrix: opsiyonel dict/list simetrik korelasyon
- nav | portfolio_value_usd (opsiyonel)

Üç VaR:
- parametrik (normal yaklaşımı),
- tarihsel (yüzdelik dilim),
- Monte Carlo (bootstrap yeniden örnekleme, deterministik tohum).

Özel kurallar:
- VaR > %15 → BLOCK
- CVaR > %20 → HALT
- Herfindahl > 0.6 → BLOCK
- Stres kaybı > %40 → HALT

Çıktı Faz 16/17/18/23 ile uyumlu; phase24 / faz24.
"""

from __future__ import annotations

import math
import random
import statistics
import time
from typing import Any, Dict, List, Literal, Optional, Sequence

from super_otonom.standard_phase_output import attach_phase_alias

ScoreType = Literal["ALPHA", "RISK", "QUALITY"]
TradePermission = Literal["ALLOW", "BLOCK", "HALT"]

_EPS = 1e-12
_MC_SEED = 42


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


def _normalize_portfolio(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return dict(raw)


def _extract_weights(d: Dict[str, Any]) -> Dict[str, float]:
    w = d.get("weights")
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
    return out


def _portfolio_return_series(d: Dict[str, Any]) -> List[float]:
    pr = d.get("portfolio_returns") or d.get("returns") or d.get("pnl_returns")
    if isinstance(pr, list) and len(pr) >= 3:
        try:
            return [float(x) for x in pr]
        except (TypeError, ValueError):
            pass

    wmap = _extract_weights(d)
    ar = d.get("asset_returns") or d.get("returns_by_symbol")
    if not isinstance(ar, dict) or not wmap:
        return []

    syms = [s for s in wmap if s in ar and isinstance(ar[s], list) and len(ar[s]) >= 3]
    if not syms:
        return []
    n = min(len(ar[s]) for s in syms)
    series: List[float] = []
    for i in range(n):
        acc = 0.0
        for s in syms:
            try:
                acc += wmap[s] * float(ar[s][i])
            except (TypeError, ValueError, IndexError):
                acc += 0.0
        series.append(acc)
    return series


def herfindahl_index(weights: Dict[str, float]) -> float:
    """Konsantrasyon [0,1]; 1 = tek varlık."""
    if not weights:
        return 1.0
    return float(sum(w * w for w in weights.values()))


def var_parametric(returns: List[float], confidence: float = 0.95) -> float:
    from super_otonom.risk.var_models import parametric_var

    return parametric_var(returns, confidence, horizon_days=1)


def var_historical(returns: List[float], confidence: float = 0.95) -> float:
    from super_otonom.risk.var_models import historical_var

    return historical_var(returns, confidence, horizon_days=1)


def var_monte_carlo(returns: List[float], confidence: float = 0.95, *, draws: int = 600) -> float:
    from super_otonom.risk.var_models import monte_carlo_var

    return monte_carlo_var(
        returns,
        confidence,
        horizon_days=1,
        draws=draws,
        seed=_MC_SEED,
    )


def cvar_expected_shortfall(returns: List[float], confidence: float = 0.95) -> float:
    from super_otonom.risk.cvar_models import historical_cvar

    return historical_cvar(returns, confidence)


def _avg_pairwise_correlation(d: Dict[str, Any]) -> float:
    cm = d.get("correlation_matrix") or d.get("corr_matrix")
    if isinstance(cm, dict):
        vals: List[float] = []
        for a, row in cm.items():
            if isinstance(row, dict):
                for b, v in row.items():
                    if str(a) < str(b):
                        try:
                            vals.append(abs(float(v)))
                        except (TypeError, ValueError):
                            continue
        if vals:
            return float(sum(vals) / len(vals))

    ar = d.get("asset_returns")
    wmap = _extract_weights(d)
    if isinstance(ar, dict) and len(ar) >= 2:
        syms = [s for s in wmap if s in ar and isinstance(ar[s], list) and len(ar[s]) >= 5]
        if len(syms) >= 2:
            cors: List[float] = []
            for i in range(len(syms)):
                for j in range(i + 1, len(syms)):
                    a, b = syms[i], syms[j]
                    n = min(len(ar[a]), len(ar[b]))
                    if n < 5:
                        continue
                    xa = [float(ar[a][k]) for k in range(n)]
                    xb = [float(ar[b][k]) for k in range(n)]
                    if statistics.stdev(xa) < _EPS or statistics.stdev(xb) < _EPS:
                        continue
                    ma, mb = statistics.mean(xa), statistics.mean(xb)
                    num = sum((xa[k] - ma) * (xb[k] - mb) for k in range(n))
                    den = math.sqrt(sum((x - ma) ** 2 for x in xa) * sum((x - mb) ** 2 for x in xb))
                    if den > _EPS:
                        cors.append(abs(num / den))
            if cors:
                return float(sum(cors) / len(cors))
    return 0.35


def _stress_max_loss_pct(weights: Dict[str, float], hhi: float, d: Dict[str, Any]) -> float:
    """Flash crash / bear senaryolarından kötü senaryo kaybı (kesir)."""
    custom = d.get("stress_scenarios") or d.get("stress")
    if isinstance(custom, dict):
        mx = 0.0
        for _name, sh in custom.items():
            try:
                mx = max(mx, abs(float(sh)))
            except (TypeError, ValueError):
                continue
        if mx > _EPS:
            return _clamp01(mx)

    conc = max(0.0, hhi - 0.25)
    flash = _clamp01(0.18 + 0.22 * conc + 0.08 * (hhi > 0.55))
    bear = _clamp01(0.30 + 0.35 * conc + 0.12 * (hhi > 0.55))
    return float(max(flash, bear))


def _aggregate_risk_01(
    var_max: float,
    cvar: float,
    hhi: float,
    corr_r: float,
    stress: float,
) -> float:
    return _clamp01(0.22 * var_max + 0.22 * cvar + 0.18 * hhi + 0.18 * corr_r + 0.20 * stress)


def _alpha_diversification(hhi: float, corr_r: float) -> float:
    div = _clamp01(1.0 - hhi * 0.85)
    corr_pen = _clamp01(1.0 - corr_r * 0.6)
    return _clamp01(0.52 * div + 0.48 * corr_pen)


def analyze_portfolio_risk(
    symbol: str,
    portfolio_data: Any,
    analysis: Optional[Dict[str, Any]] = None,
    *,
    attach_to_analysis: bool = True,
    half_life_ms: int = 54_000,
    event_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Portföy risk özetini üretir; `analysis['phase24']` / `['faz24']` yazar.
    """
    _ = symbol
    a = analysis if analysis is not None else {}
    ts = int(event_ts) if event_ts is not None else _try_ts_ms(a)
    d = _normalize_portfolio(portfolio_data)

    if not d:
        payload = _empty_phase24(ts, half_life_ms, "no_portfolio_data")
        if attach_to_analysis:
            attach_phase_alias(a, "24", payload)
        return payload

    weights = _extract_weights(d)
    if not weights:
        payload = _empty_phase24(ts, half_life_ms, "no_weights")
        if attach_to_analysis:
            attach_phase_alias(a, "24", payload)
        return payload

    ret = _portfolio_return_series(d)
    hhi = herfindahl_index(weights)

    if len(ret) >= 5:
        vp = var_parametric(ret)
        vh = var_historical(ret)
        vm = var_monte_carlo(ret)
        cv = cvar_expected_shortfall(ret)
    else:
        vp = 0.09 + 0.06 * hhi
        vh = 0.085 + 0.07 * hhi
        vm = 0.088 + 0.065 * hhi
        cv = 0.12 + 0.09 * hhi

    var_max = max(vp, vh, vm)
    corr_r = _avg_pairwise_correlation(d)
    stress_loss = _stress_max_loss_pct(weights, hhi, d)

    risk_01 = _aggregate_risk_01(var_max, cv, hhi, corr_r, stress_loss)
    alpha_01 = _alpha_diversification(hhi, corr_r)

    has_hist = len(ret) >= 5
    conf = _clamp01(0.24 + 0.38 * (1.0 if has_hist else 0.35) + 0.22 * (1.0 - hhi))
    dh = _clamp01(0.30 + 0.35 * (1.0 if has_hist else 0.25) + 0.25 * (1.0 - abs(hhi - 0.35)))

    perm: TradePermission = "ALLOW"

    if cv > 0.20:
        perm = "HALT"
    elif stress_loss > 0.40:
        perm = "HALT"
    elif var_max > 0.15:
        perm = "BLOCK"
    elif hhi > 0.6:
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
        "phase": "24",
        "source": "portfolio_risk_engine",
        "portfolio_risk": {
            "var_parametric": float(vp),
            "var_historical": float(vh),
            "var_monte_carlo": float(vm),
            "var_max": float(var_max),
            "cvar": float(cv),
            "herfindahl_hhi": float(hhi),
            "correlation_risk": float(corr_r),
            "stress_max_loss_pct": float(stress_loss),
            "weights_count": len(weights),
            "historical_returns_available": bool(has_hist),
        },
    }

    if attach_to_analysis:
        attach_phase_alias(a, "24", payload)

    return payload


def run_portfolio_risk_phase(
    symbol: str,
    portfolio_data: Any,
    analysis: Optional[Dict[str, Any]] = None,
    *,
    attach_to_analysis: bool = True,
    half_life_ms: int = 54_000,
    event_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """Pipeline girişi — `analyze_portfolio_risk` ile aynı."""
    return analyze_portfolio_risk(
        symbol,
        portfolio_data,
        analysis,
        attach_to_analysis=attach_to_analysis,
        half_life_ms=half_life_ms,
        event_ts=event_ts,
    )


def _empty_phase24(ts: int, half_life_ms: int, reason: str) -> Dict[str, Any]:
    return {
        "trade_permission": "BLOCK",
        "alpha_score": 0.0,
        "risk_score": 1.0,
        "confidence": 0.0,
        "data_health": 0.0,
        "event_ts": float(ts),
        "half_life_ms": int(half_life_ms),
        "score_type": "QUALITY",
        "phase": "24",
        "source": "portfolio_risk_engine",
        "empty_reason": reason,
        "portfolio_risk": {},
    }
