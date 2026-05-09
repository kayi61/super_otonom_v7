"""
main_loop.py yuksek kapsam: canlı çıkış, POSIX sinyal, MTF, storm, log/eylem, exception.
Kosum: pytest tests/ --cov=super_otonom.main_loop (veya --cov=super_otonom) ...
Not: --cov=super_otonom/main_path.py bazi ortamlarda modül bulunmaz; noktali isim kullanin.
Giris noktasi (if __name__) pragma ile sayim disi: çalistirma `python -m super_otonom.main_loop`.
"""
from __future__ import annotations

import asyncio
import importlib
import signal
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import super_otonom.config as _cfg

# ---------------------------------------------------------------------------
# 38–44: canlı + onay yok -> sys.exit(1) (importlib.reload)
# ---------------------------------------------------------------------------


def test_main_loop_reload_exits_on_live_without_confirm() -> None:
    import super_otonom.main_loop as ml

    orig_pm = _cfg.GENERAL.get("paper_mode", True)
    orig_lc = _cfg.GENERAL.get("live_confirm", "")
    _cfg.GENERAL["paper_mode"] = False
    _cfg.GENERAL["live_confirm"] = ""
    try:
        with pytest.raises(SystemExit) as exc:
            importlib.reload(ml)
        assert exc.value.code == 1
    finally:
        _cfg.GENERAL["paper_mode"] = orig_pm
        _cfg.GENERAL["live_confirm"] = orig_lc
        importlib.reload(ml)


# ---------------------------------------------------------------------------
# Yardimci: kisa yasayan main() senaryolari
# ---------------------------------------------------------------------------


def _ml_common_engines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pairs: list[str]
) -> Any:
    import super_otonom.bot_engine as be
    import super_otonom.main_loop as ml

    monkeypatch.setattr(be, "_STATE_FILE", str(tmp_path / "st.json"))
    monkeypatch.setattr(be, "_TRADE_LOG_FILE", str(tmp_path / "tr" / "log.log"))
    monkeypatch.setattr(ml, "PAIRS", pairs)
    monkeypatch.setattr(ml, "_POLL_INTERVAL", 0.02)
    ml._shutdown = asyncio.Event()
    ml._loop_counter = 0
    return ml


# ---------------------------------------------------------------------------
# 89–91: POSIX — asyncio.get_running_loop + add_signal_handler
# ---------------------------------------------------------------------------


def test_main_adds_posix_signal_handlers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from super_otonom import main_loop as ml
    from super_otonom.config import MTF

    ml_mod = _ml_common_engines(tmp_path, monkeypatch, ["P/USDT"])
    mtf = dict(MTF)
    mtf["enabled"] = False
    monkeypatch.setattr(ml, "MTF", mtf)

    ts0 = int(time.time() * 1000)
    row = [float(ts0), 1.0, 1.0, 1.0, 1.0, 1.0]
    sym0 = ml_mod.PAIRS[0]

    class H:
        async def fetch_all_ohlcv(self, **kw) -> dict:
            return {sym0: [row, row]}

        async def fetch_order_book(self, *a, **k) -> dict:
            return {"asks": [[1.0, 1.0]], "bids": [[0.9, 1.0]]}

        def circuit_breaker_status(self) -> dict:
            return {}

    class CM:
        def __init__(self, **kw) -> None:
            self.h = H()

        async def __aenter__(self) -> "H":  # noqa: F821
            return self.h

        async def __aexit__(self, *a) -> object:
            return None

    monkeypatch.setattr(ml, "AsyncExchangeHandler", CM)

    class MA:
        def analyze(self, sym: str, c: list) -> dict:
            return {
                "signal": "HOLD",
                "regime": "RANGING",
                "hurst": 0.5,
                "volatility": 0.05,
            }

        def apply_liquidity_context(self, *a, **k) -> None:
            pass

    monkeypatch.setattr(ml, "MarketAnalyzer", MA)
    monkeypatch.setattr(ml, "apply_storm_trip_to_risk", lambda r: False)

    mloop = MagicMock()
    mloop.add_signal_handler = MagicMock()

    async def _run() -> None:
        with patch.object(sys, "platform", "linux"):
            with patch(
                "super_otonom.main_loop.asyncio.get_running_loop",
                return_value=mloop,
            ):
                t = asyncio.create_task(ml_mod.main())
                await asyncio.sleep(0.1)
                ml_mod._shutdown.set()
                await asyncio.wait_for(t, timeout=20.0)

    asyncio.run(_run())
    assert mloop.add_signal_handler.call_count >= 2
    sargs = {c.args[0] for c in mloop.add_signal_handler.call_args_list}
    assert signal.SIGINT in sargs
    assert signal.SIGTERM in sargs


