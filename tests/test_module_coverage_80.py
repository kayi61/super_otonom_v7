"""
main_loop, bot_engine, metrics_exporter, position_sizer, risk_manager — hedef kapsam.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── position_sizer ─────────────────────────────────────────────────────────


def test_position_sizer_set_weights_and_kelly_sized() -> None:
    from super_otonom.position_sizer import PositionSizer, _KELLY_MIN_TRADES

    s = PositionSizer(max_position_pct=0.2, min_notional=0.1)
    s.set_portfolio_weights({"A": 0.3, "B": 0.7})
    r0 = s.calculate("A", 10_000.0, volatility=0.01, ai_conf=0.5, override_weight=0.4)
    assert r0 > 0.0
    s._trade_log = [
        {"pnl": 5.0},
        {"pnl": 3.0},
        {"pnl": -1.0},
        {"pnl": -1.0},
        {"pnl": 1.0},
    ]
    assert len(s._trade_log) >= _KELLY_MIN_TRADES
    k = s._kelly_fraction()
    assert 0.0 <= k <= 0.35


def test_position_sizer_kelly_all_wins_fallback() -> None:
    from super_otonom.position_sizer import PositionSizer

    s = PositionSizer()
    s._trade_log = [{"pnl": 1.0} for _ in range(6)]
    assert s._kelly_fraction() == 0.15


def test_position_sizer_validate_stale_candle() -> None:
    from super_otonom.position_sizer import PositionSizer

    s = PositionSizer(min_notional=1.0)
    with patch("super_otonom.position_sizer.time") as t:
        t.time = lambda: 1_000.0
        z = s.validate_and_calculate(
            "S",
            100.0,
            {"bids": [[100, 1.0]], "asks": [[100.1, 1.0]]},
            last_candle_ts=0.0,
            max_candle_age_ms=0.0,
        )
    assert z == 0.0


def test_position_sizer_validate_empty_book_imbalance_and_safe_small() -> None:
    from super_otonom.position_sizer import PositionSizer

    s = PositionSizer(max_position_pct=0.1, min_notional=10_000.0)
    assert s.validate_and_calculate("S", 1000.0, {"bids": [], "asks": [[1, 1.0]]}, 9999999999.0) == 0.0
    ob = {
        "bids": [[100.0, 0.0001] for _ in range(5)],
        "asks": [[100.1, 10.0] for _ in range(5)],
    }
    s2 = PositionSizer(max_position_pct=0.2, min_notional=10_000.0)
    z = s2.validate_and_calculate("S2", 50_000.0, ob, time.time() * 1000, min_bid_imbalance=0.8)
    assert z == 0.0
    s3 = PositionSizer(max_position_pct=0.1, min_notional=10_000.0)
    z2 = s3.validate_and_calculate("S3", 100.0, {"bids": [[100, 1.0]], "asks": [[100.1, 1.0]]}, time.time() * 1000, volatility=0.5, kelly_safety=0.1)
    assert z2 == 0.0


def test_position_sizer_slippage_paths() -> None:
    from super_otonom.position_sizer import PositionSizer

    s = PositionSizer(max_position_pct=0.2, min_notional=0.1)
    ob = {
        "asks": [
            [1.0, 0.00001],
            [1.0, 0.00001],
        ],
    }
    a = s.calculate_with_slippage("X", 1_000_000.0, ob, max_allowed_slippage=0.0, volatility=0.1)
    assert a >= 0.0
    ob2 = {"asks": []}
    s2 = PositionSizer()
    with patch.object(s2, "calculate", return_value=0.0):
        assert s2.calculate_with_slippage("X", 100.0, ob2) == 0.0
    ob3 = {"asks": [[-1.0, 1.0]]}
    # best_ask <= 0 → erken dönüş, ham calculate çıktısı
    expect = s2.calculate("X", 1_000.0, volatility=0.1, ai_conf=0.5)
    assert s2.calculate_with_slippage("X", 1_000.0, ob3, max_allowed_slippage=0.1, volatility=0.1) == expect


# ── risk_manager ─────────────────────────────────────────────────────────


def test_risk_dynamic_capital_zero() -> None:
    from super_otonom.risk_manager import RiskManager

    rm = RiskManager(0.0)
    assert rm.check_dynamic_risk(0.0, 0.02) is False


def test_risk_maybe_reset_and_weekly() -> None:
    from super_otonom import risk_manager as m
    from super_otonom.risk_manager import RiskManager

    t0 = 1_000_000.0
    seq = [t0, t0 + 86400.1, t0 + 86400.1 + 604800.1]
    with patch.object(m, "time") as t:
        it = iter(seq)
        t.time = lambda: next(it, seq[-1])
        rm = RiskManager(1000.0)
        rm.daily_loss = 1.0
        rm.weekly_loss = 2.0
        rm._maybe_reset()
        assert rm.daily_loss == 0.0
        assert rm.weekly_loss == 0.0


def test_risk_check_risk_branches() -> None:
    from super_otonom.config import RISK
    from super_otonom.risk_manager import RiskManager

    r = RiskManager(10_000.0)
    r.weekly_loss = 10_000.0 * (RISK["max_weekly_loss_pct"] * 1.1)
    assert r.check_risk(10_000.0, 0.0, 0.0) is False

    r2 = RiskManager(10_000.0)
    r2._peak_equity = 20_000.0
    assert r2.check_risk(1000.0, 0.0, 0.0) is False

    r3 = RiskManager(10_000.0)
    monkey = pytest.MonkeyPatch()
    try:
        monkey.setitem(RISK, "exposure_breach_emergency", False)
        assert r3.check_risk(10_000.0, open_exposure=5000.0, current_vol=0.0) is False
    finally:
        monkey.undo()

    r4 = RiskManager(10_000.0)
    for v in [0.01] * 10:
        r4.record_volatility(v)
    r4.daily_loss = 0.0
    r4.weekly_loss = 0.0
    r4._peak_equity = 20_000.0
    assert r4.check_risk(20_000.0, 0.0, current_vol=1.0) is False

    r5 = RiskManager(1_000.0)
    r5.daily_loss = 0.0
    assert r5.check_risk(1_000.0, 0.0, current_vol=0.0) is True


# ── metrics_exporter (gerçek prometheus) ───────────────────────────────────


def test_metrics_exporter_reuses_prometheus_on_duplicate() -> None:
    pytest.importorskip("prometheus_client")
    from super_otonom.metrics_exporter import _PROMETHEUS_AVAILABLE, MetricsExporter

    if not _PROMETHEUS_AVAILABLE:
        pytest.skip("prometheus_client yok")
    ns = "cov80_metrics_dup"
    a = MetricsExporter(port=0, namespace=ns)
    b = MetricsExporter(port=0, namespace=ns)
    assert a._gauges["equity"] is b._gauges["equity"]


# ── main_loop (subprocess + startup dalları) ────────────────────────────


def test_main_loop_fresh_import_exits_on_live_without_confirm() -> None:
    import os

    os.environ.get("LIVE_CONFIRM", "")
    # subprocess: patch config so paper_mode is False and not YES
    here = Path(__file__).resolve().parent.parent
    code = f"""
        import os, sys
        os.chdir(r"{here}")
        if r"{str(here)}" not in sys.path:
            sys.path.insert(0, r"{str(here)}")
        from super_otonom import config
        config.GENERAL["paper_mode"] = False
        config.GENERAL["live_confirm"] = ""
        import importlib
        import super_otonom.main_loop
    """
    r = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(here),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 1


def test_log_elite_startup_branches() -> None:
    import super_otonom.main_loop as m

    class R:
        emergency_stop = True

    class E:
        risk = R()

    m.GENERAL["dry_run"] = True
    m.GENERAL["ml_service_enabled"] = True
    m._log_elite_startup(E())
    m.GENERAL["ml_service_enabled"] = False
    m.GENERAL["dry_run"] = False
    m._log_elite_startup(E())




# ── bot_engine — ek kapsam ──────────────────────────────────────────────


def test_trade_logger_write_error() -> None:
    from super_otonom.bot_engine import TradeLogger

    m = MagicMock()
    m.__enter__ = MagicMock(side_effect=OSError("x"))
    m.__exit__ = MagicMock(return_value=False)
    tl = TradeLogger("data/trades.log")
    with patch("builtins.open", return_value=m):
        tl.log_trade({"a": 1})


def test_order_tracker_get_status_error() -> None:
    from super_otonom.bot_engine import OrderTracker

    ex = MagicMock()
    ex.get_order_status = AsyncMock(side_effect=RuntimeError("e"))
    ot = OrderTracker(ex)
    ot.track("1", "S")

    async def _run() -> None:
        await ot.check_status()

    asyncio.run(_run())


def test_bot_load_save_state_error(tmp_path: Path) -> None:
    from super_otonom import bot_engine as be
    from super_otonom.bot_engine import BotEngine

    s = tmp_path / "s.json"
    s.write_text("{bad", encoding="utf-8")
    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(be, "_STATE_FILE", str(s))
        monkey.setattr(be, "_TRADE_LOG_FILE", str(tmp_path / "t" / "tr.log"))
        BotEngine(100.0, paper=True)
    finally:
        monkey.undo()


def test_save_state_makedirs_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from super_otonom import bot_engine as be
    from super_otonom.bot_engine import BotEngine

    p = str(tmp_path / "state" / "f.json")
    monkeypatch.setattr(be, "_STATE_FILE", p)
    monkeypatch.setattr(be, "_TRADE_LOG_FILE", str(tmp_path / "tr" / "t.log"))
    e = BotEngine(100.0, paper=True)
    with patch("os.makedirs", side_effect=OSError("e")):
        e._save_state()


def test_tick_trend_follow_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from super_otonom import bot_engine as be
    from super_otonom.bot_engine import BotEngine

    monkeypatch.setattr(be, "_STATE_FILE", str(tmp_path / "s.json"))
    monkeypatch.setattr(be, "_TRADE_LOG_FILE", str(tmp_path / "t.log"))
    e = BotEngine(10000.0, paper=True)
    candles = [{"close": 100.0, "volume": 1.0, "timestamp": time.time() * 1000}]
    analysis = {
        "signal": "BUY",
        "volatility": 0.01,
        "regime": "TRENDING",
        "hurst": 0.5,
        "execution_mode": "TREND_FOLLOW",
    }

    async def _run() -> None:
        out = await e.tick("B", analysis, candles)
        assert out.get("decision_context") is not None

    asyncio.run(_run())


def test_status_emergency_line_variants(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from super_otonom import bot_engine as be
    from super_otonom.bot_engine import BotEngine

    monkeypatch.setattr(be, "_STATE_FILE", str(tmp_path / "s.json"))
    monkeypatch.setattr(be, "_TRADE_LOG_FILE", str(tmp_path / "t.log"))
    e = BotEngine(100.0, paper=True)
    e.risk.emergency_stop = True
    s = e.status()
    assert "EMERGENCY" in s.get("emergency_code_line", "")
    e.risk.emergency_stop = True
    e.risk.emergency_reason = "x"
    s2 = e.status()
    assert s2.get("emergency_code_line", "").endswith("x")


def test_tick_price_spike_with_open_ignores() -> None:
    from super_otonom import bot_engine as be
    from super_otonom.bot_engine import BotEngine
    from unittest.mock import patch

    e = BotEngine(1000.0, paper=True)
    e.open_positions["B"] = {"entry": 1.0, "qty": 1.0, "size": 1.0, "peak": 1.0}
    candles = [{"close": 1.0, "volume": 1.0, "timestamp": 0.0}]

    with patch.object(
        e._hard_limits, "check_price_tick", return_value="PRICE_BOMB"
    ), patch(
        "super_otonom.bot_engine.gate_global_trade_disable", return_value=(True, "")
    ):
        async def _run() -> None:
            await e.tick("B", {"signal": "HOLD", "volatility": 0.01}, candles)

        asyncio.run(_run())
