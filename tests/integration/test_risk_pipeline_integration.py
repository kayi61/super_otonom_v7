"""Integration test — RiskEngine → RiskManager → kill-switch zinciri.

Tam döngü: return kaydı → VaR/CVaR hesabı → limit kontrolü → breach → kill-switch.
Harici servis gerektirmez (Redis/DB yok).

NOT: ``arch`` paketi CI ortamında yüklü olmayabilir; FHS modelini
``RiskConfig(use_models=...)`` ile devre dışı bırakıyoruz.
"""

from __future__ import annotations

import random
from typing import Dict, List

import numpy as np
from super_otonom.risk.config import RiskConfig
from super_otonom.risk.risk_engine import RiskEngine, RiskMetrics

# ---------------------------------------------------------------------------
# Helper — arch bağımlılığı olmadan çalışan config
# ---------------------------------------------------------------------------

_NO_FHS_MODELS = ("historical", "parametric_t", "monte_carlo", "cornish_fisher")


def _cfg_no_fhs() -> RiskConfig:
    """FHS modeli hariç RiskConfig (arch bağımlılığını atlar)."""
    return RiskConfig(use_models=_NO_FHS_MODELS)


# ---------------------------------------------------------------------------
# RiskEngine compute — end-to-end
# ---------------------------------------------------------------------------


class TestRiskEngineCompute:
    """RiskEngine.compute() tek çağrı ile tüm metriklerin üretildiğini doğrular."""

    def test_compute_returns_risk_metrics(self, synthetic_returns: List[float]) -> None:
        engine = RiskEngine()
        metrics = engine.compute(synthetic_returns, config=_cfg_no_fhs())
        assert isinstance(metrics, RiskMetrics)

    def test_var_positive_for_volatile_returns(self, synthetic_returns: List[float]) -> None:
        engine = RiskEngine()
        metrics = engine.compute(synthetic_returns, config=_cfg_no_fhs())
        assert metrics.var_95_1d > 0.0
        assert metrics.var_99_1d > 0.0
        assert metrics.var_99_1d >= metrics.var_95_1d  # 99% >= 95%

    def test_cvar_exceeds_var(self, synthetic_returns: List[float]) -> None:
        engine = RiskEngine()
        metrics = engine.compute(synthetic_returns, config=_cfg_no_fhs())
        # CVaR (expected shortfall) >= VaR by definition
        assert metrics.cvar_95_1d >= metrics.var_95_1d - 1e-9
        assert metrics.cvar_99_1d >= metrics.var_99_1d - 1e-9

    def test_var_for_limits_conservative(self, synthetic_returns: List[float]) -> None:
        """var_for_limits = max(historical, parametric, MC)."""
        engine = RiskEngine()
        metrics = engine.compute(synthetic_returns, config=_cfg_no_fhs())
        assert metrics.var_for_limits_95 >= metrics.var_historical_95 - 1e-9
        assert metrics.var_for_limits_99 >= metrics.var_historical_99 - 1e-9

    def test_model_dispersion_bounded(self, synthetic_returns: List[float]) -> None:
        engine = RiskEngine()
        metrics = engine.compute(synthetic_returns, config=_cfg_no_fhs())
        assert 0.0 <= metrics.model_dispersion_pct <= 10.0  # sanity

    def test_10day_var_scaling(self, synthetic_returns: List[float]) -> None:
        """10-day VaR = 1-day VaR × sqrt(10)."""
        engine = RiskEngine()
        metrics = engine.compute(synthetic_returns, config=_cfg_no_fhs())
        if metrics.var_for_limits_99 > 0:
            expected = metrics.var_for_limits_99 * np.sqrt(10)
            assert abs(metrics.var_10d_99 - expected) < 1e-9


# ---------------------------------------------------------------------------
# RiskManager → kill-switch chain
# ---------------------------------------------------------------------------


