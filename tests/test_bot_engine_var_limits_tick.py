"""VR-20 — VaR limit hierarchy check in tick path integration tests."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import patch

import pytest

# ── Lightweight RiskMetrics stub ───────────────────────────────────────


@dataclass
class _StubMetrics:
    """Minimal RiskMetrics-like object for check_limits."""

    var_99_1d: float = 0.0
    cvar_975_1d: float = 0.0
    stressed_var: float = 0.0
    lvar: float = 0.0
    component_var_per_position: dict = None
    var_for_limits_95: float = 0.0

    def __post_init__(self):
        if self.component_var_per_position is None:
            self.component_var_per_position = {}


# ── Engine fixture ─────────────────────────────────────────────────────


def _be_paths(tmp_path, monkeypatch: pytest.MonkeyPatch):
    from super_otonom import bot_engine as be

    monkeypatch.setattr(be, "_STATE_FILE", str(tmp_path / "s.json"))
    monkeypatch.setattr(be, "_TRADE_LOG_FILE", str(tmp_path / "tr" / "tr.log"))
    return be


def _make_engine(be, capital: float = 10_000.0):
    eng = be.BotEngine(capital, paper=True)
    eng._state_mgr.save = lambda: None
    eng.open_positions.clear()
    # Set tick counter to match var_suite_interval for limit check to fire
    eng._tick_counter = eng._var_suite_interval
    return eng


# ── Tests ───────────────────────────────────────────────────────────────


def test_var_limits_checked_in_tick_path(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VR-20: check_limits runs during tick and detects portfolio breach."""
    from super_otonom.bot_engine_risk_bridge import tick_check_var_limits

    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)

    # Inject breaching metrics
    eng._last_risk_metrics = _StubMetrics(
        var_99_1d=0.10,  # > default limit 0.06
        cvar_975_1d=0.05,
    )

    with patch(
        "super_otonom.risk.var_limits.load_var_limits",
    ) as mock_load:
        from super_otonom.risk.var_limits import VaRLimits

        mock_load.return_value = VaRLimits()  # defaults

        tick_check_var_limits(eng)

    # Portfolio VaR breach → emergency stop should be triggered
    assert eng.risk.emergency_stop is True


def test_var_limits_no_breach_no_emergency(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VR-20: No violations → no emergency stop."""
    from super_otonom.bot_engine_risk_bridge import tick_check_var_limits

    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)

    # All within limits
    eng._last_risk_metrics = _StubMetrics(
        var_99_1d=0.02,
        cvar_975_1d=0.03,
        stressed_var=0.05,
        lvar=0.02,
    )

    with patch(
        "super_otonom.risk.var_limits.load_var_limits",
    ) as mock_load:
        from super_otonom.risk.var_limits import VaRLimits

        mock_load.return_value = VaRLimits()
        tick_check_var_limits(eng)

    assert eng.risk.emergency_stop is False


def test_var_limits_skipped_without_risk_engine(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VR-20: Skipped when _risk_engine is None."""
    from super_otonom.bot_engine_risk_bridge import tick_check_var_limits

    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)
    eng._risk_engine = None

    with patch(
        "super_otonom.risk.var_limits.load_var_limits",
        side_effect=RuntimeError("should not be called"),
    ) as mock_load:
        tick_check_var_limits(eng)

    mock_load.assert_not_called()


def test_var_limits_skipped_wrong_interval(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VR-20: Skipped when tick counter not aligned to var_suite_interval."""
    from super_otonom.bot_engine_risk_bridge import tick_check_var_limits

    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)
    eng._tick_counter = eng._var_suite_interval + 1  # Not aligned

    with patch(
        "super_otonom.risk.var_limits.load_var_limits",
        side_effect=RuntimeError("should not be called"),
    ) as mock_load:
        tick_check_var_limits(eng)

    mock_load.assert_not_called()


def test_var_limits_skipped_no_metrics(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VR-20: Skipped when _last_risk_metrics is None (no var suite yet)."""
    from super_otonom.bot_engine_risk_bridge import tick_check_var_limits

    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)
    eng._last_risk_metrics = None

    with patch(
        "super_otonom.risk.var_limits.load_var_limits",
        side_effect=RuntimeError("should not be called"),
    ) as mock_load:
        tick_check_var_limits(eng)

    mock_load.assert_not_called()


def test_var_limits_compute_error_passes(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VR-20: Compute error → conservative pass (no crash)."""
    from super_otonom.bot_engine_risk_bridge import tick_check_var_limits

    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)
    eng._last_risk_metrics = _StubMetrics()

    with patch(
        "super_otonom.risk.var_limits.load_var_limits",
        side_effect=RuntimeError("yaml boom"),
    ):
        # Should not raise
        tick_check_var_limits(eng)

    assert eng.risk.emergency_stop is False


def test_var_limits_stressed_var_breach_triggers_emergency(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VR-20: Stressed VaR breach → firm-level emergency stop."""
    from super_otonom.bot_engine_risk_bridge import tick_check_var_limits

    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)

    eng._last_risk_metrics = _StubMetrics(
        var_99_1d=0.04,  # within limits
        cvar_975_1d=0.05,  # within limits
        stressed_var=0.20,  # > default 0.15 → breach
    )

    with patch(
        "super_otonom.risk.var_limits.load_var_limits",
    ) as mock_load:
        from super_otonom.risk.var_limits import VaRLimits

        mock_load.return_value = VaRLimits()
        tick_check_var_limits(eng)

    assert eng.risk.emergency_stop is True


def test_var_limits_lvar_breach_no_emergency(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VR-20: LVaR breach alone is NOT a firm-level trigger (no emergency)."""
    from super_otonom.bot_engine_risk_bridge import tick_check_var_limits

    be = _be_paths(tmp_path, monkeypatch)
    eng = _make_engine(be)

    eng._last_risk_metrics = _StubMetrics(
        var_99_1d=0.02,
        cvar_975_1d=0.03,
        stressed_var=0.05,
        lvar=0.20,  # > default 0.08 → breach but NOT firm-level
    )

    with patch(
        "super_otonom.risk.var_limits.load_var_limits",
    ) as mock_load:
        from super_otonom.risk.var_limits import VaRLimits

        mock_load.return_value = VaRLimits()
        tick_check_var_limits(eng)

    # LVaR breach logged but no emergency stop
    assert eng.risk.emergency_stop is False
