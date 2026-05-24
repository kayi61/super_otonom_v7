"""
Signal Quality Scorer — 0-100 ağırlıklı sinyal kalitesi.

Bileşenler: Hurst (trend tutarlılığı), göreli volatilite, likidite oranı, MTF onayı.
Çıktı: quality_score, penalty_reasons (düşük bileşen etiketleri), quality_main_penalty kısası.

Sinerji Taslağı (AI Confidence ile)::
    1) AI katmanı: sinyal yönü + belirsizliği (confidence) — noise / pattern fit.
    2) Quality Scorer: piyasa rejimi + likidite + MTF — işin yapılabilirliği.
    3) Birleşim: düşük quality → BUY tamamen elenir; orta quality → sadece yüksek
       AI conf ile açılır; yüksek quality + düşük conf → hâlâ risk (gelecekte
       `min(quality, conf*100)` tavanı veya çarpanı).
    4) Pratik: önce `compute_signal_quality` (bu modül), sonra mevcut
       `ai.validate_signal` — gating ayrı (LOW_QUALITY_REJECT) ile yönlü tutarlılık.
    5) İzleme: `decision_context.signal_quality` + `ai_confidence` aynı tick logunda;
       haftalık backtest: quality bucket başına win-rate.

MarketAnalyzer: `score_signal_quality` delegasyonu analyzer.py üzerinden erişilebilir.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Tuple

# Ağırlıklar (toplam 1.0)
_W_H = float(os.getenv("SIGNAL_Q_W_HURST", "0.28") or 0.28)
_W_V = float(os.getenv("SIGNAL_Q_W_VOL", "0.22") or 0.22)
_W_L = float(os.getenv("SIGNAL_Q_W_LIQ", "0.30") or 0.30)
_W_M = float(os.getenv("SIGNAL_Q_W_MTF", "0.20") or 0.20)


def _w_norm() -> Tuple[float, float, float, float]:
    s = _W_H + _W_V + _W_L + _W_M
    if s <= 0:
        return 0.25, 0.25, 0.25, 0.25
    return _W_H / s, _W_V / s, _W_L / s, _W_M / s


def _score_hurst(analysis: Dict[str, Any], penalties: List[str]) -> float:
    h = float(analysis.get("hurst", 0.5) or 0.5)
    regime = str(analysis.get("regime", "NOISY") or "NOISY")
    h = max(0.0, min(1.0, h))
    if regime == "NOISY":
        penalties.append("hurst:noisy_regime")
        return max(0.0, 100.0 * (1.0 - 2.0 * abs(h - 0.5)))
    if regime == "MEAN_REVERTING":
        penalties.append("hurst:mean_revert_regime")
        return 35.0 + 30.0 * (1.0 - abs(h - 0.4))
    # TRENDING
    x = (h - 0.5) / 0.5
    sc = 100.0 * max(0.0, min(1.0, x))
    if sc < 45.0:
        penalties.append("hurst:weak_trend")
    return sc


def _score_volatility(analysis: Dict[str, Any], penalties: List[str]) -> float:
    v = float(analysis.get("volatility", 0.02) or 0.02)
    v = max(0.0, v)
    hi = 0.05
    gold_lo, gold_hi = 0.012, 0.04
    if gold_lo <= v <= gold_hi:
        return 100.0
    if v < gold_lo:
        sc = 100.0 * (v / gold_lo) if gold_lo > 0 else 50.0
        if sc < 50:
            penalties.append("vol:too_calm")
        return sc
    if v <= hi:
        sc = 100.0 * max(0.0, (hi - v) / (hi - gold_hi))
        if sc < 50:
            penalties.append("vol:elevated")
        return sc
    sc = max(0.0, 40.0 * (0.1 - v) / 0.05) if v < 0.1 else 0.0
    penalties.append("vol:extreme")
    return sc


def _score_liquidity(analysis: Dict[str, Any], penalties: List[str]) -> float:
    lr = analysis.get("liquidity_ratio")
    if lr is None:
        penalties.append("liquidity:unknown")
        return 55.0
    try:
        x = float(lr)
    except (TypeError, ValueError):
        penalties.append("liquidity:unknown")
        return 55.0
    x = max(0.0, min(1.0, x))
    if x < 0.2:
        penalties.append("liquidity:thin")
    sc = 100.0 * x
    return sc


def _score_mtf(analysis: Dict[str, Any], signal: str, penalties: List[str]) -> float:
    if bool(analysis.get("mtf_filtered")):
        penalties.append("mtf:filtered")
        return 15.0
    ht = str(analysis.get("high_tf_trend") or "").upper()
    if ht == "UNKNOWN" or not ht:
        return 65.0
    if signal == "BUY" and ht == "UP":
        return 100.0
    if signal == "SELL" and ht == "DOWN":
        return 100.0
    if signal in ("BUY", "SELL"):
        penalties.append("mtf:tf_mismatch")
        return 35.0
    return 70.0


def compute_signal_quality(
    analysis: Dict[str, Any],
) -> Tuple[int, List[str], Dict[str, float], str]:
    """
    Dönüş: (quality_score 0-100, penalty_reasons, component_scores, quality_main_penalty)
    """
    sig = str(analysis.get("signal", "HOLD") or "HOLD")
    ph: List[str] = []
    pv: List[str] = []
    pl: List[str] = []
    pm: List[str] = []

    sh = _score_hurst(analysis, ph)
    sv = _score_volatility(analysis, pv)
    sl = _score_liquidity(analysis, pl)
    sm = _score_mtf(analysis, sig, pm)

    wh, wv, wl, wm = _w_norm()
    total = wh * sh + wv * sv + wl * sl + wm * sm
    if analysis.get("flash_crash"):
        total = max(0.0, total * 0.4)
        ph.append("flash_crash:cut")

    score = int(max(0, min(100, round(total))))
    all_pen: List[str] = list(dict.fromkeys(ph + pv + pl + pm))
    components = {
        "hurst": round(sh, 1),
        "volatility": round(sv, 1),
        "liquidity": round(sl, 1),
        "mtf": round(sm, 1),
    }
    min_k = min(components, key=components.get)  # type: ignore[arg-type]
    if components[min_k] < 50.0:
        main = f"low_{min_k}"
    elif all_pen:
        main = all_pen[0]
    else:
        main = ""
    return score, all_pen, components, main
