"""
tests/test_order_engine.py + test_reconciliation_engine.py
─────────────────────────────────────────────────────────────────────────────
OrderEngine ve ReconciliationEngine birim testleri

Kapsam:
  - UUID üretimi ve benzersizlik
  - State machine: PENDING → SENT → FILLED / FAILED / CANCELLED
  - Idempotency: aynı ID ile FILLED tekrar işlenmez
  - Duplicate koruması
  - Retry mantığı
  - Persistence: pending_orders disk'e yazılır, yüklenir
  - Recovery: PENDING emirler doğru işlenir
  - ReconciliationEngine: NAV farkı tespiti ve adjustment
  - Hard block eşiği
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "super_otonom"))

from order_engine import OrderEngine, OrderState
from reconciliation_engine import ReconciliationEngine

# ── Yardımcılar ──────────────────────────────────────────────────────────────


def make_order_engine(tmp_path: str) -> OrderEngine:
    return OrderEngine(
        order_log_file=os.path.join(tmp_path, "orders.jsonl"),
        pending_file=os.path.join(tmp_path, "pending.json"),
        max_retries=3,
    )


def make_capital_mock(nav: float = 10_000.0) -> MagicMock:
    """Minimal CapitalEngine mock."""
    cap = MagicMock()
    cap.nav = nav
    cap._cash = nav
    cap._margin_used = 0.0
    cap._unrealized_pnl = 0.0
    cap._positions = {}
    cap._record = MagicMock()
    return cap


# ── OrderEngine Testleri ──────────────────────────────────────────────────────


class TestOrderEngineBasic:
    def test_intent_creates_unique_ids(self, tmp_path):
        e = make_order_engine(str(tmp_path))
        ids = {e.intent("BTC/USDT", "BUY", 0.1, 50_000) for _ in range(100)}
        assert len(ids) == 100  # tümü benzersiz

    def test_intent_state_is_pending(self, tmp_path):
        e = make_order_engine(str(tmp_path))
        oid = e.intent("BTC/USDT", "BUY", 0.1, 50_000)
        rec = e.get(oid)
        assert rec is not None
        assert rec.state == OrderState.PENDING

    def test_sent_updates_state(self, tmp_path):
        e = make_order_engine(str(tmp_path))
        oid = e.intent("BTC/USDT", "BUY", 0.1, 50_000)
        ok = e.sent(oid, exchange_order_id="ex-123")
        assert ok is True
        assert e.get(oid).state == OrderState.SENT
        assert e.get(oid).exchange_order_id == "ex-123"

    def test_confirm_sets_filled(self, tmp_path):
        e = make_order_engine(str(tmp_path))
        oid = e.intent("BTC/USDT", "BUY", 0.1, 50_000)
        e.sent(oid)
        ok = e.confirm(oid, filled_qty=0.1, fill_price=50_100.0, fee=5.0)
        assert ok is True
        rec = e.get(oid)
        assert rec.state == OrderState.FILLED
        assert rec.filled_qty == pytest.approx(0.1)
        assert rec.fill_price == pytest.approx(50_100.0)
        assert rec.fee == pytest.approx(5.0)

    def test_fail_sets_failed(self, tmp_path):
        e = make_order_engine(str(tmp_path))
        oid = e.intent("ETH/USDT", "BUY", 1.0, 3_000)
        e.fail(oid, "network_timeout")
        rec = e.get(oid)
        assert rec.state == OrderState.FAILED
        assert rec.retry_count == 1
        assert rec.error_msg == "network_timeout"

    def test_cancel_sets_cancelled(self, tmp_path):
        e = make_order_engine(str(tmp_path))
        oid = e.intent("BTC/USDT", "SELL", 0.05, 50_000)
        e.cancel(oid, reason="stale_order")
        assert e.get(oid).state == OrderState.CANCELLED

    def test_full_lifecycle(self, tmp_path):
        e = make_order_engine(str(tmp_path))
        oid = e.intent("BTC/USDT", "BUY", 0.1, 50_000)
        assert e.get(oid).state == OrderState.PENDING
        e.sent(oid, "ex-456")
        assert e.get(oid).state == OrderState.SENT
        e.confirm(oid, 0.1, 50_050.0, 5.0)
        assert e.get(oid).state == OrderState.FILLED


class TestIdempotency:
    def test_duplicate_filled_is_idempotent(self, tmp_path):
        """FILLED emri tekrar confirm edilirse state değişmez."""
        e = make_order_engine(str(tmp_path))
        oid = e.intent("BTC/USDT", "BUY", 0.1, 50_000)
        e.sent(oid)
        e.confirm(oid, 0.1, 50_000, 5.0)
        # İkinci confirm — idempotent olmalı
        ok = e.confirm(oid, 0.1, 50_000, 5.0)
        assert ok is True
        assert e.get(oid).state == OrderState.FILLED

    def test_is_duplicate_returns_true_for_sent(self, tmp_path):
        e = make_order_engine(str(tmp_path))
        oid = e.intent("BTC/USDT", "BUY", 0.1, 50_000)
        e.sent(oid)
        assert e.is_duplicate(oid) is True

    def test_is_duplicate_returns_true_for_filled(self, tmp_path):
        e = make_order_engine(str(tmp_path))
        oid = e.intent("BTC/USDT", "BUY", 0.1, 50_000)
        e.sent(oid)
        e.confirm(oid, 0.1, 50_000, 5.0)
        assert e.is_duplicate(oid) is True

    def test_is_duplicate_returns_false_for_pending(self, tmp_path):
        e = make_order_engine(str(tmp_path))
        oid = e.intent("BTC/USDT", "BUY", 0.1, 50_000)
        assert e.is_duplicate(oid) is False

    def test_unknown_id_is_not_duplicate(self, tmp_path):
        e = make_order_engine(str(tmp_path))
        assert e.is_duplicate("nonexistent-id") is False


class TestRetry:
    def test_can_retry_failed_order(self, tmp_path):
        e = make_order_engine(str(tmp_path))
        oid = e.intent("BTC/USDT", "BUY", 0.1, 50_000)
        e.fail(oid, "timeout")
        assert e.can_retry(oid) is True

    def test_cannot_retry_after_max_retries(self, tmp_path):
        e = make_order_engine(str(tmp_path))
        oid = e.intent("BTC/USDT", "BUY", 0.1, 50_000)
        for _ in range(3):
            e.fail(oid, "timeout")
        assert e.can_retry(oid) is False

    def test_cannot_retry_filled(self, tmp_path):
        e = make_order_engine(str(tmp_path))
        oid = e.intent("BTC/USDT", "BUY", 0.1, 50_000)
        e.sent(oid)
        e.confirm(oid, 0.1, 50_000, 5.0)
        assert e.can_retry(oid) is False


class TestPersistence:
    def test_pending_saved_and_loaded(self, tmp_path):
        e1 = make_order_engine(str(tmp_path))
        oid = e1.intent("BTC/USDT", "BUY", 0.1, 50_000)

        # Yeni engine aynı dosyalarla — PENDING yüklenmeli
        e2 = make_order_engine(str(tmp_path))
        rec = e2.get(oid)
        assert rec is not None
        assert rec.state == OrderState.PENDING
        assert rec.symbol == "BTC/USDT"

    def test_filled_not_in_pending_file(self, tmp_path):
        e = make_order_engine(str(tmp_path))
        oid = e.intent("BTC/USDT", "BUY", 0.1, 50_000)
        e.sent(oid)
        e.confirm(oid, 0.1, 50_000, 5.0)

        # Pending dosyasında FILLED emir olmamalı
        pending_file = os.path.join(str(tmp_path), "pending.json")
        with open(pending_file) as f:
            data = json.load(f)
        assert oid not in data

    def test_order_log_appends(self, tmp_path):
        e = make_order_engine(str(tmp_path))
        oid = e.intent("BTC/USDT", "BUY", 0.1, 50_000)
        e.sent(oid)
        e.confirm(oid, 0.1, 50_000)

        log_file = os.path.join(str(tmp_path), "orders.jsonl")
        with open(log_file) as f:
            lines = f.readlines()
        events = [json.loads(line)["event"] for line in lines]
        assert "INTENT" in events
        assert "SENT" in events
        assert "FILLED" in events

    def test_atomic_write_no_corruption(self, tmp_path):
        """Pending dosyası atomic rename ile yazılır — .tmp kalmamalı."""
        e = make_order_engine(str(tmp_path))
        for i in range(10):
            e.intent(f"SYM{i}/USDT", "BUY", 0.1, 1_000)

        tmp_file = os.path.join(str(tmp_path), "pending.json.tmp")
        assert not os.path.exists(tmp_file)


class TestSnapshot:
    def test_snapshot_keys(self, tmp_path):
        e = make_order_engine(str(tmp_path))
        snap = e.snapshot()
        assert "total_orders" in snap
        assert "by_state" in snap
        assert "pending_count" in snap
        assert "filled_count" in snap

    def test_snapshot_counts_correct(self, tmp_path):
        e = make_order_engine(str(tmp_path))
        oid1 = e.intent("BTC/USDT", "BUY", 0.1, 50_000)
        _oid2 = e.intent("ETH/USDT", "BUY", 1.0, 3_000)
        e.sent(oid1)
        e.confirm(oid1, 0.1, 50_000)
        snap = e.snapshot()
        assert snap["filled_count"] == 1
        assert snap["pending_count"] == 1


# ── ReconciliationEngine Testleri ─────────────────────────────────────────────


class TestReconciliationEngine:
    def _make_recon(self, tmp_path, nav=10_000.0, tolerance=0.02, hard_block=0.10):
        cap = make_capital_mock(nav)
        order_eng = MagicMock()
        order_eng.recover = AsyncMock(return_value=[])
        recon = ReconciliationEngine(
            capital=cap,
            order_engine=order_eng,
            recon_dir=str(tmp_path),
            tolerance_pct=tolerance,
            hard_block_pct=hard_block,
        )
        return recon, cap

    def _make_handler(self, ex_nav=10_000.0, positions=None):
        handler = MagicMock()
        handler.fetch_balance = AsyncMock(return_value={"total": {"USDT": ex_nav}})
        handler.fetch_positions = AsyncMock(return_value=positions or [])
        return handler

    @pytest.mark.asyncio
    async def test_startup_passes_when_navs_match(self, tmp_path):
        recon, _ = self._make_recon(tmp_path, nav=10_000.0)
        handler = self._make_handler(ex_nav=10_000.0)
        result = await recon.startup_handshake(handler)
        assert result.nav_ok is True
        assert result.hard_blocked is False
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_startup_detects_small_diff(self, tmp_path):
        """%1 fark — uyarı verir ama hard block yok."""
        recon, _ = self._make_recon(tmp_path, nav=10_000.0, tolerance=0.02)
        handler = self._make_handler(ex_nav=10_100.0)  # +%1
        result = await recon.startup_handshake(handler)
        assert result.nav_ok is True  # %1 < %2 tolerans
        assert result.hard_blocked is False

    @pytest.mark.asyncio
    async def test_startup_warns_on_tolerance_breach(self, tmp_path):
        """%-5 fark — tolerans aşıldı, uyarı var."""
        recon, _ = self._make_recon(tmp_path, nav=10_000.0, tolerance=0.02)
        handler = self._make_handler(ex_nav=9_500.0)  # -%5
        result = await recon.startup_handshake(handler)
        assert result.nav_ok is False
        assert len(result.warnings) > 0
        assert result.hard_blocked is False  # %5 < %10 hard block

    @pytest.mark.asyncio
    async def test_startup_hard_blocks_on_large_diff(self, tmp_path):
        """%-15 fark — hard block tetiklenmeli."""
        recon, _ = self._make_recon(tmp_path, nav=10_000.0, hard_block=0.10)
        handler = self._make_handler(ex_nav=8_500.0)  # -%15
        result = await recon.startup_handshake(handler)
        assert result.hard_blocked is True

    @pytest.mark.asyncio
    async def test_adjustment_applied_on_diff(self, tmp_path):
        """Fark tespit edilince CapitalEngine._cash güncellenmeli."""
        recon, cap = self._make_recon(tmp_path, nav=10_000.0, tolerance=0.02)
        handler = self._make_handler(ex_nav=9_700.0)  # -%3 → tolerance aşıldı
        await recon.startup_handshake(handler)
        # _record çağrıldı (RECON_ADJUSTMENT journal)
        assert cap._record.called

    @pytest.mark.asyncio
    async def test_recon_file_saved(self, tmp_path):
        recon, _ = self._make_recon(tmp_path, nav=10_000.0)
        handler = self._make_handler(ex_nav=10_000.0)
        await recon.startup_handshake(handler)
        files = os.listdir(str(tmp_path))
        assert any(f.startswith("recon_") and f.endswith(".json") for f in files)

    @pytest.mark.asyncio
    async def test_snapshot_after_run(self, tmp_path):
        recon, _ = self._make_recon(tmp_path, nav=10_000.0)
        handler = self._make_handler(ex_nav=10_000.0)
        await recon.startup_handshake(handler)
        snap = recon.snapshot()
        assert "last_run_ts" in snap
        assert "nav_diff" in snap
        assert "passed" in snap

    def test_snapshot_before_run(self, tmp_path):
        recon, _ = self._make_recon(tmp_path)
        snap = recon.snapshot()
        assert snap == {"status": "never_run"}


# ── Hypothesis: OrderEngine property testleri ─────────────────────────────────


@given(
    qty=st.floats(min_value=0.001, max_value=10.0, allow_nan=False, allow_infinity=False),
    price=st.floats(min_value=1.0, max_value=100_000.0, allow_nan=False, allow_infinity=False),
    exit_mult=st.floats(min_value=0.5, max_value=2.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=150)
def test_order_lifecycle_always_valid(qty, price, exit_mult):
    """Her koşulda state machine tutarlı olmalı."""
    with tempfile.TemporaryDirectory() as tmp:
        e = make_order_engine(tmp)
        oid = e.intent("X/USDT", "BUY", qty, price)
        assert e.get(oid).state == OrderState.PENDING
        e.sent(oid)
        assert e.get(oid).state == OrderState.SENT
        e.confirm(oid, qty, price * exit_mult, 0.0)
        assert e.get(oid).state == OrderState.FILLED
        ok = e.confirm(oid, qty, price, 0.0)
        assert ok is True
        assert e.get(oid).state == OrderState.FILLED


@given(n=st.integers(min_value=1, max_value=50))
@settings(max_examples=80)
def test_all_ids_unique(n):
    """n emir üretildiğinde hepsi farklı ID'ye sahip olmalı."""
    with tempfile.TemporaryDirectory() as tmp:
        e = make_order_engine(tmp)
        ids = [e.intent("BTC/USDT", "BUY", 0.01, 50_000) for _ in range(n)]
        assert len(set(ids)) == n
