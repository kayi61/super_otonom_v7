"""AILayer: get_decision_reason + validate_signal dalları (mock)."""

from __future__ import annotations

import importlib
import os
import sys
import types
from unittest.mock import MagicMock

import pytest
import super_otonom.config as cfg
from super_otonom.ai_layer import AILayer, _entry_conf_floor


def test_entry_conf_floor_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENTRY_MIN_CONFIDENCE", "nope")
    v = _entry_conf_floor()
    assert 0.45 <= v <= 0.95


def test_get_decision_reason_regimes() -> None:
    a = AILayer(model_path="___nonexistent_model_xyz___")
    assert a.get_decision_reason("HOLD", 0.5, {"regime": "NOISY"}) == "REGIME_BLOCKED_NOISY"
    assert (
        a.get_decision_reason("BUY", 0.5, {"regime": "MEAN_REVERTING"})
        == "REGIME_BLOCKED_MEAN_REVERTING"
    )
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
    srv.predict = MagicMock(return_value={"source": "no_model", "confidence": 0.6, "signal": "BUY"})
    out = a.validate_signal("S", "BUY", {"regime": "TRENDING", "hurst": 0.5})
    assert out[0] == "BUY"
    srv.predict = MagicMock(return_value={"source": "ok", "confidence": 0.7, "signal": "BUY"})
    out2 = a.validate_signal("S", "BUY", {"regime": "TRENDING", "hurst": 0.5})
    assert out2[0] == "BUY"
    srv.predict = MagicMock(return_value={"source": "ok", "confidence": 0.7, "signal": "HOLD"})
    out3 = a.validate_signal("S", "BUY", {"regime": "TRENDING", "hurst": 0.5})
    assert out3[0] == "HOLD"
    srv.predict = MagicMock(return_value={"source": "ok", "confidence": 0.7, "signal": "SELL"})
    out4 = a.validate_signal("S", "BUY", {"regime": "TRENDING", "hurst": 0.5})
    assert out4[0] == "HOLD"


def test_extract_features_and_buffer_trim() -> None:
    a = AILayer(model_path="___nonexistent_model_xyz___")
    a.seq_len = 1
    for i in range(5):
        a.update_buffer(
            "Z",
            {"close": 100.0 + i, "open": 100, "high": 101, "low": 99, "volume": 1.0},
            {"rsi": 50, "regime": "TRENDING"},
        )
    assert len(a._buffer["Z"]) <= 2


def test_stop_clears_server() -> None:
    a = AILayer(model_path="___nonexistent_model_xyz___")
    a._server = MagicMock()
    a.stop()
    a._server.stop.assert_called_once()


def test_market_models_import_success_sets_flag() -> None:
    """20-23: ModelServer importu başarılı."""
    saved = sys.modules.get("super_otonom.ai_layer")
    core = types.ModuleType("super_otonom.core")
    mm = types.ModuleType("super_otonom.core.market_models")

    class _MS:
        def __init__(self, model_path: str = "") -> None:
            pass

    mm.ModelServer = _MS
    sys.modules["super_otonom.core"] = core
    sys.modules["super_otonom.core.market_models"] = mm
    try:
        sys.modules.pop("super_otonom.ai_layer", None)
        al = importlib.import_module("super_otonom.ai_layer")
        assert al._MODEL_SERVER_AVAILABLE is True
    finally:
        sys.modules.pop("super_otonom.ai_layer", None)
        sys.modules.pop("super_otonom.core.market_models", None)
        sys.modules.pop("super_otonom.core", None)
        if saved is not None:
            sys.modules["super_otonom.ai_layer"] = saved
        importlib.import_module("super_otonom.ai_layer")


def test_ailayer_warns_when_lstm_enabled_but_file_missing(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """58-63."""
    monkeypatch.setitem(cfg.AI, "lstm_enabled", True)
    caplog.set_level("WARNING", logger="super_otonom.ai")
    p = tmp_path / "no_such_model.pt"
    AILayer(model_path=str(p))
    assert any("model bulunamadi" in r.message.lower() for r in caplog.records)


def test_ailayer_starts_modelserver_when_enabled(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """66-68: ModelServer yolu — modül nesnesi üzerinden patch (3.10/3.12 uyumu)."""
    import super_otonom.ai_layer as al

    monkeypatch.setitem(al.AI, "lstm_enabled", True)
    p = tmp_path / "w.pt"
    p.write_bytes(b"1")
    model_path = os.fspath(p.resolve())
    assert os.path.isfile(model_path)

    fake_ms = MagicMock()
    monkeypatch.setattr(al, "_MODEL_SERVER_AVAILABLE", True)
    monkeypatch.setattr(al, "ModelServer", fake_ms)

    al.AILayer(model_path=model_path)

    fake_ms.assert_called_once_with(model_path=model_path)
    fake_ms.return_value.start.assert_called_once()


def test_extract_features_zero_close() -> None:
    """75-77: string '0.0' → float 0 (truthy str, `or 1.0` atlanmaz)."""
    a = AILayer(model_path="___nonexistent_model_xyz___")
    vec = a._extract_features(
        {"close": "0.0", "open": 1, "high": 1, "low": 1, "volume": 1.0},
        {"rsi": 50.0, "ema_diff": 0.0, "vol_ratio": 1.0, "bb_pct_b": 0.5},
    )
    assert len(vec) == 8


def test_validate_signal_buffer_insufficient() -> None:
    """165-168."""
    a = AILayer(model_path="___nonexistent_model_xyz___")
    a.enabled = True
    a._server = MagicMock()
    a.seq_len = 5
    a._buffer["Z"] = [[0.0] * 7]
    sig, conf, reason = a.validate_signal("Z", "BUY", {"regime": "TRENDING", "hurst": 0.5})
    assert sig == "BUY" and reason == "AI_BUFFER_INSUFFICIENT"


def test_validate_signal_hold_passes_through_final_ai_path() -> None:
    """198-204: baz HOLD, AI BUY → son dönüş."""
    a = AILayer(model_path="___nonexistent_model_xyz___")
    a.enabled = True
    srv = MagicMock(return_value={"source": "ok", "confidence": 0.72, "signal": "BUY"})
    a._server = srv
    a.seq_len = 1
    a._buffer["K"] = [[0.0] * 7]
    sig, conf, _r = a.validate_signal("K", "HOLD", {"regime": "TRENDING", "hurst": 0.55})
    assert sig == "HOLD"
    assert 0.45 <= conf <= 0.95