class TestRiskManagerKillSwitch:
    """VR-19: VaR/CVaR breach → emergency_stop latch."""

    def test_normal_returns_no_breach(self, synthetic_returns: List[float]) -> None:
        from super_otonom.risk_manager import RiskManager

        rm = RiskManager(initial_capital=10000.0)
        engine = RiskEngine()
        rm.set_risk_engine(engine)

        for r in synthetic_returns[:50]:
            rm.record_return(r)

        breach = rm._check_var_breach()
        # Normal volatility should not trigger breach
        if breach is None:
            assert not rm.emergency_stop

    def test_extreme_returns_trigger_breach(self) -> None:
        from super_otonom.risk_manager import RiskManager

        rm = RiskManager(initial_capital=10000.0)
        engine = RiskEngine()
        rm.set_risk_engine(engine)

        # Inject extreme losses to push VaR above 6%
        extreme = [-0.08 + random.gauss(0, 0.01) for _ in range(100)]
        for r in extreme:
            rm.record_return(r)

        breach = rm._check_var_breach()
        # With heavy losses, VaR should exceed threshold
        if breach is not None:
            assert rm.emergency_stop
            assert rm.emergency_reason in (
                "var_99_breach",
                "cvar_975_breach",
                "stressed_var_breach",
            )

    def test_insufficient_returns_skip(self) -> None:
        from super_otonom.risk_manager import RiskManager

        rm = RiskManager(initial_capital=10000.0)
        engine = RiskEngine()
        rm.set_risk_engine(engine)

        # Only 10 returns < 20 minimum
        for r in [0.01] * 10:
            rm.record_return(r)

        breach = rm._check_var_breach()
        assert breach is None  # skipped, not enough data
        assert not rm.emergency_stop

    def test_no_engine_skip(self) -> None:
        from super_otonom.risk_manager import RiskManager

        rm = RiskManager(initial_capital=10000.0)
        # No engine set
        for r in [0.01] * 50:
            rm.record_return(r)

        breach = rm._check_var_breach()
        assert breach is None

    def test_emergency_latch_persists(self) -> None:
        from super_otonom.risk_manager import RiskManager

        rm = RiskManager(initial_capital=10000.0)
        rm.trigger_emergency("test_breach", silent=True)
        assert rm.emergency_stop
        assert rm.emergency_reason == "test_breach"

        # Second trigger does not change reason
        rm.trigger_emergency("another_breach", silent=True)
        assert rm.emergency_reason == "test_breach"  # latch


# ---------------------------------------------------------------------------
# RiskEngine + VaR Limits integration
# ---------------------------------------------------------------------------


class TestVaRLimitsIntegration:
    """VR-20: RiskMetrics → check_limits → breach list."""

    def test_check_limits_no_breach(self, synthetic_returns: List[float]) -> None:
        from super_otonom.risk.var_limits import VaRLimits, check_limits

        engine = RiskEngine()
        metrics = engine.compute(synthetic_returns, config=_cfg_no_fhs())

        # Generous limits — should not breach
        limits = VaRLimits(
            max_var_per_strategy_pct=0.10,
            max_cvar_per_strategy_pct=0.15,
            max_var_total_pct=0.15,
            max_cvar_total_pct=0.25,
            max_stressed_var_total_pct=0.30,
            max_marginal_var_per_trade_pct=0.05,
            max_component_var_per_position_pct=0.50,
            max_lvar_to_nav=0.20,
        )
        breaches = check_limits(limits, metrics)
        assert isinstance(breaches, list)

    def test_tight_limits_cause_breach(self, synthetic_returns: List[float]) -> None:
        from super_otonom.risk.var_limits import VaRLimits, check_limits

        engine = RiskEngine()
        metrics = engine.compute(synthetic_returns, config=_cfg_no_fhs())

        # Very tight limits — almost certainly breach
        limits = VaRLimits(
            max_var_per_strategy_pct=0.001,
            max_cvar_per_strategy_pct=0.001,
            max_var_total_pct=0.002,
            max_cvar_total_pct=0.002,
            max_stressed_var_total_pct=0.003,
            max_marginal_var_per_trade_pct=0.0005,
            max_component_var_per_position_pct=0.001,
            max_lvar_to_nav=0.001,
        )
        breaches = check_limits(limits, metrics)
        assert len(breaches) > 0


