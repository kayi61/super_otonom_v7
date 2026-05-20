"""Tests for Pre-trade Marginal VaR Gate (VR-17).

Covers:
- pre_trade_var_check() — approval / rejection logic
- Total VaR limit breach → reject
- Marginal VaR limit breach → reject
- Small diversifying trade → accept
- High-vol concentrated position → reject
- simulate_trade_weights() — weight adjustment
- PreTradeVarLimits / PreTradeVarResult frozen dataclasses
- Latency target: <30ms
- Batch check with cumulative impact
- Edge cases: empty portfolio, insufficient data, invalid inputs
- Risk package exports
- Sentinel presence
"""

from __future__ import annotations

import time

import numpy as np
import pytest
from super_otonom.risk.pre_trade_var_gate import (
    GATE_DEFAULT_CONF,
    GATE_MIN_OBS,
    PreTradeVarLimits,
    PreTradeVarResult,
    gate_result_to_dict,
    pre_trade_var_check,
    pre_trade_var_check_batch,
    pre_trade_var_gate_active,
    simulate_trade_weights,
)

# ── Fixtures ────────────────────────────────────────────────────────────────

np.random.seed(42)


def _make_returns(
    n: int = 250,
    vol: float = 0.02,
    seed: int = 42,
) -> list[float]:
    """Generate synthetic return series with given volatility."""
    rng = np.random.RandomState(seed)
    return (rng.normal(0.0, vol, n)).tolist()


def _high_vol_returns(n: int = 250, seed: int = 99) -> list[float]:
    """Generate high-volatility return series (10% daily vol)."""
    rng = np.random.RandomState(seed)
    return (rng.normal(0.0, 0.10, n)).tolist()


def _low_vol_returns(n: int = 250, seed: int = 7) -> list[float]:
    """Generate low-volatility return series (0.5% daily vol)."""
    rng = np.random.RandomState(seed)
    return (rng.normal(0.0, 0.005, n)).tolist()


def _negatively_correlated_returns(
    base: list[float],
    noise: float = 0.002,
    seed: int = 123,
) -> list[float]:
    """Generate returns negatively correlated with base."""
    rng = np.random.RandomState(seed)
    return [
        -r + rng.normal(0, noise) for r in base
    ]


@pytest.fixture
def basic_portfolio():
    """Standard two-asset portfolio for testing."""
    btc = _make_returns(250, vol=0.03, seed=1)
    eth = _make_returns(250, vol=0.04, seed=2)
    return {
        "weights": {"BTC": 0.6, "ETH": 0.4},
        "returns": {"BTC": btc, "ETH": eth},
    }


@pytest.fixture
def tight_limits():
    """Tight VaR limits for testing rejections."""
    return PreTradeVarLimits(
        max_var_total_pct=0.03,
        max_marginal_var_per_trade_pct=0.01,
    )


