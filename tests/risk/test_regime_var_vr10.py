"""VR-10 tests — Regime-conditional VaR."""

from __future__ import annotations

import numpy as np
from super_otonom.risk.config import RiskConfig
from super_otonom.risk.regime_var import (
    KNOWN_REGIMES,
    REGIME_VAR_DEFAULT_MAXLEN,
    RegimeConditionalVaR,
)
from super_otonom.risk.risk_engine import RiskEngine, RiskMetrics

# ── Fixtures ─────────────────────────────────────────────────────────────────

_RNG = np.random.default_rng(1010)

# Asymmetric mix: 80% calm (TRENDING) + 20% turbulent (CRASH_RISK).
# This mirrors real markets where crises are rarer but more extreme.
# The overall VaR is diluted by the calm majority, so
# regime_conditional_CRASH_RISK > overall_var holds.
_N_LOW = 800
_N_HIGH = 200
LOW_VOL_RETURNS = _RNG.normal(0.001, 0.008, size=_N_LOW).tolist()
HIGH_VOL_RETURNS = _RNG.normal(-0.005, 0.12, size=_N_HIGH).tolist()
MIXED_RETURNS = LOW_VOL_RETURNS + HIGH_VOL_RETURNS

LOW_VOL_REGIMES = ["TRENDING"] * _N_LOW
HIGH_VOL_REGIMES = ["CRASH_RISK"] * _N_HIGH
MIXED_REGIMES = LOW_VOL_REGIMES + HIGH_VOL_REGIMES


def _make_rcv(
    low_n: int = _N_LOW,
    high_n: int = _N_HIGH,
) -> RegimeConditionalVaR:
    """Build a pre-loaded RegimeConditionalVaR with two regimes."""
    rcv = RegimeConditionalVaR()
    for r in LOW_VOL_RETURNS[:low_n]:
        rcv.record(r, "TRENDING")
    for r in HIGH_VOL_RETURNS[:high_n]:
        rcv.record(r, "CRASH_RISK")
    return rcv


# ═══════════════════════════════════════════════════════════════════════════════
# §1  RegimeConditionalVaR class — recording & state
# ═══════════════════════════════════════════════════════════════════════════════


class TestRecording:
    """Accumulate returns by regime."""

    def test_record_single(self) -> None:
        rcv = RegimeConditionalVaR()
        rcv.record(0.01, "TRENDING")
        assert rcv.regime_count("TRENDING") == 1
        assert rcv.returns_for("TRENDING") == [0.01]

    def test_record_multiple_regimes(self) -> None:
        rcv = _make_rcv()
        assert set(rcv.regimes) == {"TRENDING", "CRASH_RISK"}
        assert rcv.regime_count("TRENDING") == _N_LOW
        assert rcv.regime_count("CRASH_RISK") == _N_HIGH

    def test_bulk_load(self) -> None:
        rcv = RegimeConditionalVaR()
        rcv.bulk_load(MIXED_RETURNS, MIXED_REGIMES)
        assert rcv.regime_count("TRENDING") == _N_LOW
        assert rcv.regime_count("CRASH_RISK") == _N_HIGH

    def test_bulk_load_mismatch_raises(self) -> None:
        rcv = RegimeConditionalVaR()
        try:
            rcv.bulk_load([0.01, 0.02], ["TRENDING"])
            assert False, "should raise ValueError"
        except ValueError:
            pass

    def test_maxlen_enforced(self) -> None:
        rcv = RegimeConditionalVaR(maxlen=50)
        for i in range(100):
            rcv.record(float(i), "TRENDING")
        assert rcv.regime_count("TRENDING") == 50

    def test_reset(self) -> None:
        rcv = _make_rcv()
        rcv.reset()
        assert rcv.regimes == []

    def test_reset_regime(self) -> None:
        rcv = _make_rcv()
        rcv.reset_regime("TRENDING")
        assert "TRENDING" not in rcv.regimes
        assert rcv.regime_count("CRASH_RISK") == _N_HIGH

    def test_empty_regime_returns_empty(self) -> None:
        rcv = RegimeConditionalVaR()
        assert rcv.returns_for("UNKNOWN") == []
        assert rcv.regime_count("UNKNOWN") == 0

    def test_default_maxlen(self) -> None:
        assert REGIME_VAR_DEFAULT_MAXLEN == 2000

    def test_known_regimes(self) -> None:
        assert "TRENDING" in KNOWN_REGIMES
        assert "RANGING" in KNOWN_REGIMES
        assert "CRASH_RISK" in KNOWN_REGIMES


