"""health_summary — format ve tekil log kurulumu."""
from __future__ import annotations

import logging

import pytest
import super_otonom.health_summary as hs


def test_format_durum_line_basic() -> None:
    st = {
        "equity": 1000.0,
        "total_pnl": 1.0,
        "pnl_pct": 0.1,
        "peak_drawdown_pct": 0.0,
        "exposure_pct": 5.0,
        "total_trades": 0,
        "emergency_stop": False,
        "emergency_code_line": "—",
        "hard_limits": {"orders_in_window": 0, "order_limit": 2, "window_sec": 10.0},
        "rate_limit": {"rl_streak": 0, "rl_trip": 0},
    }
    line = hs.format_durum_line(st)
    assert "eq=1000" in line
    assert "Fuses" in line


def test_format_tick_health_branches() -> None:
    st = {
        "pnl_pct": 1.2,
        "exposure_pct": 10.0,
        "emergency_stop": False,
        "hard_limits": {"orders_in_window": 0, "order_limit": 3},
    }
    t = hs.format_tick_health(st, None)
    assert "[OK]" in t
    st2 = dict(st, emergency_stop=True, emergency_reason="e")
    t2 = hs.format_tick_health(st2, None)
    assert "Emergency" in t2
    t3 = hs.format_tick_health(
        st,
        {
            "emergency_code": "EMERGENCY_STOP:x",
            "symbol": "S",
            "tick_id": 1,
            "entry_scale": "a",
            "liquidity_ratio": 0.5,
            "final_signal": "BUY",
            "signal_quality": 60,
            "adj_signal_quality": 55,
            "effective_quality_min": 50,
            "omega_ai_log": "x" * 200,
        },
    )
    assert "Qraw:60" in t3
    assert "…" in t3 or "omega" in t3.lower() or "x" in t3


def test_ensure_health_and_log_flush(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hs, "_HEALTH_FILE_SETUP", False)
    hs.ensure_health_file_logger(str(tmp_path))
    assert hs._HEALTH_FILE_SETUP is True
    hs.ensure_health_file_logger(str(tmp_path))
    dctx = {"symbol": "Z", "tick_id": 1}
    hs.log_tick_health(
        {
            "pnl_pct": 0.0,
            "exposure_pct": 0.0,
            "emergency_stop": False,
            "hard_limits": {"orders_in_window": 0, "order_limit": 1},
        },
        dctx,
    )
    for h in list(hs.log_health.handlers):
        if isinstance(h, logging.FileHandler):
            h.close()
            hs.log_health.removeHandler(h)
    monkeypatch.setattr(hs, "_HEALTH_FILE_SETUP", False)
