"""data_freshness — STALE / ZAMAN_KAYMASI / Redis kline eşikleri."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.fastrun


def test_max_candle_age_ms_tracks_stale_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    from super_otonom import data_freshness as df

    monkeypatch.setenv("TIMEFRAME", "1h")
    monkeypatch.delenv("POSITION_SIZER_MAX_DATA_AGE_MS", raising=False)
    monkeypatch.delenv("STALE_DATA_THRESHOLD_SEC", raising=False)
    sec = df.stale_threshold_sec()
    assert df.max_candle_age_ms() == float(sec * 1000)


def test_position_sizer_max_data_age_ms_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from super_otonom.data_freshness import max_candle_age_ms

    monkeypatch.setenv("POSITION_SIZER_MAX_DATA_AGE_MS", "999000")
    assert max_candle_age_ms() == 999000.0


def test_redis_kline_max_age_ms_default_5m_buffer(monkeypatch: pytest.MonkeyPatch) -> None:
    from super_otonom.data_freshness import redis_kline_max_age_ms

    monkeypatch.delenv("REDIS_KLINE_MAX_AGE_MS", raising=False)
    monkeypatch.setenv("REDIS_KLINE_TIMEFRAME", "5m")
    monkeypatch.setenv("REDIS_KLINE_TIMEFRAME_BUFFER_SEC", "90")
    assert redis_kline_max_age_ms() == float((300 + 90) * 1000)