# ═══════════════════════════════════════════════════════════════════════════════
# §2  var_for_current — regime-filtered VaR computation
# ═══════════════════════════════════════════════════════════════════════════════


class TestVarForCurrent:
    """Compute VaR suite from regime-filtered returns."""

    def test_returns_risk_metrics(self) -> None:
        rcv = _make_rcv()
        m = rcv.var_for_current("TRENDING")
        assert isinstance(m, RiskMetrics)
        assert m.var_95_1d > 0

    def test_crash_risk_higher_var_than_trending(self) -> None:
        """HIGH_VOL regime produces larger VaR than LOW_VOL — core invariant."""
        rcv = _make_rcv()
        m_trend = rcv.var_for_current("TRENDING")
        m_crash = rcv.var_for_current("CRASH_RISK")
        assert m_trend is not None and m_crash is not None
        assert m_crash.var_for_limits_95 > m_trend.var_for_limits_95, (
            f"CRASH_RISK VaR ({m_crash.var_for_limits_95:.4f}) must exceed "
            f"TRENDING VaR ({m_trend.var_for_limits_95:.4f})"
        )

    def test_crash_risk_higher_var_99(self) -> None:
        rcv = _make_rcv()
        m_trend = rcv.var_for_current("TRENDING")
        m_crash = rcv.var_for_current("CRASH_RISK")
        assert m_trend is not None and m_crash is not None
        assert m_crash.var_for_limits_99 > m_trend.var_for_limits_99

    def test_fallback_none_insufficient_data(self) -> None:
        rcv = RegimeConditionalVaR()
        for r in LOW_VOL_RETURNS[:50]:
            rcv.record(r, "TRENDING")
        result = rcv.var_for_current("TRENDING")
        assert result is None, "< min_obs should return None"

    def test_fallback_none_unknown_regime(self) -> None:
        rcv = _make_rcv()
        result = rcv.var_for_current("UNKNOWN_REGIME")
        assert result is None

    def test_custom_config_min_obs(self) -> None:
        rcv = RegimeConditionalVaR()
        for r in LOW_VOL_RETURNS[:30]:
            rcv.record(r, "TRENDING")
        cfg = RiskConfig(var_history_min_obs=20)
        m = rcv.var_for_current("TRENDING", config=cfg)
        assert m is not None
        assert m.var_95_1d > 0

    def test_full_var_suite_populated(self) -> None:
        rcv = _make_rcv()
        m = rcv.var_for_current("CRASH_RISK")
        assert m is not None
        assert m.var_historical_95 > 0
        assert m.var_parametric_95 > 0
        assert m.var_monte_carlo_95 > 0
        assert m.cvar_95_1d > 0


# ═══════════════════════════════════════════════════════════════════════════════
# §3  Core test: regime_conditional_HIGH_VOL > overall_var
# ═══════════════════════════════════════════════════════════════════════════════


class TestRegimeVsOverall:
    """Regime-conditional VaR from HIGH_VOL exceeds overall (mixed) VaR."""

    def test_crash_regime_var_exceeds_overall(self) -> None:
        """Acceptance criterion: regime_conditional_HIGH_VOL > overall_var."""
        overall_m = RiskEngine().compute(MIXED_RETURNS)
        overall_var = overall_m.var_for_limits_95

        rcv = _make_rcv()
        regime_m = rcv.var_for_current("CRASH_RISK")
        assert regime_m is not None
        regime_var = regime_m.var_for_limits_95

        assert regime_var > overall_var, (
            f"regime CRASH_RISK VaR ({regime_var:.4f}) must exceed "
            f"overall VaR ({overall_var:.4f})"
        )

    def test_crash_regime_var99_exceeds_trending(self) -> None:
        """At 99% confidence, CRASH_RISK regime VaR dominates TRENDING."""
        rcv = _make_rcv()
        m_trend = rcv.var_for_current("TRENDING")
        m_crash = rcv.var_for_current("CRASH_RISK")
        assert m_trend is not None and m_crash is not None
        assert m_crash.var_for_limits_99 > m_trend.var_for_limits_99

    def test_trending_regime_var_below_overall(self) -> None:
        """LOW_VOL regime produces lower VaR than overall mixed."""
        overall_m = RiskEngine().compute(MIXED_RETURNS)
        rcv = _make_rcv()
        regime_m = rcv.var_for_current("TRENDING")
        assert regime_m is not None
        assert regime_m.var_for_limits_95 < overall_m.var_for_limits_95


