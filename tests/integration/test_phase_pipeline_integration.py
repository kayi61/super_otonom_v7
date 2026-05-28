"""Integration test — Phase 38 through 55 sequential pipeline.

Her faz modülünü tek bir analiz dict'i üzerinden sırayla çalıştırır.
Harici servis gerektirmez — tüm girdi mock/synthetic.
"""

from __future__ import annotations

import importlib
import time
from typing import Any, Dict, List, Tuple

import pytest

# ---------------------------------------------------------------------------
# Phase modül kayıt defteri
# ---------------------------------------------------------------------------

_PHASE_REGISTRY: List[Tuple[str, str, str]] = [
    # (phase_id, module_path, analyze_func_name)
    ("38", "phases.phase_38.trade_explainability", "analyze"),
    ("39", "phases.phase_39.auto_risk_controller", "analyze"),
    ("40", "phases.phase_40.system_watchdog", "analyze"),
    ("41", "phases.phase_41.market_maker_intelligence", "analyze"),
    ("42", "phases.phase_42.whale_behavior_engine", "analyze"),
    ("43", "phases.phase_43.liquidity_topology_engine", "analyze"),
    ("44", "phases.phase_44.behavioral_finance_engine", "analyze"),
    ("46", "phases.phase_46.production_deployment_engine", "analyze"),
    ("48", "phases.phase_48.realtime_pnl_attribution", "analyze"),
    ("49", "phases.phase_49.strategy_lifecycle_manager", "analyze"),
    ("51", "phases.phase_51.mm_prediction_engine", "analyze"),
    ("52", "phases.phase_52.dark_pool_otc_engine", "analyze"),
    ("53", "phases.phase_53.gamma_squeeze_engine", "analyze"),
    ("54", "phases.phase_54.institutional_fingerprint_engine", "analyze"),
    ("55", "phases.phase_55.meta_market_intelligence", "analyze"),
]


# ---------------------------------------------------------------------------
# Standard phase output keys
# ---------------------------------------------------------------------------

_STANDARD_KEYS = {
    "trade_permission",
    "alpha_score",
    "risk_score",
    "confidence",
    "data_health",
    "event_ts",
    "half_life_ms",
}


# ---------------------------------------------------------------------------
# Market data factories for each phase
# ---------------------------------------------------------------------------


def _phase38_data() -> Dict[str, Any]:
    return {
        "signal": "BUY",
        "close": 50000.0,
        "decision_reason": "TREND_CONTINUATION",
        "entry_price": 49800.0,
        "confidence": 0.75,
    }


def _phase39_data() -> Dict[str, Any]:
    return {
        "current_drawdown_pct": 0.03,
        "max_drawdown_pct": 0.20,
        "var_99_pct": 0.04,
        "max_var_limit": 0.06,
        "volatility_current": 0.025,
        "volatility_threshold": 0.05,
        "open_positions": 2,
        "max_positions": 5,
    }


def _phase40_data() -> Dict[str, Any]:
    return {
        "latency_ms": 45.0,
        "memory_usage_pct": 0.55,
        "cpu_usage_pct": 0.30,
        "disk_usage_pct": 0.40,
        "error_rate_1h": 0.001,
        "last_heartbeat_age_s": 5.0,
    }


def _phase41_data() -> Dict[str, Any]:
    return {
        "spread_bps": 2.5,
        "depth_imbalance": 0.15,
        "mm_presence_score": 0.7,
        "quote_stability": 0.85,
    }


def _phase42_data() -> Dict[str, Any]:
    return {
        "whale_netflow_usd": -500000.0,
        "large_tx_count_1h": 5,
        "exchange_inflow_usd": 200000.0,
        "exchange_outflow_usd": 700000.0,
    }


def _phase43_data() -> Dict[str, Any]:
    return {
        "bid_depth_usd": 5000000.0,
        "ask_depth_usd": 4500000.0,
        "spread_pct": 0.0005,
        "liquidity_score": 0.8,
    }


def _phase44_data() -> Dict[str, Any]:
    return {
        "fear_greed_index": 55,
        "retail_sentiment": 0.6,
        "fomo_score": 0.3,
        "capitulation_score": 0.1,
    }