@pytest.fixture
def loose_limits():
    """Loose VaR limits that should always pass."""
    return PreTradeVarLimits(
        max_var_total_pct=0.50,
        max_marginal_var_per_trade_pct=0.30,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: simulate_trade_weights
# ═══════════════════════════════════════════════════════════════════════════════


class TestSimulateTradeWeights:
    def test_buy_adds_weight(self):
        w = simulate_trade_weights({"BTC": 0.6}, "ETH", 0.2, "BUY")
        assert abs(w["BTC"] - 0.6) < 1e-10
        assert abs(w["ETH"] - 0.2) < 1e-10

    def test_buy_increases_existing(self):
        w = simulate_trade_weights({"BTC": 0.6}, "BTC", 0.1, "BUY")
        assert abs(w["BTC"] - 0.7) < 1e-10

    def test_sell_reduces_weight(self):
        w = simulate_trade_weights({"BTC": 0.6, "ETH": 0.4}, "ETH", 0.2, "SELL")
        assert abs(w["ETH"] - 0.2) < 1e-10
        assert abs(w["BTC"] - 0.6) < 1e-10

    def test_sell_removes_position(self):
        w = simulate_trade_weights({"BTC": 0.6, "ETH": 0.4}, "ETH", 0.4, "SELL")
        assert "ETH" not in w
        assert abs(w["BTC"] - 0.6) < 1e-10

    def test_empty_portfolio_buy(self):
        w = simulate_trade_weights({}, "BTC", 0.5, "BUY")
        assert abs(w["BTC"] - 0.5) < 1e-10

    def test_case_insensitive_side(self):
        w = simulate_trade_weights({"BTC": 0.5}, "ETH", 0.2, "buy")
        assert abs(w["ETH"] - 0.2) < 1e-10
        w2 = simulate_trade_weights({"BTC": 0.5, "ETH": 0.2}, "ETH", 0.1, "Sell")
        assert abs(w2["ETH"] - 0.1) < 1e-10


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Core gate — approval
# ═══════════════════════════════════════════════════════════════════════════════


class TestGateApproval:
    def test_small_trade_passes(self, basic_portfolio, loose_limits):
        """Small diversifying trade should always pass with loose limits."""
        r = pre_trade_var_check(
            symbol="BTC",
            trade_weight=0.01,
            side="BUY",
            current_weights=basic_portfolio["weights"],
            asset_returns=basic_portfolio["returns"],
            limits=loose_limits,
        )
        assert r.approved is True
        assert r.reason == ""
        assert r.new_var >= 0
        assert r.marginal_var is not None

    def test_diversifier_reduces_marginal_var(self, basic_portfolio):
        """Adding negatively correlated asset should reduce VaR → negative marginal."""
        # Create a hedging asset that's negatively correlated
        hedge = _negatively_correlated_returns(basic_portfolio["returns"]["BTC"])
        returns = dict(basic_portfolio["returns"])
        returns["HEDGE"] = hedge

        # Use limits that accommodate the existing portfolio VaR
        limits = PreTradeVarLimits(
            max_var_total_pct=0.15,
            max_marginal_var_per_trade_pct=0.05,
        )
        r = pre_trade_var_check(
            symbol="HEDGE",
            trade_weight=0.05,
            side="BUY",
            current_weights=basic_portfolio["weights"],
            asset_returns=returns,
            limits=limits,
        )
        # Diversifier should have negative marginal VaR (reduces risk)
        assert r.marginal_var < 0
        assert r.new_var < r.current_var
        assert r.approved is True

    def test_result_has_latency(self, basic_portfolio, loose_limits):
        r = pre_trade_var_check(
            symbol="BTC",
            trade_weight=0.01,
            side="BUY",
            current_weights=basic_portfolio["weights"],
            asset_returns=basic_portfolio["returns"],
            limits=loose_limits,
        )
        assert r.latency_ms > 0

    def test_sell_reduces_var(self, basic_portfolio, loose_limits):
        """Selling part of a position should reduce total VaR."""
        r = pre_trade_var_check(
            symbol="BTC",
            trade_weight=0.1,
            side="SELL",
            current_weights=basic_portfolio["weights"],
            asset_returns=basic_portfolio["returns"],
            limits=loose_limits,
        )
        assert r.approved is True
        assert r.new_var <= r.current_var + 1e-10
        assert r.marginal_var <= 1e-10  # negative or zero


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Core gate — rejection
# ═══════════════════════════════════════════════════════════════════════════════


class TestGateRejection:
    def test_high_vol_total_var_breach(self):
        """High-vol asset pushing total VaR above limit → reject."""
        btc_returns = _make_returns(250, vol=0.03, seed=1)
        high_vol = _high_vol_returns(250, seed=99)

        limits = PreTradeVarLimits(
            max_var_total_pct=0.03,
            max_marginal_var_per_trade_pct=0.50,  # loose marginal
        )
        r = pre_trade_var_check(
            symbol="SHITCOIN",
            trade_weight=0.50,
            side="BUY",
            current_weights={"BTC": 0.5},
            asset_returns={"BTC": btc_returns, "SHITCOIN": high_vol},
            limits=limits,
        )
        assert r.approved is False
        assert "var_limit_breach_total" in r.reason

    def test_marginal_var_breach(self):
        """Trade causing excessive marginal VaR → reject."""
        btc = _low_vol_returns(250, seed=7)
        high_vol = _high_vol_returns(250, seed=99)

        limits = PreTradeVarLimits(
            max_var_total_pct=0.50,  # loose total
            max_marginal_var_per_trade_pct=0.005,  # very tight marginal
        )
        r = pre_trade_var_check(
            symbol="SHITCOIN",
            trade_weight=0.40,
            side="BUY",
            current_weights={"BTC": 0.6},
            asset_returns={"BTC": btc, "SHITCOIN": high_vol},
            limits=limits,
        )
        assert r.approved is False
        assert "var_limit_breach_marginal" in r.reason
        assert r.marginal_var > limits.max_marginal_var_per_trade_pct

    def test_concentrated_position_rejected(self):
        """Concentrated high-vol position → total VaR breach."""
        high_vol = _high_vol_returns(250, seed=42)

        limits = PreTradeVarLimits(
            max_var_total_pct=0.05,
            max_marginal_var_per_trade_pct=0.50,
        )
        # Start with empty portfolio, buy 100% high-vol
        r = pre_trade_var_check(
            symbol="VOLATILE",
            trade_weight=1.0,
            side="BUY",
            current_weights={},
            asset_returns={"VOLATILE": high_vol},
            limits=limits,
        )
        assert r.approved is False
        assert "var_limit_breach_total" in r.reason
        # High-vol 10% daily → VaR₉₉ >> 5%
        assert r.new_var > 0.05


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Edge cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    def test_empty_portfolio_first_trade(self, loose_limits):
        """First trade into empty portfolio → should pass with loose limits."""
        returns = {"BTC": _make_returns(250, vol=0.02, seed=1)}
        r = pre_trade_var_check(
            symbol="BTC",
            trade_weight=0.30,
            side="BUY",
            current_weights={},
            asset_returns=returns,
            limits=loose_limits,
        )
        assert r.approved is True
        assert r.current_var == 0.0  # empty portfolio has no VaR
        assert r.new_var > 0.0

    def test_insufficient_data_conservative_pass(self, loose_limits):
        """Symbol with too few observations → conservative pass."""
        r = pre_trade_var_check(
            symbol="NEWCOIN",
            trade_weight=0.10,
            side="BUY",
            current_weights={"BTC": 0.5},
            asset_returns={
                "BTC": _make_returns(250, seed=1),
                "NEWCOIN": [0.01, -0.02, 0.005],  # only 3 obs
            },
            limits=loose_limits,
        )
        assert r.approved is True
        assert r.reason == "insufficient_data_pass"

    def test_symbol_not_in_returns(self, loose_limits):
        """Unknown symbol → conservative pass."""
        r = pre_trade_var_check(
            symbol="UNKNOWN",
            trade_weight=0.10,
            side="BUY",
            current_weights={"BTC": 0.5},
            asset_returns={"BTC": _make_returns(250, seed=1)},
            limits=loose_limits,
        )
        assert r.approved is True
        assert r.reason == "insufficient_data_pass"

    def test_negative_trade_weight_rejected(self, loose_limits):
        r = pre_trade_var_check(
            symbol="BTC",
            trade_weight=-0.1,
            side="BUY",
            current_weights={"BTC": 0.5},
            asset_returns={"BTC": _make_returns(250, seed=1)},
            limits=loose_limits,
        )
        assert r.approved is False
        assert "invalid_trade_weight_negative" in r.reason

    def test_invalid_side_rejected(self, loose_limits):
        r = pre_trade_var_check(
            symbol="BTC",
            trade_weight=0.1,
            side="SHORT",
            current_weights={"BTC": 0.5},
            asset_returns={"BTC": _make_returns(250, seed=1)},
            limits=loose_limits,
        )
        assert r.approved is False
        assert "invalid_side" in r.reason

    def test_zero_trade_weight(self, loose_limits):
        """Zero-weight trade → VaR unchanged, should pass."""
        returns = {"BTC": _make_returns(250, seed=1)}
        r = pre_trade_var_check(
            symbol="BTC",
            trade_weight=0.0,
            side="BUY",
            current_weights={"BTC": 0.5},
            asset_returns=returns,
            limits=loose_limits,
        )
        assert r.approved is True
        assert abs(r.marginal_var) < 1e-10


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Latency
# ═══════════════════════════════════════════════════════════════════════════════


class TestLatency:
    def test_under_30ms_two_assets(self):
        """Pre-trade check on 2-asset portfolio should complete in <30ms."""
        btc = _make_returns(250, vol=0.03, seed=1)
        eth = _make_returns(250, vol=0.04, seed=2)

        limits = PreTradeVarLimits(
            max_var_total_pct=0.10,
            max_marginal_var_per_trade_pct=0.05,
        )

        # Warmup
        pre_trade_var_check(
            symbol="ETH",
            trade_weight=0.05,
            side="BUY",
            current_weights={"BTC": 0.6, "ETH": 0.4},
            asset_returns={"BTC": btc, "ETH": eth},
            limits=limits,
        )

        # Timed run
        t0 = time.perf_counter()
        r = pre_trade_var_check(
            symbol="ETH",
            trade_weight=0.05,
            side="BUY",
            current_weights={"BTC": 0.6, "ETH": 0.4},
            asset_returns={"BTC": btc, "ETH": eth},
            limits=limits,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert elapsed_ms < 30.0, f"Latency {elapsed_ms:.1f}ms > 30ms target"
        assert r.latency_ms < 30.0

    def test_under_30ms_ten_assets(self):
        """Pre-trade check on 10-asset portfolio should complete in <30ms."""
        returns = {f"SYM{i}": _make_returns(250, vol=0.02 + 0.005 * i, seed=i)
                   for i in range(10)}
        weights = {f"SYM{i}": 0.1 for i in range(10)}
        limits = PreTradeVarLimits(
            max_var_total_pct=0.10,
            max_marginal_var_per_trade_pct=0.05,
        )

        # Warmup
        pre_trade_var_check("SYM0", 0.02, "BUY", weights, returns, limits)

        t0 = time.perf_counter()
        result = pre_trade_var_check("SYM0", 0.02, "BUY", weights, returns, limits)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert elapsed_ms < 30.0, f"Latency {elapsed_ms:.1f}ms > 30ms target"
        assert result.approved is True


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Batch check
# ═══════════════════════════════════════════════════════════════════════════════


class TestBatchCheck:
    def test_batch_sequential(self):
        """Batch check processes trades sequentially with cumulative impact."""
        btc = _make_returns(250, vol=0.03, seed=1)
        eth = _make_returns(250, vol=0.04, seed=2)
        sol = _high_vol_returns(250, seed=3)

        limits = PreTradeVarLimits(
            max_var_total_pct=0.10,
            max_marginal_var_per_trade_pct=0.05,
        )

        trades = [
            ("BTC", 0.3, "BUY"),
            ("ETH", 0.2, "BUY"),
            ("SOL", 0.1, "BUY"),
        ]

        results = pre_trade_var_check_batch(
            trades=trades,
            current_weights={},
            asset_returns={"BTC": btc, "ETH": eth, "SOL": sol},
            limits=limits,
        )
        assert len(results) == 3
        # Each result should reference correct symbol
        assert results[0].symbol == "BTC"
        assert results[1].symbol == "ETH"
        assert results[2].symbol == "SOL"

    def test_batch_cumulative_weights(self):
        """Approved trades update weights for subsequent checks."""
        btc = _make_returns(250, vol=0.03, seed=1)
        eth = _make_returns(250, vol=0.04, seed=2)

        limits = PreTradeVarLimits(
            max_var_total_pct=0.50,  # loose
            max_marginal_var_per_trade_pct=0.50,
        )

        trades = [
            ("BTC", 0.3, "BUY"),
            ("ETH", 0.3, "BUY"),
        ]

        results = pre_trade_var_check_batch(
            trades=trades,
            current_weights={},
            asset_returns={"BTC": btc, "ETH": eth},
            limits=limits,
        )
        # First trade: empty → BTC only
        assert results[0].current_var == 0.0
        assert results[0].new_var > 0.0
        # Second trade: BTC portfolio → BTC+ETH
        assert results[1].current_var > 0.0  # now has BTC

    def test_batch_empty_trades(self):
        results = pre_trade_var_check_batch(
            trades=[],
            current_weights={"BTC": 0.5},
            asset_returns={"BTC": _make_returns(250, seed=1)},
        )
        assert results == []


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Limits dataclass
# ═══════════════════════════════════════════════════════════════════════════════


class TestLimits:
    def test_defaults(self):
        lim = PreTradeVarLimits()
        assert lim.max_var_total_pct == 0.05
        assert lim.max_marginal_var_per_trade_pct == 0.02
        assert lim.confidence == 0.99

    def test_custom(self):
        lim = PreTradeVarLimits(
            max_var_total_pct=0.10,
            max_marginal_var_per_trade_pct=0.03,
            confidence=0.95,
        )
        assert lim.max_var_total_pct == 0.10
        assert lim.max_marginal_var_per_trade_pct == 0.03
        assert lim.confidence == 0.95

    def test_frozen(self):
        lim = PreTradeVarLimits()
        with pytest.raises(AttributeError):
            lim.max_var_total_pct = 0.99  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Result dataclass
# ═══════════════════════════════════════════════════════════════════════════════


class TestResult:
    def test_defaults(self):
        r = PreTradeVarResult()
        assert r.approved is True
        assert r.reason == ""
        assert r.current_var == 0.0
        assert r.new_var == 0.0
        assert r.marginal_var == 0.0
        assert r.latency_ms == 0.0

    def test_frozen(self):
        r = PreTradeVarResult()
        with pytest.raises(AttributeError):
            r.approved = False  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Serialization
# ═══════════════════════════════════════════════════════════════════════════════


class TestSerialization:
    def test_gate_result_to_dict(self, basic_portfolio, loose_limits):
        r = pre_trade_var_check(
            symbol="BTC",
            trade_weight=0.05,
            side="BUY",
            current_weights=basic_portfolio["weights"],
            asset_returns=basic_portfolio["returns"],
            limits=loose_limits,
        )
        d = gate_result_to_dict(r)
        assert isinstance(d, dict)
        assert "approved" in d
        assert "reason" in d
        assert "current_var" in d
        assert "new_var" in d
        assert "marginal_var" in d
        assert "latency_ms" in d
        assert d["approved"] == r.approved

    def test_dict_json_serializable(self, basic_portfolio, loose_limits):
        import json

        r = pre_trade_var_check(
            symbol="BTC",
            trade_weight=0.05,
            side="BUY",
            current_weights=basic_portfolio["weights"],
            asset_returns=basic_portfolio["returns"],
            limits=loose_limits,
        )
        d = gate_result_to_dict(r)
        s = json.dumps(d)
        assert isinstance(s, str)


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Integration + exports + sentinel
# ═══════════════════════════════════════════════════════════════════════════════


class TestIntegration:
    def test_sentinel_present(self):
        assert pre_trade_var_gate_active is True

    def test_exports_from_risk_package(self):
        from super_otonom.risk import (
            PreTradeVarLimits,
            PreTradeVarResult,
            gate_result_to_dict,
            pre_trade_var_check,
            pre_trade_var_check_batch,
            simulate_trade_weights,
        )

        assert callable(pre_trade_var_check)
        assert callable(pre_trade_var_check_batch)
        assert callable(simulate_trade_weights)
        assert callable(gate_result_to_dict)
        assert PreTradeVarLimits is not None
        assert PreTradeVarResult is not None

    def test_constants(self):
        assert GATE_MIN_OBS == 20
        assert GATE_DEFAULT_CONF == 0.99

    def test_realistic_scenario_btc_eth_sol(self):
        """Realistic 3-asset portfolio: BUY small SOL allocation → accept."""
        btc = _make_returns(250, vol=0.03, seed=10)
        eth = _make_returns(250, vol=0.04, seed=20)
        sol = _make_returns(250, vol=0.05, seed=30)

        limits = PreTradeVarLimits(
            max_var_total_pct=0.10,
            max_marginal_var_per_trade_pct=0.03,
        )

        r = pre_trade_var_check(
            symbol="SOL",
            trade_weight=0.05,
            side="BUY",
            current_weights={"BTC": 0.5, "ETH": 0.3},
            asset_returns={"BTC": btc, "ETH": eth, "SOL": sol},
            limits=limits,
        )
        assert r.approved is True
        assert r.new_var > 0
        assert r.marginal_var is not None

    def test_identity_new_var_equals_current_plus_marginal(self):
        """new_var ≈ current_var + marginal_var (by definition)."""
        btc = _make_returns(250, vol=0.03, seed=1)
        eth = _make_returns(250, vol=0.04, seed=2)

        r = pre_trade_var_check(
            symbol="ETH",
            trade_weight=0.10,
            side="BUY",
            current_weights={"BTC": 0.6, "ETH": 0.4},
            asset_returns={"BTC": btc, "ETH": eth},
            limits=PreTradeVarLimits(max_var_total_pct=0.50),
        )
        assert abs(r.new_var - (r.current_var + r.marginal_var)) < 1e-10
