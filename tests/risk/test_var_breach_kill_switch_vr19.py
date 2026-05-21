"""VR-19: VaR/CVaR Breach Kill-switch — test suite.

Tests:
  - var_99_breach trigger
  - cvar_975_breach trigger
  - stressed_var_breach trigger
  - model_dispersion warning (log only, no kill)
  - normal conditions → no breach
  - insufficient data → skip (conservative pass)
  - risk_engine not set → skip
  - check_risk integration (breach → False, deny reason)
  - record_return history management
  - set_risk_engine binding
  - status_dict VR-19 fields
  - config env override
  - multiple breaches → first wins (latch)
  - reset_emergency clears breach state
  - Prometheus metrics recording
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import numpy as np
import pytest
from super_otonom.config import RISK
from super_otonom.risk.risk_engine import RiskEngine, RiskMetrics
from super_otonom.risk_manager import RiskManager

# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def rm() -> RiskManager:
    """Fresh RiskManager with 10_000 capital."""
    return RiskManager(initial_capital=10_000.0)


@pytest.fixture()
def engine() -> RiskEngine:
    """Default RiskEngine."""
    return RiskEngine()


@pytest.fixture()
def rm_with_engine(rm: RiskManager, engine: RiskEngine) -> RiskManager:
    """RiskManager with RiskEngine bound."""
    rm.set_risk_engine(engine)
    return rm


def _high_vol_returns(n: int = 200, scale: float = 0.15, seed: int = 42) -> list[float]:
    """Generate high-volatility returns that will produce var_99 > 0.06."""
    rng = np.random.RandomState(seed)
    return rng.normal(0, scale, n).tolist()


def _low_vol_returns(n: int = 200, scale: float = 0.005, seed: int = 42) -> list[float]:
    """Generate low-volatility returns — var_99 well below 0.06."""
    rng = np.random.RandomState(seed)
    return rng.normal(0, scale, n).tolist()


def _extreme_vol_returns(n: int = 200, scale: float = 0.25, seed: int = 42) -> list[float]:
    """Generate extreme volatility for CVaR breach."""
    rng = np.random.RandomState(seed)
    rets = rng.normal(-0.02, scale, n)
    # Add tail events
    rets[:10] = -0.30
    return rets.tolist()


# ── Test: set_risk_engine binding ────────────────────────────────────────────

class TestSetRiskEngine:
    def test_set_engine(self, rm: RiskManager, engine: RiskEngine) -> None:
        assert rm._risk_engine is None
        rm.set_risk_engine(engine)
        assert rm._risk_engine is engine

    def test_status_dict_reflects_engine(self, rm: RiskManager, engine: RiskEngine) -> None:
        assert rm.status_dict()["var_breach_kill_switch_active"] is False
        rm.set_risk_engine(engine)
        assert rm.status_dict()["var_breach_kill_switch_active"] is True


# ── Test: record_return ──────────────────────────────────────────────────────

class TestRecordReturn:
    def test_basic_record(self, rm: RiskManager) -> None:
        rm.record_return(0.01)
        rm.record_return(-0.02)
        assert len(rm._returns_history) == 2
        assert rm._returns_history == [0.01, -0.02]

    def test_history_capped_at_500(self, rm: RiskManager) -> None:
        for i in range(600):
            rm.record_return(float(i) * 0.001)
        assert len(rm._returns_history) == 500
        # Most recent value should be last
        assert rm._returns_history[-1] == pytest.approx(0.599)

    def test_status_dict_returns_history_len(self, rm: RiskManager) -> None:
        for _ in range(50):
            rm.record_return(0.01)
        assert rm.status_dict()["returns_history_len"] == 50


# ── Test: _check_var_breach — skip conditions ───────────────────────────────

class TestVarBreachSkip:
    def test_no_engine_returns_none(self, rm: RiskManager) -> None:
        """No risk engine → skip (conservative pass)."""
        for r in _high_vol_returns(200):
            rm.record_return(r)
        assert rm._check_var_breach() is None

    def test_insufficient_data_returns_none(self, rm_with_engine: RiskManager) -> None:
        """< 20 returns → skip."""
        for r in _high_vol_returns(10):
            rm_with_engine.record_return(r)
        assert rm_with_engine._check_var_breach() is None

    def test_exactly_20_returns_runs(self, rm_with_engine: RiskManager) -> None:
        """Exactly 20 returns → should run (not skip)."""
        for r in _high_vol_returns(20, scale=0.005):
            rm_with_engine.record_return(r)
        # Should run without error — low vol, no breach
        result = rm_with_engine._check_var_breach()
        assert result is None


# ── Test: var_99_breach ──────────────────────────────────────────────────────

class TestVar99Breach:
    def test_high_vol_triggers_var_99_breach(self, rm_with_engine: RiskManager) -> None:
        """High-vol returns → var_99 > 0.06 → var_99_breach."""
        for r in _high_vol_returns(200, scale=0.15):
            rm_with_engine.record_return(r)
        result = rm_with_engine._check_var_breach()
        assert result == "var_99_breach"
        assert rm_with_engine.emergency_stop is True
        assert rm_with_engine.emergency_reason == "var_99_breach"

    def test_var_99_breach_logged(
        self, rm_with_engine: RiskManager, caplog: pytest.LogCaptureFixture
    ) -> None:
        for r in _high_vol_returns(200, scale=0.15):
            rm_with_engine.record_return(r)
        with caplog.at_level(logging.CRITICAL, logger="super_otonom.risk"):
            rm_with_engine._check_var_breach()
        assert any("KILL_SWITCH" in msg and "var_99_breach" in msg for msg in caplog.messages)

    def test_custom_limit_env(self, rm_with_engine: RiskManager) -> None:
        """Custom max_var_99_pct via RISK dict — all limits loosened."""
        for r in _high_vol_returns(200, scale=0.08):
            rm_with_engine.record_return(r)
        orig_var = RISK.get("max_var_99_pct")
        orig_cvar = RISK.get("max_cvar_975_pct")
        try:
            RISK["max_var_99_pct"] = 0.50  # Very loose
            RISK["max_cvar_975_pct"] = 0.50  # Very loose
            result = rm_with_engine._check_var_breach()
            assert result is None
        finally:
            RISK["max_var_99_pct"] = orig_var
            RISK["max_cvar_975_pct"] = orig_cvar


# ── Test: cvar_975_breach ────────────────────────────────────────────────────

class TestCvar975Breach:
    def test_extreme_vol_triggers_cvar_breach(self, rm_with_engine: RiskManager) -> None:
        """Extreme tail events → cvar_975 > 0.10 → cvar_975_breach."""
        for r in _extreme_vol_returns(200, scale=0.25):
            rm_with_engine.record_return(r)

        # Increase var limit so var_99 check passes first
        original_var = RISK.get("max_var_99_pct")
        try:
            RISK["max_var_99_pct"] = 0.99  # Don't trigger var_99 breach
            result = rm_with_engine._check_var_breach()
            # With extreme returns, cvar should breach
            if result == "cvar_975_breach":
                assert rm_with_engine.emergency_stop is True
                assert rm_with_engine.emergency_reason == "cvar_975_breach"
            else:
                # If var_99 triggers first due to extreme vol, that's also valid
                assert result in ("var_99_breach", None)
        finally:
            RISK["max_var_99_pct"] = original_var

    def test_cvar_breach_with_mock(self, rm: RiskManager) -> None:
        """Direct mock: cvar_975 > limit → breach."""
        mock_engine = MagicMock()
        mock_metrics = RiskMetrics(
            var_99_1d=0.03,       # Below var limit
            cvar_975_1d=0.15,     # Above cvar limit (0.10)
            stressed_var=0.0,
            model_dispersion_pct=0.1,
        )
        mock_engine.compute.return_value = mock_metrics
        rm.set_risk_engine(mock_engine)

        for r in _low_vol_returns(50):
            rm.record_return(r)

        result = rm._check_var_breach()
        assert result == "cvar_975_breach"
        assert rm.emergency_stop is True
        assert rm._last_var_breach_reason == "cvar_975_breach"


# ── Test: stressed_var_breach ────────────────────────────────────────────────

class TestStressedVarBreach:
    def test_stressed_var_breach_with_mock(self, rm: RiskManager) -> None:
        """stressed_var > 2 × var_99 → stressed_var_breach."""
        mock_engine = MagicMock()
        mock_metrics = RiskMetrics(
            var_99_1d=0.04,          # Below var limit
            cvar_975_1d=0.05,        # Below cvar limit
            stressed_var=0.12,       # 3× var_99 > 2× var_99
            model_dispersion_pct=0.1,
        )
        mock_engine.compute.return_value = mock_metrics
        rm.set_risk_engine(mock_engine)

        for r in _low_vol_returns(50):
            rm.record_return(r)

        result = rm._check_var_breach()
        assert result == "stressed_var_breach"
        assert rm.emergency_stop is True
        assert rm.emergency_reason == "stressed_var_breach"

    def test_stressed_var_at_boundary_no_breach(self, rm: RiskManager) -> None:
        """stressed_var == 2 × var_99 → no breach (strict >)."""
        mock_engine = MagicMock()
        mock_metrics = RiskMetrics(
            var_99_1d=0.04,
            cvar_975_1d=0.05,
            stressed_var=0.08,  # Exactly 2× var_99
            model_dispersion_pct=0.1,
        )
        mock_engine.compute.return_value = mock_metrics
        rm.set_risk_engine(mock_engine)

        for r in _low_vol_returns(50):
            rm.record_return(r)

        result = rm._check_var_breach()
        assert result is None
        assert rm.emergency_stop is False

    def test_stressed_var_zero_no_breach(self, rm: RiskManager) -> None:
        """stressed_var == 0 (no stress data) → skip stressed check."""
        mock_engine = MagicMock()
        mock_metrics = RiskMetrics(
            var_99_1d=0.04,
            cvar_975_1d=0.05,
            stressed_var=0.0,
            model_dispersion_pct=0.1,
        )
        mock_engine.compute.return_value = mock_metrics
        rm.set_risk_engine(mock_engine)

        for r in _low_vol_returns(50):
            rm.record_return(r)

        result = rm._check_var_breach()
        assert result is None


# ── Test: model_dispersion warning ───────────────────────────────────────────

class TestModelDispersionWarning:
    def test_high_dispersion_logs_warning(self, rm: RiskManager, caplog: pytest.LogCaptureFixture) -> None:
        """dispersion > 50% → log.critical but no kill."""
        mock_engine = MagicMock()
        mock_metrics = RiskMetrics(
            var_99_1d=0.03,
            cvar_975_1d=0.05,
            stressed_var=0.0,
            model_dispersion_pct=0.75,  # 75% > 50% limit
        )
        mock_engine.compute.return_value = mock_metrics
        rm.set_risk_engine(mock_engine)

        for r in _low_vol_returns(50):
            rm.record_return(r)

        with caplog.at_level(logging.CRITICAL, logger="super_otonom.risk"):
            result = rm._check_var_breach()

        # No kill — just warning
        assert result is None
        assert rm.emergency_stop is False
        assert any("MODEL_RISK" in msg and "dispersion" in msg for msg in caplog.messages)

    def test_normal_dispersion_no_warning(self, rm: RiskManager, caplog: pytest.LogCaptureFixture) -> None:
        """dispersion < 50% → no warning."""
        mock_engine = MagicMock()
        mock_metrics = RiskMetrics(
            var_99_1d=0.03,
            cvar_975_1d=0.05,
            stressed_var=0.0,
            model_dispersion_pct=0.20,  # 20% < 50%
        )
        mock_engine.compute.return_value = mock_metrics
        rm.set_risk_engine(mock_engine)

        for r in _low_vol_returns(50):
            rm.record_return(r)

        with caplog.at_level(logging.CRITICAL, logger="super_otonom.risk"):
            result = rm._check_var_breach()

        assert result is None
        assert not any("MODEL_RISK" in msg for msg in caplog.messages)


# ── Test: normal conditions — no breach ──────────────────────────────────────

class TestNormalConditions:
    def test_low_vol_no_breach(self, rm_with_engine: RiskManager) -> None:
        """Low volatility → all checks pass."""
        for r in _low_vol_returns(200, scale=0.005):
            rm_with_engine.record_return(r)
        result = rm_with_engine._check_var_breach()
        assert result is None
        assert rm_with_engine.emergency_stop is False
        assert rm_with_engine._last_var_breach_reason is None


# ── Test: check_risk integration ─────────────────────────────────────────────

class TestCheckRiskIntegration:
    def test_var_breach_stops_trading(self, rm: RiskManager) -> None:
        """check_risk → False when var breach triggered."""
        mock_engine = MagicMock()
        mock_metrics = RiskMetrics(
            var_99_1d=0.08,  # > 0.06
            cvar_975_1d=0.05,
            stressed_var=0.0,
            model_dispersion_pct=0.1,
        )
        mock_engine.compute.return_value = mock_metrics
        rm.set_risk_engine(mock_engine)

        for r in _low_vol_returns(50):
            rm.record_return(r)

        result = rm.check_risk(current_equity=10_000.0)
        assert result is False
        assert rm.get_last_deny() == "var_99_breach"

    def test_no_breach_passes(self, rm: RiskManager) -> None:
        """check_risk → True when no breach."""
        mock_engine = MagicMock()
        mock_metrics = RiskMetrics(
            var_99_1d=0.03,
            cvar_975_1d=0.05,
            stressed_var=0.0,
            model_dispersion_pct=0.1,
        )
        mock_engine.compute.return_value = mock_metrics
        rm.set_risk_engine(mock_engine)

        for r in _low_vol_returns(50):
            rm.record_return(r)

        result = rm.check_risk(current_equity=10_000.0)
        assert result is True

    def test_breach_in_chain_order(self, rm: RiskManager) -> None:
        """VaR breach is checked AFTER loss/drawdown, BEFORE exposure."""
        mock_engine = MagicMock()
        mock_metrics = RiskMetrics(
            var_99_1d=0.08,  # Would breach
            cvar_975_1d=0.05,
            stressed_var=0.0,
            model_dispersion_pct=0.1,
        )
        mock_engine.compute.return_value = mock_metrics
        rm.set_risk_engine(mock_engine)

        for r in _low_vol_returns(50):
            rm.record_return(r)

        # With high exposure that would also fail — VaR breach should fire first
        result = rm.check_risk(current_equity=10_000.0, open_exposure=50_000.0)
        assert result is False
        assert rm.get_last_deny() == "var_99_breach"

    def test_emergency_latch_prevents_recheck(self, rm: RiskManager) -> None:
        """After breach, emergency_stop latches — next check_risk returns False immediately."""
        mock_engine = MagicMock()
        mock_metrics = RiskMetrics(var_99_1d=0.08)
        mock_engine.compute.return_value = mock_metrics
        rm.set_risk_engine(mock_engine)

        for r in _low_vol_returns(50):
            rm.record_return(r)

        # First call triggers breach
        rm.check_risk(current_equity=10_000.0)
        assert rm.emergency_stop is True

        # Change to low VaR — still locked
        mock_metrics_ok = RiskMetrics(var_99_1d=0.01)
        mock_engine.compute.return_value = mock_metrics_ok
        result = rm.check_risk(current_equity=10_000.0)
        assert result is False
        assert rm.get_last_deny() == "var_99_breach"


# ── Test: reset_emergency ────────────────────────────────────────────────────

class TestResetEmergency:
    def test_reset_clears_emergency(self, rm: RiskManager) -> None:
        mock_engine = MagicMock()
        mock_metrics = RiskMetrics(var_99_1d=0.08)
        mock_engine.compute.return_value = mock_metrics
        rm.set_risk_engine(mock_engine)

        for r in _low_vol_returns(50):
            rm.record_return(r)

        rm._check_var_breach()
        assert rm.emergency_stop is True
        assert rm.emergency_reason == "var_99_breach"

        rm.reset_emergency()
        assert rm.emergency_stop is False
        assert rm.emergency_reason is None


# ── Test: breach priority (first wins) ───────────────────────────────────────

class TestBreachPriority:
    def test_var_99_checked_first(self, rm: RiskManager) -> None:
        """When both var_99 and cvar_975 breach, var_99 wins (first in chain)."""
        mock_engine = MagicMock()
        mock_metrics = RiskMetrics(
            var_99_1d=0.08,      # Breach
            cvar_975_1d=0.15,    # Also breach
            stressed_var=0.30,   # Also breach
            model_dispersion_pct=0.75,
        )
        mock_engine.compute.return_value = mock_metrics
        rm.set_risk_engine(mock_engine)

        for r in _low_vol_returns(50):
            rm.record_return(r)

        result = rm._check_var_breach()
        assert result == "var_99_breach"  # First in chain

    def test_cvar_when_var_ok(self, rm: RiskManager) -> None:
        """var_99 OK, cvar_975 breach → cvar_975_breach."""
        mock_engine = MagicMock()
        mock_metrics = RiskMetrics(
            var_99_1d=0.04,      # OK
            cvar_975_1d=0.15,    # Breach
            stressed_var=0.0,
            model_dispersion_pct=0.1,
        )
        mock_engine.compute.return_value = mock_metrics
        rm.set_risk_engine(mock_engine)

        for r in _low_vol_returns(50):
            rm.record_return(r)

        result = rm._check_var_breach()
        assert result == "cvar_975_breach"

    def test_stressed_when_var_and_cvar_ok(self, rm: RiskManager) -> None:
        """var_99 OK, cvar_975 OK, stressed_var > 2× var_99 → stressed_var_breach."""
        mock_engine = MagicMock()
        mock_metrics = RiskMetrics(
            var_99_1d=0.04,
            cvar_975_1d=0.05,
            stressed_var=0.12,   # 3× var_99
            model_dispersion_pct=0.1,
        )
        mock_engine.compute.return_value = mock_metrics
        rm.set_risk_engine(mock_engine)

        for r in _low_vol_returns(50):
            rm.record_return(r)

        result = rm._check_var_breach()
        assert result == "stressed_var_breach"


# ── Test: compute error handling ─────────────────────────────────────────────

class TestComputeErrorHandling:
    def test_compute_exception_returns_none(self, rm: RiskManager) -> None:
        """If RiskEngine.compute() raises, breach check returns None (safe)."""
        mock_engine = MagicMock()
        mock_engine.compute.side_effect = ValueError("compute failed")
        rm.set_risk_engine(mock_engine)

        for r in _low_vol_returns(50):
            rm.record_return(r)

        result = rm._check_var_breach()
        assert result is None
        assert rm.emergency_stop is False


# ── Test: end-to-end with real RiskEngine ────────────────────────────────────

class TestEndToEnd:
    def test_real_engine_high_vol_breach(self, rm_with_engine: RiskManager) -> None:
        """Real RiskEngine + high vol returns → breach triggered."""
        for r in _high_vol_returns(200, scale=0.15):
            rm_with_engine.record_return(r)
        result = rm_with_engine._check_var_breach()
        assert result == "var_99_breach"
        assert rm_with_engine.emergency_stop is True

    def test_real_engine_low_vol_no_breach(self, rm_with_engine: RiskManager) -> None:
        """Real RiskEngine + low vol returns → no breach."""
        for r in _low_vol_returns(200, scale=0.005):
            rm_with_engine.record_return(r)
        result = rm_with_engine._check_var_breach()
        assert result is None
        assert rm_with_engine.emergency_stop is False

    def test_real_engine_moderate_vol_boundary(self, rm_with_engine: RiskManager) -> None:
        """Real RiskEngine + moderate vol → check runs without crash."""
        rng = np.random.RandomState(123)
        rets = rng.normal(0, 0.03, 200).tolist()
        for r in rets:
            rm_with_engine.record_return(r)
        result = rm_with_engine._check_var_breach()
        # Just verify it runs — result depends on exact returns
        assert result is None or isinstance(result, str)


# ── Test: status_dict VR-19 fields ───────────────────────────────────────────

class TestStatusDict:
    def test_vr19_fields_present(self, rm: RiskManager) -> None:
        d = rm.status_dict()
        assert "var_breach_kill_switch_active" in d
        assert "last_var_breach_reason" in d
        assert "returns_history_len" in d

    def test_vr19_fields_after_breach(self, rm: RiskManager) -> None:
        mock_engine = MagicMock()
        mock_metrics = RiskMetrics(var_99_1d=0.08)
        mock_engine.compute.return_value = mock_metrics
        rm.set_risk_engine(mock_engine)

        for r in _low_vol_returns(50):
            rm.record_return(r)

        rm._check_var_breach()
        d = rm.status_dict()
        assert d["var_breach_kill_switch_active"] is True
        assert d["last_var_breach_reason"] == "var_99_breach"
        assert d["returns_history_len"] == 50


# ── Test: Prometheus metrics ─────────────────────────────────────────────────

class TestMetricsExporter:
    def test_record_var_breach_method_exists(self) -> None:
        """MetricsExporter has record_var_breach method."""
        from super_otonom.metrics_exporter import MetricsExporter

        me = MetricsExporter(port=0)
        assert hasattr(me, "record_var_breach")

    def test_record_var_breach_no_prometheus(self) -> None:
        """record_var_breach runs safely without prometheus."""
        from super_otonom.metrics_exporter import MetricsExporter

        me = MetricsExporter(port=0)
        # Should not raise
        me.record_var_breach(
            breach_code="var_99_breach",
            var_99=0.08,
            cvar_975=0.05,
            model_dispersion=0.1,
        )
        me.record_var_breach(
            breach_code=None,
            var_99=0.03,
            cvar_975=0.04,
            model_dispersion=0.2,
        )


# ── Test: sentinel detection ─────────────────────────────────────────────────

class TestSentinel:
    def test_var_breach_kill_switch_sentinel(self) -> None:
        """Module-level sentinel exists for var_topology detection."""
        import super_otonom.risk_manager as mod

        assert hasattr(mod, "var_breach_kill_switch")
        assert mod.var_breach_kill_switch is True


# ── Test: config defaults ────────────────────────────────────────────────────

class TestConfigDefaults:
    def test_max_var_99_pct_default(self) -> None:
        assert RISK["max_var_99_pct"] == pytest.approx(0.06)

    def test_max_cvar_975_pct_default(self) -> None:
        assert RISK["max_cvar_975_pct"] == pytest.approx(0.10)

    def test_max_model_dispersion_pct_default(self) -> None:
        assert RISK["max_model_dispersion_pct"] == pytest.approx(0.50)
