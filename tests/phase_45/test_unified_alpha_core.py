"""Faz 45 — unified_alpha_core birim testleri.

Test edilen modül: super_otonom.signals.unified_alpha_core
Fonksiyon: run_unified_alpha_phase — kalite skoru + omega rejim + decay monitör.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stub / Mock helpers
# ---------------------------------------------------------------------------


class _FakeRisk:
    """RiskManager minimal stub."""

    def get_omega_effective_qmin(self, base_min: int) -> int:
        return max(0, min(90, int(base_min)))


class _FakeDctx:
    """DecisionContext minimal stub."""

    def __init__(self) -> None:
        self.signal_quality: int = 0
        self.adj_signal_quality: int = 0
        self.penalty_reasons: List[str] = []
        self.quality_main_penalty: str = ""
        self.omega_regime: str = ""
        self.omega_quality_mult: float = 1.0
        self.omega_size_factor: float = 1.0
        self.effective_quality_min: int = 0
        self.external_ai_log: Optional[str] = None
        self.omega_ai_log: str = ""
        self.decision_reason: str = ""
        self.entry_blocked: str = ""
        self._traces: List[str] = []

    def add_trace(self, category: str, msg: str) -> None:
        self._traces.append(f"{category}:{msg}")


class _FakeEngine:
    """BotEngine minimal stub — run_unified_alpha_phase için."""

    def __init__(self) -> None:
        self.risk = _FakeRisk()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine() -> _FakeEngine:
    return _FakeEngine()


@pytest.fixture()
def dctx() -> _FakeDctx:
    return _FakeDctx()


@pytest.fixture()
def base_analysis() -> Dict[str, Any]:
    return {
        "signal": "BUY",
        "close": 50000.0,
        "rsi": 55.0,
        "volume": 100.0,
        "atr": 500.0,
    }


@pytest.fixture()
def base_out() -> Dict[str, Any]:
    return {"final_signal": "BUY"}


# ---------------------------------------------------------------------------
# Phase output schema testi
# ---------------------------------------------------------------------------


_PHASE_SCHEMA_KEYS = {
    "trade_permission",
    "alpha_score",
    "risk_score",
    "confidence",
    "data_health",
    "event_ts",
    "half_life_ms",
}


class TestPhase45Schema:
    """Faz 45 çıktısının standart phase output şemasına uyumluluğu."""

    @patch("super_otonom.signals.unified_alpha_core.run_regime_detection_phase")
    @patch("super_otonom.signals.unified_alpha_core.monitor_alpha_decay")
    @patch("super_otonom.bot_engine.compute_signal_quality")
    def test_phase45_attached_to_analysis(
        self,
        mock_sq: MagicMock,
        mock_decay: MagicMock,
        mock_regime: MagicMock,
        engine: _FakeEngine,
        dctx: _FakeDctx,
        base_analysis: Dict[str, Any],
        base_out: Dict[str, Any],
    ) -> None:
        from super_otonom.signals.unified_alpha_core import run_unified_alpha_phase

        mock_sq.return_value = (75, ["minor"], {"rsi": 10}, "minor")
        mock_regime.return_value = (
            {"data_health": 0.9, "phase": "26"},
            ("LOW_VOL", 1.0, 1.0, 75, "ok"),
        )
        mock_decay.return_value = SimpleNamespace(
            to_dict=lambda: {"confidence": 0.85}
        )

        run_unified_alpha_phase(
            engine, "BTC/USDT", base_analysis, base_out, dctx, event_ts=time.time() * 1000
        )

        assert "phase45" in base_analysis
        assert "faz45" in base_analysis
        p45 = base_analysis["phase45"]
        assert _PHASE_SCHEMA_KEYS.issubset(p45.keys())

    @patch("super_otonom.signals.unified_alpha_core.run_regime_detection_phase")
    @patch("super_otonom.signals.unified_alpha_core.monitor_alpha_decay")
    @patch("super_otonom.bot_engine.compute_signal_quality")
    def test_trade_permission_values(
        self,
        mock_sq: MagicMock,
        mock_decay: MagicMock,
        mock_regime: MagicMock,
        engine: _FakeEngine,
        dctx: _FakeDctx,
        base_analysis: Dict[str, Any],
        base_out: Dict[str, Any],
    ) -> None:
        from super_otonom.signals.unified_alpha_core import run_unified_alpha_phase

        mock_sq.return_value = (80, [], {}, "")
        mock_regime.return_value = (
            {"data_health": 1.0},
            ("LOW_VOL", 1.0, 1.0, 80, "ok"),
        )
        mock_decay.side_effect = Exception("no decay")

        run_unified_alpha_phase(
            engine, "ETH/USDT", base_analysis, base_out, dctx, event_ts=time.time() * 1000
        )

        p45 = base_analysis["phase45"]
        assert p45["trade_permission"] in ("ALLOW", "BLOCK", "HALT")

    @patch("super_otonom.signals.unified_alpha_core.run_regime_detection_phase")
    @patch("super_otonom.signals.unified_alpha_core.monitor_alpha_decay")
    @patch("super_otonom.bot_engine.compute_signal_quality")
    def test_alpha_risk_score_range(
        self,
        mock_sq: MagicMock,
        mock_decay: MagicMock,
        mock_regime: MagicMock,
        engine: _FakeEngine,
        dctx: _FakeDctx,
        base_analysis: Dict[str, Any],
        base_out: Dict[str, Any],
    ) -> None:
        from super_otonom.signals.unified_alpha_core import run_unified_alpha_phase

        mock_sq.return_value = (60, [], {}, "")
        mock_regime.return_value = (
            {"data_health": 0.7},
            ("HIGH_VOL", 0.8, 0.9, 60, "vol_adj"),
        )
        mock_decay.side_effect = Exception("skip")

        run_unified_alpha_phase(
            engine, "SOL/USDT", base_analysis, base_out, dctx, event_ts=time.time() * 1000
        )

        p45 = base_analysis["phase45"]
        assert 0.0 <= p45["alpha_score"] <= 100.0
        assert 0.0 <= p45["risk_score"] <= 100.0
        assert 0.0 <= p45["confidence"] <= 1.0
        assert 0.0 <= p45["data_health"] <= 1.0


# ---------------------------------------------------------------------------
# Quality scoring ve reject mantigi
# ---------------------------------------------------------------------------


class TestQualityReject:
    """Kalite skoru eşiğinin altında → final_signal HOLD'a dönmeli."""

    @patch("super_otonom.signals.unified_alpha_core.run_regime_detection_phase")
    @patch("super_otonom.signals.unified_alpha_core.monitor_alpha_decay")
    @patch("super_otonom.bot_engine.compute_signal_quality")
    def test_low_quality_rejects_buy(
        self,
        mock_sq: MagicMock,
        mock_decay: MagicMock,
        mock_regime: MagicMock,
        engine: _FakeEngine,
        dctx: _FakeDctx,
        base_analysis: Dict[str, Any],
        base_out: Dict[str, Any],
    ) -> None:
        from super_otonom.signals.unified_alpha_core import run_unified_alpha_phase

        # adj quality = 30, effective min = 62 (default) → reject
        mock_sq.return_value = (30, ["weak_rsi", "low_vol"], {}, "weak_rsi")
        mock_regime.return_value = (
            {"data_health": 1.0},
            ("LOW_VOL", 1.0, 1.0, 30, "ok"),
        )
        mock_decay.side_effect = Exception("skip")

        adj, _ = run_unified_alpha_phase(
            engine, "BTC/USDT", base_analysis, base_out, dctx, event_ts=time.time() * 1000
        )

        assert adj < engine.risk.get_omega_effective_qmin(62)
        assert base_out["final_signal"] == "HOLD"
        assert "LOW_QUALITY" in base_out.get("decision_reason", "")
        assert dctx.entry_blocked == "low_quality"

    @patch("super_otonom.signals.unified_alpha_core.run_regime_detection_phase")
    @patch("super_otonom.signals.unified_alpha_core.monitor_alpha_decay")
    @patch("super_otonom.bot_engine.compute_signal_quality")
    def test_high_quality_allows_buy(
        self,
        mock_sq: MagicMock,
        mock_decay: MagicMock,
        mock_regime: MagicMock,
        engine: _FakeEngine,
        dctx: _FakeDctx,
        base_analysis: Dict[str, Any],
        base_out: Dict[str, Any],
    ) -> None:
        from super_otonom.signals.unified_alpha_core import run_unified_alpha_phase

        mock_sq.return_value = (85, [], {}, "")
        mock_regime.return_value = (
            {"data_health": 1.0},
            ("LOW_VOL", 1.0, 1.0, 85, "ok"),
        )
        mock_decay.side_effect = Exception("skip")

        adj, _ = run_unified_alpha_phase(
            engine, "BTC/USDT", base_analysis, base_out, dctx, event_ts=time.time() * 1000
        )

        assert adj >= engine.risk.get_omega_effective_qmin(62)
        # final_signal should remain BUY
        assert base_out["final_signal"] == "BUY"

    @patch("super_otonom.signals.unified_alpha_core.run_regime_detection_phase")
    @patch("super_otonom.signals.unified_alpha_core.monitor_alpha_decay")
    @patch("super_otonom.bot_engine.compute_signal_quality")
    def test_hold_signal_not_rejected(
        self,
        mock_sq: MagicMock,
        mock_decay: MagicMock,
        mock_regime: MagicMock,
        engine: _FakeEngine,
        dctx: _FakeDctx,
        base_analysis: Dict[str, Any],
    ) -> None:
        from super_otonom.signals.unified_alpha_core import run_unified_alpha_phase

        out = {"final_signal": "HOLD"}
        mock_sq.return_value = (20, ["terrible"], {}, "terrible")
        mock_regime.return_value = (
            {"data_health": 1.0},
            ("LOW_VOL", 1.0, 1.0, 20, "ok"),
        )
        mock_decay.side_effect = Exception("skip")

        run_unified_alpha_phase(
            engine, "BTC/USDT", base_analysis, out, dctx, event_ts=time.time() * 1000
        )

        # HOLD stays HOLD regardless of quality (reject only applies to BUY)
        assert out["final_signal"] == "HOLD"
        assert dctx.entry_blocked == ""


