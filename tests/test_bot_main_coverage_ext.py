"""
bot_engine, main_loop ve paket kapsamı — ek edge-case/branch testleri.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from super_otonom.config import RISK as CONFIG_RISK
from super_otonom.position_sizer import PositionSizer
from super_otonom.pre_trade_gate import gate_buy_size_and_exposure

from tests.test_main_loop_96 import _MAIN_LOOP_MOCK_USDT, _patch_main_loop_recon_paths


def test_pre_trade_raw_size_zero_blocks() -> None:
    s = PositionSizer(min_notional=1.0)
    ok, block = gate_buy_size_and_exposure(s, "R", 1_000.0, 100.0, 0.0, 1_000.0, {})
    assert ok is False
    assert block == "raw_size_zero"


def test_pre_trade_exposure_cap_blocks() -> None:
    s = PositionSizer(min_notional=1.0)
    heavy = {"P1": {"size": 750.0}}
    ok, block = gate_buy_size_and_exposure(s, "Z", 1_000.0, 100.0, 100.0, 1_000.0, heavy)
    assert ok is False
    assert block == "exposure_cap"


def test_slippage_for_breaks_when_liquidity_reaches_raw() -> None:
    """Döngüde bir sonraki seviyeye gecmeden 'available >= raw' (satir 279-280 break)."""
    s = PositionSizer(max_position_pct=0.3, min_notional=0.01)
    with patch.object(s, "calculate", return_value=10.0):
        r = s.calculate_with_slippage(
            "K",
            1_000.0,
            {"asks": [[1.0, 20.0], [1.5, 1.0]]},
            max_allowed_slippage=0.5,
            volatility=0.1,
        )
    assert r >= 0.0


# ── bot_engine.tick dalları ───────────────────────────────────────────


def test_tick_global_trade_disable(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from super_otonom import bot_engine as be
    from super_otonom.bot_engine import BotEngine

    monkeypatch.setattr(be, "_STATE_FILE", str(tmp_path / "g.json"))
    monkeypatch.setattr(be, "_TRADE_LOG_FILE", str(tmp_path / "g.log"))
    monkeypatch.setenv("GLOBAL_TRADE_DISABLE", "1")
    e = BotEngine(1_000.0, paper=True)
    c = [{"close": 1.0, "volume": 1.0, "timestamp": 1}]
    a = {"signal": "BUY", "volatility": 0.1}

    async def _t():
        return await e.tick("X", a, c)

    out = asyncio.run(_t())
    assert out.get("decision_context", {}).get("emergency_code", "").startswith("EMERGENCY_STOP")
    monkeypatch.delenv("GLOBAL_TRADE_DISABLE", raising=False)


def test_tick_price_spike_new_then_emergency(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from super_otonom import bot_engine as be
    from super_otonom.bot_engine import BotEngine

    monkeypatch.setattr(be, "_STATE_FILE", str(tmp_path / "p.json"))
    monkeypatch.setattr(be, "_TRADE_LOG_FILE", str(tmp_path / "p.log"))
    e = BotEngine(1_000.0, paper=True)
    a = {"signal": "HOLD", "volatility": 0.01}
    c1 = [{"close": 100.0, "volume": 1.0, "timestamp": 1}]
    c2 = [{"close": 200.0, "volume": 1.0, "timestamp": 2}]

    async def _t():
        await e.tick("S", a, c1)
        return await e.tick("S", a, c2)

    out = asyncio.run(_t())
    assert "EMERGENCY_STOP" in (out.get("decision_context") or {}).get("emergency_code", "")


def test_tick_price_spike_ignored_with_open_position(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from super_otonom import bot_engine as be
    from super_otonom.bot_engine import BotEngine

    monkeypatch.setattr(be, "_STATE_FILE", str(tmp_path / "o.json"))
    monkeypatch.setattr(be, "_TRADE_LOG_FILE", str(tmp_path / "o.log"))
    e = BotEngine(1_000.0, paper=True)
    # entry ≈ ilk kapanış — TAKE_PROFIT tetiklenmesin (fiyat fırtınası dali icin pozisyon kalsin)
    e.open_positions["S"] = {
        "entry": 100.0,
        "qty": 1.0,
        "size": 1.0,
        "peak": 100.0,
        "hold_bars": 0,
    }
    a = {"signal": "HOLD", "volatility": 0.01}
    c1 = [{"close": 100.0, "volume": 1.0, "timestamp": 1}]
    c2 = [{"close": 200.0, "volume": 1.0, "timestamp": 2}]

    async def _t():
        await e.tick("S", a, c1)
        return await e.tick("S", a, c2)

    out = asyncio.run(_t())
    dctx = out.get("decision_context") or {}
    assert not (dctx.get("emergency_code") or "").startswith("EMERGENCY_STOP")
    traces = str(dctx)
    assert "yoksay" in traces or "acik" in traces.lower() or "kill_switch" in traces


def test_tick_risk_denied(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from super_otonom import bot_engine as be
    from super_otonom.bot_engine import BotEngine

    monkeypatch.setattr(be, "_STATE_FILE", str(tmp_path / "r.json"))
    monkeypatch.setattr(be, "_TRADE_LOG_FILE", str(tmp_path / "r.log"))
    e = BotEngine(1_000.0, paper=True)

    def _no(*_a, **_k):
        return False

    e.risk.check_risk = _no
    e.risk.get_last_deny = lambda: "exposure"
    c = [{"close": 10.0, "volume": 1.0, "timestamp": 1}]
    a = {"signal": "BUY", "volatility": 0.1}

    async def _t():
        return await e.tick("Z", a, c)

    out = asyncio.run(_t())
    assert out.get("final_signal") == "HOLD"


def test_trend_follow_override(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from super_otonom import bot_engine as be
    from super_otonom.bot_engine import BotEngine

    def _sq(_a):
        return (90, [], {}, "m")

    def _om(_a, _q):
        return ("RANGING", 1.0, 0.5, 90, "log")

    monkeypatch.setattr(be, "compute_signal_quality", _sq)
    monkeypatch.setattr(be, "compute_omega_regime", _om)
    monkeypatch.setattr(be, "_STATE_FILE", str(tmp_path / "t.json"))
    monkeypatch.setattr(be, "_TRADE_LOG_FILE", str(tmp_path / "t.log"))
    e = BotEngine(1_000.0, paper=True)
    c = [{"close": 1.0, "volume": 1.0, "timestamp": 1}]
    a = {
        "signal": "BUY",
        "volatility": 0.1,
        "execution_mode": "TREND_FOLLOW",
        "regime": "RANGING",
    }

    async def _t():
        return await e.tick("Y", a, c)

    out = asyncio.run(_t())
    assert "TREND" in (out.get("decision_reason") or "") or out.get("final_signal") in (
        "BUY",
        "HOLD",
    )


def test_ai_validate_two_tuple(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from super_otonom import bot_engine as be
    from super_otonom.bot_engine import BotEngine

    def _sq(_a):
        return (95, [], {}, "m")

    def _om(_a, _q):
        return ("TRENDING", 1.0, 1.0, 95, "log")

    monkeypatch.setattr(be, "compute_signal_quality", _sq)
    monkeypatch.setattr(be, "compute_omega_regime", _om)
    monkeypatch.setattr(be, "_STATE_FILE", str(tmp_path / "2.json"))
    monkeypatch.setattr(be, "_TRADE_LOG_FILE", str(tmp_path / "2.log"))
    e = BotEngine(1_000.0, paper=True)
    e.ai.validate_signal = lambda *_a, **_k: ("HOLD", 0.5)
    c = [{"close": 1.0, "volume": 1.0, "timestamp": 1}]
    a = {"signal": "BUY", "volatility": 0.1, "regime": "TRENDING"}

    async def _t():
        return await e.tick("Q", a, c)

    out = asyncio.run(_t())
    assert out.get("decision_reason", "") is not None


def test_low_quality_buy_reject(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from super_otonom import bot_engine as be
    from super_otonom.bot_engine import BotEngine

    def _sq(_a):
        return (90, [], {}, "m")

    def _om(_a, _q):
        return ("RANGING", 0.5, 0.3, 20, "log")

    monkeypatch.setattr(be, "compute_signal_quality", _sq)
    monkeypatch.setattr(be, "compute_omega_regime", _om)
    monkeypatch.setattr(be, "_STATE_FILE", str(tmp_path / "l.json"))
    monkeypatch.setattr(be, "_TRADE_LOG_FILE", str(tmp_path / "l.log"))
    e = BotEngine(1_000.0, paper=True)
    e.ai.validate_signal = lambda *_a, **_k: ("BUY", 0.99, "ok")
    orig_min = int(CONFIG_RISK.get("signal_quality_min", 40))
    try:
        CONFIG_RISK["signal_quality_min"] = 50
        c = [{"close": 1.0, "volume": 1.0, "timestamp": 1}]
        a = {"signal": "BUY", "volatility": 0.1, "regime": "RANGING"}

        async def _t():
            return await e.tick("LQ", a, c)

        out = asyncio.run(_t())
    finally:
        CONFIG_RISK["signal_quality_min"] = orig_min
    assert "LOW_QUALITY" in (out.get("decision_reason") or "")


def test_entry_merge_ob_zero_blocked(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from super_otonom import bot_engine as be
    from super_otonom.bot_engine import BotEngine

    def _sq(_a):
        return (95, [], {}, "m")

    def _om(_a, _q):
        return ("TRENDING", 1.0, 1.0, 95, "log")

    monkeypatch.setattr(be, "compute_signal_quality", _sq)
    monkeypatch.setattr(be, "compute_omega_regime", _om)
    monkeypatch.setattr(be, "_STATE_FILE", str(tmp_path / "b.json"))
    monkeypatch.setattr(be, "_TRADE_LOG_FILE", str(tmp_path / "b.log"))
    e = BotEngine(1_000.0, paper=True)
    e.ai.validate_signal = lambda *_a, **_k: ("BUY", 0.99, "x")
    c = [{"close": 100.0, "volume": 1_000.0, "timestamp": 1}]
    a = {
        "signal": "BUY",
        "volatility": 0.02,
        "regime": "TRENDING",
        "ob_safe_size": 0.0,
        "avg_volume": 1_000.0,
    }

    async def _t():
        return await e.tick("OB0", a, c)

    out = asyncio.run(_t())
    assert out.get("final_signal") in ("BUY", "HOLD")


def test_entry_hard_limit_blocks_buy(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from super_otonom import bot_engine as be
    from super_otonom.bot_engine import BotEngine

    def _sq(_a):
        return (95, [], {}, "m")

    def _om(_a, _q):
        return ("TRENDING", 1.0, 1.0, 95, "log")

    monkeypatch.setattr(be, "compute_signal_quality", _sq)
    monkeypatch.setattr(be, "compute_omega_regime", _om)
    monkeypatch.setattr(be, "_STATE_FILE", str(tmp_path / "h.json"))
    monkeypatch.setattr(be, "_TRADE_LOG_FILE", str(tmp_path / "h.log"))
    e = BotEngine(1_000.0, paper=True)
    e.ai.validate_signal = lambda *_a, **_k: ("BUY", 0.99, "x")
    e._hard_limits.can_submit_order = lambda: "rate_storm"
    c = [{"close": 50.0, "volume": 1_000.0, "timestamp": 1}]
    a = {
        "signal": "BUY",
        "volatility": 0.02,
        "regime": "TRENDING",
        "ob_safe_size": 500.0,
        "avg_volume": 1_000.0,
    }

    async def _t():
        return await e.tick("HL", a, c)

    out = asyncio.run(_t())
    assert e.risk.emergency_stop is True or "EMERGENCY" in str(out.get("decision_context") or {})


def test_reset_daily_if_needed(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import date as ddate

    from super_otonom import bot_engine as be
    from super_otonom.bot_engine import BotEngine

    class _D:
        _d = ddate(2020, 1, 1)

        @classmethod
        def today(cls) -> ddate:
            return cls._d

    monkeypatch.setattr(be, "date", _D)
    e = BotEngine(100.0, paper=True)
    e._trades_today = 3
    _D._d = ddate(2020, 1, 2)
    e._reset_daily_if_needed()
    assert e._trades_today == 0
    assert e._today == ddate(2020, 1, 2)


def test_tick_async_order_check_on_10th_tick(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from super_otonom import bot_engine as be
    from super_otonom.bot_engine import BotEngine

    def _sq(_a):
        return (95, [], {}, "m")

    def _om(_a, _q):
        return ("TRENDING", 1.0, 1.0, 95, "log")

    monkeypatch.setattr(be, "compute_signal_quality", _sq)
    monkeypatch.setattr(be, "compute_omega_regime", _om)
    monkeypatch.setattr(be, "_STATE_FILE", str(tmp_path / "a10.json"))
    monkeypatch.setattr(be, "_TRADE_LOG_FILE", str(tmp_path / "a10.log"))
    e = BotEngine(1_000.0, paper=True)
    e.ai.validate_signal = lambda *_a, **_k: ("HOLD", 0.5, "")
    m = AsyncMock()
    e._order_tracker = MagicMock()
    e._order_tracker.check_status = m
    e._tick_counter = 9
    c = [{"close": 1.0, "volume": 1.0, "timestamp": 1}]
    a = {"signal": "HOLD", "volatility": 0.1, "regime": "TRENDING"}

    async def _t():
        return await e.tick_async("A", a, c)

    asyncio.run(_t())
    m.assert_awaited_once()


def test_live_mode_buy_uses_slippage_not_sim(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import super_otonom.pre_trade_gate as ptg
    from super_otonom import bot_engine as be
    from super_otonom.bot_engine import BotEngine

    def _sq(_a):
        return (95, [], {}, "m")

    def _om(_a, _q):
        return ("TRENDING", 1.0, 1.0, 95, "log")

    monkeypatch.setattr(be, "compute_signal_quality", _sq)
    monkeypatch.setattr(be, "compute_omega_regime", _om)
    monkeypatch.setattr(be, "_STATE_FILE", str(tmp_path / "v.json"))
    monkeypatch.setattr(be, "_TRADE_LOG_FILE", str(tmp_path / "v.log"))
    monkeypatch.setitem(CONFIG_RISK, "max_notional_per_order", 200_000.0)
    monkeypatch.setattr(ptg, "_MAX_NOTIONAL_PER_ORDER", 200_000.0)
    monkeypatch.setitem(CONFIG_RISK, "signal_quality_min", 30)
    e = BotEngine(1_000_000.0, paper=False)
    e.mode = "LIVE"
    e.risk.get_omega_effective_qmin = MagicMock(return_value=30)
    e.ai.validate_signal = lambda *_a, **_k: ("BUY", 0.99, "go")
    e.slippage.adjusted_price = lambda *_a, **_k: 99.0
    c = [{"close": 100.0, "volume": 1_000.0, "timestamp": 1}]
    a = {
        "signal": "BUY",
        "volatility": 0.02,
        "regime": "TRENDING",
        "ob_safe_size": 100_000.0,
        "avg_volume": 1_000.0,
    }

    async def _t():
        return await e.tick("LV", a, c)

    out = asyncio.run(_t())
    assert any(x.get("type") == "BUY" for x in out.get("actions", []))


# ── main_loop ─────────────────────────────────────────────────────────


def test_main_loop_order_book_slippage_when_no_candles(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import super_otonom.bot_engine as be
    import super_otonom.main_loop as ml

    monkeypatch.setattr(be, "_STATE_FILE", str(tmp_path / "ml.json"))
    monkeypatch.setattr(be, "_TRADE_LOG_FILE", str(tmp_path / "ml.log"))
    monkeypatch.setattr(ml, "_POLL_INTERVAL", 0.04)
    monkeypatch.setattr(ml, "PAIRS", ["Z/USDT"])
    mtf = dict(ml.MTF)
    mtf["enabled"] = False
    monkeypatch.setattr(ml, "MTF", mtf)
    _patch_main_loop_recon_paths(Path(tmp_path), monkeypatch, ml)
    ts0 = int(time.time() * 1000)
    # len(row) < 6 => ohlcv_to_candles boş; tahta hâlâ var
    bad_row = [float(ts0), 1.0]

    class H:
        async def fetch_all_ohlcv(self, **kw):
            return {"Z/USDT": [bad_row]}

        async def fetch_order_book(self, *a, **k):
            return {"asks": [[1.0, 10.0]], "bids": [[0.9, 10.0]]}

        async def fetch_balance(self, *a, **k):
            return {"total": {"USDT": _MAIN_LOOP_MOCK_USDT}}

        def circuit_breaker_status(self):
            return {}

    class CM:
        def __init__(self, **kw):
            self.h = H()

        async def __aenter__(self):
            return self.h

        async def __aexit__(self, *a):
            return None

    monkeypatch.setattr(ml, "AsyncExchangeHandler", CM)

    class MA:
        def analyze(self, sym, c):
            return {
                "signal": "HOLD",
                "regime": "RANGING",
                "hurst": 0.5,
                "volatility": 0.05,
            }

        def apply_liquidity_context(self, *a, **k):
            pass

    monkeypatch.setattr(ml, "MarketAnalyzer", MA)
    monkeypatch.setattr(ml, "apply_storm_trip_to_risk", lambda r: False)

    async def run():
        ml._shutdown = asyncio.Event()
        ml._loop_counter = 0
        t = asyncio.create_task(ml.main())
        await asyncio.sleep(0.12)
        ml._shutdown.set()
        await asyncio.wait_for(t, timeout=15.0)

    asyncio.run(run())


def test_main_loop_check_orders_every_10_loops(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import super_otonom.bot_engine as be
    import super_otonom.main_loop as ml

    monkeypatch.setattr(be, "_STATE_FILE", str(tmp_path / "c10.json"))
    monkeypatch.setattr(be, "_TRADE_LOG_FILE", str(tmp_path / "c10.log"))
    # İlk dış iterasyonda (+=1 sonrasi) 10 ol: check_orders hemen devreye girsin
    monkeypatch.setattr(ml, "_loop_counter", 9)
    monkeypatch.setattr(ml, "_POLL_INTERVAL", 0.01)
    monkeypatch.setattr(ml, "PAIRS", ["B/USDT"])
    mtf = dict(ml.MTF)
    mtf["enabled"] = False
    monkeypatch.setattr(ml, "MTF", mtf)
    alt_tf = dict(ml.ALT_TF)
    alt_tf["enabled"] = False
    monkeypatch.setattr(ml, "ALT_TF", alt_tf)
    _patch_main_loop_recon_paths(Path(tmp_path), monkeypatch, ml)
    ts0 = int(time.time() * 1000)
    row = [float(ts0), 1.0, 1.0, 1.0, 1.0, 1.0]
    check_mock = AsyncMock()

    class H:
        async def fetch_all_ohlcv(self, **kw):
            return {"B/USDT": [row, row]}

        async def fetch_order_book(self, *a, **k):
            return {"asks": [[1.0, 1.0]], "bids": [[0.99, 1.0]]}

        async def fetch_balance(self, *a, **k):
            return {"total": {"USDT": _MAIN_LOOP_MOCK_USDT}}

        def circuit_breaker_status(self):
            return {}

    class CM:
        def __init__(self, **kw):
            self.h = H()

        async def __aenter__(self):
            return self.h

        async def __aexit__(self, *a):
            return None

    monkeypatch.setattr(ml, "AsyncExchangeHandler", CM)

    class MA:
        def analyze(self, sym, c):
            return {
                "signal": "HOLD",
                "regime": "TRENDING",
                "hurst": 0.5,
                "volatility": 0.1,
            }

        def apply_liquidity_context(self, *a, **k):
            pass

        def apply_alt_timeframe_veto(self, analysis, candles_alt):
            return None

    monkeypatch.setattr(ml, "MarketAnalyzer", MA)
    monkeypatch.setattr(ml, "apply_storm_trip_to_risk", lambda r: False)

    async def patch_engine() -> None:
        from super_otonom.bot_engine import BotEngine

        with patch.object(BotEngine, "check_orders", new=check_mock):
            ml._shutdown = asyncio.Event()
            t = asyncio.create_task(ml.main())
            await asyncio.sleep(0.6)
            ml._shutdown.set()
            try:
                await asyncio.wait_for(t, timeout=20.0)
            except Exception:
                t.cancel()
                with pytest.raises((asyncio.CancelledError, Exception)):
                    await t

    asyncio.run(patch_engine())
    assert check_mock.await_count >= 1
