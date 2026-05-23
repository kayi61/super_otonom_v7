"""VR-19 — record_var_breach Prometheus integration tests.

Verifies that _check_var_breach() calls MetricsExporter.record_var_breach()
for all 3 breach types + normal (no-breach) state.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

# ── Stub RiskMetrics ───────────────────────────────────────────────────


@dataclass
class _FakeMetrics:
    var_99_1d: float = 0.02
    cvar_975_1d: float = 0.03
    stressed_var: float = 0.05
    model_dispersion_pct: float = 0.10


def _make_rm(monkeypatch: pytest.MonkeyPatch):
    """Create a RiskManager with a mock RiskEngine + mock MetricsExporter."""
    from super_otonom.risk_manager import RiskManager

    rm = RiskManager(10_000.0)

    # Stub RiskEngine
    mock_engine = MagicMock()
    rm.set_risk_engine(mock_engine)

    # Stub MetricsExporter
    mock_metrics = MagicMock()
    rm.set_metrics(mock_metrics)

    # Populate enough returns for _check_var_breach to run
    rm._returns_history = [0.001] * 30

    return rm, mock_engine, mock_metrics


# ── Tests ───────────────────────────────────────────────────────────────


def test_var_99_breach_records_prometheus(monkeypatch: pytest.MonkeyPatch) -> None:
    """VaR 99% breach → record_var_breach called with 'var_99_breach'."""
    rm, mock_engine, mock_metrics = _make_rm(monkeypatch)

    mock_engine.compute.return_value = _FakeMetrics(
        var_99_1d=0.10,  # > limit 0.06
    )

    result = rm._check_var_breach()

    assert result == "var_99_breach"
    mock_metrics.record_var_breach.assert_called_once_with(
        breach_code="var_99_breach",
        var_99=0.10,
        cvar_975=0.03,
        model_dispersion=0.10,
    )


def test_cvar_975_breach_records_prometheus(monkeypatch: pytest.MonkeyPatch) -> None:
    """CVaR 97.5% breach → record_var_breach called with 'cvar_975_breach'."""
    rm, mock_engine, mock_metrics = _make_rm(monkeypatch)

    mock_engine.compute.return_value = _FakeMetrics(
        var_99_1d=0.04,  # within limit
        cvar_975_1d=0.15,  # > limit 0.10
    )

    result = rm._check_var_breach()

    assert result == "cvar_975_breach"
    mock_metrics.record_var_breach.assert_called_once_with(
        breach_code="cvar_975_breach",
        var_99=0.04,
        cvar_975=0.15,
        model_dispersion=0.10,
    )


def test_stressed_var_breach_records_prometheus(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stressed VaR breach → record_var_breach called with 'stressed_var_breach'."""
    rm, mock_engine, mock_metrics = _make_rm(monkeypatch)

    mock_engine.compute.return_value = _FakeMetrics(
        var_99_1d=0.04,  # within limit
        cvar_975_1d=0.05,  # within limit
        stressed_var=0.12,  # > 2 × 0.04 = 0.08
    )

    result = rm._check_var_breach()

    assert result == "stressed_var_breach"
    mock_metrics.record_var_breach.assert_called_once_with(
        breach_code="stressed_var_breach",
        var_99=0.04,
        cvar_975=0.05,
        model_dispersion=0.10,
    )


def test_no_breach_records_prometheus_normal(monkeypatch: pytest.MonkeyPatch) -> None:
    """No breach → record_var_breach called with breach_code=None."""
    rm, mock_engine, mock_metrics = _make_rm(monkeypatch)

    mock_engine.compute.return_value = _FakeMetrics(
        var_99_1d=0.02,
        cvar_975_1d=0.03,
        stressed_var=0.03,
    )

    result = rm._check_var_breach()

    assert result is None
    mock_metrics.record_var_breach.assert_called_once_with(
        breach_code=None,
        var_99=0.02,
        cvar_975=0.03,
        model_dispersion=0.10,
    )


def test_no_metrics_no_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """No MetricsExporter attached → no crash."""
    from super_otonom.risk_manager import RiskManager

    rm = RiskManager(10_000.0)
    mock_engine = MagicMock()
    rm.set_risk_engine(mock_engine)
    rm._returns_history = [0.001] * 30
    # _metrics is None — should not crash

    mock_engine.compute.return_value = _FakeMetrics(var_99_1d=0.10)

    result = rm._check_var_breach()
    assert result == "var_99_breach"  # Breach still detected


def test_metrics_error_no_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """MetricsExporter.record_var_breach raises → no crash."""
    rm, mock_engine, mock_metrics = _make_rm(monkeypatch)

    mock_engine.compute.return_value = _FakeMetrics(var_99_1d=0.10)
    mock_metrics.record_var_breach.side_effect = RuntimeError("prom boom")

    result = rm._check_var_breach()
    assert result == "var_99_breach"  # Breach still works despite Prometheus error


def test_set_metrics_wired_in_bot_engine(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BotEngine.__init__ calls risk.set_metrics(self.metrics)."""
    from super_otonom import bot_engine as be

    monkeypatch.setattr(be, "_STATE_FILE", str(tmp_path / "s.json"))
    monkeypatch.setattr(be, "_TRADE_LOG_FILE", str(tmp_path / "tr" / "tr.log"))

    eng = be.BotEngine(10_000.0, paper=True)

    assert eng.risk._metrics is eng.metrics
