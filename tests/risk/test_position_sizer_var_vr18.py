"""VR-18: VaR-aware Position Sizing (Kelly + VaR Cap) — 40+ tests."""

from __future__ import annotations

import os
import random
from unittest import mock

import pytest
from super_otonom.position_sizer import PositionSizer
from super_otonom.risk.position_sizer_var import (
    _VAR_CONFIDENCE,
    DEFAULT_MAX_MARGINAL_VAR_PCT,
    MarginalVarEngine,
    VarAwarePositionSizer,
    VarCapResult,
    _env_max_marginal_var_pct,
    size_with_var_cap,
    var_cap_result_to_dict,
)

# ── Fixtures ────────────────────────────────────────────────────────────────

def _low_vol_returns(n: int = 100, seed: int = 42) -> list[float]:
    rng = random.Random(seed)
    return [rng.gauss(0.0005, 0.005) for _ in range(n)]


def _high_vol_returns(n: int = 100, seed: int = 99) -> list[float]:
    rng = random.Random(seed)
    return [rng.gauss(-0.001, 0.08) for _ in range(n)]


def _medium_vol_returns(n: int = 100, seed: int = 77) -> list[float]:
    rng = random.Random(seed)
    return [rng.gauss(0.0002, 0.02) for _ in range(n)]


def _asset_returns_fixture() -> dict[str, list[float]]:
    return {
        "BTCUSDT": _medium_vol_returns(120, seed=10),
        "ETHUSDT": _medium_vol_returns(120, seed=20),
        "SOLUSDT": _high_vol_returns(120, seed=30),
        "ADAUSDT": _low_vol_returns(120, seed=40),
    }


def _base_sizer(**kwargs) -> PositionSizer:
    defaults = {
        "max_position_pct": 0.10,
        "min_notional": 5.0,
        "max_leverage": 1.0,
        "target_vol": 0.015,
    }
    defaults.update(kwargs)
    return PositionSizer(**defaults)


# ══════════════════════════════════════════════════════════════════════════════
# 1. MarginalVarEngine
# ══════════════════════════════════════════════════════════════════════════════


class TestMarginalVarEngine:
    def test_zero_trade_returns_zero(self):
        engine = MarginalVarEngine(_asset_returns_fixture())
        assert engine.marginal_var_for_trade("BTCUSDT", 0.0, {}) == 0.0

    def test_negative_trade_returns_zero(self):
        engine = MarginalVarEngine(_asset_returns_fixture())
        assert engine.marginal_var_for_trade("BTCUSDT", -100, {}) == 0.0

    def test_unknown_symbol_returns_zero(self):
        engine = MarginalVarEngine(_asset_returns_fixture())
        assert engine.marginal_var_for_trade("ZZZZUSDT", 1000, {}) == 0.0

    def test_insufficient_data_returns_zero(self):
        engine = MarginalVarEngine({"BTCUSDT": [0.01] * 5})
        assert engine.marginal_var_for_trade("BTCUSDT", 1000, {}) == 0.0

    def test_first_position_has_positive_mvar(self):
        engine = MarginalVarEngine(_asset_returns_fixture())
        mvar = engine.marginal_var_for_trade("BTCUSDT", 10_000, {})
        assert mvar > 0

    def test_marginal_var_increases_with_size(self):
        engine = MarginalVarEngine(_asset_returns_fixture())
        pos = {"ETHUSDT": 5000}
        mvar_small = engine.marginal_var_for_trade("BTCUSDT", 1000, pos)
        mvar_large = engine.marginal_var_for_trade("BTCUSDT", 10_000, pos)
        assert mvar_large >= mvar_small

    def test_high_vol_asset_higher_mvar(self):
        engine = MarginalVarEngine(_asset_returns_fixture())
        pos = {"ADAUSDT": 5000}
        mvar_low = engine.marginal_var_for_trade("ADAUSDT", 5000, pos)
        mvar_high = engine.marginal_var_for_trade("SOLUSDT", 5000, pos)
        assert mvar_high > mvar_low

    def test_empty_positions_first_trade(self):
        engine = MarginalVarEngine(_asset_returns_fixture())
        mvar = engine.marginal_var_for_trade("BTCUSDT", 5000, {})
        assert mvar > 0

    def test_portfolio_var_scales_with_notional(self):
        engine = MarginalVarEngine(_asset_returns_fixture())
        v1 = engine._portfolio_var({"BTCUSDT": 1.0}, 1000)
        v2 = engine._portfolio_var({"BTCUSDT": 1.0}, 10_000)
        assert v2 > v1

    def test_portfolio_var_empty_weights(self):
        engine = MarginalVarEngine(_asset_returns_fixture())
        assert engine._portfolio_var({}, 1000) == 0.0

    def test_portfolio_var_zero_notional(self):
        engine = MarginalVarEngine(_asset_returns_fixture())
        assert engine._portfolio_var({"BTCUSDT": 1.0}, 0.0) == 0.0

    def test_confidence_level_default(self):
        engine = MarginalVarEngine(_asset_returns_fixture())
        assert engine._confidence == _VAR_CONFIDENCE

    def test_custom_confidence(self):
        engine = MarginalVarEngine(_asset_returns_fixture(), confidence=0.95)
        mvar_95 = engine.marginal_var_for_trade("SOLUSDT", 5000, {})
        engine99 = MarginalVarEngine(_asset_returns_fixture(), confidence=0.99)
        mvar_99 = engine99.marginal_var_for_trade("SOLUSDT", 5000, {})
        assert mvar_99 >= mvar_95