# ═══════════════════════════════════════════════════════════════════════════════
# §4  RiskEngine integration
# ═══════════════════════════════════════════════════════════════════════════════


class TestEngineIntegration:
    """RiskEngine.compute() with regime_var produces conservative limits."""

    def test_engine_regime_fields_populated(self) -> None:
        rcv = _make_rcv()
        m = RiskEngine().compute(
            MIXED_RETURNS,
            current_regime="CRASH_RISK",
            regime_var=rcv,
        )
        assert m.var_regime_conditional_95 is not None
        assert m.var_regime_conditional_99 is not None
        assert m.current_regime == "CRASH_RISK"

    def test_engine_limit_is_max_of_overall_and_regime(self) -> None:
        rcv = _make_rcv()
        overall = RiskEngine().compute(MIXED_RETURNS)
        with_regime = RiskEngine().compute(
            MIXED_RETURNS,
            current_regime="CRASH_RISK",
            regime_var=rcv,
        )
        assert with_regime.var_for_limits_95 >= overall.var_for_limits_95
        assert with_regime.var_for_limits_99 >= overall.var_for_limits_99

    def test_engine_crash_lifts_var(self) -> None:
        """CRASH_RISK regime should lift the overall limit."""
        rcv = _make_rcv()
        overall = RiskEngine().compute(MIXED_RETURNS)
        with_regime = RiskEngine().compute(
            MIXED_RETURNS,
            current_regime="CRASH_RISK",
            regime_var=rcv,
        )
        assert with_regime.var_for_limits_95 > overall.var_for_limits_95, (
            "CRASH_RISK regime should lift var_for_limits_95"
        )

    def test_engine_trending_does_not_lower_var(self) -> None:
        """TRENDING regime should not lower the limit (max rule)."""
        rcv = _make_rcv()
        overall = RiskEngine().compute(MIXED_RETURNS)
        with_regime = RiskEngine().compute(
            MIXED_RETURNS,
            current_regime="TRENDING",
            regime_var=rcv,
        )
        assert with_regime.var_for_limits_95 >= overall.var_for_limits_95

    def test_engine_fallback_insufficient_regime_data(self) -> None:
        """When regime has insufficient data, fields are None, limit unchanged."""
        rcv = RegimeConditionalVaR()
        for r in LOW_VOL_RETURNS[:10]:
            rcv.record(r, "TRENDING")
        m = RiskEngine().compute(
            MIXED_RETURNS,
            current_regime="TRENDING",
            regime_var=rcv,
        )
        assert m.var_regime_conditional_95 is None
        assert m.current_regime is None

    def test_engine_no_regime_args_backward_compat(self) -> None:
        """Without regime kwargs, engine works as before."""
        m = RiskEngine().compute(MIXED_RETURNS)
        assert m.var_regime_conditional_95 is None
        assert m.var_regime_conditional_99 is None
        assert m.current_regime is None
        assert m.var_95_1d > 0

    def test_engine_regime_var_none_no_crash(self) -> None:
        """current_regime without regime_var → no crash, no regime VaR."""
        m = RiskEngine().compute(MIXED_RETURNS, current_regime="CRASH_RISK")
        assert m.var_regime_conditional_95 is None

    def test_engine_lvar_uses_conservative_var(self) -> None:
        """LVaR should use the lifted var_market when regime VaR is higher."""
        rcv = _make_rcv()
        spreads = _RNG.lognormal(-7, 0.3, size=200).tolist()
        overall = RiskEngine().compute(
            MIXED_RETURNS,
            spread_history=spreads,
            position_notional=100_000.0,
        )
        with_regime = RiskEngine().compute(
            MIXED_RETURNS,
            current_regime="CRASH_RISK",
            regime_var=rcv,
            spread_history=spreads,
            position_notional=100_000.0,
        )
        assert with_regime.lvar >= overall.lvar


