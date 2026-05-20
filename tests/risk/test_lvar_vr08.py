"""VR-08 tests — Liquidity-adjusted VaR (LVaR): BDSS + time-to-liquidate."""

from __future__ import annotations

import numpy as np
from super_otonom.risk.config import RiskConfig
from super_otonom.risk.lvar import (
    bdss_lvar,
    compute_lvar,
    time_to_liquidate_lvar,
)
from super_otonom.risk.risk_engine import RiskEngine, RiskMetrics

# ── Fixtures ─────────────────────────────────────────────────────────────────

_RNG = np.random.default_rng(808)
SPREAD_NORMAL = (_RNG.lognormal(-7, 0.3, size=200)).tolist()  # ~0.1% spreads
SPREAD_WIDE = (_RNG.lognormal(-5, 0.5, size=200)).tolist()  # wider spreads
SPREAD_SHORT = [0.001, 0.002]  # too few for BDSS

RETURNS_500 = np.random.default_rng(909).normal(0.0, 0.02, size=500).tolist()


# ═══════════════════════════════════════════════════════════════════════════════
# §1  BDSS method
# ═══════════════════════════════════════════════════════════════════════════════


class TestBDSS:
    """BDSS: VaR_market + 0.5 * notional * (mean + alpha*std) of spreads."""

    def test_basic_computation(self) -> None:
        result = bdss_lvar(0.05, 100_000.0, SPREAD_NORMAL)
        assert result is not None
        assert result > 0.05, "LVaR must exceed market VaR"

    def test_lvar_geq_var(self) -> None:
        result = bdss_lvar(0.03, 50_000.0, SPREAD_NORMAL)
        assert result is not None
        assert result >= 0.03

    def test_larger_position_larger_lvar(self) -> None:
        lvar_small = bdss_lvar(0.05, 10_000.0, SPREAD_NORMAL)
        lvar_large = bdss_lvar(0.05, 100_000.0, SPREAD_NORMAL)
        assert lvar_small is not None and lvar_large is not None
        assert lvar_large > lvar_small, "Larger position → larger LVaR"

    def test_wider_spread_larger_lvar(self) -> None:
        lvar_tight = bdss_lvar(0.05, 50_000.0, SPREAD_NORMAL)
        lvar_wide = bdss_lvar(0.05, 50_000.0, SPREAD_WIDE)
        assert lvar_tight is not None and lvar_wide is not None
        assert lvar_wide > lvar_tight, "Wider spread → larger LVaR"

    def test_skip_short_spread_history(self) -> None:
        result = bdss_lvar(0.05, 100_000.0, SPREAD_SHORT)
        assert result is None

    def test_skip_empty_spread(self) -> None:
        result = bdss_lvar(0.05, 100_000.0, [])
        assert result is None

    def test_zero_notional(self) -> None:
        result = bdss_lvar(0.05, 0.0, SPREAD_NORMAL)
        assert result is not None
        assert result >= 0.05


# ═══════════════════════════════════════════════════════════════════════════════
# §2  Time-to-liquidate method
# ═══════════════════════════════════════════════════════════════════════════════


class TestTimeToLiquidate:
    """T_liq = qty / (participation_rate * ADV), scale VaR by sqrt(T_liq)."""

    def test_basic_computation(self) -> None:
        result = time_to_liquidate_lvar(0.05, 1000.0, 10_000.0, 0.10)
        assert result is not None
        assert result >= 0.05

    def test_larger_position_larger_lvar(self) -> None:
        lvar_small = time_to_liquidate_lvar(0.05, 100.0, 10_000.0, 0.10)
        lvar_large = time_to_liquidate_lvar(0.05, 5000.0, 10_000.0, 0.10)
        assert lvar_small is not None and lvar_large is not None
        assert lvar_large > lvar_small

    def test_lower_adv_larger_lvar(self) -> None:
        lvar_liquid = time_to_liquidate_lvar(0.05, 1000.0, 100_000.0, 0.10)
        lvar_illiquid = time_to_liquidate_lvar(0.05, 1000.0, 1_000.0, 0.10)
        assert lvar_liquid is not None and lvar_illiquid is not None
        assert lvar_illiquid > lvar_liquid

    def test_skip_zero_adv(self) -> None:
        assert time_to_liquidate_lvar(0.05, 1000.0, 0.0, 0.10) is None

    def test_skip_zero_participation(self) -> None:
        assert time_to_liquidate_lvar(0.05, 1000.0, 10_000.0, 0.0) is None


# ═══════════════════════════════════════════════════════════════════════════════
# §3  Unified compute_lvar — method selection and fallback
# ═══════════════════════════════════════════════════════════════════════════════


