"""Hata / geçersiz veri / ağ benzeri koşullar (mock, 80)."""

from __future__ import annotations

import contextlib
from unittest import mock

import pytest
import super_otonom.signals.sentiment_layer as slm
from super_otonom.ai_confidence_bridge import blend_omega_confidence
from super_otonom.kill_switch import is_ratelimit_error
from super_otonom.metrics_exporter import MetricsExporter
from super_otonom.pre_trade_gate import merge_entry_notional
from super_otonom.risk_manager import RiskManager
from super_otonom.signals.sentiment_layer import SentimentLayer


def _e429() -> BaseException:
    e = RuntimeError("http")
    e.code = 429
    return e


def _e418() -> BaseException:
    e = RuntimeError("teapot")
    e.code = 418
    return e


@pytest.mark.parametrize(
    "exc",
    [
        type("DDoSX", (Exception,), {})(),
        type("RateLimitX", (Exception,), {})(),
        _e429(),
        _e418(),
        Exception("too many requests for url"),
        Exception("you are banned"),
        Exception("http 429 error code"),
        Exception(" 429 "),
        Exception("429"),
        type("DDoSProtection", (Exception,), {})(),
    ],
)
def test_error_is_ratelimit_positive(exc: BaseException) -> None:
    assert is_ratelimit_error(exc) is True


@pytest.mark.parametrize(
    "exc",
    [
        Exception("normal failure"),
        Exception(""),
        ValueError("not rate limit"),
        KeyError("k"),
        RuntimeError("500"),
    ],
)
def test_error_is_ratelimit_negative(exc: BaseException) -> None:
    assert is_ratelimit_error(exc) is False


@pytest.mark.parametrize(
    "base, payload",
    [
        (0.5, {}),
        (0.2, {"ml_score": None}),
        (0.9, {"omega_ml_score": None}),
        (0.6, {"ml_score": "nope"}),
        (0.7, {"ml_confidence": {}}),
        (0.55, {"ml_score": float("nan")}),
        (0.4, {"omega_ml_confidence": 0.99}),
        (0.8, {"ml_score": -1}),
        (0.3, {"ml_score": 2}),
        (0.66, {"omega_ml_score": 0.1}),
    ],
)
def test_error_blend_malformed_or_edge_ml_fields(base: float, payload: dict) -> None:
    c, note = blend_omega_confidence(base, payload)
    assert 0.0 <= c <= 1.0
    assert isinstance(note, str) and note


@pytest.mark.parametrize(
    "tech, ob",
    [
        (-50.0, 100.0),
        (10.0, {1, 2}),
        (10.0, []),
        (0.0, "x"),
        (1e9, object()),
    ],
)
def test_error_merge_notional_bad_types(tech: float, ob: object) -> None:
    n, src, blk = merge_entry_notional(tech, ob)
    assert n >= 0.0
    assert isinstance(src, str)
    assert isinstance(blk, str)


@pytest.mark.parametrize("n", range(20))
def test_error_metrics_slippage_non_positive_expected(n: int) -> None:
    m = MetricsExporter(port=0, namespace=f"err_met_{n}")
    m.record_slippage("S", 0.0, 100.0 + n)
    m.record_slippage("S", -1.0, 100.0)


@pytest.mark.parametrize("n", range(20))
def test_error_sentiment_urlopen_timeout(n: int) -> None:
    s = SentimentLayer(api_url=f"http://fake-{n}.test/")

    @contextlib.contextmanager
    def boom(*_a, **_k):
        raise TimeoutError("simulated")

    with mock.patch.object(slm.urllib.request, "urlopen", boom):
        assert s._fetch_from_api() is None


@pytest.mark.parametrize("raw", ('{"broken":', "{]", "not-json", "", "null"))
def test_error_sentiment_json_decode(raw: str) -> None:
    s = SentimentLayer(api_url="http://x/")

    @contextlib.contextmanager
    def u(_r, **_k):
        class B:
            def read(self) -> bytes:
                return raw.encode("utf-8", errors="ignore")

        yield B()

    with mock.patch.object(slm.urllib.request, "urlopen", u):
        assert s._fetch_from_api() is None


@pytest.mark.parametrize("n", range(5))
def test_error_risk_with_large_numbers(n: int) -> None:
    rm = RiskManager(max(1.0, 10 ** (n % 4)))
    rm.check_risk(
        float(n * 1_000_000), open_exposure=float(n % 7) * 1e6, current_vol=0.01 + n * 0.001
    )
    assert isinstance(rm.get_last_deny(), str)