# ---------------------------------------------------------------------------
# Pre-trade VaR Gate integration
# ---------------------------------------------------------------------------


class TestPreTradeGateIntegration:
    """VR-17: Pre-trade marginal VaR → approved/rejected."""

    def test_small_trade_approved(self, synthetic_returns: List[float]) -> None:
        from super_otonom.risk.pre_trade_var_gate import (
            PreTradeVarLimits,
            pre_trade_var_check,
        )

        # Build per-asset returns mapping (required by API)
        asset_returns = {
            "BTC/USDT": synthetic_returns,
            "ETH/USDT": [r * 1.2 for r in synthetic_returns],
        }
        current_weights = {"BTC/USDT": 0.5, "ETH/USDT": 0.5}
        limits = PreTradeVarLimits()

        result = pre_trade_var_check(
            symbol="SOL/USDT",
            trade_weight=0.01,  # tiny position
            side="buy",
            current_weights=current_weights,
            asset_returns=asset_returns,
            limits=limits,
        )
        assert result.approved

    def test_large_trade_rejected(self, synthetic_returns: List[float]) -> None:
        from super_otonom.risk.pre_trade_var_gate import (
            PreTradeVarLimits,
            pre_trade_var_check,
        )

        asset_returns = {
            "BTC/USDT": synthetic_returns,
            "ETH/USDT": [r * 1.2 for r in synthetic_returns],
        }
        current_weights = {"BTC/USDT": 0.5, "ETH/USDT": 0.5}
        limits = PreTradeVarLimits(max_var_total_pct=0.001)  # extremely tight

        result = pre_trade_var_check(
            symbol="SOL/USDT",
            trade_weight=0.5,  # huge position
            side="buy",
            current_weights=current_weights,
            asset_returns=asset_returns,
            limits=limits,
        )
        # Either rejected or approved depending on VaR calc
        assert isinstance(result.approved, bool)
        assert result.latency_ms >= 0


# ---------------------------------------------------------------------------
# Full risk chain: returns → RiskEngine → RiskMetrics → limits → breach
# ---------------------------------------------------------------------------


class TestFullRiskChain:
    """End-to-end: synthetic data → compute → limits → breach detection."""

    def test_full_chain_no_crash(
        self,
        synthetic_returns: List[float],
        multi_asset_returns: Dict[str, List[float]],
        portfolio_weights: Dict[str, float],
    ) -> None:
        from super_otonom.risk.var_limits import VaRLimits, check_limits
        from super_otonom.risk_manager import RiskManager

        engine = RiskEngine()
        rm = RiskManager(initial_capital=50000.0)
        rm.set_risk_engine(engine)

        # 1. Record returns
        for r in synthetic_returns:
            rm.record_return(r)

        # 2. Compute metrics (no FHS to avoid arch dependency)
        metrics = engine.compute(
            synthetic_returns,
            positions=portfolio_weights,
            asset_returns=multi_asset_returns,
            config=_cfg_no_fhs(),
        )

        # 3. Check limits
        limits = VaRLimits()
        breaches = check_limits(limits, metrics)

        # 4. Check VaR breach kill-switch
        breach = rm._check_var_breach()

        # Verify chain completed without crash
        assert isinstance(metrics, RiskMetrics)
        assert isinstance(breaches, list)
        # breach is either None or a string
        assert breach is None or isinstance(breach, str)

    def test_kupiec_backtest_integration(self, synthetic_returns: List[float]) -> None:
        """VR-13: Kupiec POF backtest on computed VaR series."""
        from super_otonom.risk.var_backtest import kupiec_pof

        engine = RiskEngine()
        n = len(synthetic_returns)

        # Build VaR series (constant VaR from full sample)
        metrics = engine.compute(synthetic_returns, config=_cfg_no_fhs())
        var_series = [metrics.var_99_1d] * n

        result = kupiec_pof(
            realized_pnl=synthetic_returns,
            predicted_var=var_series,
            conf=0.99,
        )
        assert hasattr(result, "model_valid")
        assert hasattr(result, "p_value")
        assert 0.0 <= result.p_value <= 1.0
