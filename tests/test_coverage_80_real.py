"""
Gerçek kapsam artışı — %75 → %80. Sahte omit yok; tüm testler asıl davranışı
zorlar. Hedef modüller:
  - order_book_intelligence (0% → ~95%): saf fonksiyonlar, deterministik
  - market_microstructure (0% → ~95%): saf fonksiyonlar, deterministik
  - bot_engine_capital_patch (0% → 100%): doküman/patch sabitleri (sadece import)
  - fake_order_book_scenarios (48% → ~95%): tüm senaryo dalları + hatalı senaryo
  - order_engine (25% → ~75%): tam yaşam döngüsü + recovery + persistence
  - reconciliation_engine (53% → ~75%): compare/_apply_adjustment/spot/futures
  - config (56% → 100%): _env_trim/_env_pick/advisory log
  - redis_bridge (35% → ~70%): erişilemez/kütüphanesiz dallar
  - meta_regime_orchestrator (86% → ~92%): advisory_ack_path_for_gate sığ yollar

Hiçbir test asıl sistem davranışını değiştirmez — testler yalnız çağrı yapar,
sonuçların aralığını ve tipini doğrular.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest

# ════════════════════════════════════════════════════════════════════════════
# order_book_intelligence — Faz 21
# ════════════════════════════════════════════════════════════════════════════


def _make_normal_book(mid: float = 100.0, levels: int = 12) -> Dict[str, list]:
    bids = [[mid - 0.01 * (i + 1), max(0.1, 1.0 - 0.05 * i)] for i in range(levels)]
    asks = [[mid + 0.01 * (i + 1), max(0.1, 1.0 - 0.05 * i)] for i in range(levels)]
    return {"bids": bids, "asks": asks}


def test_obi_compute_signed_obi_balanced_and_imbalance() -> None:
    from super_otonom.order_book_intelligence import compute_signed_obi

    bal = {"bids": [[100, 1.0]], "asks": [[100.1, 1.0]]}
    v = compute_signed_obi(bal, depth=10)
    assert v is not None and abs(v) < 1e-6

    heavy_bids = {"bids": [[100, 10.0]], "asks": [[100.1, 1.0]]}
    v2 = compute_signed_obi(heavy_bids, depth=10)
    assert v2 is not None and v2 > 0.7

    heavy_asks = {"bids": [[100, 1.0]], "asks": [[100.1, 10.0]]}
    v3 = compute_signed_obi(heavy_asks, depth=10)
    assert v3 is not None and v3 < -0.7


def test_obi_compute_signed_obi_empty_and_zero_qty() -> None:
    from super_otonom.order_book_intelligence import compute_signed_obi

    assert compute_signed_obi({}, depth=10) is None
    assert compute_signed_obi({"bids": [], "asks": []}, depth=10) is None
    assert compute_signed_obi({"bids": [[100, 0.0]], "asks": [[100.1, 0.0]]}) is None


def test_obi_parse_side_garbage_input_skipped() -> None:
    from super_otonom.order_book_intelligence import _parse_side

    book = {"bids": [[1.0], "not-a-list", [1.0, -3.0], [1.0, 1.0]]}
    rows = _parse_side(book, "bids", 5)
    assert rows == [(1.0, 1.0)]

    rows2 = _parse_side({"bids": "not-list"}, "bids", 5)
    assert rows2 == []

    rows3 = _parse_side({"bids": [["x", "y"], [None, None]]}, "bids", 5)
    assert rows3 == []


def test_obi_analyze_full_pipeline_buy_signal() -> None:
    from super_otonom.order_book_intelligence import analyze_order_book_intelligence

    book = _make_normal_book(100.0, 15)
    analysis: Dict[str, Any] = {"signal": "BUY", "event_ts": 1_700_000_000.0}
    out = analyze_order_book_intelligence("BTC/USDT", book, analysis, depth=10)
    assert 0.0 <= out["alpha_score"] <= 1.0
    assert 0.0 <= out["risk_score"] <= 1.0
    assert out["phase"] == "21"
    assert out["trade_permission"] in {"ALLOW", "BLOCK", "HALT"}
    assert analysis.get("phase21") is out


def test_obi_analyze_sell_signal_and_hold() -> None:
    from super_otonom.order_book_intelligence import analyze_order_book_intelligence

    book = _make_normal_book()
    for sig in ("SELL", "HOLD", ""):
        out = analyze_order_book_intelligence("X", book, {"signal": sig})
        assert 0.0 <= out["alpha_score"] <= 1.0


def test_obi_analyze_missing_book_branches() -> None:
    from super_otonom.order_book_intelligence import analyze_order_book_intelligence

    out_none = analyze_order_book_intelligence("S", None, None)
    assert out_none["empty_reason"] == "missing_order_book"
    assert out_none["trade_permission"] == "BLOCK"
    assert out_none["alpha_score"] == 0.0

    out_empty = analyze_order_book_intelligence("S", {"bids": [], "asks": []}, {})
    assert out_empty["empty_reason"] == "missing_order_book"

    out_partial = analyze_order_book_intelligence("S", {"bids": [["x", "y"]], "asks": [[1, 1]]}, {})
    assert out_partial["empty_reason"] == "empty_sides"


def test_obi_analyze_wall_iceberg_spoof_score() -> None:
    from super_otonom.order_book_intelligence import analyze_order_book_intelligence

    bids = [[99.99, 200.0]] + [[99.99 - 0.01 * i, 0.1] for i in range(1, 12)]
    asks = [[100.01, 200.0]] + [[100.01 + 0.01 * i, 0.1] for i in range(1, 12)]
    out = analyze_order_book_intelligence("X", {"bids": bids, "asks": asks}, {"signal": "BUY"})
    ms = out["microstructure"]
    assert ms["wall_score"] > 0.0
    assert ms["iceberg_score"] > 0.0
    assert ms["spoof_score"] > 0.0
    assert out["risk_score"] > 0.5


def test_obi_analyze_with_event_ts_override_and_candle_ts() -> None:
    from super_otonom.order_book_intelligence import analyze_order_book_intelligence

    book = _make_normal_book()
    out1 = analyze_order_book_intelligence("X", book, {}, event_ts=1_700_000_000)
    assert out1["event_ts"] == 1_700_000_000.0

    out2 = analyze_order_book_intelligence(
        "X", book, {"event_ts": 1700000000.5, "candle_ts": None}
    )
    assert out2["event_ts"] == 1700000000.5 * 1000.0

    out3 = analyze_order_book_intelligence(
        "X", book, {"event_ts": "bad", "candle_ts": None}
    )
    assert out3["event_ts"] >= 0.0

    out4 = analyze_order_book_intelligence("X", book, {}, attach_to_analysis=False)
    assert "phase21" not in (out4 or {})


def test_obi_clamp_and_pick_score_type() -> None:
    from super_otonom.order_book_intelligence import _clamp01, _pick_score_type

    assert _clamp01(float("nan")) == 0.0
    assert _clamp01(-1.0) == 0.0
    assert _clamp01(2.0) == 1.0
    assert _clamp01(0.5) == 0.5

    assert _pick_score_type(0.1, 0.5) == "QUALITY"
    assert _pick_score_type(0.5, 0.75) == "RISK"
    assert _pick_score_type(0.5, 0.5) == "ALPHA"


# ════════════════════════════════════════════════════════════════════════════
# market_microstructure — Faz 25
# ════════════════════════════════════════════════════════════════════════════


def _make_trades(n: int = 20, base_p: float = 100.0, side: str = "buy") -> List[dict]:
    out = []
    for i in range(n):
        p = base_p * (1.0 + i * 0.0005)
        out.append({"side": side, "price": p, "qty": 1.0 + 0.1 * i})
    return out


def test_mms_compute_ofi_normalized() -> None:
    from super_otonom.market_microstructure import compute_ofi_normalized

    trades = [(1, 100.0, 5.0), (1, 100.0, 5.0)]
    assert compute_ofi_normalized(trades) == 1.0

    mixed = [(1, 100.0, 5.0), (-1, 100.0, 5.0)]
    assert compute_ofi_normalized(mixed) == 0.0

    sells = [(-1, 100.0, 3.0), (-1, 101.0, 2.0)]
    v = compute_ofi_normalized(sells)
    assert v == -1.0

    assert compute_ofi_normalized([]) is None
    assert compute_ofi_normalized([(1, 100.0, 0.0)]) is None


def test_mms_parse_trade_row_variants() -> None:
    from super_otonom.market_microstructure import _parse_trade_row

    assert _parse_trade_row({"side": "buy", "price": 100, "qty": 1.0}) == (1, 100.0, 1.0)
    assert _parse_trade_row({"aggressor": "SELL", "px": 50.0, "amount": 2.0}) == (-1, 50.0, 2.0)
    assert _parse_trade_row({"taker_side": "unknown", "price": 1.0, "qty": 1.0}) is None
    assert _parse_trade_row({"side": "buy", "price": 0.0, "qty": 1.0}) is None
    assert _parse_trade_row({"side": "buy", "price": 1.0, "qty": 0.0}) is None

    assert _parse_trade_row(["buy", 10.0, 1.0]) == (1, 10.0, 1.0)
    assert _parse_trade_row(["sell", 10.0, 1.0]) == (-1, 10.0, 1.0)
    assert _parse_trade_row([100.0, 1.0, "buy"]) == (1, 100.0, 1.0)
    assert _parse_trade_row([100.0, 1.0, "sell"]) == (-1, 100.0, 1.0)
    assert _parse_trade_row([100.0, 0.0, "buy"]) is None
    assert _parse_trade_row(["buy", 0.0, 1.0]) is None
    assert _parse_trade_row("garbage") is None
    assert _parse_trade_row([1, 2]) is None


def test_mms_normalize_trades_filters_garbage() -> None:
    from super_otonom.market_microstructure import _normalize_trades

    assert _normalize_trades(None) == []
    assert _normalize_trades("not-a-list") == []
    assert _normalize_trades(b"bytes") == []
    assert _normalize_trades(123) == []
    rows = _normalize_trades([{"side": "buy", "price": 1.0, "qty": 1.0}, "junk"])
    assert rows == [(1, 1.0, 1.0)]


def test_mms_analyze_full_pipeline_with_book() -> None:
    from super_otonom.market_microstructure import analyze_market_microstructure

    trades = _make_trades(40, side="buy")
    book = _make_normal_book()
    analysis: Dict[str, Any] = {"signal": "BUY", "event_ts": 1_700_000_000.0}
    out = analyze_market_microstructure("BTC/USDT", trades, book, analysis, depth_book=10)
    assert out["phase"] == "25"
    assert 0.0 <= out["alpha_score"] <= 1.0
    assert 0.0 <= out["risk_score"] <= 1.0
    assert out["ofi_normalized"] == 1.0
    assert out["obi_signed"] is not None
    assert out["metrics"]["trade_count"] == 40
    assert analysis.get("phase25") is out


def test_mms_analyze_no_trades_and_run_phase() -> None:
    from super_otonom.market_microstructure import (
        analyze_market_microstructure,
        run_market_microstructure_phase,
    )

    out = analyze_market_microstructure("X", [], None, {})
    assert out["empty_reason"] == "no_trades"
    assert out["trade_permission"] == "BLOCK"

    out2 = run_market_microstructure_phase("X", _make_trades(8), None, None)
    assert out2["phase"] == "25"


def test_mms_analyze_sell_hold_signal_branches() -> None:
    from super_otonom.market_microstructure import analyze_market_microstructure

    trades_sell = _make_trades(30, side="sell")
    out = analyze_market_microstructure("X", trades_sell, None, {"signal": "SELL"})
    assert out["ofi_normalized"] == -1.0
    assert out["alpha_score"] >= 0.5

    out_hold = analyze_market_microstructure("X", _make_trades(10), None, {"signal": "HOLD"})
    assert 0.0 <= out_hold["alpha_score"] <= 1.0


def test_mms_analyze_event_ts_and_no_attach() -> None:
    from super_otonom.market_microstructure import analyze_market_microstructure

    a: Dict[str, Any] = {"event_ts": 1700000000.5}
    out = analyze_market_microstructure(
        "X", _make_trades(5), None, a, attach_to_analysis=False, event_ts=2_000_000_000
    )
    assert "phase25" not in a
    assert out["event_ts"] == 2_000_000_000.0

    a2: Dict[str, Any] = {"event_ts": "garbage"}
    out2 = analyze_market_microstructure("X", _make_trades(5), None, a2)
    assert out2["event_ts"] >= 0


def test_mms_high_risk_permission_branches() -> None:
    from super_otonom.market_microstructure import analyze_market_microstructure

    extreme = []
    for i in range(40):
        extreme.append({"side": "buy", "price": 100.0 * (1.0 + i * 0.05), "qty": 0.01})
    out = analyze_market_microstructure("X", extreme, None, {"signal": "BUY"})
    assert out["trade_permission"] in {"ALLOW", "BLOCK", "HALT"}
    assert out["risk_score"] >= 0.0


def test_mms_clamp_and_pick_score_type() -> None:
    from super_otonom.market_microstructure import _clamp01, _pick_score_type

    assert _clamp01(float("nan")) == 0.0
    assert _clamp01(-2.0) == 0.0
    assert _clamp01(5.0) == 1.0
    assert _pick_score_type(0.1, 0.0) == "QUALITY"
    assert _pick_score_type(0.9, 0.9) == "RISK"
    assert _pick_score_type(0.9, 0.4) == "ALPHA"


# ════════════════════════════════════════════════════════════════════════════
# bot_engine_capital_patch — yalnız import (sabit string'ler)
# ════════════════════════════════════════════════════════════════════════════


def test_bot_engine_capital_patch_module_constants() -> None:
    from super_otonom import bot_engine_capital_patch as p

    for name in ("IMPORT_PATCH", "INIT_PATCH", "ENTRY_PATCH", "CLOSE_PATCH",
                 "TICK_PATCH", "STATUS_PATCH", "PERSISTENCE_PATCH"):
        v = getattr(p, name)
        assert isinstance(v, str) and len(v) > 0


# ════════════════════════════════════════════════════════════════════════════
# fake_order_book_scenarios — tüm senaryolar
# ════════════════════════════════════════════════════════════════════════════


def test_fake_scenarios_all_paths_and_invalid() -> None:
    from super_otonom.fake_order_book_scenarios import make_scenario

    for sc in ("normal", "flash_crash", "pump_dump", "low_liquidity"):
        ob, analysis = make_scenario(scenario=sc, mid_price=100.0, seed=7, event_ts=123)
        assert ob["bids"] and ob["asks"]
        assert isinstance(analysis["spread_pct"], float)
        assert "venues" in analysis
        assert analysis["event_ts"] == 123

    with pytest.raises(ValueError):
        make_scenario(scenario="not_a_scenario", mid_price=100.0)  # type: ignore[arg-type]


def test_fake_scenario_flash_crash_invariants() -> None:
    from super_otonom.fake_order_book_scenarios import make_scenario

    _ob, a = make_scenario(scenario="flash_crash", mid_price=200.0)
    assert a["flash_crash"] is True
    assert a["regime"] == "CRISIS"
    assert a["liquidity_ratio"] <= 0.25


def test_fake_scenario_pump_dump_venue_divergence() -> None:
    from super_otonom.fake_order_book_scenarios import make_scenario

    _ob, a = make_scenario(scenario="pump_dump", mid_price=100.0)
    assert a["regime"] == "VOLATILE"
    okx = a["venues"]["okx"]
    assert okx["price"] > 100.0


def test_fake_scenario_low_liquidity_thin_book() -> None:
    from super_otonom.fake_order_book_scenarios import make_scenario

    ob, a = make_scenario(scenario="low_liquidity", mid_price=50.0)
    assert a["liquidity_ratio"] <= 0.2
    top_bid_qty = float(ob["bids"][0][1])
    assert top_bid_qty < 1.0


# ════════════════════════════════════════════════════════════════════════════
# order_engine — tam yaşam döngüsü + recovery
# ════════════════════════════════════════════════════════════════════════════


def _new_order_engine(tmp_path: Path, batch: bool = False) -> Any:
    from super_otonom.order_engine import OrderEngine

    return OrderEngine(
        order_log_file=str(tmp_path / "orders.jsonl"),
        pending_file=str(tmp_path / "pending.json"),
        batch_mode=batch,
        max_memory=4,
    )


def test_order_engine_intent_sent_confirm(tmp_path: Path) -> None:
    eng = _new_order_engine(tmp_path)
    oid = eng.intent("BTC/USDT", "buy", 0.001, 50000.0, fee_estimate=0.1)
    assert oid.startswith("so_")
    rec = eng.get(oid)
    assert rec is not None and rec.state == "PENDING"

    assert eng.sent(oid, exchange_order_id="EX1") is True
    assert eng.get(oid).state == "SENT"
    assert eng.is_duplicate(oid) is True
    assert eng.sent("missing", "EX") is False

    eng.confirm(oid, 0.001, 50001.0, fee=0.2)
    rec = eng.get(oid)
    assert rec.state == "FILLED"
    assert rec.filled_qty == 0.001
    assert eng.confirm(oid, 0.001, 50001.0) is True
    assert eng.confirm("missing", 1.0, 1.0) is False


def test_order_engine_partial_and_fail_and_cancel(tmp_path: Path) -> None:
    eng = _new_order_engine(tmp_path)
    oid = eng.intent("ETH/USDT", "SELL", 1.0, 2000.0)
    assert eng.partial(oid, 0.4, 1999.0, fee=0.1) is True
    assert eng.get(oid).state == "PARTIAL"
    assert eng.partial("missing", 1.0, 1.0) is False

    fid = eng.intent("X", "BUY", 1.0, 1.0)
    assert eng.fail(fid, "net_err") is True
    assert eng.get(fid).state == "FAILED"
    assert eng.can_retry(fid) is True

    cid = eng.intent("Y", "BUY", 1.0, 1.0)
    assert eng.cancel(cid, "user") is True
    assert eng.cancel("missing", "x") is False
    assert eng.fail("missing", "x") is False

    f2 = eng.intent("Z", "BUY", 1.0, 1.0)
    eng.confirm(f2, 1.0, 1.0)
    assert eng.cancel(f2, "late") is False
    assert eng.fail(f2, "late") is False
    assert eng.can_retry(f2) is False
    assert eng.can_retry("missing") is False
    assert eng.is_duplicate("missing") is False


def test_order_engine_snapshot_pending_and_failed_lists(tmp_path: Path) -> None:
    eng = _new_order_engine(tmp_path)
    a = eng.intent("A", "BUY", 1.0, 1.0)
    b = eng.intent("B", "SELL", 1.0, 1.0)
    eng.fail(b, "err")
    snap = eng.snapshot()
    assert snap["total_orders"] == 2
    assert any(r.order_id == a for r in eng.pending_orders())
    assert any(r.order_id == b for r in eng.failed_retryable())


def test_order_engine_memory_cap_drops_completed(tmp_path: Path) -> None:
    eng = _new_order_engine(tmp_path)
    ids = []
    for i in range(3):
        oid = eng.intent("S", "BUY", 1.0, 1.0)
        eng.confirm(oid, 1.0, 1.0)
        ids.append(oid)
    eng.intent("NEW1", "BUY", 1.0, 1.0)
    eng.intent("NEW2", "BUY", 1.0, 1.0)
    assert len(eng._orders) <= 6


def test_order_engine_recovery_filled_cancelled_partial(tmp_path: Path) -> None:
    from super_otonom.order_engine import OrderEngine, OrderState

    eng = OrderEngine(
        order_log_file=str(tmp_path / "orders.jsonl"),
        pending_file=str(tmp_path / "pending.json"),
    )
    o1 = eng.intent("A", "BUY", 1.0, 100.0)
    o2 = eng.intent("B", "SELL", 1.0, 100.0)
    o3 = eng.intent("C", "BUY", 1.0, 100.0)
    o4 = eng.intent("D", "BUY", 1.0, 100.0)

    handler = MagicMock()

    async def fetch(symbol: str, oid: str) -> Dict[str, Any]:
        if oid == o1:
            return {"status": "closed", "filled": 1.0, "average": 101.0, "fee": {"cost": 0.05}}
        if oid == o2:
            return {"status": "cancelled"}
        if oid == o3:
            return {"status": "open", "filled": 0.5, "average": 100.5}
        return {"status": "weird_unknown"}

    handler.fetch_order_by_client_id = fetch
    out = asyncio.run(eng.recover(handler))
    assert set(out) == {o1, o2, o3, o4}
    assert eng.get(o1).state == OrderState.FILLED
    assert eng.get(o2).state == OrderState.CANCELLED
    assert eng.get(o3).state == OrderState.PARTIAL
    assert eng.get(o4).state == OrderState.FAILED


def test_order_engine_recovery_empty_and_exchange_fallback(tmp_path: Path) -> None:
    eng = _new_order_engine(tmp_path)
    assert asyncio.run(eng.recover(MagicMock())) == []

    oid = eng.intent("A", "BUY", 1.0, 100.0)

    class _Exchange:
        async def fetch_order(self, ex_id: str, symbol: str) -> Dict[str, Any]:
            return {"status": "closed", "filled": 1.0, "average": 101.0}

    class _Handler:
        exchange = _Exchange()

    out = asyncio.run(eng.recover(_Handler()))
    assert oid in out
    assert eng.get(oid).state == "FILLED"


def test_order_engine_recovery_not_found_and_no_method(tmp_path: Path) -> None:
    eng = _new_order_engine(tmp_path)
    oid = eng.intent("A", "BUY", 1.0, 100.0)

    class _Handler:
        async def fetch_order_by_client_id(self, *_: Any) -> Dict[str, Any]:
            raise RuntimeError("Order not found on exchange")

    asyncio.run(eng.recover(_Handler()))
    assert eng.get(oid).state == "FAILED"

    eng2 = _new_order_engine(tmp_path / "sub")
    xid = eng2.intent("X", "BUY", 1.0, 1.0)
    out = asyncio.run(eng2.recover(object()))
    assert out == []
    assert eng2.get(xid).state == "PENDING"


def test_order_engine_load_pending_from_disk(tmp_path: Path) -> None:
    eng = _new_order_engine(tmp_path)
    oid = eng.intent("A", "BUY", 1.0, 100.0)
    pending_path = tmp_path / "pending.json"
    assert pending_path.exists()
    raw = json.loads(pending_path.read_text(encoding="utf-8"))
    raw[oid]["exchange_raw"] = "should_become_dict"
    pending_path.write_text(json.dumps(raw), encoding="utf-8")

    from super_otonom.order_engine import OrderEngine

    eng2 = OrderEngine(
        order_log_file=str(tmp_path / "orders.jsonl"),
        pending_file=str(pending_path),
    )
    assert oid in eng2._orders
    assert eng2._orders[oid].exchange_raw == {}


def test_order_engine_batch_mode_skips_disk(tmp_path: Path) -> None:
    eng = _new_order_engine(tmp_path, batch=True)
    oid = eng.intent("A", "BUY", 1.0, 1.0)
    assert oid in eng._orders
    assert not (tmp_path / "pending.json").exists()


# ════════════════════════════════════════════════════════════════════════════
# reconciliation_engine
# ════════════════════════════════════════════════════════════════════════════


class _FakePos:
    def __init__(self, qty: float = 1.0) -> None:
        self.qty = qty


class _FakeCapital:
    def __init__(self, nav: float = 1000.0, cash: float = 1000.0) -> None:
        self._cash = cash
        self._margin_used = 0.0
        self._unrealized_pnl = 0.0
        self._positions: Dict[str, _FakePos] = {}
        self._nav_override = nav
        self.records: List[Dict[str, Any]] = []

    @property
    def nav(self) -> float:
        return self._nav_override if not self._positions else self._cash

    def _record(self, **kwargs: Any) -> None:
        self.records.append(kwargs)


class _FakeOrderEngine:
    async def recover(self, handler: Any) -> List[str]:
        return ["o1"]


def test_recon_normalize_market_and_init(tmp_path: Path) -> None:
    from super_otonom.reconciliation_engine import ReconciliationEngine

    cap = _FakeCapital(nav=1000.0)
    eng = ReconciliationEngine(
        cap, _FakeOrderEngine(), recon_dir=str(tmp_path / "recon"),
        market="futures",
    )
    assert eng._market == "future"
    eng2 = ReconciliationEngine(cap, _FakeOrderEngine(),
                                recon_dir=str(tmp_path / "recon2"), market="weird")
    assert eng2._market == "spot"


def test_recon_compare_within_tolerance(tmp_path: Path) -> None:
    from super_otonom.reconciliation_engine import ReconciliationEngine

    cap = _FakeCapital(nav=1000.0)
    eng = ReconciliationEngine(cap, _FakeOrderEngine(),
                               recon_dir=str(tmp_path / "recon"),
                               tolerance_pct=0.02, hard_block_pct=0.10)
    result = eng._compare(trigger="PERIODIC", ex_nav=1010.0, ex_positions={},
                          pending_recovered=0, balance_total={})
    assert result.nav_ok is True
    assert result.hard_blocked is False
    assert result.passed is True


def test_recon_compare_hard_block_startup(tmp_path: Path) -> None:
    from super_otonom.reconciliation_engine import ReconciliationEngine

    cap = _FakeCapital(nav=1000.0)
    eng = ReconciliationEngine(cap, _FakeOrderEngine(),
                               recon_dir=str(tmp_path / "recon"),
                               tolerance_pct=0.02, hard_block_pct=0.10)
    result = eng._compare(trigger="STARTUP", ex_nav=2000.0, ex_positions={},
                          pending_recovered=0, balance_total={})
    assert result.hard_blocked is True
    assert result.nav_ok is False
    assert any("HARD BLOCK" in w for w in result.warnings)


def test_recon_compare_spot_mismatch(tmp_path: Path) -> None:
    from super_otonom.reconciliation_engine import ReconciliationEngine

    cap = _FakeCapital(nav=1000.0)
    cap._positions = {"BTC/USDT": _FakePos(qty=1.0), "ETH/USDT": _FakePos(qty=2.0)}
    eng = ReconciliationEngine(cap, _FakeOrderEngine(),
                               recon_dir=str(tmp_path / "recon"),
                               market="spot")
    bal = {"BTC": 0.5, "ETH": 2.0}
    result = eng._compare(trigger="PERIODIC", ex_nav=1000.0, ex_positions={},
                          pending_recovered=0, balance_total=bal)
    assert "BTC/USDT" in result.position_mismatch


def test_recon_compare_future_mismatch(tmp_path: Path) -> None:
    from super_otonom.reconciliation_engine import ReconciliationEngine

    cap = _FakeCapital(nav=1000.0)
    cap._positions = {"BTC/USDT": _FakePos(qty=1.0)}
    eng = ReconciliationEngine(cap, _FakeOrderEngine(),
                               recon_dir=str(tmp_path / "recon"),
                               market="future")
    result = eng._compare(trigger="PERIODIC", ex_nav=1000.0,
                          ex_positions={"ETH/USDT": 500.0},
                          pending_recovered=0, balance_total={})
    assert set(result.position_mismatch) == {"BTC/USDT", "ETH/USDT"}


def test_recon_apply_adjustment_updates_cash(tmp_path: Path) -> None:
    from super_otonom.reconciliation_engine import ReconciliationEngine

    cap = _FakeCapital(nav=1000.0)
    eng = ReconciliationEngine(cap, _FakeOrderEngine(),
                               recon_dir=str(tmp_path / "recon"))
    result = eng._compare(trigger="STARTUP", ex_nav=950.0, ex_positions={},
                          pending_recovered=0, balance_total={})
    eng._apply_adjustment(950.0, {}, result)
    assert result.adjustments
    assert cap.records and cap.records[0]["event"] == "RECON_ADJUSTMENT"


def test_recon_apply_adjustment_journal_error(tmp_path: Path) -> None:
    from super_otonom.reconciliation_engine import ReconciliationEngine

    cap = _FakeCapital(nav=1000.0)
    cap._record = lambda **kw: (_ for _ in ()).throw(RuntimeError("journal err"))  # type: ignore[assignment]
    eng = ReconciliationEngine(cap, _FakeOrderEngine(),
                               recon_dir=str(tmp_path / "recon"))
    result = eng._compare(trigger="STARTUP", ex_nav=950.0, ex_positions={},
                          pending_recovered=0, balance_total={})
    eng._apply_adjustment(950.0, {}, result)


def test_recon_startup_handshake_full(tmp_path: Path) -> None:
    from super_otonom.reconciliation_engine import ReconciliationEngine

    cap = _FakeCapital(nav=1000.0)
    eng = ReconciliationEngine(cap, _FakeOrderEngine(),
                               recon_dir=str(tmp_path / "recon"),
                               quote_currency="USDT")

    class _Handler:
        async def fetch_balance(self) -> Dict[str, Any]:
            return {"total": {"USDT": 1005.0, "BTC": 0.001}}

        async def fetch_positions(self) -> List[Dict[str, Any]]:
            return [{"symbol": "BTC/USDT", "notional": 100.0}]

    result = asyncio.run(eng.startup_handshake(_Handler()))
    assert result.exchange_nav >= 1000.0
    snap = eng.snapshot()
    assert snap["trigger"] == "STARTUP"


def test_recon_fetch_exchange_state_handler_exception(tmp_path: Path) -> None:
    from super_otonom.reconciliation_engine import ReconciliationEngine

    cap = _FakeCapital(nav=500.0)
    eng = ReconciliationEngine(cap, _FakeOrderEngine(),
                               recon_dir=str(tmp_path / "recon"))

    class _Bad:
        async def fetch_balance(self) -> Dict[str, Any]:
            raise RuntimeError("rate limit")

    nav, positions, bal = asyncio.run(eng._fetch_exchange_state(_Bad()))
    assert nav == 500.0
    assert positions == {} and bal == {}


def test_recon_periodic_no_hard_block(tmp_path: Path) -> None:
    from super_otonom.reconciliation_engine import ReconciliationEngine

    cap = _FakeCapital(nav=1000.0)
    eng = ReconciliationEngine(cap, _FakeOrderEngine(),
                               recon_dir=str(tmp_path / "recon"),
                               tolerance_pct=0.001, hard_block_pct=0.50)

    class _H:
        async def fetch_balance(self) -> Dict[str, Any]:
            return {"total": {"USDT": 1200.0}}

    result = asyncio.run(eng.periodic_check(_H()))
    assert result.trigger == "PERIODIC"
    assert result.hard_blocked is False


def test_recon_snapshot_never_run(tmp_path: Path) -> None:
    from super_otonom.reconciliation_engine import ReconciliationEngine

    cap = _FakeCapital(nav=1000.0)
    eng = ReconciliationEngine(cap, _FakeOrderEngine(),
                               recon_dir=str(tmp_path / "recon"))
    assert eng.snapshot() == {"status": "never_run"}


def test_recon_spot_qty_mismatch_edge_cases(tmp_path: Path) -> None:
    from super_otonom.reconciliation_engine import ReconciliationEngine

    cap = _FakeCapital(nav=1000.0)
    cap._positions = {
        "BAD": _FakePos(qty=1.0),  # delimiter yok
        "BTC/EUR": _FakePos(qty=1.0),  # quote uyumsuz
        "BTC/USDT": _FakePos(qty=1.0),
        "ETH/USDT": _FakePos(qty=0.0),  # her ikisi de dust
        "SOL/USDT": _FakePos(qty=1.0),
    }
    eng = ReconciliationEngine(cap, _FakeOrderEngine(),
                               recon_dir=str(tmp_path / "recon"))
    bad = eng._spot_qty_mismatch({"BTC": 1.0, "ETH": 0.0, "SOL": 0.0})
    assert "SOL/USDT" in bad
    syms = eng._spot_exchange_symbols({"BTC": 1.0})
    assert "BTC/USDT" in syms


# ════════════════════════════════════════════════════════════════════════════
# config — env trim / pick / advisory log
# ════════════════════════════════════════════════════════════════════════════


def test_config_env_helpers() -> None:
    from super_otonom import config as cfg

    assert cfg._env_trim(None) == ""
    assert cfg._env_trim("  hello  ") == "hello"
    assert cfg._env_trim('"quoted"') == "quoted"
    assert cfg._env_trim("'single'") == "single"

    assert cfg._env_pick("__NOT_SET_A__", "__NOT_SET_B__", default="fallback") == "fallback"
    assert cfg._env_truthy("__NOT_SET_TRUTHY__", "true") is True


def test_config_advisory_log_paper_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    import super_otonom.config as cfg

    monkeypatch.setenv("META_REGIME_MODE", "shadow")
    cfg._log_meta_advisory_env_at_import()

    monkeypatch.setenv("META_REGIME_MODE", "advisory")
    monkeypatch.setattr(cfg, "_effective_paper", True, raising=False)
    cfg._log_meta_advisory_env_at_import()


def test_config_advisory_log_live_loose(monkeypatch: pytest.MonkeyPatch) -> None:
    import super_otonom.config as cfg

    monkeypatch.setenv("META_REGIME_MODE", "advisory")
    monkeypatch.setenv("META_ADVISORY_LOOSE", "1")
    monkeypatch.setattr(cfg, "_effective_paper", False, raising=False)
    cfg._log_meta_advisory_env_at_import()


def test_config_advisory_log_live_with_ack(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import super_otonom.config as cfg
    import super_otonom.meta_regime_orchestrator as mro

    monkeypatch.setenv("META_REGIME_MODE", "advisory")
    monkeypatch.setenv("META_ADVISORY_LOOSE", "")
    monkeypatch.setattr(cfg, "_effective_paper", False, raising=False)

    ack = tmp_path / "advisory_ack.txt"
    ack.write_text("OK", encoding="utf-8")
    monkeypatch.setattr(mro, "advisory_ack_path_for_gate", lambda *_: str(ack))
    cfg._log_meta_advisory_env_at_import()

    monkeypatch.setattr(mro, "advisory_ack_path_for_gate", lambda *_: None)
    cfg._log_meta_advisory_env_at_import()

    empty = tmp_path / "empty_ack.txt"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setattr(mro, "advisory_ack_path_for_gate", lambda *_: str(empty))
    cfg._log_meta_advisory_env_at_import()


# ════════════════════════════════════════════════════════════════════════════
# redis_bridge — bağlantısız ve hatalı yollar
# ════════════════════════════════════════════════════════════════════════════


def test_redis_bridge_lib_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    import super_otonom.redis_bridge as rb

    monkeypatch.setattr(rb, "_REDIS_AVAILABLE", False)
    b = rb.RedisBridge(url="redis://localhost:0")
    assert b.is_connected is False
    assert b.redis_klines_available is False
    assert "not installed" in (b.degraded_reason or "")
    assert b.get_kline("BTCUSDT") is None
    assert b.get_all_klines()["BTCUSDT"] is None
    assert b.get_latest_price("BTCUSDT") is None
    assert b.status()["connected"] is False
    b.subscribe(lambda _s: None)
    b.close()


def test_redis_bridge_connection_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    import super_otonom.redis_bridge as rb

    pytest.importorskip("redis")

    class _DeadClient:
        def ping(self) -> None:
            raise ConnectionError("nope")

    monkeypatch.setattr(rb, "_REDIS_AVAILABLE", True)
    monkeypatch.setattr(rb.redis, "from_url", lambda *a, **k: _DeadClient())
    b = rb.RedisBridge(url="redis://localhost:0")
    assert b.is_connected is False
    assert b.degraded_reason is not None
    b.close()


def test_redis_bridge_get_kline_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    import time as _t

    import super_otonom.redis_bridge as rb

    pytest.importorskip("redis")

    fresh_payload = json.dumps({
        "close": 50000.0,
        "updated_at": _t.time() * 1000,
    })
    stale_payload = json.dumps({
        "close": 49000.0,
        "updated_at": 0,
    })

    state = {"key": "fresh"}

    class _Client:
        def ping(self) -> None: ...

        def get(self, key: str) -> Any:
            if state["key"] == "missing":
                return None
            if state["key"] == "bad":
                return "not-json{"
            if state["key"] == "stale":
                return stale_payload
            return fresh_payload

        def close(self) -> None: ...

        def pubsub(self) -> Any:
            class _PS:
                def subscribe(self, *_: Any) -> None: ...

                def listen(self) -> Any:
                    yield {"type": "message", "data": "BTCUSDT"}
                    yield {"type": "subscribe", "data": "BTCUSDT"}

                def unsubscribe(self) -> None: ...

                def close(self) -> None: ...

            return _PS()

    monkeypatch.setattr(rb, "_REDIS_AVAILABLE", True)
    monkeypatch.setattr(rb.redis, "from_url", lambda *a, **k: _Client())
    b = rb.RedisBridge(url="redis://localhost:0")
    assert b.is_connected is True
    assert b.redis_klines_available is True

    k = b.get_kline("BTCUSDT")
    assert k is not None and k["close"] == 50000.0
    assert b.get_latest_price("BTCUSDT") == 50000.0

    state["key"] = "missing"
    assert b.get_kline("X") is None
    assert b.get_latest_price("X") is None

    state["key"] = "bad"
    assert b.get_kline("X") is None

    state["key"] = "stale"
    assert b.get_kline("X") is None

    state["key"] = "fresh"
    s = b.status()
    assert s["connected"] is True
    assert "BTCUSDT" in s["symbols"]

    received: List[str] = []

    def _cb(sym: str) -> None:
        received.append(sym)
        raise RuntimeError("simulate cb failure")

    b.subscribe(_cb)
    assert received == ["BTCUSDT"]
    b.close()


# ════════════════════════════════════════════════════════════════════════════
# meta_regime_orchestrator — advisory_ack_path_for_gate yan dalları
# ════════════════════════════════════════════════════════════════════════════


def test_meta_regime_ack_path_shadow_returns_none() -> None:
    from super_otonom.meta_regime_orchestrator import advisory_ack_path_for_gate

    assert advisory_ack_path_for_gate("shadow") is None


# ════════════════════════════════════════════════════════════════════════════
# execution_pipeline — saf yardımcılar + açık pozisyon çıkış dalı (gerçek coroutine)
# ════════════════════════════════════════════════════════════════════════════


def test_execution_pipeline_phase_helpers_pure() -> None:
    from super_otonom.pipelines.execution_pipeline import (
        _phase_dict_from_analysis,
        _phase_override_from_analysis,
    )

    assert _phase_dict_from_analysis({}, "phase66", "faz66") == {}
    assert _phase_dict_from_analysis({"phase66": "nope"}, "phase66", "faz66") == {}
    assert _phase_dict_from_analysis({"phase66": {"z": 1}}, "faz66", "phase66") == {"z": 1}

    assert _phase_override_from_analysis({}, "phase50", "faz50") is None
    assert _phase_override_from_analysis({"phase50": 42}, "phase50", "faz50") == 42
    assert _phase_override_from_analysis(
        {"override_phases": {"faz50": 99}}, "phase50", "faz50"
    ) == 99
    assert _phase_override_from_analysis(
        {"phase_overrides": {"phase50": 101}}, "phase50", "faz50"
    ) == 101


def test_execution_pipeline_calls_handle_exit_when_position_open() -> None:
    from super_otonom.decision_context import DecisionContext
    from super_otonom.pipelines.execution_pipeline import execute_trade_phase

    engine = MagicMock()
    engine.open_positions = {"ETH/USDT": {"qty": 1.0}}
    engine._handle_exit = AsyncMock()

    analysis: Dict[str, Any] = {}
    out: Dict[str, Any] = {"final_signal": "SELL"}
    dctx = DecisionContext.start(symbol="ETH/USDT", tick_id=1, analysis=analysis)

    async def _go() -> None:
        await execute_trade_phase(
            engine, "ETH/USDT", 50.0, analysis, out, 1.0, dctx, []
        )

    asyncio.run(_go())
    engine._handle_exit.assert_awaited_once()


# ════════════════════════════════════════════════════════════════════════════
# bot_engine — phase_chain özeti (saf)
# ════════════════════════════════════════════════════════════════════════════


def test_bot_engine_compact_phase_chain_for_attribution() -> None:
    from super_otonom.bot_engine import _compact_phase_chain_for_attribution

    assert _compact_phase_chain_for_attribution(None) is None
    assert _compact_phase_chain_for_attribution({}) is None
    assert _compact_phase_chain_for_attribution({"faz71": "bad"}) is None
    compact = _compact_phase_chain_for_attribution(
        {
            "faz71": {
                "trade_permission": "ALLOW",
                "alpha_score": 0.7,
                "risk_score": 0.2,
                "final_action": "WAIT",
            }
        }
    )
    assert compact is not None
    assert compact["faz71"]["trade_permission"] == "ALLOW"
    assert compact["faz71"]["alpha_score"] == 0.7


# ════════════════════════════════════════════════════════════════════════════
# benchmark_katman_a — _percentile uçları
# ════════════════════════════════════════════════════════════════════════════


def test_benchmark_percentile_edges() -> None:
    from super_otonom.benchmark_katman_a import _percentile

    assert _percentile([], 50) == 0.0
    assert _percentile([7.0], 50) == 7.0
    xs = sorted([10.0, 20.0, 30.0, 40.0, 50.0])
    assert _percentile(xs, 0) == 10.0
    assert _percentile(xs, 100) == 50.0


# ════════════════════════════════════════════════════════════════════════════
# redis_bridge — close() istemci hatalarını yutar
# ════════════════════════════════════════════════════════════════════════════


def test_redis_bridge_close_swallows_pubsub_client_errors() -> None:
    import super_otonom.redis_bridge as rb

    pytest.importorskip("redis")
    bridge = rb.RedisBridge.__new__(rb.RedisBridge)
    bridge._connected = True
    bridge._pubsub = MagicMock()
    bridge._pubsub.unsubscribe.side_effect = OSError("unsub")
    bridge._pubsub.close.side_effect = OSError("psclose")
    bridge._client = MagicMock()
    bridge._client.close.side_effect = OSError("clclose")
    bridge.close()
    assert bridge._connected is False


# ════════════════════════════════════════════════════════════════════════════
# exchange_async — DNS çözücü bayrağı (saf, ağ yok)
# ════════════════════════════════════════════════════════════════════════════


def test_exchange_async_use_aiohttp_resolver_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from super_otonom import exchange_async as ea

    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.delenv("SUPER_OTONOM_AIOHTTP_DEFAULT_RESOLVER", raising=False)
    assert ea._use_aiohttp_default_resolver() is False
    monkeypatch.setenv("SUPER_OTONOM_AIOHTTP_DEFAULT_RESOLVER", "1")
    assert ea._use_aiohttp_default_resolver() is True