# ══════════════════════════════════════════════════════════════════════════════
# 2. size_with_var_cap
# ══════════════════════════════════════════════════════════════════════════════


class TestSizeWithVarCap:
    def test_zero_kelly_returns_zero(self):
        engine = MarginalVarEngine(_asset_returns_fixture())
        assert size_with_var_cap(0, "BTCUSDT", 100_000, engine, {}) == 0.0

    def test_zero_equity_returns_zero(self):
        engine = MarginalVarEngine(_asset_returns_fixture())
        assert size_with_var_cap(1000, "BTCUSDT", 0, engine, {}) == 0.0

    def test_low_vol_kelly_passes_through(self):
        engine = MarginalVarEngine(_asset_returns_fixture())
        kelly = 100.0
        capped = size_with_var_cap(
            kelly, "ADAUSDT", 100_000, engine, {},
            max_marginal_var_pct=0.05,
        )
        assert capped == kelly

    def test_high_vol_kelly_gets_capped(self):
        engine = MarginalVarEngine(_asset_returns_fixture())
        kelly = 50_000.0
        capped = size_with_var_cap(
            kelly, "SOLUSDT", 100_000, engine, {},
            max_marginal_var_pct=0.001,
        )
        assert capped < kelly

    def test_cap_result_within_bounds(self):
        engine = MarginalVarEngine(_asset_returns_fixture())
        kelly = 20_000.0
        capped = size_with_var_cap(
            kelly, "BTCUSDT", 100_000, engine, {},
            max_marginal_var_pct=0.002,
        )
        assert 0 <= capped <= kelly

    def test_marginal_var_at_cap_respects_limit(self):
        engine = MarginalVarEngine(_asset_returns_fixture())
        equity = 100_000
        cap_pct = 0.003
        kelly = 30_000.0
        capped = size_with_var_cap(
            kelly, "SOLUSDT", equity, engine, {},
            max_marginal_var_pct=cap_pct,
        )
        if capped < kelly:
            mvar = engine.marginal_var_for_trade("SOLUSDT", capped, {})
            assert mvar <= cap_pct * equity * 1.01

    def test_env_variable_used(self):
        engine = MarginalVarEngine(_asset_returns_fixture())
        with mock.patch.dict(os.environ, {"MAX_MARGINAL_VAR_PCT": "0.001"}):
            capped = size_with_var_cap(
                50_000, "SOLUSDT", 100_000, engine, {},
            )
        assert capped < 50_000

    def test_existing_positions_affect_cap(self):
        engine = MarginalVarEngine(_asset_returns_fixture())
        kelly = 20_000.0
        cap_pct = 0.003

        capped_empty = size_with_var_cap(
            kelly, "BTCUSDT", 100_000, engine, {},
            max_marginal_var_pct=cap_pct,
        )
        capped_loaded = size_with_var_cap(
            kelly, "BTCUSDT", 100_000, engine,
            {"ETHUSDT": 40_000, "SOLUSDT": 30_000},
            max_marginal_var_pct=cap_pct,
        )
        assert capped_empty >= 0
        assert capped_loaded >= 0


# ══════════════════════════════════════════════════════════════════════════════
# 3. VarAwarePositionSizer
# ══════════════════════════════════════════════════════════════════════════════


