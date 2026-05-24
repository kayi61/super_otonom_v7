"""SentimentLayer: API, önbellek, eşikler, veto."""

from __future__ import annotations

import contextlib
import importlib
import json
import sys
import time
import types
from unittest import mock

import pytest
import super_otonom.signals.sentiment_layer as slm
from super_otonom.signals.sentiment_layer import SentimentLayer, _dynamic_fallback_score


@contextlib.contextmanager
def _fake_urlopen(_req, **kw):
    raw = json.dumps({"data": [{"value": 25}]}).encode()

    class _R:
        def read(self) -> bytes:
            return raw

    yield _R()


def test_fetch_from_api_fear_greed_format() -> None:
    s = SentimentLayer(api_url="http://test.example/fg", api_key="")
    with mock.patch.object(slm.urllib.request, "urlopen", _fake_urlopen):
        v = s._fetch_from_api()
    assert v is not None
    assert 0.0 <= v <= 1.0


def test_fetch_from_api_score_key() -> None:
    raw = json.dumps({"score": 0.42}).encode()

    @contextlib.contextmanager
    def u(_r, **kw):
        class _B:
            def read(self) -> bytes:
                return raw

        yield _B()

    s = SentimentLayer(api_url="http://x/s")
    with mock.patch.object(slm.urllib.request, "urlopen", u):
        v = s._fetch_from_api()
    assert v == 0.42


def test_fetch_from_api_error_returns_none() -> None:
    s = SentimentLayer(api_url="http://x/s")
    with mock.patch.object(slm.urllib.request, "urlopen", side_effect=OSError("e")):
        assert s._fetch_from_api() is None


def test_get_market_sentiment_cache_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    s = SentimentLayer()
    s.clear_mock()
    s._api_url = "http://c"
    monkeypatch.setattr(slm, "_CACHE_TTL_SEC", 3600)
    s._cache = {"score": 0.5, "status": "NEUTRAL", "source": "x"}
    s._cache_ts = time.time()
    r1 = s.get_market_sentiment()
    r2 = s.get_market_sentiment()
    assert r1 == r2


def test_bearish_and_bullish_status_from_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = SentimentLayer(api_url="http://a")
    monkeypatch.setattr(s, "_fetch_from_api", lambda: 0.1)
    s._cache = None
    s._cache_ts = 0.0
    r = s.get_market_sentiment()
    assert r["status"] == "BEARISH_PANIC"
    monkeypatch.setattr(s, "_fetch_from_api", lambda: 0.99)
    s._cache = None
    s._cache_ts = 0.0
    r2 = s.get_market_sentiment()
    assert r2["status"] == "BULLISH_EUPHORIA"


def test_dynamic_fallback_by_utc_hour() -> None:
    with mock.patch("super_otonom.signals.sentiment_layer.datetime.datetime") as mdt:
        for hour, expected in [
            (3, 0.45),
            (10, 0.50),
            (16, 0.55),
            (23, 0.48),
        ]:
            mdt.now.return_value.hour = hour
            v = _dynamic_fallback_score()
            assert abs(v - expected) < 0.001


def test_http_import_error_sets_flag() -> None:
    """48-53: urllib.request yüklenemezse _HTTP_AVAILABLE False."""
    urllib_stash = {
        k: sys.modules.pop(k) for k in list(sys.modules) if k == "urllib" or k.startswith("urllib.")
    }
    saved_sl = sys.modules.pop("super_otonom.signals.sentiment_layer", None)
    try:
        sys.modules["urllib"] = types.ModuleType("urllib")
        mod = importlib.import_module("super_otonom.signals.sentiment_layer")
        assert mod._HTTP_AVAILABLE is False
    finally:
        sys.modules.pop("super_otonom.signals.sentiment_layer", None)
        for k in list(sys.modules):
            if k == "urllib" or k.startswith("urllib."):
                sys.modules.pop(k, None)
        sys.modules.update(urllib_stash)
        if saved_sl is not None:
            sys.modules["super_otonom.signals.sentiment_layer"] = saved_sl
        importlib.import_module("super_otonom.signals.sentiment_layer")


def test_fetch_from_api_sends_bearer_when_key_set() -> None:
    """77-78: Authorization başlığı."""
    captured: dict = {}

    @contextlib.contextmanager
    def u(req, **kw):
        gh = getattr(req, "get_header", None)
        captured["auth"] = gh("Authorization") if callable(gh) else ""
        raw = json.dumps({"data": [{"value": 50}]}).encode()

        class _B:
            def read(self) -> bytes:
                return raw

        yield _B()

    s = SentimentLayer(api_url="http://example/fg", api_key="secret")
    with mock.patch.object(slm.urllib.request, "urlopen", u):
        assert s._fetch_from_api() == 0.5
    assert "Bearer" in (captured.get("auth") or "")


def test_fetch_from_api_empty_data_uses_score_key() -> None:
    """82-86: data boş → score anahtarı."""
    raw = json.dumps({"data": [], "score": 0.37}).encode()

    @contextlib.contextmanager
    def u(_r, **kw):
        class _B:
            def read(self) -> bytes:
                return raw

        yield _B()

    s = SentimentLayer(api_url="http://x/s")
    with mock.patch.object(slm.urllib.request, "urlopen", u):
        assert abs(s._fetch_from_api() - 0.37) < 1e-9


def test_validate_with_sentiment_fetches_when_none() -> None:
    """134-135: sentiment=None → get_market_sentiment."""
    s = SentimentLayer(mock_score=0.5)
    sig, reason = s.validate_with_sentiment("BUY", None)
    assert sig == "BUY"
    assert "SENTIMENT_OK" in reason