# ---------------------------------------------------------------------------
# Decay entegrasyonu
# ---------------------------------------------------------------------------


class TestDecayIntegration:
    @patch("super_otonom.signals.unified_alpha_core.run_regime_detection_phase")
    @patch("super_otonom.signals.unified_alpha_core.monitor_alpha_decay")
    @patch("super_otonom.bot_engine.compute_signal_quality")
    def test_decay_snapshot_attached(
        self,
        mock_sq: MagicMock,
        mock_decay: MagicMock,
        mock_regime: MagicMock,
        engine: _FakeEngine,
        dctx: _FakeDctx,
        base_analysis: Dict[str, Any],
        base_out: Dict[str, Any],
    ) -> None:
        from super_otonom.signals.unified_alpha_core import run_unified_alpha_phase

        mock_sq.return_value = (80, [], {}, "")
        mock_regime.return_value = (
            {"data_health": 1.0},
            ("LOW_VOL", 1.0, 1.0, 80, "ok"),
        )
        mock_decay.return_value = SimpleNamespace(
            to_dict=lambda: {"confidence": 0.75, "freshness": "stale"}
        )

        run_unified_alpha_phase(
            engine, "BTC/USDT", base_analysis, base_out, dctx, event_ts=time.time() * 1000
        )

        p45 = base_analysis["phase45"]
        assert "decay" in p45
        assert p45["decay"]["confidence"] == 0.75
        # confidence is multiplied by decay confidence
        assert p45["confidence"] <= 1.0

    @patch("super_otonom.signals.unified_alpha_core.run_regime_detection_phase")
    @patch("super_otonom.signals.unified_alpha_core.monitor_alpha_decay")
    @patch("super_otonom.bot_engine.compute_signal_quality")
    def test_decay_failure_graceful(
        self,
        mock_sq: MagicMock,
        mock_decay: MagicMock,
        mock_regime: MagicMock,
        engine: _FakeEngine,
        dctx: _FakeDctx,
        base_analysis: Dict[str, Any],
        base_out: Dict[str, Any],
    ) -> None:
        from super_otonom.signals.unified_alpha_core import run_unified_alpha_phase

        mock_sq.return_value = (70, [], {}, "")
        mock_regime.return_value = (
            {"data_health": 1.0},
            ("LOW_VOL", 1.0, 1.0, 70, "ok"),
        )
        mock_decay.side_effect = RuntimeError("decay service down")

        # Should not raise
        run_unified_alpha_phase(
            engine, "BTC/USDT", base_analysis, base_out, dctx, event_ts=time.time() * 1000
        )

        p45 = base_analysis["phase45"]
        assert "decay" not in p45  # decay failed, not attached


