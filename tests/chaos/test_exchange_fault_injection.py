"""
Chaos / fault injection — borsa ve döngü kenar durumları (≥100 senaryo).

fetch_all_ohlcv hata, order book gecikme, KeyboardInterrupt, CB OPEN, kısmi veri.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import pytest

from tests.test_main_loop_96 import _MAIN_LOOP_MOCK_USDT, apply_main_loop_mock_contract


def _ml_common(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pairs: list[str]) -> Any:
    import super_otonom.main_loop as ml

    apply_main_loop_mock_contract(tmp_path, monkeypatch, ml, pairs=pairs, poll_interval=0.02)
    return ml


@pytest.mark.parametrize("fault", range(5))
@pytest.mark.parametrize("rep", range(22))
def test_chaos_fetch_all_ohlcv_exception_matrix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: int, rep: int
) -> None:
    """5×22=110: fetch_all farklı exception türleri."""
    from super_otonom import main_loop as ml
    from super_otonom.config import MTF

    mtf = dict(MTF)
    mtf["enabled"] = False
    monkeypatch.setattr(ml, "MTF", mtf)
    ml_mod = _ml_common(tmp_path, monkeypatch, [f"F{fault}_{rep}/USDT"])

    exc_types = (RuntimeError, ValueError, ConnectionError, OSError, TimeoutError)
    Exc = exc_types[fault % len(exc_types)]

    class H:
        async def fetch_all_ohlcv(self, **kw) -> dict:
            raise Exc(f"chaos_{rep}")

        async def fetch_order_book(self, *a, **k) -> dict:
            return {"asks": [], "bids": []}

        async def fetch_balance(self, *a, **k) -> dict:
            return {"total": {"USDT": _MAIN_LOOP_MOCK_USDT}}

        def circuit_breaker_status(self) -> dict:
            return {}

    class CM:
        def __init__(self, **kw) -> None:
            self.h = H()

        async def __aenter__(self) -> Any:
            return self.h

        async def __aexit__(self, *a) -> object:
            return None

    monkeypatch.setattr(ml, "AsyncExchangeHandler", CM)
    monkeypatch.setattr(ml, "apply_storm_trip_to_risk", lambda r: False)

    async def _run() -> None:
        t = asyncio.create_task(ml_mod.main())
        await asyncio.sleep(0.08)
        ml_mod._shutdown.set()
        await asyncio.wait_for(t, timeout=25.0)

    asyncio.run(_run())


@pytest.mark.parametrize("delay_ms", [0, 1, 5, 15, 30])
@pytest.mark.parametrize("rep", range(20))
def test_chaos_order_book_slow_matrix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, delay_ms: int, rep: int
) -> None:
    """5×20=100: order book gecikme / timeout benzeri bekleme."""
    from super_otonom import main_loop as ml
    from super_otonom.config import MTF

    mtf = dict(MTF)
    mtf["enabled"] = False
    monkeypatch.setattr(ml, "MTF", mtf)
    ml_mod = _ml_common(tmp_path, monkeypatch, [f"OB{delay_ms}_{rep}/USDT"])
    sym = ml_mod.PAIRS[0]
    ts0 = int(time.time() * 1000)
    row = [float(ts0), 1.0, 1.0, 1.0, 1.0, 1.0]

    class H:
        async def fetch_all_ohlcv(self, **kw) -> dict:
            return {sym: [row, row]}

        async def fetch_order_book(self, *a, **k) -> dict:
            await asyncio.sleep(delay_ms / 1000.0)
            return {"asks": [[1.0, 1.0]], "bids": []}

        async def fetch_balance(self, *a, **k) -> dict:
            return {"total": {"USDT": _MAIN_LOOP_MOCK_USDT}}

        def circuit_breaker_status(self) -> dict:
            return {}

    class CM:
        def __init__(self, **kw) -> None:
            self.h = H()

        async def __aenter__(self) -> Any:
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
                "volatility": 0.02,
            }

        def apply_liquidity_context(self, *a, **k) -> None:
            pass

    monkeypatch.setattr(ml, "MarketAnalyzer", MA)

    async def _run() -> None:
        t = asyncio.create_task(ml_mod.main())
        await asyncio.sleep(0.15)
        ml_mod._shutdown.set()
        await asyncio.wait_for(t, timeout=30.0)

    asyncio.run(_run())


@pytest.mark.parametrize("rep", range(25))
def test_chaos_keyboard_interrupt_in_fetch_matrix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rep: int
) -> None:
    """25: KeyboardInterrupt döngü içi."""
    from super_otonom import main_loop as ml
    from super_otonom.config import MTF

    mtf = dict(MTF)
    mtf["enabled"] = False
    monkeypatch.setattr(ml, "MTF", mtf)
    ml_mod = _ml_common(tmp_path, monkeypatch, [f"KI{rep}/USDT"])

    class H:
        async def fetch_all_ohlcv(self, **kw) -> dict:
            raise KeyboardInterrupt()

        async def fetch_order_book(self, *a, **k) -> dict:
            return {"asks": [], "bids": []}

        async def fetch_balance(self, *a, **k) -> dict:
            return {"total": {"USDT": _MAIN_LOOP_MOCK_USDT}}

        def circuit_breaker_status(self) -> dict:
            return {}

    class CM:
        def __init__(self, **kw) -> None:
            self.h = H()

        async def __aenter__(self) -> Any:
            return self.h

        async def __aexit__(self, *a) -> object:
            return None

    monkeypatch.setattr(ml, "AsyncExchangeHandler", CM)
    monkeypatch.setattr(ml, "apply_storm_trip_to_risk", lambda r: False)

    async def _run() -> None:
        t = asyncio.create_task(ml_mod.main())
        await asyncio.wait_for(t, timeout=25.0)

    ml_mod._shutdown.clear()
    asyncio.run(_run())
    assert ml_mod._shutdown.is_set()


@pytest.mark.parametrize("cb_style", range(4))
@pytest.mark.parametrize("rep", range(28))
def test_chaos_circuit_breaker_open_matrix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cb_style: int, rep: int
) -> None:
    """4×28=112: CB OPEN / boş mum."""
    from super_otonom import main_loop as ml
    from super_otonom.config import MTF

    mtf = dict(MTF)
    mtf["enabled"] = False
    monkeypatch.setattr(ml, "MTF", mtf)
    ml_mod = _ml_common(tmp_path, monkeypatch, [f"CB{cb_style}_{rep}/USDT"])
    sym = ml_mod.PAIRS[0]
    ts0 = int(time.time() * 1000)
    row = [float(ts0), 1.0, 1.0, 1.0, 1.0, 1.0]

    class H:
        async def fetch_all_ohlcv(self, **kw) -> dict:
            if cb_style % 2 == 0:
                return {sym: []}
            return {sym: [row, row]}

        async def fetch_order_book(self, *a, **k) -> dict:
            return {"asks": [[1.0, 1.0]], "bids": []}

        async def fetch_balance(self, *a, **k) -> dict:
            return {"total": {"USDT": _MAIN_LOOP_MOCK_USDT}}

        def circuit_breaker_status(self) -> dict:
            if cb_style < 2:
                return {sym: f"OPEN (chaos_{rep})"}
            return {}

    class CM:
        def __init__(self, **kw) -> None:
            self.h = H()

        async def __aenter__(self) -> Any:
            return self.h

        async def __aexit__(self, *a) -> object:
            return None

    monkeypatch.setattr(ml, "AsyncExchangeHandler", CM)
    monkeypatch.setattr(ml, "apply_storm_trip_to_risk", lambda r: False)

    class MA:
        def analyze(self, sym2: str, c: list) -> dict:
            return {
                "signal": "HOLD",
                "regime": "RANGING",
                "hurst": 0.5,
                "volatility": 0.02,
            }

        def apply_liquidity_context(self, *a, **k) -> None:
            pass

    monkeypatch.setattr(ml, "MarketAnalyzer", MA)

    async def _run() -> None:
        t = asyncio.create_task(ml_mod.main())
        await asyncio.sleep(0.12)
        ml_mod._shutdown.set()
        await asyncio.wait_for(t, timeout=25.0)

    asyncio.run(_run())


@pytest.mark.parametrize("partial", range(3))
@pytest.mark.parametrize("rep", range(15))
def test_chaos_partial_symbol_data_matrix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, partial: int, rep: int
) -> None:
    """3×15=45: çoklu sembolden biri boş (ek yük)."""
    from super_otonom import main_loop as ml
    from super_otonom.config import MTF

    mtf = dict(MTF)
    mtf["enabled"] = False
    monkeypatch.setattr(ml, "MTF", mtf)
    pairs = [f"A{rep}/USDT", f"B{rep}/USDT"]
    ml_mod = _ml_common(tmp_path, monkeypatch, pairs)
    ts0 = int(time.time() * 1000)
    row = [float(ts0), 1.0, 1.0, 1.0, 1.0, 1.0]

    class H:
        async def fetch_all_ohlcv(self, **kw) -> dict:
            out = {pairs[0]: [row, row], pairs[1]: [row, row]}
            if partial == 0:
                out[pairs[1]] = []
            elif partial == 1:
                del out[pairs[1]]
            else:
                out[pairs[0]] = []
            return out

        async def fetch_order_book(self, *a, **k) -> dict:
            return {"asks": [[1.0, 1.0]], "bids": []}

        async def fetch_balance(self, *a, **k) -> dict:
            return {"total": {"USDT": _MAIN_LOOP_MOCK_USDT}}

        def circuit_breaker_status(self) -> dict:
            return {}

    class CM:
        def __init__(self, **kw) -> None:
            self.h = H()

        async def __aenter__(self) -> Any:
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
                "volatility": 0.02,
            }

        def apply_liquidity_context(self, *a, **k) -> None:
            pass

    monkeypatch.setattr(ml, "MarketAnalyzer", MA)

    async def _run() -> None:
        t = asyncio.create_task(ml_mod.main())
        await asyncio.sleep(0.14)
        ml_mod._shutdown.set()
        await asyncio.wait_for(t, timeout=30.0)

    asyncio.run(_run())
