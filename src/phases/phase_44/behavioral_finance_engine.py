"""
Faz 44 — Davranışsal finans: Wyckoff döngüsü, Soros refleksivitesi, disposition, narrative momentum.

Sadece NumPy.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Literal, Tuple

import numpy as np

_EPS = 1e-12
_HALF_LIFE_MS = 30_000
_REFLEX_OVERHEAT = 0.80

WyckoffPhase = Literal["ACCUMULATION", "MARKUP", "DISTRIBUTION", "MARKDOWN", "NEUTRAL"]


def _clip01(x: float | np.floating) -> float:
    return float(np.clip(np.asarray(x, dtype=float), 0.0, 1.0))


def _now_ms() -> float:
    return float(time.time() * 1000.0)


def _pick_score_type(data_health: float, risk_score: float) -> str:
    if data_health < 0.42:
        return "QUALITY"
    if risk_score >= 0.72:
        return "RISK"
    return "ALPHA"


_WYCKOFF_ALPHA: Dict[str, float] = {
    "ACCUMULATION": 0.8,
    "MARKUP": 0.9,
    "DISTRIBUTION": 0.2,
    "MARKDOWN": 0.1,
    "NEUTRAL": 0.5,
}


def compute_wyckoff_phase(
    price_history: List[float],
    volume_history: List[float],
) -> Tuple[WyckoffPhase, float]:
    ph = np.asarray(price_history, dtype=float).ravel()
    vh = np.asarray(volume_history, dtype=float).ravel()
    if ph.size < 10 or vh.size < 10:
        return "NEUTRAL", _WYCKOFF_ALPHA["NEUTRAL"]

    p10 = float(ph[-10])
    p_last = float(ph[-1])
    price_change_pct = (p_last - p10) / max(abs(p10), _EPS)

    v_recent = float(np.mean(vh[-5:]))
    v_prev = float(np.mean(vh[-10:-5]))
    vol_change_pct = (v_recent - v_prev) / max(abs(v_prev), _EPS)

    phase: WyckoffPhase = "NEUTRAL"

    if price_change_pct > 0.05:
        if vol_change_pct < -0.1:
            phase = "DISTRIBUTION"
        elif vol_change_pct > 0.0:
            phase = "MARKUP"
    elif price_change_pct < -0.05:
        if vol_change_pct > 0.1:
            phase = "ACCUMULATION"
        elif vol_change_pct < 0.0:
            phase = "MARKDOWN"

    return phase, float(_WYCKOFF_ALPHA[phase])


def compute_reflexivity(
    price_history: List[float],
    sentiment_score: float,
) -> Tuple[float, float, float]:
    """reflexivity [-1,1], reflexivity_score [0,1], price_momentum clipped."""
    ph = np.asarray(price_history, dtype=float).ravel()
    if ph.size < 5:
        return 0.0, 0.5, 0.0
    p5 = float(ph[-5])
    p1 = float(ph[-1])
    raw_mom = (p1 - p5) / max(abs(p5), _EPS) / 0.1
    price_momentum = float(np.clip(raw_mom, -1.0, 1.0))
    s = float(np.clip(sentiment_score, 0.0, 1.0))
    reflexivity = float(np.clip(price_momentum * s, -1.0, 1.0))
    reflexivity_score = _clip01((reflexivity + 1.0) / 2.0)
    return reflexivity, reflexivity_score, price_momentum


def compute_disposition_score(rsi: float) -> float:
    """50 nötrde 1.0; uçlara yakın düşer."""
    r = float(np.clip(rsi, 0.0, 100.0))
    return _clip01(1.0 - abs(r - 50.0) / 50.0)


def compute_narrative_score(funding_rate: float) -> float:
    return _clip01(0.5 - float(funding_rate) * 100.0)


def compute_alpha_components(
    wyckoff_alpha: float,
    reflexivity_score: float,
    rsi: float,
    narrative_score: float,
) -> float:
    """Ağırlıklı birleşim [0,1]; refleksivite > 0.8 → aşırı ısınma, alpha düşürülür."""
    w = float(wyckoff_alpha)
    rs = float(reflexivity_score)
    if rs > _REFLEX_OVERHEAT:
        reflex_term = 1.0 - rs
    else:
        reflex_term = rs
    r = float(np.clip(rsi, 0.0, 100.0))
    if r > 50.0:
        rsi_term = 1.0 - r / 100.0
    else:
        rsi_term = (r / 50.0) * 0.8

    alpha = (
        0.30 * w
        + 0.25 * _clip01(reflex_term)
        + 0.30 * _clip01(rsi_term)
        + 0.15 * _clip01(narrative_score)
    )
    return _clip01(alpha)


def validate_market_data(data: Any) -> Tuple[bool, str]:
    if data is None or not isinstance(data, dict):
        return False, "market_data_missing_or_invalid"

    req = ("price_history", "volume_history", "sentiment_score", "rsi", "funding_rate")
    for k in req:
        if k not in data:
            return False, f"missing_field:{k}"

    ph = data["price_history"]
    vh = data["volume_history"]
    if not isinstance(ph, (list, tuple)) or not isinstance(vh, (list, tuple)):
        return False, "history_not_sequence"
    if len(ph) < 20 or len(vh) < 20:
        return False, "history_too_short"
    if len(ph) != len(vh):
        return False, "history_length_mismatch"

    try:
        s = float(data["sentiment_score"])
        rsi = float(data["rsi"])
        float(data["funding_rate"])
    except (TypeError, ValueError):
        return False, "numeric_parse_error"

    if not (0.0 <= s <= 1.0):
        return False, "sentiment_out_of_range"
    if not (0.0 <= rsi <= 100.0):
        return False, "rsi_out_of_range"

    return True, ""


def analyze(market_data: dict | None) -> dict:
    """Davranışsal finans analizi — Faz 44 standart payload."""
    ts = _now_ms()
    empty: Dict[str, Any] = {}

    ok, err = validate_market_data(market_data)
    if not ok:
        return {
            "phase": 44,
            "module": "behavioral_finance_engine",
            "trade_permission": "BLOCK",
            "alpha_score": 0.0,
            "risk_score": 1.0,
            "score_type": "QUALITY",
            "confidence": 0.0,
            "data_health": 0.0,
            "event_ts": ts,
            "half_life_ms": _HALF_LIFE_MS,
            "analysis": empty,
            "reason": err,
        }

    assert market_data is not None
    d = market_data
    ph = [float(x) for x in d["price_history"]]
    vh = [float(x) for x in d["volume_history"]]
    sentiment = float(d["sentiment_score"])
    rsi = float(d["rsi"])
    funding = float(d["funding_rate"])

    phase, wyckoff_alpha = compute_wyckoff_phase(ph, vh)
    _, reflexivity_score, _ = compute_reflexivity(ph, sentiment)
    disposition_score = compute_disposition_score(rsi)
    narrative_score = compute_narrative_score(funding)

    alpha_score = compute_alpha_components(wyckoff_alpha, reflexivity_score, rsi, narrative_score)
    risk_score = _clip01(1.0 - alpha_score)

    data_health = float(np.clip(len(ph) / 20.0, 0.1, 1.0))
    confidence = _clip01(data_health * (1.0 - 0.2 * risk_score))

    score_type = _pick_score_type(data_health, risk_score)

    trade_permission = "ALLOW"
    reason = "conditions_normal"

    if d.get("force_halt") is True:
        trade_permission = "HALT"
        reason = "force_halt"

    nested = {
        "wyckoff_phase": phase,
        "wyckoff_alpha": wyckoff_alpha,
        "reflexivity_score": reflexivity_score,
        "disposition_score": disposition_score,
        "narrative_score": narrative_score,
        "rsi": rsi,
        "funding_rate": funding,
    }

    return {
        "phase": 44,
        "module": "behavioral_finance_engine",
        "trade_permission": trade_permission,
        "alpha_score": alpha_score,
        "risk_score": risk_score,
        "score_type": score_type,
        "confidence": confidence,
        "data_health": data_health,
        "event_ts": ts,
        "half_life_ms": _HALF_LIFE_MS,
        "analysis": nested,
        "reason": reason,
    }
