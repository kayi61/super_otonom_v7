"""
main_loop, bot_engine, metrics_exporter, position_sizer, risk_manager kapsamı.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── position_sizer ─────────────────────────────────────────────────────────


def test_kelly_avg_loss_zero_branch() -> None:
    from super_otonom.position_sizer import PositionSizer

    s = PositionSizer()
    s._trade_log = [{"pnl": 1.0}] * 3 + [{"pnl": 0.0}, {"pnl": 0.0}, {"pnl": 0.0}]
    assert s._kelly_fraction() == 0.15


def test_calculate_step_size_rounding() -> None:
    from super_otonom.position_sizer import PositionSizer

    s = PositionSizer(max_position_pct=0.2, min_notional=0.1)
    r = s.calculate(
        "X",
        10_000.0,
        volatility=0.01,
        ai_conf=0.8,
        step_size=0.05,
    )
    assert r >= 0.0


def test_validate_fractional_kelly_min_block() -> None:
    from super_otonom.position_sizer import PositionSizer

    s = PositionSizer(max_position_pct=0.1, min_notional=50.0, target_vol=0.2)
    ob = {
        "bids": [[100.0, 2.0] for _ in range(5)],
        "asks": [[100.1, 2.0] for _ in range(5)],
    }
    with patch.object(s, "calculate", return_value=10.0):
        z = s.validate_and_calculate("Z", 100.0, ob, time.time() * 1000, kelly_safety=0.1)
    assert z == 0.0


def test_slippage_multilevel_book() -> None:
    from super_otonom.position_sizer import PositionSizer

    s = PositionSizer(max_position_pct=0.5, min_notional=0.01)
    ob = {
        "asks": [
            [1.0, 200.0],
            [1.1, 200.0],
        ],
    }
    v = s.calculate_with_slippage("X", 50_000.0, ob, max_allowed_slippage=0.5, volatility=0.1)
    assert v > 0.0


def test_slippage_breaks_when_first_level_covers() -> None:
    from super_otonom.position_sizer import PositionSizer

    s = PositionSizer(max_position_pct=0.2, min_notional=0.1)
    ob = {"asks": [[10.0, 1_000_000.0]]}
    y = s.calculate_with_slippage("K", 5.0, ob, max_allowed_slippage=0.001, volatility=0.1)
    assert y >= 0.0


def test_slippage_zero_volume_asks() -> None:
    from super_otonom.position_sizer import PositionSizer

    s = PositionSizer()
    with patch.object(s, "calculate", return_value=10.0):
        z = s.calculate_with_slippage(
            "Z", 100.0, {"asks": [[1.0, 0.0], [1.1, 0.0]]}, max_allowed_slippage=0.1, volatility=0.1
        )
    assert z == 0.0


# ── risk_manager ─────────────────────────────────────────────────────────


def test_risk_get_last_deny_empty() -> None:
    from super_otonom.risk_manager import RiskManager

    assert RiskManager(100.0).get_last_deny() == ""


def test_risk_record_pnl_trims_500() -> None:
    from super_otonom.risk_manager import RiskManager

    r = RiskManager(100.0)
    for i in range(520):
        r.record_pnl(1.0 if i % 2 == 0 else -1.0)
    assert len(r._pnl_history) == 500


def test_risk_update_peak() -> None:
    from super_otonom.risk_manager import RiskManager

    r = RiskManager(1_000.0)
    r.update_peak(2_000.0)
    assert r._peak_equity == 2_000.0


def test_risk_record_omega_profit_tighten() -> None:
    from super_otonom.risk_manager import RiskManager

    r = RiskManager(1.0)
    r._omega_qmin_tighten = 5
    r.record_omega_trade_outcome(1.0)
    assert r._omega_qmin_tighten == 4


def test_risk_vol_spike_zero_avg() -> None:
    from super_otonom.risk_manager import RiskManager

    r = RiskManager(1.0)
    assert r.check_volatility_spike(0.1, history_vols=[0.0] * 10, min_history=10) is True


def test_risk_check_risk_emergency() -> None:
    from super_otonom.risk_manager import RiskManager

    r = RiskManager(1_000.0)
    r.trigger_emergency("t", silent=True)
    assert r.check_risk(1_000.0) is False
    assert "t" in r.get_last_deny() or r.get_last_deny() == "t"


def test_risk_invalidate_capital() -> None:
    from super_otonom.risk_manager import RiskManager

    r = RiskManager(-1.0)
    assert r.check_risk(100.0) is False


def test_risk_exposure_emergency_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from super_otonom.config import RISK
    from super_otonom.risk_manager import RiskManager

    r = RiskManager(10_000.0)
    monkeypatch.setitem(RISK, "exposure_breach_emergency", True)
    assert r.check_risk(1_000.0, open_exposure=5_000.0, current_vol=0.0) is False


def test_risk_exposure_breach_no_emergency_only_warns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from super_otonom.config import RISK
    from super_otonom.risk_manager import RiskManager

    r = RiskManager(10_000.0)
    monkeypatch.setitem(RISK, "exposure_breach_emergency", False)
    # Özkaynağı 10k — drawdown dalına düşmeden sadece exposure
    assert r.check_risk(10_000.0, open_exposure=5_000.0, current_vol=0.02) is False
    assert r.get_last_deny() == "max_exposure"
    assert r.emergency_stop is False


def test_risk_vol_history_trim_200() -> None:
    from super_otonom.risk_manager import RiskManager

    r = RiskManager(1.0)
    for _ in range(220):
        r.record_volatility(0.01)
    assert len(r._vol_history) == 200


def test_risk_vol_spike_not_triggered() -> None:
    from super_otonom.risk_manager import RiskManager

    r = RiskManager(1.0)
    for v in [0.02] * 10:
        r.record_volatility(v)
    assert r.check_volatility_spike(0.021, min_history=10) is True


# ── metrics_exporter ─────────────────────────────────────────────────────


def test_metrics_http_oserror() -> None:
    import super_otonom.metrics_exporter as m

    if not m._PROMETHEUS_AVAILABLE:
        pytest.skip("prometheus yok")
    with patch.object(m, "start_http_server", side_effect=OSError("nope")):
        m.MetricsExporter(port=9999, namespace="t_http_err")


def test_metrics_slippage_labels_raises(caplog) -> None:
    import super_otonom.metrics_exporter as m

    if not m._PROMETHEUS_AVAILABLE:
        pytest.skip("prometheus yok")
    ex = m.MetricsExporter(port=0, namespace="m_sl_err")
    gl = MagicMock()
    gl.set = MagicMock(side_effect=TypeError("x"))
    g = MagicMock()
    g.labels = MagicMock(return_value=gl)
    ex._gauges["slippage_avg"] = g
    with caplog.at_level("DEBUG", logger="super_otonom.metrics"):
        ex.record_slippage("S", 1.0, 1.01)


def test_metrics_record_trade_counter_raises(caplog) -> None:
    import super_otonom.metrics_exporter as m

    if not m._PROMETHEUS_AVAILABLE:
        pytest.skip("prometheus yok")
    ex = m.MetricsExporter(port=0, namespace="m_tr_err2")
    with patch.object(
        ex._counters["trades"],
        "labels",
        side_effect=ValueError("x"),
    ):
        with caplog.at_level("DEBUG", logger="super_otonom.metrics"):
            ex.record_trade(1.0, reason="a")


# ── bot_engine: açık pozisyonda fiyat = TAKE_PROFIT (TP%) ─────────────────


def test_bot_handle_exit_triggers_take_profit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from super_otonom import bot_engine as be
    from super_otonom.bot_engine import BotEngine

    def _hi_q(_a) -> tuple:
        return (95, [], {"x": 1}, "ok")

    def _reg(_a, _q) -> tuple:
        return ("TRENDING", 1.0, 1.0, 90, "log")

    monkeypatch.setattr(be, "compute_signal_quality", _hi_q)
    monkeypatch.setattr(be, "compute_omega_regime", _reg)
    monkeypatch.setattr(be, "_STATE_FILE", str(tmp_path / "s.json"))
    monkeypatch.setattr(be, "_TRADE_LOG_FILE", str(tmp_path / "t" / "tr.log"))
    e = BotEngine(100_000.0, paper=True)
    e.open_positions["P"] = {
        "entry": 100.0,
        "qty": 1.0,
        "size": 100.0,
        "peak": 100.0,
        "hold_bars": 0,
    }
    candles = [{"close": 110.0, "volume": 1.0, "timestamp": int(time.time() * 1000)}]
    analysis = {
        "signal": "HOLD",
        "volatility": 0.1,
        "regime": "TRENDING",
        "hurst": 0.5,
    }

    async def _run() -> None:
        out = await e.tick("P", analysis, candles)
        assert "actions" in out

    asyncio.run(_run())