# ═══════════════════════════════════════════════════════════════════════════════
# §5  Edge cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Boundary conditions and graceful degradation."""

    def test_single_regime_all_data(self) -> None:
        rcv = RegimeConditionalVaR()
        rcv.bulk_load(LOW_VOL_RETURNS, ["TRENDING"] * len(LOW_VOL_RETURNS))
        m = rcv.var_for_current("TRENDING")
        assert m is not None

    def test_empty_rcv_returns_none(self) -> None:
        rcv = RegimeConditionalVaR()
        assert rcv.var_for_current("TRENDING") is None

    def test_ranging_regime(self) -> None:
        rcv = RegimeConditionalVaR()
        ranging = _RNG.normal(0.0, 0.015, size=150).tolist()
        rcv.bulk_load(ranging, ["RANGING"] * 150)
        m = rcv.var_for_current("RANGING")
        assert m is not None
        assert m.var_95_1d > 0

    def test_three_regimes(self) -> None:
        rcv = RegimeConditionalVaR()
        for r in LOW_VOL_RETURNS[:150]:
            rcv.record(r, "TRENDING")
        for r in HIGH_VOL_RETURNS[:150]:
            rcv.record(r, "CRASH_RISK")
        ranging = _RNG.normal(0.0, 0.015, size=150).tolist()
        for r in ranging:
            rcv.record(r, "RANGING")
        assert len(rcv.regimes) == 3
        m_t = rcv.var_for_current("TRENDING")
        m_c = rcv.var_for_current("CRASH_RISK")
        m_r = rcv.var_for_current("RANGING")
        assert m_t is not None and m_c is not None and m_r is not None
        assert m_c.var_for_limits_95 > m_r.var_for_limits_95

    def test_regime_at_exact_min_obs(self) -> None:
        rcv = RegimeConditionalVaR()
        cfg = RiskConfig(var_history_min_obs=100)
        data = _RNG.normal(0.0, 0.02, size=100).tolist()
        rcv.bulk_load(data, ["TRENDING"] * 100)
        m = rcv.var_for_current("TRENDING", config=cfg)
        assert m is not None

    def test_regime_one_below_min_obs(self) -> None:
        rcv = RegimeConditionalVaR()
        cfg = RiskConfig(var_history_min_obs=100)
        data = _RNG.normal(0.0, 0.02, size=99).tolist()
        rcv.bulk_load(data, ["TRENDING"] * 99)
        m = rcv.var_for_current("TRENDING", config=cfg)
        assert m is None


# ═══════════════════════════════════════════════════════════════════════════════
# §6  Topology & manifest
# ═══════════════════════════════════════════════════════════════════════════════


class TestTopology:
    """var_topology detects regime_conditional_var in risk package."""

    def test_regime_conditional_var_present(self) -> None:
        from super_otonom.var_topology import inspect_var_topology

        topo = inspect_var_topology()
        assert topo.regime_conditional_var_present is True

    def test_manifest_payload_has_flag(self) -> None:
        from super_otonom.var_topology import build_manifest_payload, inspect_var_topology

        topo = inspect_var_topology()
        payload = build_manifest_payload(topo)
        assert payload["regime_conditional_var_present"] is True

    def test_disclosure_no_regime_limitation_removed(self) -> None:
        from super_otonom.var_topology import var_disclosure

        disc = var_disclosure()
        assert "no_regime_conditional_var" not in disc["limitations"]


# ═══════════════════════════════════════════════════════════════════════════════
# §7  Public API
# ═══════════════════════════════════════════════════════════════════════════════


class TestPublicAPI:
    """Verify exports from the risk package."""

    def test_import_from_package(self) -> None:
        from super_otonom.risk import RegimeConditionalVaR as RCV  # noqa: F401

    def test_import_from_module(self) -> None:
        from super_otonom.risk.regime_var import (  # noqa: F401
            KNOWN_REGIMES,
            REGIME_VAR_DEFAULT_MAXLEN,
            RegimeConditionalVaR,
        )

    def test_risk_metrics_has_regime_fields(self) -> None:
        m = RiskMetrics()
        assert m.var_regime_conditional_95 is None
        assert m.var_regime_conditional_99 is None
        assert m.current_regime is None
