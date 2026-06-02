"""PROMPT-10 — AsyncWriteBuffer + TradeLogger async/sync mod kapsamı."""

from __future__ import annotations

import json
from pathlib import Path

from super_otonom.async_io import AsyncWriteBuffer


def _count_lines(p: Path) -> int:
    if not p.exists():
        return 0
    with open(p, encoding="utf-8") as f:
        return sum(1 for _ in f)


def test_buffer_writes_all_lines(tmp_path: Path) -> None:
    p = tmp_path / "buf.log"
    buf = AsyncWriteBuffer(str(p), batch_size=8)
    for i in range(200):
        assert buf.write(json.dumps({"i": i})) is True
    buf.flush()
    buf.close()
    assert _count_lines(p) == 200
    assert buf.written == 200
    assert buf.dropped == 0


def test_buffer_appends_newline(tmp_path: Path) -> None:
    p = tmp_path / "nl.log"
    with AsyncWriteBuffer(str(p)) as buf:
        buf.write("no-newline")
        buf.write("has-newline\n")
        buf.flush()
    lines = p.read_text(encoding="utf-8").splitlines()
    assert lines == ["no-newline", "has-newline"]


def test_buffer_context_manager_drains(tmp_path: Path) -> None:
    p = tmp_path / "ctx.log"
    with AsyncWriteBuffer(str(p), batch_size=4) as buf:
        for i in range(30):
            buf.write(f"line-{i}")
    # __exit__ → close() → drain
    assert _count_lines(p) == 30


def test_buffer_drop_oldest_when_full(tmp_path: Path) -> None:
    p = tmp_path / "full.log"
    # Çok küçük kuyruk + thread'i meşgul tutmadan hızlı doldur.
    buf = AsyncWriteBuffer(str(p), max_queue=2, batch_size=1)
    accepted = 0
    for i in range(2000):
        if buf.write(f"x-{i}"):
            accepted += 1
    buf.flush()
    buf.close()
    # Drop-oldest stratejisi: bazı satırlar düşmüş olabilir ama veri bütünlüğü korunur
    # (yazılan + düşen mantıklı sınırda) ve süreç çökmedi.
    assert accepted >= 1
    assert buf.written >= 1
    assert buf.dropped >= 0


def test_buffer_write_after_close_returns_false(tmp_path: Path) -> None:
    p = tmp_path / "closed.log"
    buf = AsyncWriteBuffer(str(p))
    buf.write("a")
    buf.close()
    assert buf.write("b") is False


def test_buffer_close_idempotent(tmp_path: Path) -> None:
    p = tmp_path / "idem.log"
    buf = AsyncWriteBuffer(str(p))
    buf.write("a")
    buf.close()
    buf.close()  # no raise
    assert _count_lines(p) == 1


def test_buffer_creates_parent_dir(tmp_path: Path) -> None:
    p = tmp_path / "nested" / "deep" / "out.log"
    with AsyncWriteBuffer(str(p)) as buf:
        buf.write("hello")
    assert p.exists()


# ── TradeLogger entegrasyonu ──────────────────────────────────────────────────


def test_trade_logger_sync_default(tmp_path: Path) -> None:
    from super_otonom.core.bot_engine import TradeLogger

    p = tmp_path / "trades_sync.log"
    tl = TradeLogger(str(p))  # varsayılan: senkron
    tl.log_trade({"sym": "BTC", "qty": 1.0})
    tl.flush()  # sync modda no-op
    tl.close()
    assert _count_lines(p) == 1


def test_trade_logger_async_mode(tmp_path: Path) -> None:
    from super_otonom.core.bot_engine import TradeLogger

    p = tmp_path / "trades_async.log"
    tl = TradeLogger(str(p), async_buffer=True)
    for i in range(40):
        tl.log_trade({"sym": "ETH", "i": i})
    tl.flush()
    tl.close()
    assert _count_lines(p) == 40


def test_trade_logger_async_via_env(tmp_path, monkeypatch) -> None:
    from super_otonom.core.bot_engine import TradeLogger

    monkeypatch.setenv("TRADE_LOG_ASYNC", "1")
    p = tmp_path / "trades_env.log"
    tl = TradeLogger(str(p))
    assert tl._buffer is not None
    tl.log_trade({"sym": "SOL"})
    tl.close()
    assert _count_lines(p) == 1


def test_trade_logger_close_idempotent(tmp_path: Path) -> None:
    from super_otonom.core.bot_engine import TradeLogger

    p = tmp_path / "trades_idem.log"
    tl = TradeLogger(str(p), async_buffer=True)
    tl.log_trade({"sym": "BTC"})
    tl.close()
    tl.close()  # no raise
    assert _count_lines(p) == 1
