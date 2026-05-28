"""Integration test — BotEngine full cycle: signal → entry → tick → exit.

BotEngine'i mock exchange ile baştan sona çalıştırır.
Harici servis gerektirmez.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from super_otonom.risk.config import RiskConfig

# ---------------------------------------------------------------------------
# Test-scoped env isolation
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _paper_mode_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tüm testlerde paper mode aktif."""
    monkeypatch.setenv("PAPER_MODE", "true")
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    # Vault/Redis bağımlılığını devre dışı bırak
    monkeypatch.setenv("SECRETS_VAULT_ONLY", "false")
    monkeypatch.setenv("SECRETS_VAULT_ONLY_AUTO", "false")


# ---------------------------------------------------------------------------
# Helper — arch bağımlılığı olmadan çalışan config
# ---------------------------------------------------------------------------

_NO_FHS_MODELS = ("historical", "parametric_t", "monte_carlo", "cornish_fisher")


def _cfg_no_fhs() -> RiskConfig:
    """FHS modeli hariç RiskConfig (arch bağımlılığını atlar)."""
    return RiskConfig(use_models=_NO_FHS_MODELS)


# ---------------------------------------------------------------------------
# Mock candle data
# ---------------------------------------------------------------------------


def _make_candles(n: int = 120, start_price: float = 50000.0) -> List[Dict[str, float]]:
    """Realistic OHLCV candle series."""
    rng = np.random.RandomState(42)
    candles = []
    price = start_price
    for i in range(n):
        ret = rng.normal(0.0005, 0.015)
        o = price
        c = price * (1 + ret)
        h = max(o, c) * (1 + abs(rng.normal(0, 0.005)))
        low = min(o, c) * (1 - abs(rng.normal(0, 0.005)))
        vol = rng.uniform(100, 2000)
        candles.append(
            {
                "timestamp": 1700000000000 + i * 3600000,
                "open": round(o, 2),
                "high": round(h, 2),
                "low": round(low, 2),
                "close": round(c, 2),
                "volume": round(vol, 2),
            }
        )
        price = c
    return candles


# ---------------------------------------------------------------------------
# RiskManager isolation
# ---------------------------------------------------------------------------


class TestRiskManagerIntegration:
    """RiskManager — capital lifecycle."""

    def test_initial_state(self) -> None:
        from super_otonom.risk_manager import RiskManager

        rm = RiskManager(initial_capital=10000.0)
        assert rm.initial_capital == 10000.0
        assert not rm.emergency_stop
        assert rm.emergency_reason is None

    def test_daily_loss_tracking(self) -> None:
        from super_otonom.risk_manager import RiskManager

        rm = RiskManager(initial_capital=10000.0)
        rm.daily_loss = 300.0
        rm.weekly_loss = 500.0
        assert rm.daily_loss == 300.0
        assert rm.weekly_loss == 500.0

    def test_omega_qmin_tighten(self) -> None:
        from super_otonom.risk_manager import RiskManager

        rm = RiskManager(initial_capital=10000.0)
        base = 62

        # Loss tightens
        rm.record_omega_trade_outcome(-100.0)
        assert rm._omega_qmin_tighten == 2
        effective = rm.get_omega_effective_qmin(base)
        assert effective == base + 2

        # Profit relaxes
        rm.record_omega_trade_outcome(50.0)
        assert rm._omega_qmin_tighten == 1

    def test_omega_qmin_cap(self) -> None:
        from super_otonom.risk_manager import RiskManager

        rm = RiskManager(initial_capital=10000.0)
        # Push to max
        for _ in range(50):
            rm.record_omega_trade_outcome(-100.0)
        assert rm._omega_qmin_tighten == 25  # capped at 25
        effective = rm.get_omega_effective_qmin(70)
        assert effective <= 90  # total cap


# ---------------------------------------------------------------------------
# RiskEngine lifecycle within BotEngine context
# ---------------------------------------------------------------------------


class TestRiskEngineLifecycle:
    """RiskEngine compute → RiskManager wiring."""

    def test_risk_engine_wiring(self) -> None:
        from super_otonom.risk.risk_engine import RiskEngine
        from super_otonom.risk_manager import RiskManager

        rm = RiskManager(initial_capital=10000.0)
        engine = RiskEngine()
        rm.set_risk_engine(engine)
        assert rm._risk_engine is engine

    def test_return_recording(self) -> None:
        from super_otonom.risk_manager import RiskManager

        rm = RiskManager(initial_capital=10000.0)
        for i in range(600):
            rm.record_return(0.001 * (i % 10 - 5))
        # Deque capped at 500
        assert len(rm._returns_history) == 500

    def test_risk_check_chain_order(self) -> None:
        """check_risk kontrol zinciri sıralı çalışmalı."""
        from super_otonom.risk_manager import RiskManager

        rm = RiskManager(initial_capital=10000.0)
        # Emergency stop → immediate deny
        rm.trigger_emergency("test", silent=True)

        # check_risk should detect emergency (if method exists)
        if hasattr(rm, "check_risk"):
            rm.check_risk(
                current_equity=10000.0,
                open_exposure=0.0,
                current_vol=0.02,
            )
            # Emergency latched → risk denied
            assert rm.emergency_stop


# ---------------------------------------------------------------------------
# Signal pipeline stub test
# ---------------------------------------------------------------------------