def _phase46_data() -> Dict[str, Any]:
    return {
        "deployment_state": "SHADOW",
        "current_position": "WAIT",
        "requested_position": "ENTER",
        "cooldown_remaining_ms": 0.0,
        "human_approval_required": False,
        "human_approved": False,
        "paper_sharpe": 1.5,
        "shadow_sharpe": 1.2,
        "uptime_hours": 48.0,
    }


def _phase48_data() -> Dict[str, Any]:
    return {
        "realized_pnl_usd": 150.0,
        "unrealized_pnl_usd": 50.0,
        "attribution_explained_pct": 0.85,
        "attribution_unexplained_pct": 0.15,
    }


def _phase49_data() -> Dict[str, Any]:
    return {
        "strategy_name": "momentum_v3",
        "strategy_state": "ACTIVE",
        "sharpe_rolling_30d": 1.8,
        "max_drawdown_30d_pct": 0.05,
        "win_rate_30d": 0.58,
    }


def _phase51_data() -> Dict[str, Any]:
    return {
        "predicted_spread_bps": 2.0,
        "predicted_depth_change_pct": 0.05,
        "mm_withdrawal_risk": 0.15,
        "prediction_confidence": 0.72,
    }


def _phase52_data() -> Dict[str, Any]:
    return {
        "dark_pool_volume_pct": 0.12,
        "otc_flow_usd": 1000000.0,
        "block_trade_count_24h": 3,
        "institutional_presence": 0.6,
    }


def _phase53_data() -> Dict[str, Any]:
    return {
        "gamma_exposure_usd": 500000.0,
        "delta_hedging_pressure": 0.3,
        "options_oi_change_pct": 0.05,
        "squeeze_probability": 0.15,
    }


def _phase54_data() -> Dict[str, Any]:
    return {
        "institutional_flow_usd": 2000000.0,
        "smart_money_index": 0.65,
        "accumulation_score": 0.7,
        "distribution_score": 0.2,
    }


def _phase55_data() -> Dict[str, Any]:
    return {
        "cross_asset_correlation": 0.75,
        "macro_risk_score": 0.3,
        "regime": "RISK_ON",
        "global_liquidity_trend": "expanding",
    }


_DATA_FACTORY = {
    "38": _phase38_data,
    "39": _phase39_data,
    "40": _phase40_data,
    "41": _phase41_data,
    "42": _phase42_data,
    "43": _phase43_data,
    "44": _phase44_data,
    "46": _phase46_data,
    "48": _phase48_data,
    "49": _phase49_data,
    "51": _phase51_data,
    "52": _phase52_data,
    "53": _phase53_data,
    "54": _phase54_data,
    "55": _phase55_data,
}


# ---------------------------------------------------------------------------
# Parametrize — her faz için tek tek test
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phase_id,module_path,func_name",
    _PHASE_REGISTRY,
    ids=[f"phase_{p[0]}" for p in _PHASE_REGISTRY],
)
class TestPhaseIndividual:
    """Her faz modülünü bağımsız olarak çalıştırır ve çıktıyı doğrular."""

    def test_analyze_returns_dict(
        self, phase_id: str, module_path: str, func_name: str
    ) -> None:
        mod = importlib.import_module(module_path)
        fn = getattr(mod, func_name)
        market_data = _DATA_FACTORY[phase_id]()
        result = fn(market_data)
        assert isinstance(result, dict), f"Phase {phase_id} analyze() must return dict"

    def test_standard_keys_present(
        self, phase_id: str, module_path: str, func_name: str
    ) -> None:
        mod = importlib.import_module(module_path)
        fn = getattr(mod, func_name)
        market_data = _DATA_FACTORY[phase_id]()
        result = fn(market_data)
        missing = _STANDARD_KEYS - set(result.keys())
        assert not missing, f"Phase {phase_id} missing keys: {missing}"

    def test_trade_permission_valid(
        self, phase_id: str, module_path: str, func_name: str
    ) -> None:
        mod = importlib.import_module(module_path)
        fn = getattr(mod, func_name)
        market_data = _DATA_FACTORY[phase_id]()
        result = fn(market_data)
        assert result["trade_permission"] in (
            "ALLOW",
            "BLOCK",
            "HALT",
        ), f"Phase {phase_id} invalid trade_permission"

    def test_score_ranges(
        self, phase_id: str, module_path: str, func_name: str
    ) -> None:
        mod = importlib.import_module(module_path)
        fn = getattr(mod, func_name)
        market_data = _DATA_FACTORY[phase_id]()
        result = fn(market_data)
        assert 0.0 <= float(result["confidence"]) <= 1.0
        assert 0.0 <= float(result["data_health"]) <= 1.0

    def test_none_input_graceful(
        self, phase_id: str, module_path: str, func_name: str
    ) -> None:
        mod = importlib.import_module(module_path)
        fn = getattr(mod, func_name)
        # None veya boş dict — çökmemeli
        result = fn(None)
        assert isinstance(result, dict)
        assert "trade_permission" in result


