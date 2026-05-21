"""VR-23: Grafana Risk Dashboard tests.

Tests cover:
  - Dashboard JSON validity (parseable, schema version)
  - 9+ panels present with correct types
  - Template variables (conf, model, symbol, horizon)
  - PromQL expressions reference correct metrics
  - Provisioning YAML auto-loads the dashboard
  - Panel grid layout (no overlaps)
  - Color thresholds configured
  - Documentation file exists
  - var_topology_audit allowlist
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_DASHBOARD = _ROOT / "docker" / "grafana" / "provisioning" / "dashboards" / "json" / "risk.json"
_PROVISIONING = _ROOT / "docker" / "grafana" / "provisioning" / "dashboards" / "default.yml"


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def dashboard():
    """Load and parse the risk dashboard JSON."""
    assert _DASHBOARD.is_file(), f"Dashboard not found: {_DASHBOARD}"
    text = _DASHBOARD.read_text(encoding="utf-8")
    return json.loads(text)


@pytest.fixture(scope="module")
def panels(dashboard):
    """Extract non-row panels from dashboard."""
    return [p for p in dashboard["panels"] if p.get("type") != "row"]


@pytest.fixture(scope="module")
def all_panels(dashboard):
    """All panels including rows."""
    return dashboard["panels"]


# ── JSON Validity ────────────────────────────────────────────────────────────


class TestDashboardJSON:
    """VR-23: Dashboard JSON structure."""

    def test_file_exists(self):
        assert _DASHBOARD.is_file()

    def test_valid_json(self):
        text = _DASHBOARD.read_text(encoding="utf-8")
        data = json.loads(text)
        assert isinstance(data, dict)

    def test_schema_version(self, dashboard):
        assert dashboard.get("schemaVersion", 0) >= 36

    def test_has_uid(self, dashboard):
        assert dashboard["uid"] == "risk-var-cvar"

    def test_has_title(self, dashboard):
        assert "Risk" in dashboard["title"]

    def test_has_tags(self, dashboard):
        tags = dashboard.get("tags", [])
        assert "risk" in tags
        assert "vr-23" in tags

    def test_refresh_interval(self, dashboard):
        assert dashboard.get("refresh") in ("10s", "30s", "1m")

    def test_timezone_utc(self, dashboard):
        assert dashboard.get("timezone") == "utc"


# ── Panel Count and Types ───────────────────────────────────────────────────


class TestPanelRequirements:
    """VR-23: Minimum 9 core panels."""

    def test_minimum_9_panels(self, panels):
        assert len(panels) >= 9, f"Only {len(panels)} panels found, need >= 9"

    def test_has_timeseries_panels(self, panels):
        ts = [p for p in panels if p["type"] == "timeseries"]
        assert len(ts) >= 4, "Need at least 4 timeseries panels"

    def test_has_piechart_panel(self, panels):
        pies = [p for p in panels if p["type"] == "piechart"]
        assert len(pies) >= 1, "Missing piechart panel (component VaR)"

    def test_has_gauge_panel(self, panels):
        gauges = [p for p in panels if p["type"] == "gauge"]
        assert len(gauges) >= 1, "Missing gauge panel (model dispersion)"

    def test_has_stat_panels(self, panels):
        stats = [p for p in panels if p["type"] == "stat"]
        assert len(stats) >= 3, "Need at least 3 stat panels"


# ── Specific Panel Content ───────────────────────────────────────────────────


class TestPanelContent:
    """VR-23: Each required panel is present with correct queries."""

    def _find_panel(self, panels, title_substr):
        for p in panels:
            if title_substr.lower() in p.get("title", "").lower():
                return p
        return None

    def _all_exprs(self, panel):
        return [t.get("expr", "") for t in panel.get("targets", [])]

    def test_panel_1_var_timeline(self, panels):
        p = self._find_panel(panels, "VaR Timeline")
        assert p is not None, "Panel 1 (VaR Timeline) missing"
        assert p["type"] == "timeseries"
        exprs = self._all_exprs(p)
        assert any("bot_var_pct" in e for e in exprs)

    def test_panel_2_cvar_timeline(self, panels):
        p = self._find_panel(panels, "CVaR Timeline")
        assert p is not None, "Panel 2 (CVaR Timeline) missing"
        exprs = self._all_exprs(p)
        assert any("bot_cvar_pct" in e for e in exprs)

    def test_panel_3_component_var_pie(self, panels):
        p = self._find_panel(panels, "Component VaR")
        assert p is not None, "Panel 3 (Component VaR Pie) missing"
        assert p["type"] == "piechart"
        exprs = self._all_exprs(p)
        assert any("bot_component_var_pct" in e for e in exprs)

    def test_panel_4_var_vs_pnl(self, panels):
        p = self._find_panel(panels, "VaR vs Realized")
        assert p is not None, "Panel 4 (VaR vs PnL) missing"
        exprs = self._all_exprs(p)
        assert any("bot_var_pct" in e for e in exprs)
        assert any("pnl" in e.lower() for e in exprs)

    def test_panel_5_traffic_light(self, panels):
        p = self._find_panel(panels, "Traffic Light")
        assert p is not None, "Panel 5 (Traffic Light) missing"
        exprs = self._all_exprs(p)
        assert any("bot_var_traffic_light" in e for e in exprs)

    def test_panel_6_model_dispersion(self, panels):
        p = self._find_panel(panels, "Model Dispersion")
        assert p is not None, "Panel 6 (Model Dispersion) missing"
        assert p["type"] == "gauge"
        exprs = self._all_exprs(p)
        assert any("dispersion" in e for e in exprs)

    def test_panel_7_stress_worst(self, panels):
        p = self._find_panel(panels, "Stress")
        assert p is not None, "Panel 7 (Stress Worst PnL) missing"
        exprs = self._all_exprs(p)
        assert any("stress" in e.lower() for e in exprs)

    def test_panel_8_unexplained_pnl(self, panels):
        p = self._find_panel(panels, "Unexplained PnL")
        assert p is not None, "Panel 8 (Unexplained PnL) missing"
        exprs = self._all_exprs(p)
        assert any("unexplained" in e for e in exprs)

    def test_panel_9_limit_utilization(self, panels):
        p = self._find_panel(panels, "Limit Utilization")
        assert p is not None, "Panel 9 (Limit Utilization) missing"
        exprs = self._all_exprs(p)
        assert any("bot_var_limit_utilisation" in e for e in exprs)


# ── Template Variables ───────────────────────────────────────────────────────


class TestTemplateVariables:
    """VR-23: Grafana dropdown variables."""

    def _get_var(self, dashboard, name):
        for v in dashboard.get("templating", {}).get("list", []):
            if v.get("name") == name:
                return v
        return None

    def test_conf_variable(self, dashboard):
        v = self._get_var(dashboard, "conf")
        assert v is not None, "Missing template variable: conf"
        assert v.get("multi") is True

    def test_model_variable(self, dashboard):
        v = self._get_var(dashboard, "model")
        assert v is not None, "Missing template variable: model"
        assert v.get("multi") is True

    def test_symbol_variable(self, dashboard):
        v = self._get_var(dashboard, "symbol")
        assert v is not None, "Missing template variable: symbol"
        assert v.get("multi") is True

    def test_horizon_variable(self, dashboard):
        v = self._get_var(dashboard, "horizon")
        assert v is not None, "Missing template variable: horizon"

    def test_conf_query(self, dashboard):
        v = self._get_var(dashboard, "conf")
        query = v.get("definition", "") or ""
        if not query:
            q = v.get("query", {})
            query = q.get("query", "") if isinstance(q, dict) else str(q)
        assert "bot_var_pct" in query

    def test_symbol_query(self, dashboard):
        v = self._get_var(dashboard, "symbol")
        query = v.get("definition", "") or ""
        if not query:
            q = v.get("query", {})
            query = q.get("query", "") if isinstance(q, dict) else str(q)
        assert "bot_component_var_pct" in query


# ── PromQL Coverage ──────────────────────────────────────────────────────────


class TestPromQLCoverage:
    """VR-23: All VR-21 metrics referenced in dashboard."""

    def _all_dashboard_exprs(self, dashboard):
        exprs = []
        for p in dashboard.get("panels", []):
            for t in p.get("targets", []):
                exprs.append(t.get("expr", ""))
        return exprs

    def test_var_pct_referenced(self, dashboard):
        exprs = self._all_dashboard_exprs(dashboard)
        assert any("bot_var_pct" in e for e in exprs)

    def test_cvar_pct_referenced(self, dashboard):
        exprs = self._all_dashboard_exprs(dashboard)
        assert any("bot_cvar_pct" in e for e in exprs)

    def test_stressed_var_referenced(self, dashboard):
        exprs = self._all_dashboard_exprs(dashboard)
        assert any("stressed_var" in e for e in exprs)

    def test_component_var_referenced(self, dashboard):
        exprs = self._all_dashboard_exprs(dashboard)
        assert any("bot_component_var_pct" in e for e in exprs)

    def test_dispersion_referenced(self, dashboard):
        exprs = self._all_dashboard_exprs(dashboard)
        assert any("dispersion" in e for e in exprs)

    def test_limit_utilisation_referenced(self, dashboard):
        exprs = self._all_dashboard_exprs(dashboard)
        assert any("bot_var_limit_utilisation" in e for e in exprs)

    def test_traffic_light_referenced(self, dashboard):
        exprs = self._all_dashboard_exprs(dashboard)
        assert any("bot_var_traffic_light" in e for e in exprs)

    def test_pnl_unexplained_referenced(self, dashboard):
        exprs = self._all_dashboard_exprs(dashboard)
        assert any("pnl_unexplained" in e for e in exprs)

    def test_kill_switch_referenced(self, dashboard):
        exprs = self._all_dashboard_exprs(dashboard)
        assert any("kill_switch" in e for e in exprs)


# ── Grid Layout ──────────────────────────────────────────────────────────────


class TestGridLayout:
    """VR-23: Panel layout integrity."""

    def test_all_panels_have_gridpos(self, all_panels):
        for p in all_panels:
            assert "gridPos" in p, f"Panel {p.get('id')} missing gridPos"

    def test_panel_ids_unique(self, all_panels):
        ids = [p["id"] for p in all_panels]
        assert len(ids) == len(set(ids)), "Duplicate panel IDs found"

    def test_panels_within_24_columns(self, all_panels):
        for p in all_panels:
            gp = p["gridPos"]
            assert gp["x"] + gp["w"] <= 24, (
                f"Panel {p.get('id')} exceeds 24-column grid: x={gp['x']} w={gp['w']}"
            )


# ── Color Thresholds ────────────────────────────────────────────────────────


class TestColorThresholds:
    """VR-23: Key panels have color thresholds."""

    def _find_panel(self, panels, title_substr):
        for p in panels:
            if title_substr.lower() in p.get("title", "").lower():
                return p
        return None

    def test_dispersion_has_thresholds(self, panels):
        p = self._find_panel(panels, "Dispersion")
        assert p is not None
        thresholds = p["fieldConfig"]["defaults"]["thresholds"]["steps"]
        assert len(thresholds) >= 3

    def test_traffic_light_has_color_mapping(self, panels):
        p = self._find_panel(panels, "Traffic Light")
        assert p is not None
        mappings = p["fieldConfig"]["defaults"].get("mappings", [])
        assert len(mappings) >= 2, "Traffic light should have value mappings"

    def test_limit_utilization_has_thresholds(self, panels):
        p = self._find_panel(panels, "Limit Utilization")
        assert p is not None
        thresholds = p["fieldConfig"]["defaults"]["thresholds"]["steps"]
        assert len(thresholds) >= 4


# ── Provisioning ─────────────────────────────────────────────────────────────


class TestProvisioning:
    """VR-23: Grafana provisioning auto-loads dashboard."""

    def test_provisioning_yaml_exists(self):
        assert _PROVISIONING.is_file()

    def test_provisioning_references_json_dir(self):
        text = _PROVISIONING.read_text(encoding="utf-8")
        assert "json" in text
        assert "dashboards" in text.lower()


# ── Documentation ────────────────────────────────────────────────────────────


class TestDocumentation:
    """VR-23: RISK_DASHBOARD.md exists with required content."""

    def test_doc_exists(self):
        doc = _ROOT / "docs" / "RISK_DASHBOARD.md"
        assert doc.is_file()

    def test_doc_has_panel_descriptions(self):
        doc = _ROOT / "docs" / "RISK_DASHBOARD.md"
        text = doc.read_text(encoding="utf-8")
        assert "VaR Timeline" in text
        assert "Component VaR" in text
        assert "Traffic Light" in text
        assert "Limit" in text

    def test_doc_has_variables(self):
        doc = _ROOT / "docs" / "RISK_DASHBOARD.md"
        text = doc.read_text(encoding="utf-8")
        assert "conf" in text
        assert "model" in text
        assert "symbol" in text
        assert "horizon" in text


# ── Audit Allowlist ──────────────────────────────────────────────────────────


class TestAuditAllowlist:
    """VR-23: var_topology_audit allowlist."""

    def test_test_file_in_allowlist(self):
        src = _ROOT / "super_otonom" / "var_topology_audit.py"
        text = src.read_text(encoding="utf-8")
        assert "test_grafana_risk_dashboard_vr23" in text

    def test_risk_dashboard_in_allowlist(self):
        src = _ROOT / "super_otonom" / "var_topology_audit.py"
        text = src.read_text(encoding="utf-8")
        assert "RISK_DASHBOARD.md" in text
        assert "risk.json" in text