# ---------------------------------------------------------------------------
# 157–158, 161, 196: CB OPEN uyarisi + storm (ana dongu; prep OB oncesi cikis)
# ---------------------------------------------------------------------------


def test_circuit_open_warning_and_storm_trip_both_sites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from super_otonom import main_loop as ml
    from super_otonom.config import MTF

    mtf = dict(MTF)
    mtf["enabled"] = False
    monkeypatch.setattr(ml, "MTF", mtf)
    ml_mod = _ml_common_engines(tmp_path, monkeypatch, ["C/USDT"])

    sym = "C/USDT"
    ts0 = int(time.time() * 1000)
    row = [float(ts0), 1.0, 1.0, 1.0, 1.0, 1.0]

    class H:
        async def fetch_all_ohlcv(self, **kw) -> dict:
            return {sym: [row, row]}

        async def fetch_order_book(self, *a, **k) -> dict:
            return {"asks": [[1.0, 1.0]], "bids": [[0.9, 1.0]]}

        def circuit_breaker_status(self) -> dict:
            return {sym: "OPEN (sim test)"}

    class CM:
        def __init__(self, **kw) -> None:
            self.h = H()

        async def __aenter__(self) -> "H":  # noqa: F821
            return self.h

        async def __aexit__(self, *a) -> object:
            return None

    monkeypatch.setattr(ml, "AsyncExchangeHandler", CM)

    class MA2:
        def analyze(self, sym2: str, c: list) -> dict:
            return {
                "signal": "HOLD",
                "regime": "TRENDING",
                "hurst": 0.5,
                "volatility": 0.1,
            }

        def apply_liquidity_context(self, *a, **k) -> None:
            pass

    monkeypatch.setattr(ml, "MarketAnalyzer", MA2)

    n = [0]

    def _storm(r) -> bool:
        n[0] += 1
        return n[0] <= 2

    monkeypatch.setattr(ml, "apply_storm_trip_to_risk", _storm)

    async def _g() -> None:
        t = asyncio.create_task(ml_mod.main())
        await asyncio.sleep(0.2)
        ml_mod._shutdown.set()
        await asyncio.wait_for(t, timeout=25.0)

    with caplog.at_level("WARNING", logger="super_otonom.main"):
        asyncio.run(_g())
    assert "CircuitBreaker" in caplog.text
    assert n[0] >= 1


# ---------------------------------------------------------------------------
# 170-171: 1H yok; 178: MTF + analyze_v5_1
# ---------------------------------------------------------------------------


