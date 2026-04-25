from __future__ import annotations

import asyncio

import pytest
from super_otonom.ai_confidence_bridge import format_ml_inference_payload
from super_otonom.decision_context import DecisionContext
from super_otonom.ml_client import MLClient


def test_format_payload_includes_key_fields() -> None:
    a = {
        "signal": "BUY", "regime": "TRENDING", "hurst": 0.6,
        "volatility": 0.02, "rsi": 55.0, "ob_safe_size": 100.0,
    }
    p = format_ml_inference_payload("BTC/USDT", a, tick_id=3)
    assert p["schema"] == "super_otonom.ml.inference.v1"
    assert p["symbol"] == "BTC/USDT"
    assert p["tick_id"] == 3
    assert p["signal"] == "BUY"


def test_ml_client_disabled_no_hang() -> None:
    c = MLClient(service_url="", enabled=False)
    a = {"signal": "HOLD"}
    d = DecisionContext.start("X", 1, a)

    async def _run() -> None:
        await c.enrich_analysis("X", a, d)

    asyncio.run(_run())
    assert d.external_ai_log.startswith("[EXTERNAL-AI] disabled")
    assert "ml_score" not in a


def test_ml_client_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ML_SERVICE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("ML_SERVICE_TIMEOUT", "1.5")
    monkeypatch.setenv("ML_SERVICE_ENABLED", "true")
    c = MLClient.from_env()
    assert c._enabled
    assert c._timeout == 1.5
