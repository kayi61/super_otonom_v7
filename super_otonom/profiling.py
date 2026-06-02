"""Performans profiling + bellek izleme altyapısı (PROMPT-10).

Hafif ve opsiyonel araçlar — üretimde sıcak yolu yavaşlatmaz:

- :func:`profile_method`  — ``ENABLE_PROFILING`` aktifken cProfile ile fonksiyon
  profilleme (sync + async). Kapalıyken dekoratör fonksiyonu *değiştirmeden* döner
  (sıfır ek yük).
- :func:`rss_bytes` / :class:`MemorySnapshot` — RSS + tracemalloc bellek ölçümü
  (``psutil`` opsiyonel; yoksa ``resource`` / ``/proc`` fallback).
- :class:`TickLatencyTracker` — tick gecikmesi yuvarlanan istatistik (p50/p95/max).
- :func:`record_tick_performance` — ``MetricsExporter``'a RSS + latency yazımı (graceful).

Ortam değişkenleri:
- ``ENABLE_PROFILING=1`` — :func:`profile_method` aktifleşir.
- ``PROFILING_LOG_LIMIT`` — profil çıktısında gösterilecek satır sayısı (vars. 20).
"""

from __future__ import annotations

import cProfile
import functools
import io
import logging
import os
import pstats
import time
import tracemalloc
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, List, Optional, Tuple, TypeVar

log = logging.getLogger("super_otonom.profiling")

F = TypeVar("F", bound=Callable[..., Any])

_TRUTHY = ("1", "true", "yes", "on")


def profiling_enabled() -> bool:
    """``ENABLE_PROFILING`` env truthy ise True."""
    return (os.getenv("ENABLE_PROFILING", "") or "").strip().lower() in _TRUTHY


def _profile_log_limit() -> int:
    try:
        return max(1, int(os.getenv("PROFILING_LOG_LIMIT", "20")))
    except (TypeError, ValueError):
        return 20


def format_profile(profiler: cProfile.Profile, *, sort: str = "cumulative", limit: int = 20) -> str:
    """cProfile sonucunu okunabilir tabloya çevirir."""
    buf = io.StringIO()
    stats = pstats.Stats(profiler, stream=buf)
    stats.strip_dirs().sort_stats(sort).print_stats(limit)
    return buf.getvalue()


def profile_method(
    func: Optional[F] = None,
    *,
    sort: str = "cumulative",
    limit: Optional[int] = None,
    logger: Optional[logging.Logger] = None,
) -> Any:
    """Koşullu cProfile dekoratörü.

    ``ENABLE_PROFILING`` kapalıyken orijinal fonksiyonu **olduğu gibi** döndürür —
    çağrı yolunda hiçbir ek yük olmaz. Açıkken her çağrı cProfile ile sarmalanır ve
    sonuç ``logger`` (vars. ``super_otonom.profiling``) üzerinden DEBUG seviyesinde
    loglanır. Sync ve async (coroutine) fonksiyonları destekler.
    """

    def _decorate(fn: F) -> F:
        # Karar import/decorate anında DEĞİL, çağrı anında verilir — testler env'i
        # runtime'da değiştirebilsin diye.
        log_obj = logger or log

        if _is_coroutine_function(fn):

            @functools.wraps(fn)
            async def _async_wrapper(*args: Any, **kwargs: Any) -> Any:
                if not profiling_enabled():
                    return await fn(*args, **kwargs)
                pr = cProfile.Profile()
                pr.enable()
                try:
                    return await fn(*args, **kwargs)
                finally:
                    pr.disable()
                    _emit(pr, fn, sort, limit, log_obj)

            return _async_wrapper  # type: ignore[return-value]

        @functools.wraps(fn)
        def _sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            if not profiling_enabled():
                return fn(*args, **kwargs)
            pr = cProfile.Profile()
            pr.enable()
            try:
                return fn(*args, **kwargs)
            finally:
                pr.disable()
                _emit(pr, fn, sort, limit, log_obj)

        return _sync_wrapper  # type: ignore[return-value]

    if func is not None:
        return _decorate(func)
    return _decorate


def _is_coroutine_function(fn: Callable[..., Any]) -> bool:
    import inspect

    return inspect.iscoroutinefunction(fn)


def _emit(
    pr: cProfile.Profile,
    fn: Callable[..., Any],
    sort: str,
    limit: Optional[int],
    log_obj: logging.Logger,
) -> None:
    try:
        text = format_profile(pr, sort=sort, limit=limit or _profile_log_limit())
        log_obj.debug("profile %s:\n%s", getattr(fn, "__qualname__", repr(fn)), text)
    except Exception as exc:  # profil çıktısı asla çağrıyı bozmamalı
        log_obj.debug("profile_method emit hata: %s", exc)


# ── Bellek ölçümü ──────────────────────────────────────────────────────────────

try:  # psutil opsiyonel — yoksa fallback
    import psutil as _psutil

    _PROCESS = _psutil.Process()
    _PSUTIL = True
except Exception:  # pragma: no cover - ortam bağımlı
    _psutil = None  # type: ignore[assignment]
    _PROCESS = None
    _PSUTIL = False


def rss_bytes() -> int:
    """Süreç RSS bellek kullanımı (bytes). Ölçülemezse 0.

    Öncelik: psutil → resource (Unix) → ``/proc/self/statm`` → 0.
    """
    if _PSUTIL and _PROCESS is not None:
        try:
            return int(_PROCESS.memory_info().rss)
        except Exception:
            pass
    try:  # Unix: resource.ru_maxrss (Linux KB, macOS bytes)
        import resource
        import sys

        ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(ru) if sys.platform == "darwin" else int(ru) * 1024
    except Exception:
        pass
    try:  # Linux: /proc/self/statm — sayfa cinsinden RSS
        with open("/proc/self/statm", "r", encoding="ascii") as fh:
            rss_pages = int(fh.read().split()[1])
        return rss_pages * os.sysconf("SC_PAGE_SIZE")
    except Exception:
        return 0


