"""BotEngine — Hypothesis RuleBasedStateMachine (durum + tick zinciri)."""

from __future__ import annotations

import asyncio
import math
import os
import shutil
import tempfile
import time
from typing import Any

import pytest
import super_otonom.bot_engine as bemod
from hypothesis.stateful import RuleBasedStateMachine, initialize, precondition, rule
from super_otonom.bot_engine import BotEngine

from hypothesis import settings
from hypothesis import strategies as st

pytestmark = pytest.mark.hypothesis


class BotEngineStateMachine(RuleBasedStateMachine):
    """Paper BotEngine: PnL kaydı ve HOLD tick ile tutarlılık."""

    def __init__(self) -> None:
        super().__init__()
        self.engine: BotEngine | None = None
        self.td: str | None = None
        self._prev_state: str | None = None

    @initialize()
    def setup_engine(self) -> None:
        self.td = tempfile.mkdtemp(prefix="hyp_be_")
        self._prev_state = bemod._STATE_FILE
        bemod._STATE_FILE = os.path.join(self.td, "state.json")
        self.engine = BotEngine(25_000.0, paper=True)

    def teardown(self) -> None:
        if self._prev_state is not None:
            bemod._STATE_FILE = self._prev_state
        if self.td and os.path.isdir(self.td):
            shutil.rmtree(self.td, ignore_errors=True)

    @precondition(lambda self: self.engine is not None)
    @rule(
        pnl=st.floats(
            min_value=-800.0,
            max_value=800.0,
            allow_nan=False,
            allow_infinity=False,
            width=64,
        )
    )
    def record_risk_pnl(self, pnl: float) -> None:
        e = self.engine
        assert e is not None
        e.risk.record_pnl(pnl)
        assert math.isfinite(e.risk.daily_loss)
        assert e.risk.daily_loss >= 0.0

    @precondition(lambda self: self.engine is not None)
    @rule(
        vol=st.floats(
            min_value=0.002,
            max_value=0.06,
            allow_nan=False,
            allow_infinity=False,
        ),
        price=st.floats(
            min_value=0.5,
            max_value=200_000.0,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    def tick_hold_path(self, vol: float, price: float) -> None:
        e = self.engine
        assert e is not None
        analysis: dict[str, Any] = {
            "signal": "HOLD",
            "volatility": vol,
            "regime": "RANGING",
            "hurst": 0.5,
            "ob_safe_size": None,
        }
        ts = time.time() * 1000
        candles = [
            {"close": price * 0.999, "volume": 100.0, "timestamp": ts - 60_000},
            {"close": price, "volume": 100.0, "timestamp": ts},
        ]
        out = asyncio.run(e.tick("BTC/USDT", analysis, candles))
        assert out["final_signal"] in ("HOLD", "BUY", "SELL")
        assert math.isfinite(e.equity)

    @precondition(lambda self: self.engine is not None)
    @rule()
    def reset_emergency_if_latched(self) -> None:
        e = self.engine
        assert e is not None
        if e.risk.emergency_stop:
            e.risk.reset_emergency()
            assert e.risk.emergency_stop is False


TestBotEngineStateful = BotEngineStateMachine.TestCase
TestBotEngineStateful.settings = settings(
    max_examples=125,
    stateful_step_count=40,
    deadline=None,
)