def test_empty_pair_skips_debug_and_mtf_uses_v51(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from super_otonom import main_loop as ml
    from super_otonom.config import ASYNC_EXCHANGE, MTF

    mtf = dict(MTF)
    mtf["enabled"] = True
    mtf["timeframe"] = "4h"
    mtf["candle_limit"] = 5
    monkeypatch.setattr(ml, "MTF", mtf)
    ml_mod = _ml_common_engines(
        tmp_path, monkeypatch, ["FULL/BTC", "NO1H/ETH"]
    )
    mtf_time = mtf["timeframe"]
    ex_tf = ASYNC_EXCHANGE["timeframe"]

    ts0 = int(time.time() * 1000)
    r1h = [float(ts0), 2.0, 2.0, 2.0, 2.0, 2.0]
    r4h = [float(ts0), 2.0, 2.0, 2.0, 2.0, 2.0]

    class H2:
        async def fetch_all_ohlcv(self, **kw) -> dict:
            tf = kw.get("timeframe", "")
            if tf == mtf_time:
                return {
                    "FULL/BTC": [r4h, r4h],
                    "NO1H/ETH": [],
                }
            if tf == ex_tf:
                return {
                    "FULL/BTC": [r1h, r1h],
                    "NO1H/ETH": [],
                }
            return {"FULL/BTC": [r1h, r1h]}

        async def fetch_order_book(self, *a, **k) -> dict:
            return {"asks": [[1.0, 1.0]], "bids": [[0.9, 1.0]]}

        def circuit_breaker_status(self) -> dict:
            return {}

    class CM2:
        def __init__(self, **kw) -> None:
            self.h = H2()

        async def __aenter__(self) -> "H2":  # noqa: F821
            return self.h

        async def __aexit__(self, *a) -> object:
            return None

    monkeypatch.setattr(ml, "AsyncExchangeHandler", CM2)
    used: list[str] = []

    class MA3:
        def analyze(self, sym: str, c: list) -> dict:
            used.append("analyze_1h")
            return {
                "signal": "HOLD",
                "regime": "RANGING",
                "hurst": 0.5,
                "volatility": 0.1,
            }

        def analyze_v5_1(self, sym: str, a: list, b: list) -> dict:
            used.append("v51")
            return {
                "signal": "HOLD",
                "regime": "TRENDING",
                "hurst": 0.6,
                "volatility": 0.1,
                "high_tf_trend": "UP",
            }

        def apply_liquidity_context(self, *a, **k) -> None:
            pass

    monkeypatch.setattr(ml, "MarketAnalyzer", MA3)
    monkeypatch.setattr(ml, "apply_storm_trip_to_risk", lambda r: False)

    async def _r() -> None:
        t = asyncio.create_task(ml_mod.main())
        await asyncio.sleep(0.3)
        ml_mod._shutdown.set()
        await asyncio.wait_for(t, timeout=30.0)

    with caplog.at_level("DEBUG", logger="super_otonom.main"):
        asyncio.run(_r())
    assert "1H veri yok" in caplog.text
    assert "v51" in used


# ---------------------------------------------------------------------------
# 212-220: ob var, candles_1h bos
# ---------------------------------------------------------------------------


def test_order_book_slippage_when_candles_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from super_otonom import main_loop as ml
    from super_otonom.config import MTF

    mtf = dict(MTF)
    mtf["enabled"] = False
    monkeypatch.setattr(ml, "MTF", mtf)
    ml_mod = _ml_common_engines(tmp_path, monkeypatch, ["BAD/USDT"])
    ts0 = int(time.time() * 1000)
    short_row = [float(ts0), 1.0]
    sym0 = ml_mod.PAIRS[0]

    class Hb:
        async def fetch_all_ohlcv(self, **kw) -> dict:
            return {sym0: [short_row]}

        async def fetch_order_book(self, *a, **k) -> dict:
            return {"asks": [[1.0, 10.0]], "bids": [[0.5, 10.0]]}

        def circuit_breaker_status(self) -> dict:
            return {}

    class CMb:
        def __init__(self, **kw) -> None:
            self.h = Hb()

        async def __aenter__(self) -> "Hb":  # noqa: F821
            return self.h

        async def __aexit__(self, *a) -> object:
            return None

    monkeypatch.setattr(ml, "AsyncExchangeHandler", CMb)

    class MAb:
        def analyze(self, sym: str, c: list) -> dict:
            return {
                "signal": "HOLD",
                "regime": "RANGING",
                "hurst": 0.5,
                "volatility": 0.1,
            }

        def apply_liquidity_context(self, *a, **k) -> None:
            pass

    monkeypatch.setattr(ml, "MarketAnalyzer", MAb)
    monkeypatch.setattr(ml, "apply_storm_trip_to_risk", lambda r: False)

    async def _b() -> None:
        t = asyncio.create_task(ml_mod.main())
        await asyncio.sleep(0.12)
        ml_mod._shutdown.set()
        await asyncio.wait_for(t, timeout=20.0)

    asyncio.run(_b())


# ---------------------------------------------------------------------------
# 240-247, 252-255, 258-264: decision_reason, V6, EYLEM + slippage
# ---------------------------------------------------------------------------


def test_rich_decision_v6_and_action_slippage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from super_otonom import main_loop as ml
    from super_otonom.bot_engine import BotEngine
    from super_otonom.config import MTF

    mtf = dict(MTF)
    mtf["enabled"] = False
    monkeypatch.setattr(ml, "MTF", mtf)
    ml_mod = _ml_common_engines(tmp_path, monkeypatch, ["LIVEP/USDT"])

    ts0 = int(time.time() * 1000)
    row = [float(ts0), 100.0, 101.0, 99.0, 100.0, 1_000.0]

    class Hr:
        async def fetch_all_ohlcv(self, **kw) -> dict:
            return {ml_mod.PAIRS[0]: [row, row]}

        async def fetch_order_book(self, *a, **k) -> dict:
            return {"asks": [[100.0, 10.0]], "bids": [[99.0, 10.0]]}

        def circuit_breaker_status(self) -> dict:
            return {}

    class CM:
        def __init__(self, **kw) -> None:
            self.h = Hr()

        async def __aenter__(self) -> "Hr":  # noqa: F821
            return self.h

        async def __aexit__(self, *a) -> object:
            return None

    monkeypatch.setattr(ml, "AsyncExchangeHandler", CM)

    class MA:
        def analyze(self, sym: str, c: list) -> dict:
            return {
                "signal": "BUY",
                "regime": "TRENDING",
                "hurst": 0.5,
                "volatility": 0.1,
            }

        def apply_liquidity_context(self, *a, **k) -> None:
            pass

    monkeypatch.setattr(ml, "MarketAnalyzer", MA)
    monkeypatch.setattr(ml, "apply_storm_trip_to_risk", lambda r: False)

    tick_out = {
        "decision_context": {"symbol": "LIVEP/USDT", "tick_id": 1},
        "decision_reason": "unit_probe",
        "final_signal": "BUY",
        "ai_confidence": 0.77,
        "sentiment_status": "CALM",
        "corr_multiplier": 0.5,
        "actions": [{"type": "BUY", "price": 99.0}],
    }
    with patch.object(BotEngine, "tick", new=AsyncMock(return_value=tick_out)):
        async def _u() -> None:
            t = asyncio.create_task(ml_mod.main())
            await asyncio.sleep(0.2)
            ml_mod._shutdown.set()
            await asyncio.wait_for(t, timeout=20.0)

        with caplog.at_level("INFO", logger="super_otonom.main"):
            asyncio.run(_u())

    assert "AI KARAR" in caplog.text
    assert "V6 DURUM" in caplog.text
    assert "EYLEM" in caplog.text


def test_rich_sell_action_also_triggers_slippage_metric(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EYLEM dali: SELL (satir 261, record_slippage)."""
    from super_otonom import main_loop as ml
    from super_otonom.bot_engine import BotEngine
    from super_otonom.config import MTF

    mtf = dict(MTF)
    mtf["enabled"] = False
    monkeypatch.setattr(ml, "MTF", mtf)
    ml_mod = _ml_common_engines(tmp_path, monkeypatch, ["SELLP/USDT"])
    ts0 = int(time.time() * 1000)
    row = [float(ts0), 50.0, 51.0, 49.0, 50.0, 500.0]

    class Hse:
        async def fetch_all_ohlcv(self, **kw) -> dict:
            return {ml_mod.PAIRS[0]: [row, row]}

        async def fetch_order_book(self, *a, **k) -> dict:
            return {"asks": [[50.0, 10.0]], "bids": [[49.0, 10.0]]}

        def circuit_breaker_status(self) -> dict:
            return {}

    class CMb:
        def __init__(self, **kw) -> None:
            self.h = Hse()

        async def __aenter__(self) -> "Hse":  # noqa: F821
            return self.h

        async def __aexit__(self, *a) -> object:
            return None

    monkeypatch.setattr(ml, "AsyncExchangeHandler", CMb)

    class MAs:
        def analyze(self, sym: str, c: list) -> dict:
            return {
                "signal": "SELL",
                "regime": "RANGING",
                "hurst": 0.5,
                "volatility": 0.1,
            }

        def apply_liquidity_context(self, *a, **k) -> None:
            pass

    monkeypatch.setattr(ml, "MarketAnalyzer", MAs)
    monkeypatch.setattr(ml, "apply_storm_trip_to_risk", lambda r: False)

    tick_out = {
        "decision_context": None,
        "decision_reason": "exit",
        "final_signal": "SELL",
        "actions": [{"type": "SELL", "price": 48.0}],
    }
    with patch.object(BotEngine, "tick", new=AsyncMock(return_value=tick_out)):
        async def _g() -> None:
            t = asyncio.create_task(ml_mod.main())
            await asyncio.sleep(0.12)
            ml_mod._shutdown.set()
            await asyncio.wait_for(t, timeout=20.0)

        asyncio.run(_g())


# ---------------------------------------------------------------------------
# 280-281: outer try except
# ---------------------------------------------------------------------------


def test_main_loop_exception_logged_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from super_otonom import main_loop as ml
    from super_otonom.config import MTF

    mtf = dict(MTF)
    mtf["enabled"] = False
    monkeypatch.setattr(ml, "MTF", mtf)
    ml_mod = _ml_common_engines(tmp_path, monkeypatch, ["ERR/USDT"])

    class H:
        async def fetch_all_ohlcv(self, **kw) -> dict:
            raise RuntimeError("kablo kesildi")

        async def fetch_order_book(self, *a, **k) -> dict:
            return {"asks": [], "bids": []}

        def circuit_breaker_status(self) -> dict:
            return {}

    class CM:
        def __init__(self, **kw) -> None:
            self.h = H()

        async def __aenter__(self) -> "H":  # noqa: F821
            return self.h

        async def __aexit__(self, *a) -> object:
            return None

    monkeypatch.setattr(ml, "AsyncExchangeHandler", CM)
    monkeypatch.setattr(ml, "apply_storm_trip_to_risk", lambda r: False)

    async def _e() -> None:
        t = asyncio.create_task(ml_mod.main())
        await asyncio.sleep(0.1)
        ml_mod._shutdown.set()
        await asyncio.wait_for(t, timeout=20.0)

    with caplog.at_level("ERROR", logger="super_otonom.main"):
        asyncio.run(_e())
    assert "Ana dongu hatasi" in caplog.text or "kablo" in caplog.text


# ---------------------------------------------------------------------------
# 286-286: poll TimeoutError
# ---------------------------------------------------------------------------


def test_wait_shutdown_timeout_pymodule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Döngü sonundaki wait_for(..., timeout=POLL) TimeoutError sigrasi (284-286)."""
    from super_otonom import main_loop as ml
    from super_otonom.config import MTF

    mtf = dict(MTF)
    mtf["enabled"] = False
    monkeypatch.setattr(ml, "MTF", mtf)
    ml_mod = _ml_common_engines(tmp_path, monkeypatch, ["T/USDT"])
    ml_mod._POLL_INTERVAL = 0.05
    ts0 = int(time.time() * 1000)
    row = [float(ts0), 1.0, 1.0, 1.0, 1.0, 1.0]

    class Hw:
        async def fetch_all_ohlcv(self, **kw) -> dict:
            return {ml_mod.PAIRS[0]: [row, row]}

        async def fetch_order_book(self, *a, **k) -> dict:
            return {"asks": [[1.0, 1.0]], "bids": []}

        def circuit_breaker_status(self) -> dict:
            return {}

    class CM:
        def __init__(self, **kw) -> None:
            self.h = Hw()

        async def __aenter__(self) -> "Hw":  # noqa: F821
            return self.h

        async def __aexit__(self, *a) -> object:
            return None

    monkeypatch.setattr(ml, "AsyncExchangeHandler", CM)
    ml_mod._POLL_INTERVAL = 0.05

    class MA:
        def analyze(self, sym: str, c: list) -> dict:
            return {
                "signal": "HOLD",
                "regime": "RANGING",
                "hurst": 0.5,
                "volatility": 0.1,
            }

        def apply_liquidity_context(self, *a, **k) -> None:
            pass

    monkeypatch.setattr(ml, "MarketAnalyzer", MA)
    monkeypatch.setattr(ml, "apply_storm_trip_to_risk", lambda r: False)

    async def _w() -> None:
        t = asyncio.create_task(ml_mod.main())
        await asyncio.sleep(0.2)
        ml_mod._shutdown.set()
        await asyncio.wait_for(t, timeout=20.0)

    asyncio.run(_w())


# ---------------------------------------------------------------------------
# Windows SIGINT, CB tick atlama, KeyboardInterrupt, shutdown hata
# ---------------------------------------------------------------------------


def test_main_windows_registers_sigint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from super_otonom import main_loop as ml
    from super_otonom.config import MTF

    mtf = dict(MTF)
    mtf["enabled"] = False
    monkeypatch.setattr(ml, "MTF", mtf)
    ml_mod = _ml_common_engines(tmp_path, monkeypatch, ["W/USDT"])
    ts0 = int(time.time() * 1000)
    row = [float(ts0), 1.0, 1.0, 1.0, 1.0, 1.0]
    sym0 = ml_mod.PAIRS[0]

    class Hw:
        async def fetch_all_ohlcv(self, **kw) -> dict:
            return {sym0: [row, row]}

        async def fetch_order_book(self, *a, **k) -> dict:
            return {"asks": [[1.0, 1.0]], "bids": []}

        def circuit_breaker_status(self) -> dict:
            return {}

    class CM:
        def __init__(self, **kw) -> None:
            self.h = Hw()

        async def __aenter__(self) -> "Hw":  # noqa: F821
            return self.h

        async def __aexit__(self, *a) -> object:
            return None

    monkeypatch.setattr(ml, "AsyncExchangeHandler", CM)
    monkeypatch.setattr(ml, "apply_storm_trip_to_risk", lambda r: False)

    class MA:
        def analyze(self, sym: str, c: list) -> dict:
            return {
                "signal": "HOLD",
                "regime": "RANGING",
                "hurst": 0.5,
                "volatility": 0.1,
            }

        def apply_liquidity_context(self, *a, **k) -> None:
            pass

    monkeypatch.setattr(ml, "MarketAnalyzer", MA)
    sig_mock = MagicMock(return_value=None)

    async def _run() -> None:
        with patch.object(sys, "platform", "win32"):
            with patch("super_otonom.main_loop.signal.signal", sig_mock):
                t = asyncio.create_task(ml_mod.main())
                await asyncio.sleep(0.12)
                ml_mod._shutdown.set()
                await asyncio.wait_for(t, timeout=20.0)

    with caplog.at_level("INFO", logger="super_otonom.main"):
        asyncio.run(_run())
    sig_mock.assert_called()
    assert "Windows" in caplog.text


def test_main_windows_sigint_bind_failure_still_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from super_otonom import main_loop as ml
    from super_otonom.config import MTF

    mtf = dict(MTF)
    mtf["enabled"] = False
    monkeypatch.setattr(ml, "MTF", mtf)
    ml_mod = _ml_common_engines(tmp_path, monkeypatch, ["WF/USDT"])
    ts0 = int(time.time() * 1000)
    row = [float(ts0), 1.0, 1.0, 1.0, 1.0, 1.0]
    sym0 = ml_mod.PAIRS[0]

    class Hw:
        async def fetch_all_ohlcv(self, **kw) -> dict:
            return {sym0: [row, row]}

        async def fetch_order_book(self, *a, **k) -> dict:
            return {"asks": [[1.0, 1.0]], "bids": []}

        def circuit_breaker_status(self) -> dict:
            return {}

    class CM:
        def __init__(self, **kw) -> None:
            self.h = Hw()

        async def __aenter__(self) -> "Hw":  # noqa: F821
            return self.h

        async def __aexit__(self, *a) -> object:
            return None

    monkeypatch.setattr(ml, "AsyncExchangeHandler", CM)
    monkeypatch.setattr(ml, "apply_storm_trip_to_risk", lambda r: False)

    class MA:
        def analyze(self, sym: str, c: list) -> dict:
            return {
                "signal": "HOLD",
                "regime": "RANGING",
                "hurst": 0.5,
                "volatility": 0.1,
            }

        def apply_liquidity_context(self, *a, **k) -> None:
            pass

    monkeypatch.setattr(ml, "MarketAnalyzer", MA)

    async def _run() -> None:
        with patch.object(sys, "platform", "win32"):
            with patch(
                "super_otonom.main_loop.signal.signal",
                side_effect=ValueError("no signal"),
            ):
                t = asyncio.create_task(ml_mod.main())
                await asyncio.sleep(0.12)
                ml_mod._shutdown.set()
                await asyncio.wait_for(t, timeout=20.0)

    asyncio.run(_run())


def test_tick_skipped_when_cb_opens_after_prep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from super_otonom import main_loop as ml
    from super_otonom.bot_engine import BotEngine
    from super_otonom.config import MTF

    mtf = dict(MTF)
    mtf["enabled"] = False
    monkeypatch.setattr(ml, "MTF", mtf)
    ml_mod = _ml_common_engines(tmp_path, monkeypatch, ["CBLATE/USDT"])
    sym = ml_mod.PAIRS[0]
    ts0 = int(time.time() * 1000)
    row = [float(ts0), 1.0, 1.0, 1.0, 1.0, 1.0]

    class Hlate:
        def __init__(self) -> None:
            self._n = 0

        async def fetch_all_ohlcv(self, **kw) -> dict:
            return {sym: [row, row]}

        async def fetch_order_book(self, *a, **k) -> dict:
            return {"asks": [[1.0, 1.0]], "bids": []}

        def circuit_breaker_status(self) -> dict:
            self._n += 1
            # 1=loop ozet, 2=prep CB kontrolu, 3=tick oncesi (burada OPEN)
            if self._n >= 3:
                return {sym: "OPEN (late)"}
            return {}

    class CM:
        def __init__(self, **kw) -> None:
            self.h = Hlate()

        async def __aenter__(self) -> "Hlate":  # noqa: F821
            return self.h

        async def __aexit__(self, *a) -> object:
            return None

    monkeypatch.setattr(ml, "AsyncExchangeHandler", CM)
    monkeypatch.setattr(ml, "apply_storm_trip_to_risk", lambda r: False)

    class MA:
        def analyze(self, sym2: str, c: list) -> dict:
            return {
                "signal": "BUY",
                "regime": "TRENDING",
                "hurst": 0.5,
                "volatility": 0.1,
            }

        def apply_liquidity_context(self, *a, **k) -> None:
            pass

    monkeypatch.setattr(ml, "MarketAnalyzer", MA)

    tick_mock = AsyncMock(
        return_value={
            "decision_context": None,
            "decision_reason": "",
            "final_signal": "HOLD",
            "actions": [],
        }
    )

    async def _run() -> None:
        with patch.object(BotEngine, "tick", tick_mock):
            with caplog.at_level("WARNING", logger="super_otonom.main"):
                t = asyncio.create_task(ml_mod.main())
                await asyncio.sleep(0.2)
                ml_mod._shutdown.set()
                await asyncio.wait_for(t, timeout=20.0)

    asyncio.run(_run())
    assert "CB_OPEN" in caplog.text
    tick_mock.assert_not_called()


def test_main_loop_keyboard_interrupt_in_fetch_breaks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from super_otonom import main_loop as ml
    from super_otonom.config import MTF

    mtf = dict(MTF)
    mtf["enabled"] = False
    monkeypatch.setattr(ml, "MTF", mtf)
    ml_mod = _ml_common_engines(tmp_path, monkeypatch, ["KI/USDT"])

    class H:
        async def fetch_all_ohlcv(self, **kw) -> dict:
            raise KeyboardInterrupt()

        async def fetch_order_book(self, *a, **k) -> dict:
            return {"asks": [], "bids": []}

        def circuit_breaker_status(self) -> dict:
            return {}

    class CM:
        def __init__(self, **kw) -> None:
            self.h = H()

        async def __aenter__(self) -> "H":  # noqa: F821
            return self.h

        async def __aexit__(self, *a) -> object:
            return None

    monkeypatch.setattr(ml, "AsyncExchangeHandler", CM)
    monkeypatch.setattr(ml, "apply_storm_trip_to_risk", lambda r: False)

    async def _run() -> None:
        with caplog.at_level("WARNING", logger="super_otonom.main"):
            t = asyncio.create_task(ml_mod.main())
            await asyncio.wait_for(t, timeout=20.0)

    ml_mod._shutdown.clear()
    asyncio.run(_run())
    assert ml_mod._shutdown.is_set()


@pytest.mark.filterwarnings(
    "ignore:coroutine 'Event.wait' was never awaited:RuntimeWarning"
)
def test_main_loop_keyboard_interrupt_on_poll_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from super_otonom import main_loop as ml
    from super_otonom.config import MTF

    mtf = dict(MTF)
    mtf["enabled"] = False
    monkeypatch.setattr(ml, "MTF", mtf)
    ml_mod = _ml_common_engines(tmp_path, monkeypatch, ["KP/USDT"])
    ts0 = int(time.time() * 1000)
    row = [float(ts0), 1.0, 1.0, 1.0, 1.0, 1.0]
    sym0 = ml_mod.PAIRS[0]

    class H:
        async def fetch_all_ohlcv(self, **kw) -> dict:
            return {sym0: [row, row]}

        async def fetch_order_book(self, *a, **k) -> dict:
            return {"asks": [[1.0, 1.0]], "bids": []}

        def circuit_breaker_status(self) -> dict:
            return {}

    class CM:
        def __init__(self, **kw) -> None:
            self.h = H()

        async def __aenter__(self) -> "H":  # noqa: F821
            return self.h

        async def __aexit__(self, *a) -> object:
            return None

    monkeypatch.setattr(ml, "AsyncExchangeHandler", CM)
    monkeypatch.setattr(ml, "apply_storm_trip_to_risk", lambda r: False)

    class MA:
        def analyze(self, sym: str, c: list) -> dict:
            return {
                "signal": "HOLD",
                "regime": "RANGING",
                "hurst": 0.5,
                "volatility": 0.1,
            }

        def apply_liquidity_context(self, *a, **k) -> None:
            pass

    monkeypatch.setattr(ml, "MarketAnalyzer", MA)

    calls = [0]
    orig_wait = ml_mod.asyncio.wait_for

    async def wait_wrapper(*args: Any, **kwargs: Any) -> Any:
        calls[0] += 1
        if calls[0] >= 2:
            raise KeyboardInterrupt()
        return await orig_wait(*args, **kwargs)

    async def _run() -> None:
        with patch.object(ml_mod.asyncio, "wait_for", wait_wrapper):
            with caplog.at_level("WARNING", logger="super_otonom.main"):
                t = asyncio.create_task(ml_mod.main())
                await asyncio.wait_for(t, timeout=25.0)

    ml_mod._shutdown.clear()
    asyncio.run(_run())
    assert ml_mod._shutdown.is_set()


def test_engine_shutdown_error_logged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from super_otonom import main_loop as ml
    from super_otonom.bot_engine import BotEngine
    from super_otonom.config import MTF

    mtf = dict(MTF)
    mtf["enabled"] = False
    monkeypatch.setattr(ml, "MTF", mtf)
    ml_mod = _ml_common_engines(tmp_path, monkeypatch, ["SD/USDT"])
    ts0 = int(time.time() * 1000)
    row = [float(ts0), 1.0, 1.0, 1.0, 1.0, 1.0]
    sym0 = ml_mod.PAIRS[0]

    class H:
        async def fetch_all_ohlcv(self, **kw) -> dict:
            return {sym0: [row, row]}

        async def fetch_order_book(self, *a, **k) -> dict:
            return {"asks": [[1.0, 1.0]], "bids": []}

        def circuit_breaker_status(self) -> dict:
            return {}

    class CM:
        def __init__(self, **kw) -> None:
            self.h = H()

        async def __aenter__(self) -> "H":  # noqa: F821
            return self.h

        async def __aexit__(self, *a) -> object:
            return None

    monkeypatch.setattr(ml, "AsyncExchangeHandler", CM)
    monkeypatch.setattr(ml, "apply_storm_trip_to_risk", lambda r: False)

    class MA:
        def analyze(self, sym: str, c: list) -> dict:
            return {
                "signal": "HOLD",
                "regime": "RANGING",
                "hurst": 0.5,
                "volatility": 0.1,
            }

        def apply_liquidity_context(self, *a, **k) -> None:
            pass

    monkeypatch.setattr(ml, "MarketAnalyzer", MA)

    async def _run() -> None:
        with patch.object(BotEngine, "shutdown", side_effect=RuntimeError("x")):
            with caplog.at_level("WARNING", logger="super_otonom.main"):
                t = asyncio.create_task(ml_mod.main())
                await asyncio.sleep(0.1)
                ml_mod._shutdown.set()
                await asyncio.wait_for(t, timeout=20.0)

    asyncio.run(_run())
    assert "engine.shutdown hata" in caplog.text