@dataclass(frozen=True)
class MemorySnapshot:
    """tracemalloc anlık görüntüsü + RSS damgası."""

    label: str
    rss: int
    traced_current: int
    traced_peak: int
    snapshot: Optional[Any] = None  # tracemalloc.Snapshot (opsiyonel)

    def top_stats(self, limit: int = 10) -> List[str]:
        if self.snapshot is None:
            return []
        stats = self.snapshot.statistics("lineno")[:limit]
        return [str(s) for s in stats]


def start_tracemalloc(nframe: int = 1) -> bool:
    """tracemalloc başlatır (zaten açıksa dokunmaz). Başlatıldıysa True."""
    if tracemalloc.is_tracing():
        return False
    tracemalloc.start(nframe)
    return True


def stop_tracemalloc() -> None:
    if tracemalloc.is_tracing():
        tracemalloc.stop()


def take_memory_snapshot(label: str = "", *, capture_traces: bool = True) -> MemorySnapshot:
    """Anlık RSS + tracemalloc ölçümü döndürür.

    ``capture_traces`` ve tracemalloc aktifse satır-bazlı snapshot da saklanır;
    aksi halde yalnızca sayaçlar (current/peak) okunur.
    """
    current, peak = (tracemalloc.get_traced_memory() if tracemalloc.is_tracing() else (0, 0))
    snap = (
        tracemalloc.take_snapshot() if (capture_traces and tracemalloc.is_tracing()) else None
    )
    return MemorySnapshot(
        label=label,
        rss=rss_bytes(),
        traced_current=int(current),
        traced_peak=int(peak),
        snapshot=snap,
    )


def diff_snapshots(
    before: MemorySnapshot,
    after: MemorySnapshot,
    *,
    top: int = 10,
) -> Tuple[int, List[str]]:
    """İki snapshot arası RSS deltası ve en çok büyüyen tahsis satırları.

    Dönüş: ``(rss_delta_bytes, ["<line>: +<size>", ...])``.
    """
    rss_delta = after.rss - before.rss
    lines: List[str] = []
    if before.snapshot is not None and after.snapshot is not None:
        stats = after.snapshot.compare_to(before.snapshot, "lineno")[:top]
        lines = [str(s) for s in stats]
    return rss_delta, lines


# ── Tick gecikmesi ──────────────────────────────────────────────────────────────


@dataclass
class TickLatencyTracker:
    """Tick gecikmesi (ms) yuvarlanan istatistik — sabit bellekli deque."""

    maxlen: int = 500
    _samples: Deque[float] = field(default_factory=lambda: deque(maxlen=500))
    last_ms: float = 0.0
    count: int = 0

    def __post_init__(self) -> None:
        if self._samples.maxlen != self.maxlen:
            self._samples = deque(self._samples, maxlen=self.maxlen)

    def record(self, latency_ms: float) -> None:
        v = max(0.0, float(latency_ms))
        self._samples.append(v)
        self.last_ms = v
        self.count += 1

    def _pct(self, q: float) -> float:
        if not self._samples:
            return 0.0
        ordered = sorted(self._samples)
        idx = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
        return ordered[idx]

    @property
    def p50(self) -> float:
        return self._pct(0.50)

    @property
    def p95(self) -> float:
        return self._pct(0.95)

    @property
    def max_ms(self) -> float:
        return max(self._samples) if self._samples else 0.0

    @property
    def mean_ms(self) -> float:
        return (sum(self._samples) / len(self._samples)) if self._samples else 0.0

    def stats(self) -> dict:
        return {
            "count": self.count,
            "last_ms": round(self.last_ms, 3),
            "mean_ms": round(self.mean_ms, 3),
            "p50_ms": round(self.p50, 3),
            "p95_ms": round(self.p95, 3),
            "max_ms": round(self.max_ms, 3),
        }


class _Timer:
    """``with measure_latency_ms() as t: ...`` → ``t.elapsed_ms``."""

    __slots__ = ("_start", "elapsed_ms")

    def __init__(self) -> None:
        self._start = 0.0
        self.elapsed_ms = 0.0

    def __enter__(self) -> "_Timer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.elapsed_ms = (time.perf_counter() - self._start) * 1000.0


def measure_latency_ms() -> _Timer:
    """Context manager: blok süresini ms cinsinden ``.elapsed_ms`` olarak verir."""
    return _Timer()


def record_tick_performance(
    metrics: Any,
    latency_ms: float,
    *,
    rss: Optional[int] = None,
) -> None:
    """``MetricsExporter.record_performance`` çağrısını güvenli sarmalar.

    ``metrics`` None veya uyumsuzsa sessizce no-op. Sıcak yol asla bozulmaz.
    """
    if metrics is None:
        return
    fn = getattr(metrics, "record_performance", None)
    if not callable(fn):
        return
    try:
        fn(rss_bytes() if rss is None else rss, float(latency_ms))
    except Exception as exc:  # pragma: no cover - savunmacı
        log.debug("record_tick_performance hata: %s", exc)


__all__ = [
    "MemorySnapshot",
    "TickLatencyTracker",
    "diff_snapshots",
    "format_profile",
    "measure_latency_ms",
    "profile_method",
    "profiling_enabled",
    "record_tick_performance",
    "rss_bytes",
    "start_tracemalloc",
    "stop_tracemalloc",
    "take_memory_snapshot",
]
