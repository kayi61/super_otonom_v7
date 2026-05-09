"""
Faz 39 — Otomatik risk kontrolü: Kelly boyutlandırma, drawdown gate, ardışık kayıp kesici.

Sadece NumPy.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Literal, Tuple

import numpy as np

_EPS = 1e-9
_HALF_LIFE_MS = 10_000
_KELLY_CAP = 0.25

TradePermission = Literal["ALLOW", "BLOCK", "HALT"]


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


def compute_kelly(win_rate: float, avg_win: float, avg_loss: float) -> Tuple[float, float]:
    """Kelly kesri [0, 0.25] ve half-Kelly."""
    w = float(np.clip(win_rate, 0.0, 1.0))
    aw = float(max(avg_win, 0.0))
    al = float(max(abs(avg_loss), _EPS))
    b = aw / al
    raw = w - (1.0 - w) / max(b, _EPS)
    kelly = float(np.clip(raw, 0.0, _KELLY_CAP))
    half = kelly * 0.5
    return kelly, half


def compute_drawdown(equity_curve: List[float]) -> Tuple[float, float]:
    """current_drawdown ∈ [0,1], peak equity."""
    eq = np.asarray([float(x) for x in equity_curve], dtype=float)
    if eq.size == 0:
        return 0.0, 0.0
    peak = float(np.max(eq))
    cur = float(eq[-1])
    dd = (peak - cur) / max(peak, _EPS)
    return float(np.clip(dd, 0.0, 1.0)), peak


def count_consecutive_losses(recent_trades: List[Dict[str, Any]]) -> int:
    """Sondan geriye ardışık negatif pnl sayısı."""
    if not recent_trades:
        return 0
    n = 0
    for t in reversed(recent_trades):
        if not isinstance(t, dict):
            break
        try:
            pnl = float(t.get("pnl", 0.0))
        except (TypeError, ValueError):
            break
        if pnl < 0.0:
            n += 1
        else:
            break
    return n


def validate_market_data(data: Any) -> Tuple[bool, str]:
    if data is None or not isinstance(data, dict):
        return False, "market_data_missing_or_invalid"

    req = (
        "equity_curve",
        "recent_trades",
        "win_rate",
        "avg_win",
        "avg_loss",
        "max_drawdown_pct",
        "consecutive_loss_limit",
    )
    for k in req:
        if k not in data:
            return False, f"missing_field:{k}"

    ec = data["equity_curve"]
    if not isinstance(ec, (list, tuple)) or len(ec) == 0:
        return False, "equity_curve_empty"
    try:
        for x in ec:
            float(x)
    except (TypeError, ValueError):
        return False, "equity_curve_non_numeric"

    rt = data["recent_trades"]
    if not isinstance(rt, list):
        return False, "recent_trades_not_list"

    try:
        wr = float(data["win_rate"])
        float(data["avg_win"])
        float(data["avg_loss"])
        mdd = float(data["max_drawdown_pct"])
        int(data["consecutive_loss_limit"])
    except (TypeError, ValueError):
        return False, "numeric_parse_error"

    if not (0.0 <= wr <= 1.0):
        return False, "win_rate_out_of_range"
    if not (0.0 <= mdd <= 1.0):
        return False, "max_drawdown_pct_out_of_range"
    if int(data["consecutive_loss_limit"]) < 1:
        return False, "consecutive_loss_limit_invalid"

    return True, ""


def analyze(market_data: dict | None) -> dict:
    """Kelly + drawdown + kayıp zinciri — Faz 39 standart payload."""
    ts = _now_ms()
    empty: Dict[str, Any] = {}

    ok, err = validate_market_data(market_data)
    if not ok:
        return {
            "phase": 39,
            "module": "auto_risk_controller",
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

    equity = [float(x) for x in d["equity_curve"]]
    trades = d["recent_trades"]
    win_rate = float(d["win_rate"])
    avg_win = float(d["avg_win"])
    avg_loss = float(d["avg_loss"])
    max_dd_pct = float(d["max_drawdown_pct"])
    loss_limit = int(d["consecutive_loss_limit"])

    kelly_fraction, half_kelly = compute_kelly(win_rate, avg_win, avg_loss)

    current_drawdown, _ = compute_drawdown(equity)
    drawdown_breach = bool(current_drawdown >= max_dd_pct)

    consecutive_losses = count_consecutive_losses(trades)
    loss_break = bool(consecutive_losses >= loss_limit)

    drawdown_score = _clip01(current_drawdown / max(max_dd_pct, _EPS))
    loss_streak_score = _clip01(consecutive_losses / max(loss_limit, 1))

    risk_score = _clip01(0.6 * drawdown_score + 0.4 * loss_streak_score)

    alpha_score = _clip01(kelly_fraction * 2.0)

    data_health = float(np.clip(len(equity) / 100.0, 0.1, 1.0))
    confidence = _clip01(data_health * (1.0 - risk_score * 0.5))

    score_type = _pick_score_type(data_health, risk_score)

    trade_permission: TradePermission = "ALLOW"
    reason = "risk_checks_passed"

    if drawdown_breach:
        trade_permission = "BLOCK"
        reason = "drawdown_gate"
    elif loss_break:
        trade_permission = "BLOCK"
        reason = "consecutive_loss_breaker"

    nested = {
        "kelly_fraction": float(kelly_fraction),
        "half_kelly": float(half_kelly),
        "current_drawdown": float(current_drawdown),
        "drawdown_breach": drawdown_breach,
        "consecutive_losses": int(consecutive_losses),
        "drawdown_score": float(drawdown_score),
        "loss_streak_score": float(loss_streak_score),
    }

    return {
        "phase": 39,
        "module": "auto_risk_controller",
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
