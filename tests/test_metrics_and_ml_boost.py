"""metrics_exporter + ml_client ek dallar (kapsam)."""

from __future__ import annotations

import json
from unittest import mock

import pytest
from super_otonom.decision_context import DecisionContext
from super_otonom.metrics_exporter import MetricsExporter


def test_metrics_start_http_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    m_mod = __import__("super_otonom.metrics_exporter", fromlist=["*"])
    if not getattr(m_mod, "start_http_server", None):
        pytest.skip("prometheus_client yok")
    with mock.patch.object(m_mod, "start_http_server", side_effect=OSError("bind")):
        m = MetricsExporter(port=18080, namespace="t_bind")
    assert m.is_active


def test_metrics_update_coerces_and_skips_bad_values() -> None:
    m = MetricsExporter(port=0, namespace="t_coerce")
    if not m.is_active:
        pytest.skip("prometheus yok")
    m.update(
        {
            "equity": "bad",
            "free_capital": 100.0,
            "emergency_stop": True,
            "win_rate": None,
            "dynamic_daily_limit": 4.0,
        }
    )
    m.update_circuit_breakers({"S": "OPEN (x)"})
    m.update_circuit_breakers({"S": "CLOSED"})
    m.record_slippage("B", 0.0, 1.0)
    m.record_trade(float("nan"), "x")


def test_metrics_record_analysis_regime_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    m = MetricsExporter(port=0, namespace="t_an")
    if not m.is_active:
        pytest.skip("prometheus yok")
    m.record_analysis({"symbol": "Z", "hurst": 0.5, "volatility": 0.1, "regime": "WEIRD_NEW"})
    gl = m._gauges.get("regime")
    if gl and hasattr(gl, "labels"):
        with mock.patch.object(gl, "labels", side_effect=TypeError("x")):
            m.record_analysis({"symbol": "Z", "regime": "TRENDING"})


def test_ml_client_parse_and_inference_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    from super_otonom import ml_client as mc

    c = mc.MLClient(service_url="http://127.0.0.1:9", enabled=True)
    assert c._parse_response_body(b"notjson") == {}
    assert c._parse_response_body(b"") == {}
    b = c._parse_response_body(json.dumps([1, 2, 3]).encode())
    assert b == {}

    async def run1():
        with mock.patch.object(c, "_sync_http_post", return_value=(b'{"score":"x"}', 1.0)):
            r = await c.fetch_inference("S", {"signal": "HOLD"}, tick_id=1)
        assert r.error == "score_not_float"

    import asyncio

    asyncio.run(run1())

    async def run2():
        with mock.patch.object(c, "_sync_http_post", side_effect=OSError("net")):
            r = await c.fetch_inference("S", {"signal": "HOLD"}, tick_id=1)
        assert r.error == "OSError"

    asyncio.run(run2())

    async def run3():
        with mock.patch.object(c, "_sync_http_post", return_value=(b'{"foo":1}', 2.0)):
            r = await c.fetch_inference("S", {"signal": "HOLD"}, tick_id=1)
        assert r.error == "no_score_field"

    asyncio.run(run3())

    dctx = DecisionContext.start("S", 1, {})
    mc.reset_ml_client_for_tests()
    monkeypatch.setenv("ML_SERVICE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("ML_SERVICE_ENABLED", "true")

    async def run4():
        ce = mc.MLClient(service_url="http://127.0.0.1:9", enabled=True)
        a: dict = {"signal": "BUY"}
        with mock.patch.object(ce, "fetch_inference") as fi:
            fi.return_value = mc.MLInferenceResult(0.7, {"x": 1}, 3.0, None)
            await ce.enrich_analysis("S", a, dctx, tick_id=2)
        assert a.get("ml_score") == 0.7

    asyncio.run(run4())
    mc.reset_ml_client_for_tests()
    monkeypatch.delenv("ML_SERVICE_URL", raising=False)
    monkeypatch.delenv("ML_SERVICE_ENABLED", raising=False)
