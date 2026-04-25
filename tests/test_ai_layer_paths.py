"""AILayer: get_decision_reason + validate_signal dalları (mock)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from super_otonom.ai_layer import AILayer, _entry_conf_floor


def test_entry_conf_floor_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENTRY_MIN_CONFIDENCE", "nope")
    v = _entry_conf_floor()
    assert 0.45 <= v <= 0.95


def test_get_decision_reason_regimes() -> None:
    a = AILayer(model_path="___nonexistent_model_xyz___")
    assert a.get_decision_reason("HOLD", 0.5, {"regime": "NOISY"}) == "REGIME_BLOCKED_NOISY"
    assert a.get_decision_reason("BUY", 0.5, {"regime": "MEAN_REVERTING"}) == "REGIME_BLOCKED_MEAN_REVERTING"
    assert "VOLATILITY" in a.get_decision_reason("HOLD", 0.5, {"regime": "TRENDING", "hurst": 0.99})
    assert a.get_decision_reason("BUY", 0.9, {"regime": "TRENDING"}) == "STRONG_AI_CONVICTION"


def test_validate_signal_chattering_regime() -> None:
    a = AILayer(model_path="___nonexistent_model_xyz___")
    f, c, r = a.validate_signal("X", "BUY", {"regime": "NOISY"})
    assert f == "HOLD"


def test_validate_signal_fallback_mode() -> None:
    a = AILayer(model_path="___nonexistent_model_xyz___")
    s, c, r = a.validate_signal("X", "BUY", {"regime": "TRENDING", "hurst": 0.5})
    assert s == "BUY" and c >= 0.45


def test_validate_signal_with_enabled_mock_server() -> None:
    a = AILayer(model_path="___nonexistent_model_xyz___")
    a.enabled = True
    srv = MagicMock()
    a._server = srv
    a.seq_len = 2
    a._buffer["S"] = [[0.0] * 7, [0.0] * 7]
    srv.predict = MagicMock(
        return_value={"source": "no_model", "confidence": 0.6, "signal": "BUY"}
    )
    out = a.validate_signal("S", "BUY", {"regime": "TRENDING", "hurst": 0.5})
    assert out[0] == "BUY"
    srv.predict = MagicMock(
        return_value={"source": "ok", "confidence": 0.7, "signal": "BUY"}
    )
    out2 = a.validate_signal("S", "BUY", {"regime": "TRENDING", "hurst": 0.5})
    assert out2[0] == "BUY"
    srv.predict = MagicMock(
        return_value={"source": "ok", "confidence": 0.7, "signal": "HOLD"}
    )
    out3 = a.validate_signal("S", "BUY", {"regime": "TRENDING", "hurst": 0.5})
    assert out3[0] == "HOLD"
    srv.predict = MagicMock(
        return_value={"source": "ok", "confidence": 0.7, "signal": "SELL"}
    )
    out4 = a.validate_signal("S", "BUY", {"regime": "TRENDING", "hurst": 0.5})
    assert out4[0] == "HOLD"


def test_extract_features_and_buffer_trim() -> None:
    a = AILayer(model_path="___nonexistent_model_xyz___")
    a.seq_len = 1
    for i in range(5):
        a.update_buffer("Z", {"close": 100.0 + i, "open": 100, "high": 101, "low": 99, "volume": 1.0}, {"rsi": 50, "regime": "TRENDING"})
    assert len(a._buffer["Z"]) <= 2


def test_stop_clears_server() -> None:
    a = AILayer(model_path="___nonexistent_model_xyz___")
    a._server = MagicMock()
    a.stop()
    a._server.stop.assert_called_once()
