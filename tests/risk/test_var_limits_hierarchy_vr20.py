"""VR-20: VaR Limit Hierarchy — test suite.

Tests:
  - VaRLimits dataclass defaults
  - validate() invariants (all valid, hierarchy violations)
  - is_valid property
  - to_dict serialization
  - load_var_limits() from YAML
  - load_var_limits() env override chain
  - load_var_limits() env > YAML > defaults priority
  - load_var_limits() missing YAML → defaults
  - load_var_limits() skip_env flag
  - check_limits() portfolio VaR breach
  - check_limits() CVaR breach
  - check_limits() stressed VaR breach
  - check_limits() LVaR breach
  - check_limits() component VaR concentration breach
  - check_limits() all clean → empty list
  - deploy_env_check integration
  - sentinel detection
  - YAML parser fallback (no PyYAML)
  - boundary conditions
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest
from super_otonom.risk.risk_engine import RiskMetrics
from super_otonom.risk.var_limits import (
    VaRLimits,
    _env_overrides,
    _load_yaml,
    check_limits,
    load_var_limits,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def defaults() -> VaRLimits:
    """Default limits."""
    return VaRLimits()


@pytest.fixture()
def tmp_yaml(tmp_path: Path) -> Path:
    """Create a temporary YAML config."""
    p = tmp_path / "var_limits.yaml"
    p.write_text(
        textwrap.dedent("""\
        # Test overrides
        max_var_per_strategy_pct: 0.03
        max_cvar_per_strategy_pct: 0.04
        max_var_total_pct: 0.08
        max_cvar_total_pct: 0.12
        max_stressed_var_total_pct: 0.20
        max_marginal_var_per_trade_pct: 0.01
        max_component_var_per_position_pct: 0.50
        max_lvar_to_nav: 0.10
        """),
        encoding="utf-8",
    )
    return p


@pytest.fixture()
def invalid_yaml(tmp_path: Path) -> Path:
    """YAML with hierarchy violation."""
    p = tmp_path / "bad_limits.yaml"
    p.write_text(
        textwrap.dedent("""\
        max_var_per_strategy_pct: 0.10
        max_var_total_pct: 0.05
        """),
        encoding="utf-8",
    )
    return p


# ── Test: Dataclass Defaults ─────────────────────────────────────────────────


class TestDefaults:
    def test_default_values(self, defaults: VaRLimits) -> None:
        assert defaults.max_var_per_strategy_pct == 0.02
        assert defaults.max_cvar_per_strategy_pct == 0.03
        assert defaults.max_var_total_pct == 0.06
        assert defaults.max_cvar_total_pct == 0.10
        assert defaults.max_stressed_var_total_pct == 0.15
        assert defaults.max_marginal_var_per_trade_pct == 0.005
        assert defaults.max_component_var_per_position_pct == 0.40
        assert defaults.max_lvar_to_nav == 0.08

    def test_frozen(self, defaults: VaRLimits) -> None:
        with pytest.raises(AttributeError):
            defaults.max_var_total_pct = 0.99  # type: ignore[misc]

    def test_defaults_are_valid(self, defaults: VaRLimits) -> None:
        assert defaults.is_valid
        assert defaults.validate() == []


# ── Test: validate() invariants ──────────────────────────────────────────────


class TestValidate:
    def test_strategy_ge_portfolio_var(self) -> None:
        """strategy VaR >= portfolio VaR → violation."""
        lim = VaRLimits(max_var_per_strategy_pct=0.06, max_var_total_pct=0.06)
        issues = lim.validate()
        assert any("max_var_per_strategy_pct" in i for i in issues)

    def test_strategy_gt_portfolio_var(self) -> None:
        """strategy VaR > portfolio VaR → violation."""
        lim = VaRLimits(max_var_per_strategy_pct=0.10, max_var_total_pct=0.06)
        issues = lim.validate()
        assert any("max_var_per_strategy_pct" in i for i in issues)

    def test_strategy_ge_portfolio_cvar(self) -> None:
        lim = VaRLimits(max_cvar_per_strategy_pct=0.10, max_cvar_total_pct=0.10)
        issues = lim.validate()
        assert any("max_cvar_per_strategy_pct" in i for i in issues)

    def test_portfolio_var_ge_stressed_var(self) -> None:
        lim = VaRLimits(max_var_total_pct=0.15, max_stressed_var_total_pct=0.15)
        issues = lim.validate()
        assert any("max_var_total_pct" in i for i in issues)

    def test_marginal_ge_strategy(self) -> None:
        lim = VaRLimits(
            max_marginal_var_per_trade_pct=0.02,
            max_var_per_strategy_pct=0.02,
        )
        issues = lim.validate()
        assert any("max_marginal_var_per_trade_pct" in i for i in issues)

    def test_zero_limit_invalid(self) -> None:
        lim = VaRLimits(max_var_per_strategy_pct=0.0)
        issues = lim.validate()
        assert any("outside (0, 1]" in i for i in issues)

    def test_negative_limit_invalid(self) -> None:
        lim = VaRLimits(max_lvar_to_nav=-0.01)
        issues = lim.validate()
        assert any("outside (0, 1]" in i for i in issues)

    def test_over_one_invalid(self) -> None:
        lim = VaRLimits(max_component_var_per_position_pct=1.5)
        issues = lim.validate()
        assert any("outside (0, 1]" in i for i in issues)

    def test_exactly_one_valid(self) -> None:
        """1.0 is within (0, 1]."""
        lim = VaRLimits(max_component_var_per_position_pct=1.0)
        # This field at 1.0 is OK, but hierarchy might fail
        issues = [i for i in lim.validate() if "outside (0, 1]" in i and "component" in i]
        assert len(issues) == 0

    def test_multiple_violations(self) -> None:
        """Multiple violations reported simultaneously."""
        lim = VaRLimits(
            max_var_per_strategy_pct=0.10,
            max_var_total_pct=0.05,
            max_cvar_per_strategy_pct=0.20,
            max_cvar_total_pct=0.10,
            max_marginal_var_per_trade_pct=0.50,
        )
        issues = lim.validate()
        assert len(issues) >= 3


# ── Test: is_valid property ──────────────────────────────────────────────────


class TestIsValid:
    def test_valid_defaults(self) -> None:
        assert VaRLimits().is_valid is True

    def test_invalid_hierarchy(self) -> None:
        lim = VaRLimits(max_var_per_strategy_pct=0.10, max_var_total_pct=0.05)
        assert lim.is_valid is False


# ── Test: to_dict ────────────────────────────────────────────────────────────


class TestToDict:
    def test_all_keys_present(self, defaults: VaRLimits) -> None:
        d = defaults.to_dict()
        assert len(d) == 8
        assert "max_var_per_strategy_pct" in d
        assert "max_lvar_to_nav" in d

    def test_values_match(self, defaults: VaRLimits) -> None:
        d = defaults.to_dict()
        assert d["max_var_total_pct"] == 0.06


# ── Test: _load_yaml ─────────────────────────────────────────────────────────


class TestLoadYaml:
    def test_valid_yaml(self, tmp_yaml: Path) -> None:
        data = _load_yaml(tmp_yaml)
        assert data["max_var_per_strategy_pct"] == 0.03
        assert data["max_var_total_pct"] == 0.08

    def test_missing_file(self, tmp_path: Path) -> None:
        data = _load_yaml(tmp_path / "nonexistent.yaml")
        assert data == {}

    def test_comment_only_yaml(self, tmp_path: Path) -> None:
        p = tmp_path / "comments.yaml"
        p.write_text("# only comments\n# nothing here\n", encoding="utf-8")
        data = _load_yaml(p)
        assert data == {}

    def test_inline_comments(self, tmp_path: Path) -> None:
        p = tmp_path / "inline.yaml"
        p.write_text("max_var_total_pct: 0.07  # custom\n", encoding="utf-8")
        data = _load_yaml(p)
        assert data["max_var_total_pct"] == pytest.approx(0.07)


# ── Test: _env_overrides ─────────────────────────────────────────────────────


class TestEnvOverrides:
    def test_env_override(self) -> None:
        with patch.dict(os.environ, {"MAX_VAR_TOTAL_PCT": "0.09"}):
            overrides = _env_overrides()
        assert overrides["max_var_total_pct"] == pytest.approx(0.09)

    def test_invalid_env_skipped(self) -> None:
        with patch.dict(os.environ, {"MAX_VAR_TOTAL_PCT": "not_a_number"}):
            overrides = _env_overrides()
        assert "max_var_total_pct" not in overrides

    def test_no_env_empty(self) -> None:
        # Ensure test env doesn't have our vars
        clean_env = {k: v for k, v in os.environ.items() if not k.startswith("MAX_")}
        with patch.dict(os.environ, clean_env, clear=True):
            overrides = _env_overrides()
        assert len(overrides) == 0


# ── Test: load_var_limits — override chain ───────────────────────────────────


class TestLoadVarLimits:
    def test_defaults_when_no_yaml_no_env(self, tmp_path: Path) -> None:
        """No YAML, no env → pure defaults."""
        lim = load_var_limits(yaml_path=tmp_path / "missing.yaml", skip_env=True)
        assert lim.max_var_total_pct == 0.06
        assert lim.is_valid

    def test_yaml_overrides_defaults(self, tmp_yaml: Path) -> None:
        lim = load_var_limits(yaml_path=tmp_yaml, skip_env=True)
        assert lim.max_var_per_strategy_pct == 0.03
        assert lim.max_var_total_pct == 0.08
        assert lim.is_valid

    def test_env_overrides_yaml(self, tmp_yaml: Path) -> None:
        """env > YAML > defaults."""
        with patch.dict(os.environ, {"MAX_VAR_TOTAL_PCT": "0.07"}):
            lim = load_var_limits(yaml_path=tmp_yaml)
        # env wins over YAML's 0.08
        assert lim.max_var_total_pct == pytest.approx(0.07)
        # YAML still applies for non-env fields
        assert lim.max_var_per_strategy_pct == 0.03

    def test_skip_env_flag(self, tmp_yaml: Path) -> None:
        with patch.dict(os.environ, {"MAX_VAR_TOTAL_PCT": "0.99"}):
            lim = load_var_limits(yaml_path=tmp_yaml, skip_env=True)
        # env ignored → YAML value
        assert lim.max_var_total_pct == 0.08

    def test_partial_yaml(self, tmp_path: Path) -> None:
        """YAML with only some fields → rest are defaults."""
        p = tmp_path / "partial.yaml"
        p.write_text("max_var_total_pct: 0.07\n", encoding="utf-8")
        lim = load_var_limits(yaml_path=p, skip_env=True)
        assert lim.max_var_total_pct == 0.07
        assert lim.max_var_per_strategy_pct == 0.02  # default

    def test_unknown_yaml_keys_ignored(self, tmp_path: Path) -> None:
        p = tmp_path / "extra.yaml"
        p.write_text("max_var_total_pct: 0.07\nfake_key: 999\n", encoding="utf-8")
        lim = load_var_limits(yaml_path=p, skip_env=True)
        assert lim.max_var_total_pct == 0.07
        assert not hasattr(lim, "fake_key")

    def test_invalid_yaml_produces_invalid_limits(self, invalid_yaml: Path) -> None:
        lim = load_var_limits(yaml_path=invalid_yaml, skip_env=True)
        assert not lim.is_valid


# ── Test: check_limits ───────────────────────────────────────────────────────


class TestCheckLimits:
    def test_all_clean(self) -> None:
        lim = VaRLimits()
        metrics = RiskMetrics(
            var_99_1d=0.03,
            cvar_975_1d=0.05,
            stressed_var=0.08,
            lvar=0.05,
        )
        breaches = check_limits(lim, metrics)
        assert breaches == []

    def test_portfolio_var_breach(self) -> None:
        lim = VaRLimits()
        metrics = RiskMetrics(var_99_1d=0.08)  # > 0.06
        breaches = check_limits(lim, metrics)
        assert any("portfolio_var_99" in b for b in breaches)

    def test_portfolio_cvar_breach(self) -> None:
        lim = VaRLimits()
        metrics = RiskMetrics(var_99_1d=0.03, cvar_975_1d=0.15)  # > 0.10
        breaches = check_limits(lim, metrics)
        assert any("portfolio_cvar_975" in b for b in breaches)

    def test_stressed_var_breach(self) -> None:
        lim = VaRLimits()
        metrics = RiskMetrics(var_99_1d=0.03, cvar_975_1d=0.05, stressed_var=0.20)
        breaches = check_limits(lim, metrics)
        assert any("stressed_var" in b for b in breaches)

    def test_lvar_breach(self) -> None:
        lim = VaRLimits()
        metrics = RiskMetrics(var_99_1d=0.03, lvar=0.12)  # > 0.08
        breaches = check_limits(lim, metrics)
        assert any("lvar" in b for b in breaches)

    def test_component_var_concentration(self) -> None:
        lim = VaRLimits()
        metrics = RiskMetrics(
            var_99_1d=0.03,
            var_for_limits_95=0.05,
            component_var_per_position={"BTC": 0.04, "ETH": 0.01},
        )
        # BTC: 0.04 / 0.05 = 0.80 > 0.40 limit
        breaches = check_limits(lim, metrics)
        assert any("component_var[BTC]" in b for b in breaches)
        assert not any("component_var[ETH]" in b for b in breaches)

    def test_component_var_zero_total(self) -> None:
        """Zero total VaR → no division error, no breach."""
        lim = VaRLimits()
        metrics = RiskMetrics(
            var_for_limits_95=0.0,
            component_var_per_position={"BTC": 0.01},
        )
        breaches = check_limits(lim, metrics)
        assert not any("component_var" in b for b in breaches)

    def test_multiple_breaches(self) -> None:
        lim = VaRLimits()
        metrics = RiskMetrics(
            var_99_1d=0.08,
            cvar_975_1d=0.15,
            stressed_var=0.20,
            lvar=0.12,
        )
        breaches = check_limits(lim, metrics)
        assert len(breaches) >= 4

    def test_at_boundary_no_breach(self) -> None:
        """Exactly at limit → no breach (strict >)."""
        lim = VaRLimits()
        metrics = RiskMetrics(
            var_99_1d=0.06,  # == limit
            cvar_975_1d=0.10,
            stressed_var=0.15,
            lvar=0.08,
        )
        breaches = check_limits(lim, metrics)
        assert breaches == []

    def test_custom_limits(self) -> None:
        """Custom limits affect breach detection."""
        lim = VaRLimits(max_var_total_pct=0.10)
        metrics = RiskMetrics(var_99_1d=0.08)  # < custom 0.10
        breaches = check_limits(lim, metrics)
        assert not any("portfolio_var_99" in b for b in breaches)


# ── Test: deploy_env_check integration ───────────────────────────────────────


class TestDeployEnvCheck:
    def test_valid_limits_pass(self) -> None:
        """Default limits pass deploy_env_check validation."""
        lim = load_var_limits(skip_env=True)
        assert lim.is_valid

    def test_invalid_limits_detected(self, invalid_yaml: Path) -> None:
        """Invalid hierarchy detected during validation."""
        lim = load_var_limits(yaml_path=invalid_yaml, skip_env=True)
        issues = lim.validate()
        assert len(issues) > 0
        assert any("must be <" in i for i in issues)


# ── Test: sentinel detection ─────────────────────────────────────────────────


class TestSentinel:
    def test_var_limit_hierarchy_sentinel(self) -> None:
        import super_otonom.risk.var_limits as mod

        assert hasattr(mod, "var_limit_hierarchy_active")
        assert mod.var_limit_hierarchy_active is True


# ── Test: public import from risk package ────────────────────────────────────


class TestPublicImport:
    def test_import_from_risk(self) -> None:
        from super_otonom.risk import VaRLimits, check_limits, load_var_limits

        assert VaRLimits is not None
        assert callable(load_var_limits)
        assert callable(check_limits)


# ── Test: YAML with real config/var_limits.yaml ──────────────────────────────


class TestRealYaml:
    def test_shipped_yaml_valid(self) -> None:
        """The shipped config/var_limits.yaml produces valid limits."""
        repo = Path(__file__).resolve().parents[2]
        yaml_path = repo / "config" / "var_limits.yaml"
        if yaml_path.is_file():
            lim = load_var_limits(yaml_path=yaml_path, skip_env=True)
            assert lim.is_valid, f"Shipped YAML invalid: {lim.validate()}"
