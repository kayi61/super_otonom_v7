"""Hızlı audit düzeltmeleri — Sharpe annualize, main_loop finally, data_freshness."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from super_otonom.data_freshness import periods_per_year_from_timeframe

pytestmark = pytest.mark.fastrun

_ROOT = Path(__file__).resolve().parents[1]


def test_periods_per_year_1h_crypto_24_7() -> None:
    ppy = periods_per_year_from_timeframe("1h")
    assert 8700 < ppy < 8800


def test_periods_per_year_5m() -> None:
    ppy = periods_per_year_from_timeframe("5m")
    assert 105_000 < ppy < 106_000


def test_main_loop_finally_ws_vars_initialized_before_try() -> None:
    src = (_ROOT / "super_otonom" / "main_loop.py").read_text(encoding="utf-8")
    main_idx = src.index("async def main()")
    try_idx = src.index("    try:", main_idx)
    chunk = src[main_idx:try_idx]
    assert "_ws_manager" in chunk and "= None" in chunk
    assert "_ws_task" in chunk


def test_backtester_uses_resolve_periods_per_year() -> None:
    src = (_ROOT / "super_otonom" / "backtester.py").read_text(encoding="utf-8")
    assert "resolve_periods_per_year" in src
    ast.parse(src)
    assert "252.0 * 24.0 * 12.0" not in src
