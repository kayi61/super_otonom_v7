"""PROMPT-10 — pytest-benchmark performans ölçüm seti.

``benchmark`` fixture'ı pytest-benchmark eklentisinden gelir. pytest-xdist
(``-n auto``) altında otomatik devre dışı kalır: fixture fonksiyonu bir kez
çalıştırıp sonucu döndürür — bu yüzden assertion'lar her iki modda da geçerlidir.
Eklenti yoksa tüm modül atlanır.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytest_benchmark")

from super_otonom.profiling import (  # noqa: E402
    TickLatencyTracker,
    rss_bytes,
    take_memory_snapshot,
)
from super_otonom.risk.var_models import historical_var  # noqa: E402

_RETURNS = [((-1) ** i) * (0.001 * (i % 37) + 0.0005) for i in range(512)]


def test_benchmark_historical_var(benchmark) -> None:
    """Sıcak risk yolu: tarihsel VaR percentile hesabı."""
    var = benchmark(historical_var, _RETURNS, 0.99, horizon_days=1)
    assert var >= 0.0


def test_benchmark_rss_bytes(benchmark) -> None:
    """RSS okuma ucuz olmalı (tick başına çağrılabilir)."""
    val = benchmark(rss_bytes)
    assert isinstance(val, int)
    assert val >= 0


def test_benchmark_latency_tracker_record(benchmark) -> None:
    """TickLatencyTracker.record + p95 — sabit bellekli, hızlı."""
    tracker = TickLatencyTracker(maxlen=512)

    def _hot() -> float:
        tracker.record(3.14)
        return tracker.p95

    p95 = benchmark(_hot)
    assert p95 >= 0.0


def test_benchmark_memory_snapshot(benchmark) -> None:
    """tracemalloc kapalıyken snapshot ucuz olmalı (yalnızca RSS)."""
    snap = benchmark(take_memory_snapshot, "bench", capture_traces=False)
    assert snap.rss >= 0
    assert snap.label == "bench"