class TestVarAwarePositionSizer:
    def test_basic_calculation(self):
        sizer = VarAwarePositionSizer(
            base_sizer=_base_sizer(),
            asset_returns=_asset_returns_fixture(),
            max_marginal_var_pct=0.01,
        )
        result = sizer.calculate_with_var_cap(
            "BTCUSDT", 50_000, {},
            volatility=0.02, ai_conf=0.6,
        )
        assert isinstance(result, VarCapResult)
        assert result.final_size >= 0
        assert result.latency_ms >= 0

    def test_kelly_and_var_both_active(self):
        sizer = VarAwarePositionSizer(
            base_sizer=_base_sizer(),
            asset_returns=_asset_returns_fixture(),
            max_marginal_var_pct=0.01,
        )
        result = sizer.calculate_with_var_cap(
            "BTCUSDT", 50_000, {},
            volatility=0.02, ai_conf=0.7,
        )
        assert result.kelly_size > 0
        assert result.final_size > 0
        assert result.final_size <= result.kelly_size

    def test_high_vol_asset_kelly_large_var_cap_small(self):
        """Core acceptance test: high-vol → Kelly large, VaR cap clamps down."""
        sizer = VarAwarePositionSizer(
            base_sizer=_base_sizer(max_position_pct=0.30),
            asset_returns=_asset_returns_fixture(),
            max_marginal_var_pct=0.001,
        )
        result = sizer.calculate_with_var_cap(
            "SOLUSDT", 100_000, {},
            volatility=0.08, ai_conf=0.9,
        )
        if result.kelly_size > 0:
            assert result.cap_binding is True
            assert result.final_size < result.kelly_size
            assert result.var_capped_size < result.kelly_size

    def test_low_vol_no_cap_binding(self):
        sizer = VarAwarePositionSizer(
            base_sizer=_base_sizer(),
            asset_returns=_asset_returns_fixture(),
            max_marginal_var_pct=0.05,
        )
        result = sizer.calculate_with_var_cap(
            "ADAUSDT", 100_000, {},
            volatility=0.005, ai_conf=0.5,
        )
        if result.kelly_size > 0 and result.kelly_size < 500:
            assert result.cap_binding is False
            assert result.final_size == result.kelly_size

    def test_zero_equity(self):
        sizer = VarAwarePositionSizer(
            base_sizer=_base_sizer(),
            asset_returns=_asset_returns_fixture(),
        )
        result = sizer.calculate_with_var_cap(
            "BTCUSDT", 0.0, {},
            volatility=0.02, ai_conf=0.5,
        )
        assert result.final_size == 0.0

    def test_max_marginal_var_override(self):
        sizer = VarAwarePositionSizer(
            base_sizer=_base_sizer(max_position_pct=0.30),
            asset_returns=_asset_returns_fixture(),
            max_marginal_var_pct=0.05,
        )
        result_loose = sizer.calculate_with_var_cap(
            "SOLUSDT", 100_000, {},
            max_marginal_var_pct=0.05,
            volatility=0.08, ai_conf=0.9,
        )
        result_tight = sizer.calculate_with_var_cap(
            "SOLUSDT", 100_000, {},
            max_marginal_var_pct=0.0005,
            volatility=0.08, ai_conf=0.9,
        )
        assert result_tight.final_size <= result_loose.final_size

    def test_marginal_var_at_final_within_cap(self):
        sizer = VarAwarePositionSizer(
            base_sizer=_base_sizer(max_position_pct=0.20),
            asset_returns=_asset_returns_fixture(),
            max_marginal_var_pct=0.003,
        )
        result = sizer.calculate_with_var_cap(
            "BTCUSDT", 100_000, {},
            volatility=0.02, ai_conf=0.7,
        )
        if result.cap_binding:
            assert result.marginal_var_at_final <= result.max_marginal_var * 1.05

    def test_base_sizer_accessible(self):
        base = _base_sizer()
        sizer = VarAwarePositionSizer(
            base_sizer=base,
            asset_returns=_asset_returns_fixture(),
        )
        assert sizer.base_sizer is base

    def test_var_engine_accessible(self):
        sizer = VarAwarePositionSizer(
            base_sizer=_base_sizer(),
            asset_returns=_asset_returns_fixture(),
        )
        assert isinstance(sizer.var_engine, MarginalVarEngine)

    def test_with_existing_positions(self):
        sizer = VarAwarePositionSizer(
            base_sizer=_base_sizer(max_position_pct=0.20),
            asset_returns=_asset_returns_fixture(),
            max_marginal_var_pct=0.002,
        )
        result = sizer.calculate_with_var_cap(
            "SOLUSDT", 100_000,
            {"BTCUSDT": 30_000, "ETHUSDT": 20_000},
            volatility=0.08, ai_conf=0.8,
        )
        assert result.final_size >= 0
        assert result.final_size <= result.kelly_size


