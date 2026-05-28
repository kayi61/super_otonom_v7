"""VR-21: Prometheus VaR/CVaR/Stres Metrikleri — Tam Suite tests.

Tests cover:
  - New labeled gauges registration (var_pct, cvar_pct, stressed_var_pct, etc.)
  - record_var_suite() with RiskMetrics-like object
  - Limit utilisation calculation with VaRLimits
  - Component VaR per-symbol recording
  - Model dispersion gauge
  - No-op when disabled
  - Alert rules YAML validation
  - Sentinel presence
  - Edge cases: None values, zero limits, empty metrics
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

from tests._prompt04_source import METRICS_EXPORTER_PATCH, module_source_path

_PKG = Path(__file__).resolve().parents[2] / "super_otonom"

# ── Fake RiskMetrics for testing ─────────────────────────────────────────────

@dataclass(frozen=True)
class FakeMetrics:
    """Minimal RiskMetrics-like object for VR-21 tests."""

    var_historical_95: float = 0.015
    var_parametric_95: float = 0.018
    var_monte_carlo_95: float = 0.016
    var_cornish_fisher_95: float = 0.017
    var_for_limits_95: float = 0.018
    var_historical_99: float = 0.025
    var_parametric_99: float = 0.030
    var_monte_carlo_99: float = 0.027
    var_cornish_fisher_99: float = 0.028
    var_for_limits_99: float = 0.030
    var_evt_99: Optional[float] = None
    var_fhs_95: Optional[float] = None
    var_fhs_99: Optional[float] = None
    var_regime_conditional_95: Optional[float] = None
    var_regime_conditional_99: Optional[float] = None
    cvar_historical_95: float = 0.020
    cvar_parametric_95: float = 0.024
    cvar_monte_carlo_95: float = 0.022
    cvar_historical_99: float = 0.035
    cvar_parametric_99: float = 0.040
    cvar_monte_carlo_99: float = 0.038
    cvar_975_1d: float = 0.045
    cvar_95_1d: float = 0.024
    cvar_99_1d: float = 0.040
    cvar_evt_99: Optional[float] = None
    cvar_fhs_95: Optional[float] = None
    cvar_fhs_99: Optional[float] = None
    stressed_var: float = 0.08
    stressed_var_worst_period: str = "2022_luna"
    stressed_var_breach: bool = False
    model_dispersion_pct: float = 0.35
    var_99_1d: float = 0.030
    lvar: float = 0.04
    component_var_per_position: Dict[str, float] = field(
        default_factory=lambda: {"BTC/USDT": 0.012, "ETH/USDT": 0.006},
    )
    marginal_var_per_position: Dict[str, float] = field(
        default_factory=lambda: {"BTC/USDT": 0.008, "ETH/USDT": 0.004},
    )


@dataclass(frozen=True)
class FakeLimits:
    """Minimal VaRLimits-like object for VR-21 tests."""

    max_var_total_pct: float = 0.06
    max_cvar_total_pct: float = 0.10
    max_stressed_var_total_pct: float = 0.15
    max_lvar_to_nav: float = 0.08
    max_var_per_strategy_pct: float = 0.02
    max_marginal_var_per_trade_pct: float = 0.005


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def exporter():
    """Create MetricsExporter with port=0 (no HTTP server)."""
    # Isolate prometheus registry per test
    with patch(f"{METRICS_EXPORTER_PATCH}._PROMETHEUS_AVAILABLE", True):
        with patch(f"{METRICS_EXPORTER_PATCH}.Gauge") as mock_gauge, \
             patch(f"{METRICS_EXPORTER_PATCH}.Counter") as mock_counter, \
             patch(f"{METRICS_EXPORTER_PATCH}.Histogram") as mock_histo, \
             patch(f"{METRICS_EXPORTER_PATCH}.start_http_server"):

            # Make mock gauges that track .set() and .labels().set()
            created_gauges = {}

            def make_gauge(name, desc, labels=None):
                g = MagicMock()
                g._name = name
                if labels:
                    g._labels = labels
                    label_instances = {}

                    def labels_fn(**kwargs):
                        key = tuple(sorted(kwargs.items()))
                        if key not in label_instances:
                            label_instances[key] = MagicMock()
                        return label_instances[key]

                    g.labels = labels_fn
                    g._label_instances = label_instances
                created_gauges[name] = g
                return g

            mock_gauge.side_effect = make_gauge
            mock_counter.side_effect = lambda *a, **kw: MagicMock()
            mock_histo.side_effect = lambda *a, **kw: MagicMock()

            from super_otonom.metrics_exporter import MetricsExporter

            exp = MetricsExporter(port=0)
            exp._created_gauges = created_gauges
            yield exp


@pytest.fixture()
def metrics():
    return FakeMetrics()


@pytest.fixture()
def limits():
    return FakeLimits()


# ── Gauge registration tests ────────────────────────────────────────────────

class TestGaugeRegistration:
    """VR-21: Verify all new gauges are created."""

    def test_var_pct_gauge_exists(self, exporter):
        assert "var_pct" in exporter._gauges

    def test_cvar_pct_gauge_exists(self, exporter):
        assert "cvar_pct" in exporter._gauges

    def test_stressed_var_pct_gauge_exists(self, exporter):
        assert "stressed_var_pct" in exporter._gauges

    def test_component_var_pct_gauge_exists(self, exporter):
        assert "component_var_pct" in exporter._gauges

    def test_var_model_dispersion_pct_gauge_exists(self, exporter):
        assert "var_model_dispersion_pct" in exporter._gauges

    def test_var_limit_utilisation_gauge_exists(self, exporter):
        assert "var_limit_utilisation" in exporter._gauges

    def test_var_pct_has_labels(self, exporter):
        """var_pct gauge should have conf, model, scope labels."""
        g = exporter._created_gauges.get("bot_var_pct")
        assert g is not None
        assert g._labels == ["conf", "model", "scope"]

    def test_cvar_pct_has_labels(self, exporter):
        g = exporter._created_gauges.get("bot_cvar_pct")
        assert g is not None
        assert g._labels == ["conf", "model", "scope"]

    def test_component_var_pct_has_symbol_label(self, exporter):
        g = exporter._created_gauges.get("bot_component_var_pct")
        assert g is not None
        assert g._labels == ["symbol"]

    def test_var_limit_utilisation_has_level_label(self, exporter):
        g = exporter._created_gauges.get("bot_var_limit_utilisation")
        assert g is not None
        assert g._labels == ["level"]


# ── record_var_suite() tests ─────────────────────────────────────────────────

class TestRecordVarSuite:
    """VR-21: record_var_suite() writes all VaR/CVaR metrics."""

    def test_basic_call_no_error(self, exporter, metrics):
        """Should not raise."""
        exporter.record_var_suite(metrics)

    def test_var_pct_labels_set(self, exporter, metrics):
        exporter.record_var_suite(metrics)
        g = exporter._gauges["var_pct"]
        # Check that labels were called for historical 95
        instance = g.labels(conf="95", model="historical", scope="portfolio")
        instance.set.assert_called_once_with(0.015)

    def test_var_pct_parametric_99(self, exporter, metrics):
        exporter.record_var_suite(metrics)
        g = exporter._gauges["var_pct"]
        instance = g.labels(conf="99", model="parametric_t", scope="portfolio")
        instance.set.assert_called_once_with(0.030)

    def test_var_pct_aggregate_95(self, exporter, metrics):
        exporter.record_var_suite(metrics)
        g = exporter._gauges["var_pct"]
        instance = g.labels(conf="95", model="aggregate", scope="portfolio")
        instance.set.assert_called_once_with(0.018)

    def test_cvar_pct_975(self, exporter, metrics):
        exporter.record_var_suite(metrics)
        g = exporter._gauges["cvar_pct"]
        instance = g.labels(conf="975", model="aggregate", scope="portfolio")
        instance.set.assert_called_once_with(0.045)

    def test_cvar_pct_historical_95(self, exporter, metrics):
        exporter.record_var_suite(metrics)
        g = exporter._gauges["cvar_pct"]
        instance = g.labels(conf="95", model="historical", scope="portfolio")
        instance.set.assert_called_once_with(0.020)

    def test_stressed_var_pct_set(self, exporter, metrics):
        exporter.record_var_suite(metrics)
        exporter._gauges["stressed_var_pct"].set.assert_called_once_with(0.08)

    def test_model_dispersion_set(self, exporter, metrics):
        exporter.record_var_suite(metrics)
        exporter._gauges["var_model_dispersion_pct"].set.assert_called_once_with(0.35)

    def test_component_var_btc(self, exporter, metrics):
        exporter.record_var_suite(metrics)
        g = exporter._gauges["component_var_pct"]
        # BTC component: 0.012 / 0.018 = 0.6667
        instance = g.labels(symbol="BTC/USDT")
        val = instance.set.call_args[0][0]
        assert abs(val - 0.012 / 0.018) < 1e-6

    def test_component_var_eth(self, exporter, metrics):
        exporter.record_var_suite(metrics)
        g = exporter._gauges["component_var_pct"]
        instance = g.labels(symbol="ETH/USDT")
        val = instance.set.call_args[0][0]
        assert abs(val - 0.006 / 0.018) < 1e-6

    def test_none_optional_fields_skipped(self, exporter):
        """Fields that are None should not call .set()."""
        m = FakeMetrics(var_evt_99=None, var_fhs_95=None, var_fhs_99=None)
        exporter.record_var_suite(m)
        # evt 99 should not be set
        g = exporter._gauges["var_pct"]
        instances = getattr(g, "_label_instances", {})
        evt_key = tuple(sorted({"conf": "99", "model": "evt", "scope": "portfolio"}.items()))
        if evt_key in instances:
            instances[evt_key].set.assert_not_called()

    def test_optional_fhs_fields_written_when_present(self, exporter):
        m = FakeMetrics(var_fhs_95=0.019, var_fhs_99=0.031, cvar_fhs_95=0.025, cvar_fhs_99=0.042)
        exporter.record_var_suite(m)
        g = exporter._gauges["var_pct"]
        instance = g.labels(conf="95", model="fhs", scope="portfolio")
        instance.set.assert_called_once_with(0.019)


# ── Limit utilisation tests ──────────────────────────────────────────────────

class TestLimitUtilisation:
    """VR-21: Limit utilisation gauge calculation."""

    def test_utilisation_with_limits(self, exporter, metrics, limits):
        exporter.record_var_suite(metrics, limits=limits)
        g = exporter._gauges["var_limit_utilisation"]
        # var_99: 0.030 / 0.06 = 0.5
        instance = g.labels(level="var_99")
        val = instance.set.call_args[0][0]
        assert abs(val - 0.5) < 1e-6

    def test_cvar_utilisation(self, exporter, metrics, limits):
        exporter.record_var_suite(metrics, limits=limits)
        g = exporter._gauges["var_limit_utilisation"]
        # cvar_975: 0.045 / 0.10 = 0.45
        instance = g.labels(level="cvar_975")
        val = instance.set.call_args[0][0]
        assert abs(val - 0.45) < 1e-6

    def test_stressed_var_utilisation(self, exporter, metrics, limits):
        exporter.record_var_suite(metrics, limits=limits)
        g = exporter._gauges["var_limit_utilisation"]
        # stressed_var: 0.08 / 0.15 ≈ 0.5333
        instance = g.labels(level="stressed_var")
        val = instance.set.call_args[0][0]
        assert abs(val - 0.08 / 0.15) < 1e-6

    def test_lvar_utilisation(self, exporter, metrics, limits):
        exporter.record_var_suite(metrics, limits=limits)
        g = exporter._gauges["var_limit_utilisation"]
        # lvar: 0.04 / 0.08 = 0.5
        instance = g.labels(level="lvar")
        val = instance.set.call_args[0][0]
        assert abs(val - 0.5) < 1e-6

    def test_no_limits_no_utilisation(self, exporter, metrics):
        """Without limits arg, utilisation should not be written."""
        exporter.record_var_suite(metrics, limits=None)
        g = exporter._gauges["var_limit_utilisation"]
        instances = getattr(g, "_label_instances", {})
        # No label instances should have been created
        assert len(instances) == 0

    def test_utilisation_above_one(self, exporter, limits):
        """Breach scenario: utilisation > 1.0."""
        m = FakeMetrics(var_99_1d=0.08)  # 0.08 / 0.06 = 1.333
        exporter.record_var_suite(m, limits=limits)
        g = exporter._gauges["var_limit_utilisation"]
        instance = g.labels(level="var_99")
        val = instance.set.call_args[0][0]
        assert val > 1.0
        assert abs(val - 0.08 / 0.06) < 1e-6

    def test_zero_limit_guard(self, exporter, metrics):
        """Zero limit should not cause division error."""

        @dataclass(frozen=True)
        class ZeroLimits:
            max_var_total_pct: float = 0.0
            max_cvar_total_pct: float = 0.10
            max_stressed_var_total_pct: float = 0.15
            max_lvar_to_nav: float = 0.08

        exporter.record_var_suite(metrics, limits=ZeroLimits())
        g = exporter._gauges["var_limit_utilisation"]
        instance = g.labels(level="var_99")
        val = instance.set.call_args[0][0]
        assert val == 0.0


# ── Component VaR external dict ──────────────────────────────────────────────

class TestComponentVarExternal:
    """VR-21: Component VaR from external dict overrides metrics."""

    def test_external_component_var(self, exporter, metrics):
        custom = {"SOL/USDT": 0.005, "AVAX/USDT": 0.003}
        exporter.record_var_suite(metrics, component_var=custom)
        g = exporter._gauges["component_var_pct"]
        instance = g.labels(symbol="SOL/USDT")
        val = instance.set.call_args[0][0]
        assert abs(val - 0.005 / 0.018) < 1e-6

    def test_empty_component_var(self, exporter):
        m = FakeMetrics(component_var_per_position={})
        exporter.record_var_suite(m)
        g = exporter._gauges["component_var_pct"]
        instances = getattr(g, "_label_instances", {})
        assert len(instances) == 0


# ── No-op when disabled ──────────────────────────────────────────────────────

class TestNoOp:
    """VR-21: No-op when prometheus_client not available."""

    def test_disabled_no_error(self, metrics):
        with patch(f"{METRICS_EXPORTER_PATCH}._PROMETHEUS_AVAILABLE", False):
            from super_otonom.metrics_exporter import MetricsExporter

            exp = MetricsExporter(port=0)
            # Should not raise
            exp.record_var_suite(metrics)


# ── Alert YAML validation ────────────────────────────────────────────────────

class TestAlertYAML:
    """VR-21: Validate alert rule structure."""

    @pytest.fixture()
    def alert_data(self):
        import yaml

        path = Path(__file__).resolve().parents[2] / "docker" / "prometheus" / "alerts.yml"
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def _get_alert(self, alert_data, name):
        for group in alert_data["groups"]:
            for rule in group["rules"]:
                if rule["alert"] == name:
                    return rule
        return None

    def test_var_approaching_limit_exists(self, alert_data):
        rule = self._get_alert(alert_data, "BotVaRApproachingLimit")
        assert rule is not None
        assert rule["labels"]["severity"] == "warning"
        assert "0.8" in rule["expr"]

    def test_var_limit_breach_exists(self, alert_data):
        rule = self._get_alert(alert_data, "BotVaRLimitBreach")
        assert rule is not None
        assert rule["labels"]["severity"] == "critical"
        assert "1.0" in rule["expr"]

    def test_cvar_limit_breach_exists(self, alert_data):
        rule = self._get_alert(alert_data, "BotCVaRLimitBreach")
        assert rule is not None
        assert rule["labels"]["severity"] == "critical"

    def test_model_dispersion_high_exists(self, alert_data):
        rule = self._get_alert(alert_data, "BotModelDispersionHigh")
        assert rule is not None
        assert rule["labels"]["severity"] == "warning"
        assert "0.5" in rule["expr"]

    def test_pnl_unexplained_high_exists(self, alert_data):
        rule = self._get_alert(alert_data, "BotPnLUnexplainedHigh")
        assert rule is not None
        assert "0.0015" in rule["expr"]

    def test_stressed_var_approaching_exists(self, alert_data):
        rule = self._get_alert(alert_data, "BotStressedVaRApproachingLimit")
        assert rule is not None
        assert rule["labels"]["severity"] == "warning"

    def test_lvar_breach_exists(self, alert_data):
        rule = self._get_alert(alert_data, "BotLVaRLimitBreach")
        assert rule is not None
        assert rule["labels"]["severity"] == "warning"

    def test_all_vr21_alerts_have_annotations(self, alert_data):
        vr21_alerts = [
            "BotVaRApproachingLimit",
            "BotVaRLimitBreach",
            "BotCVaRLimitBreach",
            "BotModelDispersionHigh",
            "BotPnLUnexplainedHigh",
            "BotStressedVaRApproachingLimit",
            "BotLVaRLimitBreach",
        ]
        for name in vr21_alerts:
            rule = self._get_alert(alert_data, name)
            assert rule is not None, f"Missing alert: {name}"
            assert "summary" in rule["annotations"], f"{name}: missing summary"


# ── Sentinel tests ───────────────────────────────────────────────────────────

class TestSentinel:
    """VR-21: var_topology sentinel."""

    def test_sentinel_in_metrics_exporter(self):
        text = module_source_path(_PKG, "metrics_exporter").read_text(encoding="utf-8")
        assert "prometheus_var_full_suite" in text

    def test_sentinel_set_on_instance(self, exporter):
        assert getattr(exporter, "_prometheus_var_full_suite", False) is True


# ── var_topology_audit allowlist ─────────────────────────────────────────────

class TestAuditAllowlist:
    """VR-21: Test file and substrings in audit allowlist."""

    def test_test_file_in_allowlist(self):
        text = module_source_path(_PKG, "var_topology_audit").read_text(encoding="utf-8")
        assert "test_prometheus_var_suite_vr21" in text

    def test_substrings_in_allowlist(self):
        text = module_source_path(_PKG, "var_topology_audit").read_text(encoding="utf-8")
        for s in (
            "prometheus_var_full_suite",
            "record_var_suite",
            "var_limit_utilisation",
            "var_model_dispersion",
            "component_var_pct",
            "stressed_var_pct",
        ):
            assert s in text, f"Missing allow substr: {s}"


# ── Integration with real VaRLimits ──────────────────────────────────────────

class TestRealVaRLimitsIntegration:
    """VR-21: Integration with actual VaRLimits from risk package."""

    def test_with_real_limits(self, exporter, metrics):
        from super_otonom.risk.var_limits import VaRLimits

        real_limits = VaRLimits()
        # Should not raise
        exporter.record_var_suite(metrics, limits=real_limits)
        g = exporter._gauges["var_limit_utilisation"]
        instance = g.labels(level="var_99")
        val = instance.set.call_args[0][0]
        # 0.030 / 0.06 = 0.5
        assert abs(val - 0.5) < 1e-6


# ── Edge cases ───────────────────────────────────────────────────────────────

class TestEdgeCases:
    """VR-21: Edge cases and error resilience."""

    def test_empty_metrics_object(self, exporter):
        """Object with no attributes should not raise."""

        class EmptyMetrics:
            pass

        exporter.record_var_suite(EmptyMetrics())

    def test_partial_metrics(self, exporter):
        """Object with only some attributes should work."""

        class PartialMetrics:
            var_historical_95 = 0.015
            stressed_var = 0.05
            model_dispersion_pct = 0.20

        exporter.record_var_suite(PartialMetrics())
        exporter._gauges["stressed_var_pct"].set.assert_called_once_with(0.05)
        exporter._gauges["var_model_dispersion_pct"].set.assert_called_once_with(0.20)

    def test_negative_var_values(self, exporter):
        """Negative VaR values should be passed through (not our job to filter)."""
        m = FakeMetrics(var_historical_95=-0.01)
        exporter.record_var_suite(m)
        g = exporter._gauges["var_pct"]
        instance = g.labels(conf="95", model="historical", scope="portfolio")
        instance.set.assert_called_once_with(-0.01)

    def test_very_large_dispersion(self, exporter):
        m = FakeMetrics(model_dispersion_pct=5.0)
        exporter.record_var_suite(m)
        exporter._gauges["var_model_dispersion_pct"].set.assert_called_once_with(5.0)

    def test_component_var_with_zero_var_total(self, exporter):
        """var_for_limits_95 = 0 should not cause ZeroDivisionError."""
        m = FakeMetrics(var_for_limits_95=0.0)
        exporter.record_var_suite(m)
        # Component var ratio should be 0.0
        g = exporter._gauges["component_var_pct"]
        instance = g.labels(symbol="BTC/USDT")
        val = instance.set.call_args[0][0]
        assert val == 0.0

    def test_record_var_suite_called_twice(self, exporter, metrics, limits):
        """Multiple calls should not raise or accumulate errors."""
        exporter.record_var_suite(metrics, limits=limits)
        exporter.record_var_suite(metrics, limits=limits)

    def test_regime_var_when_present(self, exporter):
        m = FakeMetrics(var_regime_conditional_95=0.022, var_regime_conditional_99=0.038)
        exporter.record_var_suite(m)
        g = exporter._gauges["var_pct"]
        instance = g.labels(conf="95", model="regime", scope="portfolio")
        instance.set.assert_called_with(0.022)
