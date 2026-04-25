"""apply_liquidity_context — oran + entry_scale sözleşmesi."""
from __future__ import annotations

import pytest
from super_otonom.analyzer import MarketAnalyzer


def test_liquidity_blocked_when_ob_zero() -> None:
    a: dict = {}
    MarketAnalyzer.apply_liquidity_context(a, 0.0, 100.0)
    assert a["entry_scale"] == "blocked"
    assert a["liquidity_ratio"] == 0.0


def test_liquidity_full_when_ratio_high() -> None:
    a: dict = {}
    MarketAnalyzer.apply_liquidity_context(a, 100.0, 100.0)
    assert a["liquidity_ratio"] == 1.0
    assert a["entry_scale"] == "full"


def test_liquidity_scaled_mid() -> None:
    a: dict = {}
    # 50/100 = 0.5 — 0.3 ile 0.8 arası → scaled
    MarketAnalyzer.apply_liquidity_context(a, 50.0, 100.0)
    assert a["entry_scale"] == "scaled"
    assert a["liquidity_ratio"] == 0.5


def test_liquidity_minimal_low() -> None:
    a: dict = {}
    MarketAnalyzer.apply_liquidity_context(a, 20.0, 100.0)
    assert a["entry_scale"] == "minimal"
    assert a["liquidity_ratio"] == 0.2


def test_liquidity_unknown_no_ob(monkeypatch: pytest.MonkeyPatch) -> None:
    a: dict = {}
    MarketAnalyzer.apply_liquidity_context(a, None, 100.0)
    assert a["entry_scale"] == "unknown"
    assert a["liquidity_ratio"] is None


def test_liquidity_unknown_zero_target() -> None:
    a: dict = {}
    MarketAnalyzer.apply_liquidity_context(a, 50.0, 0.0)
    assert a["entry_scale"] == "unknown"
    assert a["liquidity_ratio"] is None
