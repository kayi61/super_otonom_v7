from __future__ import annotations

from super_otonom.health_summary import format_durum_line, format_tick_health


def test_format_tick_health_ok() -> None:
    st = {
        "pnl_pct": 0.2,
        "exposure_pct": 15.0,
        "emergency_stop": False,
        "emergency_reason": None,
        "hard_limits": {"orders_in_window": 0, "order_limit": 10},
    }
    d = {
        "symbol": "BTC/USDT",
        "tick_id": 3,
        "emergency_code": None,
        "entry_scale": "full",
        "liquidity_ratio": 0.45,
        "final_signal": "BUY",
        "signal_quality": 80,
        "adj_signal_quality": 85,
        "effective_quality_min": 50,
        "omega_ai_log": "[OMEGA-AI] TRENDING | x",
    }
    s = format_tick_health(st, d)
    assert "[OK]" in s
    assert "0/10" in s
    assert "BTC/USDT" in s
    assert "Exp: 15" in s
    assert "Liq:" in s
    assert "Qraw:80" in s
    assert "Qadj:85" in s
    assert "effective_qmin:50" in s
    assert "Scale:FULL" in s
    assert "BUY" in s
    assert "OMEGA-AI" in s


def test_format_durum_includes_fuses() -> None:
    st = {
        "equity": 100.0,
        "total_pnl": 0.0,
        "pnl_pct": 0.0,
        "peak_drawdown_pct": 0.0,
        "exposure_pct": 0.0,
        "total_trades": 0,
        "emergency_stop": False,
        "emergency_code_line": "—",
        "hard_limits": {"orders_in_window": 1, "order_limit": 5, "window_sec": 1.0},
        "rate_limit": {"rl_streak": 0, "rl_trip": 5},
    }
    line = format_durum_line(st)
    assert "Fuses" in line
    assert "rl=0/5" in line
    assert "ob=1/5" in line
