"""AILayer: rejim ve fallback (LSTM kapalı)."""
from __future__ import annotations

import pytest
from super_otonom.ai_layer import AILayer


@pytest.fixture
def ai_no_model(tmp_path) -> AILayer:
    bad_path = str(tmp_path / "missing.pt")
    return AILayer(model_path=bad_path)


def test_validate_signal_blocks_noisy_regime(ai_no_model: AILayer) -> None:
    sig, conf, reason = ai_no_model.validate_signal(
        "BTC/USDT",
        "BUY",
        {"regime": "NOISY", "hurst": 0.5, "rsi": 50.0},
    )
    assert sig == "HOLD"
    assert conf < 0.5
    assert "REGIME" in reason or "NOISY" in reason


def test_validate_signal_blocks_mean_reverting(ai_no_model: AILayer) -> None:
    sig, conf, _reason = ai_no_model.validate_signal(
        "ETH/USDT",
        "BUY",
        {"regime": "MEAN_REVERTING", "hurst": 0.4, "rsi": 50.0},
    )
    assert sig == "HOLD"


def test_validate_signal_passes_trending_to_technical_when_no_model(
    ai_no_model: AILayer,
) -> None:
    sig, conf, reason = ai_no_model.validate_signal(
        "BTC/USDT",
        "SELL",
        {"regime": "TRENDING", "hurst": 0.58, "rsi": 45.0},
    )
    assert sig == "SELL"
    assert conf > 0
    assert "FALLBACK" in reason or "TECHNICAL" in reason or "MODEL" in reason


def test_get_decision_reason_regime_priority(ai_no_model: AILayer) -> None:
    r = ai_no_model.get_decision_reason("BUY", 0.9, {"regime": "NOISY"})
    assert r == "REGIME_BLOCKED_NOISY"


def test_update_buffer_crops_long_history(ai_no_model: AILayer) -> None:
    sym = "X"
    for i in range(100):
        ai_no_model.update_buffer(
            sym,
            {"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            {"rsi": 50, "ema_diff": 0, "vol_ratio": 1, "bb_pct_b": 0.5},
        )
    assert len(ai_no_model._buffer[sym]) <= ai_no_model.seq_len * 2
