"""
Faz 49 — Strateji yaşam döngüsü: Champion/Challenger, rolling backtest, registry simülasyonu.

Sadece NumPy.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple

import numpy as np

_HALF_LIFE_MS = 60_000
_DEFAULT_MIN_TRADES = 30
_DEFAULT_PROMOTE_THRESHOLD = 0.10
_ROLLING_BAD_THRESHOLD = 0.3
_RISK_BUMP_ROLLING_BAD = 0.08


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


def strategy_score(sharpe: float, max_drawdown: float, win_rate: float) -> float:
    """Champion/Challenger birleşik skor [0, 1]."""
    sh = float(sharpe)
    dd = float(max_drawdown)
    wr = float(win_rate)
    raw = 0.4 * (sh / 3.0) + 0.3 * (1.0 - dd) + 0.3 * wr
    return _clip01(raw)


def validate_market_data(data: Any) -> Tuple[bool, str]:
    if data is None or not isinstance(data, dict):
        return False, "market_data_missing_or_invalid"

    if "champion" not in data or not isinstance(data["champion"], dict):
        return False, "champion_invalid"
    if "challenger" not in data or not isinstance(data["challenger"], dict):
        return False, "challenger_invalid"

    champ_keys = ("name", "sharpe", "max_drawdown", "win_rate", "trade_count", "version")
    for side, blob in (("champion", data["champion"]), ("challenger", data["challenger"])):
        for k in champ_keys:
            if k not in blob:
                return False, f"missing_field:{side}:{k}"
        try:
            float(blob["sharpe"])
            float(blob["max_drawdown"])
            float(blob["win_rate"])
            int(blob["trade_count"])
        except (TypeError, ValueError):
            return False, f"numeric_parse_error:{side}"
        if not isinstance(blob["name"], str) or not isinstance(blob["version"], str):
            return False, f"name_or_version_not_str:{side}"

    if "rolling_backtest_scores" not in data or not isinstance(
        data["rolling_backtest_scores"], list
    ):
        return False, "rolling_backtest_scores_invalid"

    scores: List[Any] = data["rolling_backtest_scores"]
    if len(scores) == 0:
        return False, "rolling_backtest_scores_empty"

    for i, s in enumerate(scores):
        try:
            float(s)
        except (TypeError, ValueError):
            return False, f"rolling_score_parse_error:{i}"

    mtc = data.get("min_trade_count", _DEFAULT_MIN_TRADES)
    pt = data.get("promote_threshold", _DEFAULT_PROMOTE_THRESHOLD)
    try:
        int(mtc)
        float(pt)
    except (TypeError, ValueError):
        return False, "threshold_params_invalid"
    if int(mtc) < 0:
        return False, "min_trade_count_negative"

    return True, ""


def analyze(market_data: dict | None) -> dict:
    """Strateji yaşam döngüsü analizi — Faz 49 standart payload."""
    ts = _now_ms()
    empty: Dict[str, Any] = {}

    ok, err = validate_market_data(market_data)
    if not ok:
        return {
            "phase": 49,
            "module": "strategy_lifecycle_manager",
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

    min_trade_count = int(d.get("min_trade_count", _DEFAULT_MIN_TRADES))
    promote_threshold = float(d.get("promote_threshold", _DEFAULT_PROMOTE_THRESHOLD))

    ch = d["champion"]
    q = d["challenger"]

    champ_score = strategy_score(
        float(ch["sharpe"]),
        float(ch["max_drawdown"]),
        float(ch["win_rate"]),
    )
    chall_score = strategy_score(
        float(q["sharpe"]),
        float(q["max_drawdown"]),
        float(q["win_rate"]),
    )

    chall_trades = int(q["trade_count"])
    min_trade_count_met = chall_trades >= min_trade_count

    beats_threshold = chall_score > champ_score * (1.0 + promote_threshold)
    promotion_candidate = bool(min_trade_count_met and beats_threshold)

    arr = np.asarray(d["rolling_backtest_scores"], dtype=float).ravel()
    rolling_mean = float(np.mean(arr))
    rolling_std = float(np.std(arr))
    rolling_score = _clip01(rolling_mean / 3.0)

    third_term = float(chall_score if promotion_candidate else champ_score * 0.8)
    alpha_score = _clip01(
        0.5 * champ_score + 0.3 * rolling_score + 0.2 * third_term
    )
    risk_score = _clip01(1.0 - alpha_score)

    if rolling_mean < _ROLLING_BAD_THRESHOLD:
        risk_score = _clip01(risk_score + _RISK_BUMP_ROLLING_BAD)
        alpha_score = _clip01(1.0 - risk_score)

    n_roll = len(d["rolling_backtest_scores"])
    data_health = float(np.clip(n_roll / 20.0, 0.1, 1.0))
    confidence = float(data_health * champ_score)

    score_type = _pick_score_type(data_health, risk_score)

    registry = {
        "champion_version": str(ch["version"]),
        "challenger_version": str(q["version"]),
        "promotion_candidate": promotion_candidate,
        "champ_score": float(champ_score),
        "chall_score": float(chall_score),
    }

    nested = {
        "champ_score": float(champ_score),
        "chall_score": float(chall_score),
        "promotion_candidate": promotion_candidate,
        "rolling_mean": float(rolling_mean),
        "rolling_std": float(rolling_std),
        "rolling_score": float(rolling_score),
        "registry": registry,
        "min_trade_count_met": min_trade_count_met,
    }

    trade_permission = "ALLOW"
    reason = "lifecycle_ok"

    if rolling_mean < 0.0:
        trade_permission = "BLOCK"
        reason = "rolling_mean_negative"
    elif champ_score < 0.2:
        trade_permission = "BLOCK"
        reason = "champion_insufficient"

    return {
        "phase": 49,
        "module": "strategy_lifecycle_manager",
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
