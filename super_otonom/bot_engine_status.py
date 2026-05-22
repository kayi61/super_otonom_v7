"""BotEngine status computation — extracted to reduce god-class size."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from super_otonom.kill_switch import get_rate_limit_storm_tracker

if TYPE_CHECKING:
    from super_otonom.bot_engine import BotEngine


def calc_wr_rr(trade_log: List[Dict[str, Any]]) -> Tuple[Optional[float], Optional[float], str]:
    n = len(trade_log)
    if n == 0:
        return None, None, "kapanan_islem_yok"
    recent = trade_log[-50:]
    wins = [t for t in recent if t["pnl"] > 0]
    losses = [t for t in recent if t["pnl"] <= 0]
    wr = len(wins) / len(recent) if recent else 0.0
    aw = sum(t["pnl"] for t in wins) / len(wins) if wins else 1.0
    al = sum(abs(t["pnl"]) for t in losses) / len(losses) if losses else 1.0
    rr = aw / al if al > 0 else 2.0
    guven = f"dusuk_ornek n={n}" if n < 5 else f"son {len(recent)} islem_ozet"
    return float(wr), float(rr), guven


def compute_engine_status(engine: BotEngine) -> Dict[str, Any]:
    total_pnl = engine.equity - engine.initial_capital
    pnl_pct = (total_pnl / engine.initial_capital) * 100.0 if engine.initial_capital else 0.0
    peak_dd = (
        (engine._peak_equity - engine.equity) / engine._peak_equity * 100.0
        if engine._peak_equity > 0
        else 0.0
    )
    risk_st = engine.risk.status_dict()
    wr, rr, guven = calc_wr_rr(engine.trade_log)
    corr_summary = engine.correlation_mgr.summary()
    open_exp = 0.0
    for p in engine.open_positions.values():
        open_exp += float(p.get("qty", 0)) * float(p.get("entry", 0))
    exp_pct = (open_exp / engine.equity * 100.0) if engine.equity > 0 else 0.0
    emg = bool(risk_st.get("emergency_stop"))
    er = risk_st.get("emergency_reason")
    if emg and er:
        ecode_line = f"EMERGENCY_STOP:{er}"
    elif emg:
        ecode_line = "EMERGENCY_STOP"
    else:
        ecode_line = "—"
    return {
        "mode": engine.mode,
        "initial_capital": round(engine.initial_capital, 2),
        "equity": round(engine.equity, 2),
        "free_capital": round(engine.free_capital, 2),
        "total_pnl": round(total_pnl, 2),
        "pnl_pct": round(pnl_pct, 2),
        "peak_drawdown_pct": round(peak_dd, 2),
        "exposure_notional": round(open_exp, 2),
        "exposure_pct": round(exp_pct, 1),
        "open_positions": len(engine.open_positions),
        "trades_today": engine._trades_today,
        "total_trades": len(engine.trade_log),
        "win_rate": None if wr is None else round(wr * 100, 1),
        "rr_ratio": None if rr is None else round(rr, 2),
        "metrik_guveni": guven,
        "var_95": risk_st["var_95"],
        "daily_loss": risk_st["daily_loss"],
        "emergency_stop": risk_st["emergency_stop"],
        "emergency_reason": risk_st.get("emergency_reason"),
        "emergency_code_line": ecode_line,
        "last_risk_deny": risk_st.get("last_risk_deny"),
        "omega_qmin_tighten": risk_st.get("omega_qmin_tighten"),
        "dynamic_daily_limit": risk_st.get("dynamic_daily_limit_pct"),
        "hard_limits": engine._hard_limits.status_line(),
        "rate_limit": get_rate_limit_storm_tracker().status_dict(),
        "corr_tracked_symbols": corr_summary["tracked_symbols"],
        "order_tracker_active": engine._order_tracker is not None,
        "capital": engine.capital.snapshot(),
        "risk_ontology": engine.onto.snapshot(),
        "alerts": engine.alerts.snapshot() if engine.alerts else None,
        "state_corrupt_fallback": engine._state_corrupt_fallback,
        "safe_mode_block_new_entries": engine._safe_mode_block_new_entries,
        "safe_mode_reason": engine._safe_mode_reason,
    }
