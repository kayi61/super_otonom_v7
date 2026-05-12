"""exchange_async: OHLCV dönüştürme ve sahte veri yolu."""

from __future__ import annotations

from super_otonom.exchange_async import ohlcv_to_candles


def test_ohlcv_to_candles_parses_rows() -> None:
    raw = [
        [1_000_000.0, 10.0, 11.0, 9.0, 10.5, 100.0],
        [1_000_300.0, 10.5, 12.0, 10.0, 11.0, 120.0],
    ]
    out = ohlcv_to_candles(raw)
    assert len(out) == 2
    assert out[0]["close"] == 10.5
    assert out[1]["volume"] == 120.0
    assert "timestamp" in out[0]


def test_ohlcv_to_candles_skips_short_rows() -> None:
    raw = [
        [1.0, 2.0, 3.0],  # too short
        [1_000_000.0, 10.0, 11.0, 9.0, 10.5, 100.0],
    ]
    out = ohlcv_to_candles(raw)
    assert len(out) == 1