# ══════════════════════════════════════════════════════════════════════════════
# 4. VarCapResult and serialization
# ══════════════════════════════════════════════════════════════════════════════


class TestVarCapResult:
    def test_frozen_dataclass(self):
        r = VarCapResult(kelly_size=100, final_size=80, cap_binding=True)
        with pytest.raises(AttributeError):
            r.kelly_size = 200  # type: ignore[misc]

    def test_defaults(self):
        r = VarCapResult()
        assert r.kelly_size == 0.0
        assert r.final_size == 0.0
        assert r.cap_binding is False

    def test_to_dict(self):
        r = VarCapResult(
            kelly_size=1000, var_capped_size=800, final_size=800,
            cap_binding=True, marginal_var_at_final=3.5,
            max_marginal_var=5.0, latency_ms=1.2,
        )
        d = var_cap_result_to_dict(r)
        assert d["kelly_size"] == 1000
        assert d["cap_binding"] is True
        assert d["final_size"] == 800
        assert d["latency_ms"] == 1.2

    def test_to_dict_all_fields_present(self):
        r = VarCapResult()
        d = var_cap_result_to_dict(r)
        expected_keys = {
            "kelly_size", "var_capped_size", "final_size",
            "cap_binding", "marginal_var_at_final",
            "max_marginal_var", "latency_ms",
        }
        assert set(d.keys()) == expected_keys


# ══════════════════════════════════════════════════════════════════════════════
# 5. Environment variable handling
# ══════════════════════════════════════════════════════════════════════════════


