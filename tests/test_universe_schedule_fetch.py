"""universe_schedule_fetch — ccxt mock, ağ yok."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from super_otonom.universe_schedule_fetch import (
    _ohlcv_window_ms,
    _top_usdt_symbols,
    entries_to_schedule,
    fetch_schedule_entries,
    main,
)

pytestmark = pytest.mark.fastrun


def test_entries_to_schedule_active_and_delisted() -> None:
    rows = entries_to_schedule(
        [
            {"symbol": "BTC/USDT", "active_from_ms": 1000.0, "active_until_ms": None},
            {"symbol": "X/USDT", "active_from_ms": None},
            {
                "symbol": "OCEAN/USDT",
                "active_from_ms": 2000.0,
                "active_until_ms": 3000.0,
            },
        ]
    )
    assert len(rows) == 2
    assert rows[1]["symbol"] == "OCEAN/USDT"
    assert rows[1]["active_until_ms"] == 3000.0


def test_ohlcv_window_ms_tail_and_head() -> None:
    ex = MagicMock()
    ex.fetch_ohlcv.side_effect = [
        [[1000, 1, 2, 0, 1, 0], [2000, 1, 2, 0, 1, 0]],
        [[500, 1, 2, 0, 1, 0]],
    ]
    win = _ohlcv_window_ms(ex, "BTC/USDT", timeframe="1d")
    assert win is not None
    assert win[0] == 500.0
    assert win[1] == 2000.0
    assert win[2] == 2


def test_ohlcv_window_ms_empty_returns_none() -> None:
    ex = MagicMock()
    ex.fetch_ohlcv.return_value = []
    assert _ohlcv_window_ms(ex, "BTC/USDT") is None


def test_ohlcv_window_ms_exception_returns_none() -> None:
    ex = MagicMock()
    ex.fetch_ohlcv.side_effect = RuntimeError("network")
    assert _ohlcv_window_ms(ex, "BTC/USDT") is None


def test_top_usdt_symbols_sorted_by_volume() -> None:
    ex = MagicMock()
    ex.load_markets.return_value = {
        "AAA/USDT": {"quote": "USDT", "spot": True, "active": True},
        "BBB/USDT": {"quote": "USDT", "spot": True, "active": True},
    }
    ex.fetch_ticker.side_effect = [
        {"quoteVolume": 100.0},
        {"quoteVolume": 500.0},
    ]
    out = _top_usdt_symbols(ex, 1)
    assert out == ["BBB/USDT"]


def test_fetch_schedule_entries_active_and_no_data() -> None:
    ex = MagicMock()
    ex.markets = {
        "BTC/USDT": {"active": True},
        "OLD/USDT": {"active": False},
    }
    ex.rateLimit = 100

    def _fetch(sym: str, timeframe: str = "1d", limit: int = 1000, since: int | None = None):
        if sym == "BTC/USDT":
            if since:
                return [[1000, 1, 1, 1, 1, 1]]
            return [[1000, 1, 1, 1, 1, 1], [2000, 1, 1, 1, 1, 1]]
        return []

    ex.fetch_ohlcv.side_effect = _fetch

    with patch(
        "super_otonom.universe_schedule_fetch._make_exchange", return_value=ex
    ):
        rows = fetch_schedule_entries(["BTC/USDT", "OLD/USDT"], timeframe="1d")

    assert len(rows) == 2
    btc = next(r for r in rows if r["symbol"] == "BTC/USDT")
    old = next(r for r in rows if r["symbol"] == "OLD/USDT")
    assert btc["active_until_ms"] is None
    assert btc["status"] == "active"
    assert old["status"] == "no_data"


def test_main_writes_schedule(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "sched.json"
    meta = tmp_path / "meta.json"
    fake_rows = [
        {
            "symbol": "BTC/USDT",
            "active_from_ms": 1000.0,
            "active_until_ms": None,
            "status": "active",
            "market_active": True,
            "ohlcv_bars_sampled": 2,
            "last_bar_ms": 2000.0,
        },
        {
            "symbol": "ETH/USDT",
            "active_from_ms": 1000.0,
            "active_until_ms": None,
            "status": "active",
            "market_active": True,
            "ohlcv_bars_sampled": 2,
            "last_bar_ms": 2000.0,
        },
    ]
    monkeypatch.setattr(
        "super_otonom.universe_schedule_fetch.fetch_schedule_entries",
        lambda *a, **k: fake_rows,
    )
    assert (
        main(
            [
                "--symbols",
                "BTC/USDT,ETH/USDT",
                "--no-delist",
                "--out",
                str(out),
                "--meta-out",
                str(meta),
            ]
        )
        == 0
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data) == 2
    assert meta.is_file()


def test_main_json_stdout(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    fake_rows = [
        {
            "symbol": "BTC/USDT",
            "active_from_ms": 1.0,
            "active_until_ms": None,
            "status": "active",
            "market_active": True,
        },
        {
            "symbol": "ETH/USDT",
            "active_from_ms": 1.0,
            "active_until_ms": None,
            "status": "active",
            "market_active": True,
        },
    ]
    monkeypatch.setattr(
        "super_otonom.universe_schedule_fetch.fetch_schedule_entries",
        lambda *a, **k: fake_rows,
    )
    assert main(["--symbols", "BTC/USDT,ETH/USDT", "--no-delist", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 2


def test_main_default_core_and_top_n(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ex = MagicMock()
    monkeypatch.setattr(
        "super_otonom.universe_schedule_fetch._make_exchange", lambda: ex
    )
    monkeypatch.setattr(
        "super_otonom.universe_schedule_fetch._top_usdt_symbols",
        lambda _ex, _n: ["ADA/USDT"],
    )
    fake_rows = [
        {
            "symbol": s,
            "active_from_ms": 1.0,
            "active_until_ms": None,
            "status": "active",
            "market_active": True,
        }
        for s in ("BTC/USDT", "ETH/USDT", "ADA/USDT")
    ]
    monkeypatch.setattr(
        "super_otonom.universe_schedule_fetch.fetch_schedule_entries",
        lambda *a, **k: fake_rows,
    )
    out = tmp_path / "s.json"
    assert main(["--no-delist", "--out", str(out), "--top-n", "1"]) == 0


def test_main_fails_when_schedule_too_small(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "super_otonom.universe_schedule_fetch.fetch_schedule_entries",
        lambda *a, **k: [
            {
                "symbol": "BTC/USDT",
                "active_from_ms": 1.0,
                "active_until_ms": None,
                "status": "active",
                "market_active": True,
            }
        ],
    )
    assert (
        main(
            [
                "--symbols",
                "BTC/USDT",
                "--no-delist",
                "--out",
                str(tmp_path / "s.json"),
            ]
        )
        == 1
    )