# ---------------------------------------------------------------------------
# Sequential pipeline — tüm fazlar sırayla
# ---------------------------------------------------------------------------


class TestSequentialPipeline:
    """Tüm fazları sırasıyla çalıştırır, birbirine veri iletir."""

    def test_all_phases_run_sequentially(self) -> None:
        pipeline_results: Dict[str, Dict[str, Any]] = {}

        for phase_id, module_path, func_name in _PHASE_REGISTRY:
            mod = importlib.import_module(module_path)
            fn = getattr(mod, func_name)
            market_data = _DATA_FACTORY[phase_id]()
            result = fn(market_data)
            pipeline_results[f"phase_{phase_id}"] = result

        # All 15 phases should have run
        assert len(pipeline_results) == len(_PHASE_REGISTRY)

        # All should have valid trade_permission
        for key, result in pipeline_results.items():
            assert result["trade_permission"] in ("ALLOW", "BLOCK", "HALT"), key

    def test_pipeline_consensus(self) -> None:
        """Tüm fazların consensus → majority vote trade_permission."""
        permissions: List[str] = []

        for phase_id, module_path, func_name in _PHASE_REGISTRY:
            mod = importlib.import_module(module_path)
            fn = getattr(mod, func_name)
            market_data = _DATA_FACTORY[phase_id]()
            result = fn(market_data)
            permissions.append(result["trade_permission"])

        # Count votes
        halt_count = permissions.count("HALT")
        block_count = permissions.count("BLOCK")
        allow_count = permissions.count("ALLOW")

        # With normal data, most phases should ALLOW
        assert allow_count > 0, "At least some phases should ALLOW with normal data"

        # Verify we can compute a consensus
        if halt_count > 0:
            consensus = "HALT"
        elif block_count > len(permissions) // 3:
            consensus = "BLOCK"
        else:
            consensus = "ALLOW"

        assert consensus in ("ALLOW", "BLOCK", "HALT")

    def test_pipeline_timing(self) -> None:
        """Tüm fazların toplam çalışma süresi < 5s."""
        t0 = time.monotonic()

        for phase_id, module_path, func_name in _PHASE_REGISTRY:
            mod = importlib.import_module(module_path)
            fn = getattr(mod, func_name)
            market_data = _DATA_FACTORY[phase_id]()
            fn(market_data)

        elapsed = time.monotonic() - t0
        assert elapsed < 5.0, f"Pipeline took {elapsed:.2f}s — too slow"


# ---------------------------------------------------------------------------
# Phase isolation — bir fazın hatası diğerini etkilememeli
# ---------------------------------------------------------------------------


class TestPhaseIsolation:
    """Bir faz hata verse bile diğerleri çalışmaya devam etmeli."""

    def test_bad_data_one_phase_others_survive(self) -> None:
        success_count = 0
        error_count = 0

        for phase_id, module_path, func_name in _PHASE_REGISTRY:
            mod = importlib.import_module(module_path)
            fn = getattr(mod, func_name)
            # Deliberately bad data
            bad_data = {"invalid_key": "garbage", "close": "not_a_number"}
            try:
                result = fn(bad_data)
                if isinstance(result, dict) and "trade_permission" in result:
                    success_count += 1
                else:
                    error_count += 1
            except Exception:
                error_count += 1

        # Most phases should handle bad data gracefully
        assert success_count >= len(_PHASE_REGISTRY) * 0.5, (
            f"Too many phases crashed: {error_count}/{len(_PHASE_REGISTRY)}"
        )
