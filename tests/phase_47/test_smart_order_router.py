"""Faz 47 — smart_order_router birim testleri.

Test edilen modül: super_otonom.smart_order_router
Fonksiyon: compute_smart_order_route — venue seçimi + yönlendirme.
"""

from __future__ import annotations

import time
from typing import Any, Dict

import pytest
from super_otonom.smart_order_router import (
    SmartOrderRouteResult,
    compute_smart_order_route,
)

# ---------------------------------------------------------------------------
# Stub helpers
# ---------------------------------------------------------------------------


def _phase74(
    *,
    leader: str = "binance",
    pref: str = "leader",
    latency_arb: int = 20,
) -> Dict[str, Any]:
    return {
        "leader_venue": leader,
        "route_preference": pref,
        "latency_arb_risk": latency_arb,
    }


def _phase80(
    *,
    action: str = "ENTER",
    perm: str = "ALLOW",
) -> Dict[str, Any]:
    return {"final_action": action, "trade_permission": perm}


def _phase76(*, mode: str = "normal") -> Dict[str, Any]:
    return {"regime_execution_mode": mode}


def _venues(**kw: Any) -> Dict[str, Dict[str, Any]]:
    base = {
        "binance": {"latency_ms": 25, "fee_pct": 0.001},
        "bybit": {"latency_ms": 40, "fee_pct": 0.001},
        "okx": {"latency_ms": 55, "fee_pct": 0.0008},
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# Result dataclass testi
# ---------------------------------------------------------------------------


class TestSmartOrderRouteResult:
    def test_to_dict(self) -> None:
        r = SmartOrderRouteResult(
            preferred_venue="binance",
            route_preference="leader",
            leader_venue="binance",
            execution_mode="normal",
            reason="leader_present",
            venues_available=3,
            event_ts=1000,
            half_life_ms=20000,
        )
        d = r.to_dict()
        assert d["preferred_venue"] == "binance"
        assert d["venues_available"] == 3
        assert isinstance(d, dict)

    def test_frozen(self) -> None:
        r = SmartOrderRouteResult(
            preferred_venue="binance",
            route_preference="leader",
            leader_venue="binance",
            execution_mode="normal",
            reason="test",
            venues_available=1,
            event_ts=1000,
            half_life_ms=20000,
        )
        with pytest.raises(AttributeError):
            r.preferred_venue = "bybit"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Normal routing — leader venue present
# ---------------------------------------------------------------------------


class TestLeaderRouting:
    def test_leader_present_selected(self) -> None:
        r = compute_smart_order_route(
            symbol="BTC/USDT",
            analysis={"venues": _venues()},
            phase74=_phase74(leader="binance"),
            phase80=_phase80(),
            event_ts=int(time.time() * 1000),
        )
        assert r.preferred_venue == "binance"
        assert r.reason == "leader_present"
        assert r.venues_available == 3

    def test_leader_not_in_venues_fallback(self) -> None:
        r = compute_smart_order_route(
            symbol="BTC/USDT",
            analysis={"venues": {"bybit": {"latency_ms": 30}, "okx": {"latency_ms": 50}}},
            phase74=_phase74(leader="binance"),
            phase80=_phase80(),
            event_ts=int(time.time() * 1000),
        )
        # binance not in venues → fallback to first
        assert r.preferred_venue in ("bybit", "okx")
        assert r.reason == "fallback_first_venue"


# ---------------------------------------------------------------------------
# BLOCK / HALT → no venue
# ---------------------------------------------------------------------------


class TestBlockedRouting:
    def test_block_permission_empty_venue(self) -> None:
        r = compute_smart_order_route(
            symbol="BTC/USDT",
            analysis={"venues": _venues()},
            phase74=_phase74(),
            phase80=_phase80(perm="BLOCK"),
            event_ts=int(time.time() * 1000),
        )
        assert r.preferred_venue == ""
        assert r.reason == "blocked_or_halt"

    def test_halt_permission_empty_venue(self) -> None:
        r = compute_smart_order_route(
            symbol="BTC/USDT",
            analysis={"venues": _venues()},
            phase74=_phase74(),
            phase80=_phase80(perm="HALT"),
            event_ts=int(time.time() * 1000),
        )
        assert r.preferred_venue == ""

    def test_halt_action_empty_venue(self) -> None:
        r = compute_smart_order_route(
            symbol="BTC/USDT",
            analysis={"venues": _venues()},
            phase74=_phase74(),
            phase80=_phase80(action="HALT", perm="ALLOW"),
            event_ts=int(time.time() * 1000),
        )
        assert r.preferred_venue == ""
        assert r.reason == "blocked_or_halt"


# ---------------------------------------------------------------------------
# Crisis mode → lowest latency venue
# ---------------------------------------------------------------------------


class TestCrisisMode:
    def test_crisis_selects_lowest_latency(self) -> None:
        venues = {
            "binance": {"latency_ms": 100},
            "bybit": {"latency_ms": 15},
            "okx": {"latency_ms": 200},
        }
        r = compute_smart_order_route(
            symbol="BTC/USDT",
            analysis={"venues": venues},
            phase74=_phase74(leader="okx"),
            phase80=_phase80(),
            phase76=_phase76(mode="crisis"),
            event_ts=int(time.time() * 1000),
        )
        assert r.preferred_venue == "bybit"
        assert "crisis" in r.reason or "latency" in r.reason

    def test_crisis_no_latency_data_fallback(self) -> None:
        venues = {
            "binance": {"fee_pct": 0.001},  # no latency_ms
            "bybit": {"fee_pct": 0.001},
        }
        r = compute_smart_order_route(
            symbol="BTC/USDT",
            analysis={"venues": venues},
            phase74=_phase74(leader="binance"),
            phase80=_phase80(),
            phase76=_phase76(mode="crisis"),
            event_ts=int(time.time() * 1000),
        )
        # No latency data → falls through crisis path to leader check
        assert r.preferred_venue == "binance"


# ---------------------------------------------------------------------------
# No venues
# ---------------------------------------------------------------------------


class TestNoVenues:
    def test_no_venues_use_leader_hint(self) -> None:
        r = compute_smart_order_route(
            symbol="BTC/USDT",
            analysis={},
            phase74=_phase74(leader="binance"),
            phase80=_phase80(),
            event_ts=int(time.time() * 1000),
        )
        assert r.preferred_venue == "binance"
        assert r.reason == "no_venues_use_leader_hint"
        assert r.venues_available == 0

    def test_no_venues_no_leader(self) -> None:
        r = compute_smart_order_route(
            symbol="BTC/USDT",
            analysis={},
            phase74=_phase74(leader=""),
            phase80=_phase80(),
            event_ts=int(time.time() * 1000),
        )
        assert r.preferred_venue == ""
        assert r.venues_available == 0


# ---------------------------------------------------------------------------
# Timestamp ve half_life
# ---------------------------------------------------------------------------


class TestTimestamps:
    def test_event_ts_provided(self) -> None:
        ts = 1700000000000
        r = compute_smart_order_route(
            symbol="BTC/USDT",
            analysis={"venues": _venues()},
            phase74=_phase74(),
            phase80=_phase80(),
            event_ts=ts,
        )
        assert r.event_ts == ts

    def test_event_ts_none_uses_now(self) -> None:
        before = int(time.time() * 1000)
        r = compute_smart_order_route(
            symbol="BTC/USDT",
            analysis={"venues": _venues()},
            phase74=_phase74(),
            phase80=_phase80(),
        )
        after = int(time.time() * 1000) + 100
        assert before <= r.event_ts <= after

    def test_half_life_clamped(self) -> None:
        r = compute_smart_order_route(
            symbol="BTC/USDT",
            analysis={"venues": _venues()},
            phase74=_phase74(),
            phase80=_phase80(),
            half_life_ms=1,  # too small
            event_ts=int(time.time() * 1000),
        )
        assert r.half_life_ms >= 2000

        r2 = compute_smart_order_route(
            symbol="BTC/USDT",
            analysis={"venues": _venues()},
            phase74=_phase74(),
            phase80=_phase80(),
            half_life_ms=999999,  # too large
            event_ts=int(time.time() * 1000),
        )
        assert r2.half_life_ms <= 300000


# ---------------------------------------------------------------------------
# Execution mode propagation
# ---------------------------------------------------------------------------


class TestExecutionMode:
    def test_execution_mode_from_phase76(self) -> None:
        r = compute_smart_order_route(
            symbol="BTC/USDT",
            analysis={"venues": _venues()},
            phase74=_phase74(),
            phase80=_phase80(),
            phase76=_phase76(mode="twap_only"),
            event_ts=int(time.time() * 1000),
        )
        assert r.execution_mode == "twap_only"

    def test_no_phase76_unknown_mode(self) -> None:
        r = compute_smart_order_route(
            symbol="BTC/USDT",
            analysis={"venues": _venues()},
            phase74=_phase74(),
            phase80=_phase80(),
            phase76=None,
            event_ts=int(time.time() * 1000),
        )
        assert r.execution_mode == "unknown"


# ---------------------------------------------------------------------------
# Edge cases — None inputs, malformed data
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_phase74_none_fields(self) -> None:
        r = compute_smart_order_route(
            symbol="BTC/USDT",
            analysis={"venues": _venues()},
            phase74={"leader_venue": None, "route_preference": None},
            phase80=_phase80(),
            event_ts=int(time.time() * 1000),
        )
        assert r.leader_venue == ""
        assert r.route_preference == "unknown"

    def test_venues_with_invalid_latency(self) -> None:
        venues = {
            "binance": {"latency_ms": "not_a_number"},
            "bybit": {"latency_ms": 20},
        }
        r = compute_smart_order_route(
            symbol="BTC/USDT",
            analysis={"venues": venues},
            phase74=_phase74(leader=""),
            phase80=_phase80(),
            phase76=_phase76(mode="crisis"),
            event_ts=int(time.time() * 1000),
        )
        # invalid latency skipped, bybit selected
        assert r.preferred_venue == "bybit"

    def test_venues_not_dict(self) -> None:
        r = compute_smart_order_route(
            symbol="BTC/USDT",
            analysis={"venues": "invalid"},
            phase74=_phase74(leader="binance"),
            phase80=_phase80(),
            event_ts=int(time.time() * 1000),
        )
        assert r.preferred_venue == "binance"
        assert r.reason == "no_venues_use_leader_hint"