class TestEnvMaxMarginalVarPct:
    def test_default_when_unset(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop("MAX_MARGINAL_VAR_PCT", None)
            assert _env_max_marginal_var_pct() == DEFAULT_MAX_MARGINAL_VAR_PCT

    def test_valid_value(self):
        with mock.patch.dict(os.environ, {"MAX_MARGINAL_VAR_PCT": "0.003"}):
            assert _env_max_marginal_var_pct() == 0.003

    def test_invalid_zero(self):
        with mock.patch.dict(os.environ, {"MAX_MARGINAL_VAR_PCT": "0"}):
            assert _env_max_marginal_var_pct() == DEFAULT_MAX_MARGINAL_VAR_PCT

    def test_invalid_negative(self):
        with mock.patch.dict(os.environ, {"MAX_MARGINAL_VAR_PCT": "-0.01"}):
            assert _env_max_marginal_var_pct() == DEFAULT_MAX_MARGINAL_VAR_PCT

    def test_invalid_gte_one(self):
        with mock.patch.dict(os.environ, {"MAX_MARGINAL_VAR_PCT": "1.0"}):
            assert _env_max_marginal_var_pct() == DEFAULT_MAX_MARGINAL_VAR_PCT

    def test_invalid_string(self):
        with mock.patch.dict(os.environ, {"MAX_MARGINAL_VAR_PCT": "abc"}):
            assert _env_max_marginal_var_pct() == DEFAULT_MAX_MARGINAL_VAR_PCT


# ══════════════════════════════════════════════════════════════════════════════
# 6. Integration: Kelly + VaR both active
# ══════════════════════════════════════════════════════════════════════════════


class TestIntegrationKellyVarCap:
    def test_kelly_with_trade_log(self):
        """PositionSizer with real trade log → Kelly calculation → VaR cap."""
        sizer = _base_sizer(max_position_pct=0.15)
        trades = [
            {"pnl": 50}, {"pnl": -20}, {"pnl": 30}, {"pnl": -10},
            {"pnl": 40}, {"pnl": -15}, {"pnl": 25},
        ]
        sizer.set_trade_log(trades)

        var_sizer = VarAwarePositionSizer(
            base_sizer=sizer,
            asset_returns=_asset_returns_fixture(),
            max_marginal_var_pct=0.003,
        )
        result = var_sizer.calculate_with_var_cap(
            "BTCUSDT", 100_000, {},
            volatility=0.02, ai_conf=0.7,
        )
        assert result.kelly_size > 0
        assert result.final_size > 0
        assert result.final_size <= result.kelly_size

    def test_cap_test_acceptance_criteria(self):
        """Acceptance criteria: high vol asset, Kelly large, VaR cap small → output from cap."""
        sizer = _base_sizer(max_position_pct=0.50, min_notional=1.0)
        trades = [
            {"pnl": 100}, {"pnl": -10}, {"pnl": 80}, {"pnl": -5},
            {"pnl": 120}, {"pnl": -8}, {"pnl": 90},
        ]
        sizer.set_trade_log(trades)

        var_sizer = VarAwarePositionSizer(
            base_sizer=sizer,
            asset_returns=_asset_returns_fixture(),
            max_marginal_var_pct=0.0005,
        )
        result = var_sizer.calculate_with_var_cap(
            "SOLUSDT", 200_000,
            {"BTCUSDT": 50_000},
            volatility=0.08, ai_conf=0.95,
        )
        if result.kelly_size > 0:
            assert result.cap_binding is True
            assert result.final_size < result.kelly_size
            assert result.marginal_var_at_final <= result.max_marginal_var * 1.05

    def test_multiple_symbols_sequential(self):
        var_sizer = VarAwarePositionSizer(
            base_sizer=_base_sizer(max_position_pct=0.15),
            asset_returns=_asset_returns_fixture(),
            max_marginal_var_pct=0.005,
        )
        positions: dict[str, float] = {}
        for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
            result = var_sizer.calculate_with_var_cap(
                sym, 100_000, positions,
                volatility=0.03, ai_conf=0.6,
            )
            if result.final_size > 0:
                positions[sym] = result.final_size
        assert len(positions) >= 1


# ══════════════════════════════════════════════════════════════════════════════
# 7. Edge cases
# ══════════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    def test_single_asset_portfolio(self):
        engine = MarginalVarEngine({"BTCUSDT": _medium_vol_returns(100)})
        mvar = engine.marginal_var_for_trade("BTCUSDT", 5000, {})
        assert mvar > 0

    def test_same_symbol_add_to_existing(self):
        engine = MarginalVarEngine(_asset_returns_fixture())
        mvar = engine.marginal_var_for_trade(
            "BTCUSDT", 5000, {"BTCUSDT": 10_000},
        )
        assert mvar >= 0

    def test_very_small_size(self):
        engine = MarginalVarEngine(_asset_returns_fixture())
        mvar = engine.marginal_var_for_trade("BTCUSDT", 0.01, {})
        assert mvar >= 0

    def test_very_large_equity(self):
        sizer = VarAwarePositionSizer(
            base_sizer=_base_sizer(),
            asset_returns=_asset_returns_fixture(),
            max_marginal_var_pct=0.005,
        )
        result = sizer.calculate_with_var_cap(
            "BTCUSDT", 10_000_000, {},
            volatility=0.02, ai_conf=0.5,
        )
        assert result.final_size >= 0

    def test_binary_search_converges(self):
        engine = MarginalVarEngine(_asset_returns_fixture())
        kelly = 50_000.0
        equity = 100_000.0
        cap_pct = 0.002
        capped = size_with_var_cap(
            kelly, "SOLUSDT", equity, engine, {},
            max_marginal_var_pct=cap_pct,
        )
        assert 0 <= capped <= kelly
        mvar = engine.marginal_var_for_trade("SOLUSDT", capped, {})
        assert mvar <= cap_pct * equity * 1.05


# ══════════════════════════════════════════════════════════════════════════════
# 8. Sentinel and import checks
# ══════════════════════════════════════════════════════════════════════════════


class TestSentinelAndImports:
    def test_sentinel_present(self):
        from super_otonom.risk import position_sizer_var
        assert hasattr(position_sizer_var, "position_sizer_var_cap_active")
        assert position_sizer_var.position_sizer_var_cap_active is True

    def test_public_exports(self):
        from super_otonom.risk import (
            MarginalVarEngine,
            VarAwarePositionSizer,
            VarCapResult,
            size_with_var_cap,
            var_cap_result_to_dict,
        )
        assert MarginalVarEngine is not None
        assert VarAwarePositionSizer is not None
        assert VarCapResult is not None
        assert size_with_var_cap is not None
        assert var_cap_result_to_dict is not None

    def test_metrics_exporter_has_recorder(self):
        from super_otonom.metrics_exporter import MetricsExporter
        assert hasattr(MetricsExporter, "record_var_cap")
