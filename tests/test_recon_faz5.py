"""Faz 5 — sim/paper mutabakat ve pending recovery (fastrun)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.fastrun


def test_recon_skips_exchange_fetch_dry_paper(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from super_otonom.reconciliation_engine import ReconciliationEngine

    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("PAPER_MODE", "true")
    monkeypatch.setenv("RECON_SIM_SKIP_SIGNED_FETCH", "1")
    monkeypatch.delenv("RECON_FETCH_BALANCE_IN_SIM", raising=False)

    cap = MagicMock()
    cap.nav = 1234.0
    cap._positions = {}
    oe = MagicMock()

    async def _rec(*_: object, **__: object) -> list[str]:
        return []

    oe.recover = _rec

    recon = ReconciliationEngine(cap, oe, recon_dir=str(tmp_path / "r"))

    async def _run() -> None:
        ex_nav, pos, bal = await recon._fetch_exchange_state(MagicMock())
        assert ex_nav == 1234.0
        assert pos == {}
        assert bal == {}

    asyncio.run(_run())


def test_recon_fetch_when_flag_set(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from super_otonom.reconciliation_engine import ReconciliationEngine

    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("PAPER_MODE", "true")
    monkeypatch.setenv("RECON_FETCH_BALANCE_IN_SIM", "1")

    cap = MagicMock()
    cap.nav = 100.0
    cap._positions = {}
    oe = MagicMock()

    async def _rec2(*_: object, **__: object) -> list[str]:
        return []

    oe.recover = _rec2

    class _H:
        async def fetch_balance(self):
            return {"total": {"USDT": 999.0}}

    recon = ReconciliationEngine(cap, oe, recon_dir=str(tmp_path / "r2"))

    async def _run() -> None:
        ex_nav, _, bal = await recon._fetch_exchange_state(_H())
        assert ex_nav == 999.0
        assert bal.get("USDT") == 999.0

    asyncio.run(_run())


def test_order_engine_save_pending_removes_file_when_empty(tmp_path) -> None:
    from super_otonom.order_engine import OrderEngine

    pend = tmp_path / "p.json"
    eng = OrderEngine(
        order_log_file=str(tmp_path / "o.jsonl"),
        pending_file=str(pend),
        batch_mode=False,
    )
    oid = eng.intent("X/USDT", "BUY", 1.0, 1.0)
    eng.confirm(oid, 1.0, 1.0, 0.0)
    assert eng.get(oid).state == "FILLED"
    eng._save_pending()
    assert not pend.exists()


def test_recover_skipped_auto_cancel_clears_pending(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from super_otonom.order_engine import OrderEngine, OrderState

    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("PAPER_MODE", "true")
    monkeypatch.setenv("RECON_AUTO_FAIL_SKIPPED_PENDING", "true")

    pend = tmp_path / "p2.json"
    eng = OrderEngine(
        order_log_file=str(tmp_path / "o2.jsonl"),
        pending_file=str(pend),
        batch_mode=False,
    )
    oid = eng.intent("Z/USDT", "BUY", 1.0, 1.0)
    eng.sent(oid, exchange_order_id="x")
    out = asyncio.run(eng.recover(object()))
    assert out == []
    assert eng.get(oid).state == OrderState.CANCELLED
    assert not pend.exists()