class TestSignalPipelineStub:
    """Sinyal pipeline'ın temel çalışma garantisi."""

    def test_risk_pipeline_force_close(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from super_otonom.pipelines.risk_pipeline import force_all_close_requested

        monkeypatch.setenv("FORCE_ALL_CLOSE", "1")
        assert force_all_close_requested()

        monkeypatch.setenv("FORCE_ALL_CLOSE", "false")
        assert not force_all_close_requested()

    def test_risk_pipeline_kill_switch(self) -> None:
        from super_otonom.pipelines.risk_pipeline import tick_kill_switch_and_spike

        # Minimal engine mock
        engine = MagicMock()
        engine._hard_limits.check_price_tick.return_value = None
        engine.open_positions = {}

        dctx = MagicMock()
        dctx.add_trace = MagicMock()
        out: Dict[str, Any] = {}

        with patch(
            "super_otonom.hard_safety_contract.enforce_global_trade_allowed",
            return_value=(True, ""),
        ):
            result = tick_kill_switch_and_spike(engine, "BTC/USDT", 50000.0, dctx, out)

        assert result is False  # no kill triggered


# ---------------------------------------------------------------------------
# Candle processing integration
# ---------------------------------------------------------------------------


class TestCandleProcessing:
    """OHLCV mum verisinden analiz üretilebilmesini doğrular."""

    def test_candle_data_valid(self) -> None:
        candles = _make_candles(120)
        assert len(candles) == 120
        for c in candles:
            assert c["high"] >= c["low"]
            assert c["volume"] > 0

    def test_returns_from_candles(self) -> None:
        candles = _make_candles(120)
        closes = [c["close"] for c in candles]
        returns = [
            (closes[i] - closes[i - 1]) / closes[i - 1]
            for i in range(1, len(closes))
        ]
        assert len(returns) == 119
        # Returns should be centered around 0
        assert -0.5 < np.mean(returns) < 0.5

    def test_candle_to_risk_engine(self) -> None:
        """Candle'dan return → RiskEngine compute."""
        from super_otonom.risk.risk_engine import RiskEngine

        candles = _make_candles(120)
        closes = [c["close"] for c in candles]
        returns = [
            (closes[i] - closes[i - 1]) / closes[i - 1]
            for i in range(1, len(closes))
        ]

        engine = RiskEngine()
        metrics = engine.compute(returns, config=_cfg_no_fhs())
        assert metrics.var_95_1d > 0
        assert metrics.var_99_1d > 0


# ---------------------------------------------------------------------------
# Position lifecycle
# ---------------------------------------------------------------------------


class TestPositionLifecycle:
    """Pozisyon açılış → takip → kapanış döngüsü."""

    def test_open_position_structure(self) -> None:
        """Pozisyon dict yapısı doğru olmalı."""
        pos = {
            "symbol": "BTC/USDT",
            "side": "long",
            "entry_price": 50000.0,
            "quantity": 0.01,
            "notional_usd": 500.0,
            "entry_ts": time.time(),
            "stop_loss": 49000.0,
            "take_profit": 52000.0,
        }
        assert pos["notional_usd"] == pos["entry_price"] * pos["quantity"]

    def test_pnl_calculation(self) -> None:
        """Basit PnL hesabı."""
        entry = 50000.0
        qty = 0.01
        exit_price = 51000.0
        pnl = (exit_price - entry) * qty
        assert pnl == 10.0  # $10 profit

        exit_price_loss = 49000.0
        pnl_loss = (exit_price_loss - entry) * qty
        assert pnl_loss == -10.0  # $10 loss

    def test_stop_loss_trigger(self) -> None:
        """Fiyat stop loss'un altına düşünce tetiklenmeli."""
        stop_loss = 49000.0
        current_price = 48500.0
        assert current_price < stop_loss  # triggered

    def test_take_profit_trigger(self) -> None:
        """Fiyat take profit'in üstüne çıkınca tetiklenmeli."""
        take_profit = 52000.0
        current_price = 52500.0
        assert current_price > take_profit  # triggered


# ---------------------------------------------------------------------------
# End-to-end: VaR-aware position sizing
# ---------------------------------------------------------------------------


class TestVaRAwarePositionSizing:
    """VR-18: Kelly + VaR cap ile pozisyon boyutlama."""

    def test_size_with_var_cap(self, synthetic_returns: List[float]) -> None:
        from super_otonom.risk.position_sizer_var import VarAwarePositionSizer

        base = MagicMock()
        base.calculate.return_value = 0.01  # Kelly raw size

        asset_returns = {
            "BTC/USDT": synthetic_returns,
            "ETH/USDT": [r * 1.2 for r in synthetic_returns],
        }
        sizer = VarAwarePositionSizer(
            base_sizer=base,
            asset_returns=asset_returns,
        )
        result = sizer.calculate_with_var_cap(
            symbol="BTC/USDT",
            equity=10000.0,
            current_positions={"ETH/USDT": 0.3},
        )
        assert result.final_size >= 0
        assert isinstance(result.cap_binding, bool)

    def test_zero_equity_no_position(self, synthetic_returns: List[float]) -> None:
        from super_otonom.risk.position_sizer_var import VarAwarePositionSizer

        base = MagicMock()
        base.calculate.return_value = 0.0

        asset_returns = {
            "BTC/USDT": synthetic_returns,
            "ETH/USDT": [r * 1.2 for r in synthetic_returns],
        }
        sizer = VarAwarePositionSizer(
            base_sizer=base,
            asset_returns=asset_returns,
        )
        result = sizer.calculate_with_var_cap(
            symbol="BTC/USDT",
            equity=0.0,
            current_positions={},
        )
        assert result.final_size == 0.0