# ---------------------------------------------------------------------------
# Omega rejim entegrasyonu
# ---------------------------------------------------------------------------


class TestOmegaRegime:
    @patch("super_otonom.signals.unified_alpha_core.run_regime_detection_phase")
    @patch("super_otonom.signals.unified_alpha_core.monitor_alpha_decay")
    @patch("super_otonom.bot_engine.compute_signal_quality")
    def test_omega_regime_propagated_to_dctx(
        self,
        mock_sq: MagicMock,
        mock_decay: MagicMock,
        mock_regime: MagicMock,
        engine: _FakeEngine,
        dctx: _FakeDctx,
        base_analysis: Dict[str, Any],
        base_out: Dict[str, Any],
    ) -> None:
        from super_otonom.signals.unified_alpha_core import run_unified_alpha_phase

        mock_sq.return_value = (72, [], {}, "")
        mock_regime.return_value = (
            {"data_health": 0.8},
            ("HIGH_VOL", 0.85, 0.9, 72, "vol_adj"),
        )
        mock_decay.side_effect = Exception("skip")

        run_unified_alpha_phase(
            engine, "BTC/USDT", base_analysis, base_out, dctx, event_ts=time.time() * 1000
        )

        assert dctx.omega_regime == "HIGH_VOL"
        assert dctx.omega_quality_mult == 0.85
        assert dctx.omega_size_factor == 0.9
        p45 = base_analysis["phase45"]
        assert p45["omega_regime"] == "HIGH_VOL"

    @patch("super_otonom.signals.unified_alpha_core.run_regime_detection_phase")
    @patch("super_otonom.signals.unified_alpha_core.monitor_alpha_decay")
    @patch("super_otonom.bot_engine.compute_signal_quality")
    def test_return_value_tuple(
        self,
        mock_sq: MagicMock,
        mock_decay: MagicMock,
        mock_regime: MagicMock,
        engine: _FakeEngine,
        dctx: _FakeDctx,
        base_analysis: Dict[str, Any],
        base_out: Dict[str, Any],
    ) -> None:
        from super_otonom.signals.unified_alpha_core import run_unified_alpha_phase

        mock_sq.return_value = (65, [], {}, "")
        omega_t = ("NEUTRAL", 1.0, 1.0, 65, "no_adj")
        mock_regime.return_value = ({"data_health": 1.0}, omega_t)
        mock_decay.side_effect = Exception("skip")

        adj, returned_omega = run_unified_alpha_phase(
            engine, "BTC/USDT", base_analysis, base_out, dctx, event_ts=time.time() * 1000
        )

        assert isinstance(adj, int)
        assert adj == 65
        assert returned_omega == omega_t


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    @patch("super_otonom.signals.unified_alpha_core.run_regime_detection_phase")
    @patch("super_otonom.signals.unified_alpha_core.monitor_alpha_decay")
    @patch("super_otonom.bot_engine.compute_signal_quality")
    def test_no_event_ts_uses_now(
        self,
        mock_sq: MagicMock,
        mock_decay: MagicMock,
        mock_regime: MagicMock,
        engine: _FakeEngine,
        dctx: _FakeDctx,
        base_analysis: Dict[str, Any],
        base_out: Dict[str, Any],
    ) -> None:
        from super_otonom.signals.unified_alpha_core import run_unified_alpha_phase

        mock_sq.return_value = (70, [], {}, "")
        mock_regime.return_value = ({"data_health": 1.0}, ("LOW_VOL", 1.0, 1.0, 70, "ok"))
        mock_decay.side_effect = Exception("skip")

        before = time.time() * 1000
        run_unified_alpha_phase(
            engine, "BTC/USDT", base_analysis, base_out, dctx, event_ts=None
        )
        after = time.time() * 1000

        p45 = base_analysis["phase45"]
        assert before <= p45["event_ts"] <= after + 100

    @patch("super_otonom.signals.unified_alpha_core.run_regime_detection_phase")
    @patch("super_otonom.signals.unified_alpha_core.monitor_alpha_decay")
    @patch("super_otonom.bot_engine.compute_signal_quality")
    def test_phase26_ref_stored(
        self,
        mock_sq: MagicMock,
        mock_decay: MagicMock,
        mock_regime: MagicMock,
        engine: _FakeEngine,
        dctx: _FakeDctx,
        base_analysis: Dict[str, Any],
        base_out: Dict[str, Any],
    ) -> None:
        from super_otonom.signals.unified_alpha_core import run_unified_alpha_phase

        phase26_data = {"data_health": 0.95, "regime": "bull"}
        mock_sq.return_value = (70, [], {}, "")
        mock_regime.return_value = (phase26_data, ("LOW_VOL", 1.0, 1.0, 70, "ok"))
        mock_decay.side_effect = Exception("skip")

        run_unified_alpha_phase(
            engine, "BTC/USDT", base_analysis, base_out, dctx, event_ts=time.time() * 1000
        )

        p45 = base_analysis["phase45"]
        assert p45["phase26_ref"] is phase26_data
