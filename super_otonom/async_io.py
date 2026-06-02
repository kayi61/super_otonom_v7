"""Async-dostu, bloke etmeyen dosya yazımı (PROMPT-10).

:class:`AsyncWriteBuffer` — sıcak yoldan (tick / async event loop) çağrılan satır
yazımlarını arka plan thread'ine devreder. ``write()`` yalnızca kuyruğa ekler
(mikro-saniye); gerçek disk I/O ayrı bir daemon thread'de toplu (batched) yapılır,
böylece asyncio event loop'u bloke olmaz.

Tasarım hedefleri:
- **Bloke etmeyen üretici**: ``write()`` asla disk beklemez.
- **Sınırlı bellek**: kuyruk dolarsa en eski satır düşürülür (drop-oldest), sayaç tutulur.
- **Dayanıklı**: I/O hatası üreticiyi bozmaz; ``close()`` kalan satırları drain eder.
- **Append-only**: her flush dosyayı ``a`` modunda açar (çökme güvenliği).
"""

from __future__ import annotations

import logging
import os
import queue
import threading
from typing import List, Optional

log = logging.getLogger("super_otonom.async_io")

_SENTINEL = object()


class AsyncWriteBuffer:
    """Thread destekli, bloke etmeyen satır yazıcı (append-only)."""

    def __init__(
        self,
        filepath: str,
        *,
        max_queue: int = 10_000,
        batch_size: int = 256,
        poll_timeout: float = 0.25,
        encoding: str = "utf-8",
    ) -> None:
        self.filepath = filepath
        self.encoding = encoding
        self._batch_size = max(1, batch_size)
        self._poll_timeout = max(0.01, poll_timeout)
        self._q: "queue.Queue[object]" = queue.Queue(maxsize=max(1, max_queue))
        self._dropped = 0
        self._written = 0
        self._closed = False
        self._lock = threading.Lock()
        d = os.path.dirname(filepath)
        if d:
            os.makedirs(d, exist_ok=True)
        self._thread = threading.Thread(
            target=self._run, name="async-write-buffer", daemon=True
        )
        self._thread.start()

    # ── Üretici (sıcak yol) ─────────────────────────────────────────────────
    def write(self, line: str) -> bool:
        """Satırı kuyruğa ekler (bloke etmez). Eklendiyse True.

        Kuyruk doluysa en eski satırı düşürür ve yenisini koyar (drop-oldest),
        ``dropped`` sayacını artırır.
        """
        if self._closed:
            return False
        item = line if line.endswith("\n") else line + "\n"
        try:
            self._q.put_nowait(item)
            return True
        except queue.Full:
            with self._lock:
                self._dropped += 1
            try:
                self._q.get_nowait()  # en eskiyi at
                self._q.task_done()
                self._q.put_nowait(item)
                return True
            except (queue.Empty, queue.Full):
                return False

    # ── Tüketici (arka plan thread) ─────────────────────────────────────────
    def _run(self) -> None:
        while True:
            first = self._q.get()
            if first is _SENTINEL:
                self._q.task_done()
                return
            batch: List[str] = [first]  # type: ignore[list-item]
            for _ in range(self._batch_size - 1):
                try:
                    nxt = self._q.get_nowait()
                except queue.Empty:
                    break
                if nxt is _SENTINEL:
                    self._flush_batch(batch)
                    for _line in batch:
                        self._q.task_done()
                    self._q.task_done()  # sentinel
                    return
                batch.append(nxt)  # type: ignore[arg-type]
            self._flush_batch(batch)
            for _line in batch:
                self._q.task_done()

    def _flush_batch(self, batch: List[str]) -> None:
        if not batch:
            return
        try:
            with open(self.filepath, "a", encoding=self.encoding) as f:
                f.write("".join(batch))
            with self._lock:
                self._written += len(batch)
        except Exception as exc:  # üretici asla bozulmaz
            log.error("AsyncWriteBuffer yazma hatasi: %s", exc)

    # ── Yönetim ─────────────────────────────────────────────────────────────
    def flush(self, timeout: Optional[float] = 5.0) -> None:
        """Kuyruktaki tüm satırlar diske yazılana kadar bekler (best-effort)."""
        if self._closed:
            return
        if timeout is None:
            self._q.join()
            return
        # queue.join() timeout desteklemez → unfinished_tasks ile poll et.
        import time as _t

        deadline = _t.perf_counter() + timeout
        while self._q.unfinished_tasks > 0 and _t.perf_counter() < deadline:
            _t.sleep(0.01)

    def close(self, timeout: float = 5.0) -> None:
        """Kalan satırları drain eder, thread'i durdurur (idempotent)."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            self._q.put_nowait(_SENTINEL)
        except queue.Full:
            try:
                self._q.get_nowait()
                self._q.task_done()
                self._q.put_nowait(_SENTINEL)
            except (queue.Empty, queue.Full):
                pass
        self._thread.join(timeout=timeout)

    @property
    def dropped(self) -> int:
        return self._dropped

    @property
    def written(self) -> int:
        return self._written

    def __enter__(self) -> "AsyncWriteBuffer":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


__all__ = ["AsyncWriteBuffer"]