class TestComputeLvar:
    """Unified LVaR entry point: method dispatch, fallback, data_health."""

    def test_bdss_with_data(self) -> None:
        lvar, dh = compute_lvar(0.05, 100_000.0, SPREAD_NORMAL, method="bdss")
        assert lvar > 0.05
        assert dh == 1.0

    def test_bdss_no_data_fallback(self) -> None:
        lvar, dh = compute_lvar(0.05, 100_000.0, None, method="bdss")
        assert lvar == 0.05
        assert dh == 0.0

    def test_bdss_short_spread_fallback(self) -> None:
        lvar, dh = compute_lvar(0.05, 100_000.0, SPREAD_SHORT, method="bdss")
        assert lvar == 0.05
        assert dh == 0.0

    def test_ttl_with_data(self) -> None:
        lvar, dh = compute_lvar(
            0.05, 0.0, None,
            position_qty=1000.0, adv=10_000.0,
            method="time_to_liquidate",
        )
        assert lvar >= 0.05
        assert dh == 1.0

    def test_ttl_no_data_fallback(self) -> None:
        lvar, dh = compute_lvar(
            0.05, 0.0, None,
            position_qty=0.0, adv=0.0,
            method="time_to_liquidate",
        )
        assert lvar == 0.05
        assert dh == 0.0

    def test_max_of_both_with_both(self) -> None:
        lvar, dh = compute_lvar(
            0.05, 100_000.0, SPREAD_NORMAL,
            position_qty=1000.0, adv=10_000.0,
            method="max_of_both",
        )
        assert lvar > 0.05
        assert dh == 1.0

    def test_max_of_both_only_ttl(self) -> None:
        lvar, dh = compute_lvar(
            0.05, 0.0, None,
            position_qty=5000.0, adv=10_000.0,
            method="max_of_both",
        )
        assert lvar >= 0.05
        assert dh == 0.5

    def test_max_of_both_no_data(self) -> None:
        lvar, dh = compute_lvar(0.05, 0.0, None, method="max_of_both")
        assert lvar == 0.05
        assert dh == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# §4  RiskMetrics + RiskEngine integration
# ═══════════════════════════════════════════════════════════════════════════════


class TestRiskMetricsLVaR:
    """LVaR fields in RiskMetrics, populated by RiskEngine."""

    def test_lvar_default_zero(self) -> None:
        m = RiskMetrics()
        assert m.lvar == 0.0
        assert m.lvar_data_health == 0.0

    def test_engine_lvar_no_spread_data(self) -> None:
        m = RiskEngine().compute(RETURNS_500)
        assert m.lvar == m.var_95_1d
        assert m.lvar_data_health == 0.0

    def test_engine_lvar_with_spread_data(self) -> None:
        m = RiskEngine().compute(
            RETURNS_500,
            spread_history=SPREAD_NORMAL,
            position_notional=100_000.0,
        )
        assert m.lvar > m.var_95_1d
        assert m.lvar_data_health == 1.0

    def test_engine_lvar_increases_with_position(self) -> None:
        m_small = RiskEngine().compute(
            RETURNS_500,
            spread_history=SPREAD_NORMAL,
            position_notional=10_000.0,
        )
        m_large = RiskEngine().compute(
            RETURNS_500,
            spread_history=SPREAD_NORMAL,
            position_notional=500_000.0,
        )
        assert m_large.lvar > m_small.lvar


# ═══════════════════════════════════════════════════════════════════════════════
# §5  Config validation
# ═══════════════════════════════════════════════════════════════════════════════


class TestLVaRConfig:
    """RiskConfig LVaR fields and validation."""

    def test_default_config(self) -> None:
        cfg = RiskConfig()
        assert cfg.lvar_method == "bdss"
        assert cfg.lvar_participation_rate == 0.10
        assert cfg.is_valid

    def test_invalid_method(self) -> None:
        cfg = RiskConfig(lvar_method="invalid")
        issues = cfg.validate()
        assert any("lvar_method" in i for i in issues)

    def test_invalid_participation_rate(self) -> None:
        cfg = RiskConfig(lvar_participation_rate=0.0)
        issues = cfg.validate()
        assert any("lvar_participation_rate" in i for i in issues)

    def test_valid_methods(self) -> None:
        for m in ("bdss", "time_to_liquidate", "max_of_both"):
            cfg = RiskConfig(lvar_method=m)
            assert cfg.is_valid, f"method={m} should be valid"


# ═══════════════════════════════════════════════════════════════════════════════
# §6  var_topology — LVaR detected as present
# ═══════════════════════════════════════════════════════════════════════════════


class TestVarTopologyLVaR:
    """var_topology should detect liquidity_adjusted_var as present."""

    def test_topology_detects_lvar(self) -> None:
        from super_otonom.var_topology import inspect_var_topology

        t = inspect_var_topology()
        assert t.liquidity_adjusted_var_present is True

    def test_disclosure_no_lvar_limitation(self) -> None:
        from super_otonom.var_topology import var_disclosure

        d = var_disclosure()
        assert "no_liquidity_adjusted_var" not in d["limitations"]

    def test_topology_contract_clean(self) -> None:
        from super_otonom.var_topology import validate_var_topology_contract

        issues = validate_var_topology_contract()
        assert issues == [], f"Contract violations: {issues}"


# ═══════════════════════════════════════════════════════════════════════════════
# §7  Prometheus metric exists
# ═══════════════════════════════════════════════════════════════════════════════


class TestPrometheusLVaR:
    """Prometheus gauge bot_var_liquidity_adjusted{symbol=...} registered."""

    def test_gauge_registered(self) -> None:
        from super_otonom.metrics_exporter import MetricsExporter

        m = MetricsExporter(port=0)
        assert "var_liquidity_adjusted" in m._gauges

    def test_record_lvar(self) -> None:
        from super_otonom.metrics_exporter import MetricsExporter

        m = MetricsExporter(port=0)
        m.record_lvar("BTC/USDT", 0.065)
