"""PROMPT-10 — profiling.py + profile_tick / memory_check script kapsamı."""

from __future__ import annotations

import asyncio
import logging

import pytest
from super_otonom import profiling as P

# ── profiling_enabled / env ──────────────────────────────────────────────────


def test_profiling_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENABLE_PROFILING", raising=False)
    assert P.profiling_enabled() is False


@pytest.mark.parametrize("val", ["1", "true", "YES", "on"])
def test_profiling_enabled_truthy(monkeypatch: pytest.MonkeyPatch, val: str) -> None:
    monkeypatch.setenv("ENABLE_PROFILING", val)
    assert P.profiling_enabled() is True


# ── profile_method: sync / async, enabled / disabled ─────────────────────────


def test_profile_method_disabled_zero_overhead(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENABLE_PROFILING", raising=False)

    @P.profile_method
    def double(x: int) -> int:
        return x * 2

    assert double(21) == 42


def test_profile_method_enabled_sync_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("ENABLE_PROFILING", "1")

    @P.profile_method(sort="tottime", limit=3)
    def work(n: int) -> int:
        return sum(range(n))

    with caplog.at_level(logging.DEBUG, logger="super_otonom.profiling"):
        assert work(1000) == 499500
    assert any("profile" in r.message for r in caplog.records)


def test_profile_method_async(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_PROFILING", "1")

    @P.profile_method
    async def aw(x: int) -> int:
        await asyncio.sleep(0)
        return x + 1

    assert asyncio.run(aw(41)) == 42


def test_profile_method_async_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENABLE_PROFILING", raising=False)

    @P.profile_method
    async def aw(x: int) -> int:
        return x

    assert asyncio.run(aw(7)) == 7


# ── RSS / memory ──────────────────────────────────────────────────────────────


def test_rss_bytes_positive() -> None:
    assert P.rss_bytes() > 0


def test_memory_snapshot_and_diff() -> None:
    started = P.start_tracemalloc(nframe=2)
    before = P.take_memory_snapshot("a")
    blob = [bytearray(1024) for _ in range(2000)]  # noqa: F841
    after = P.take_memory_snapshot("b")
    rss_delta, top = P.diff_snapshots(before, after, top=5)
    assert isinstance(rss_delta, int)
    assert isinstance(top, list)
    assert after.traced_current >= 0
    if started:
        P.stop_tracemalloc()


def test_snapshot_top_stats_without_traces() -> None:
    snap = P.take_memory_snapshot("x", capture_traces=False)
    assert snap.top_stats() == []
    assert snap.rss >= 0


# ── TickLatencyTracker ────────────────────────────────────────────────────────


def test_latency_tracker_stats() -> None:
    t = P.TickLatencyTracker(maxlen=100)
    for v in range(1, 101):
        t.record(float(v))
    assert t.count == 100
    assert t.last_ms == 100.0
    assert t.max_ms == 100.0
    assert 49.0 <= t.p50 <= 52.0
    assert 94.0 <= t.p95 <= 96.0
    assert 49.0 <= t.mean_ms <= 52.0
    s = t.stats()
    assert s["count"] == 100 and s["max_ms"] == 100.0


def test_latency_tracker_empty() -> None:
    t = P.TickLatencyTracker()
    assert t.p50 == 0.0 and t.p95 == 0.0 and t.max_ms == 0.0 and t.mean_ms == 0.0


def test_latency_tracker_maxlen_bounded() -> None:
    t = P.TickLatencyTracker(maxlen=10)
    for v in range(100):
        t.record(float(v))
    assert len(t._samples) == 10
    assert t.count == 100  # sayaç toplam çağrı


def test_latency_tracker_clamps_negative() -> None:
    t = P.TickLatencyTracker()
    t.record(-5.0)
    assert t.last_ms == 0.0


# ── measure_latency_ms ────────────────────────────────────────────────────────


def test_measure_latency_ms() -> None:
    with P.measure_latency_ms() as timer:
        sum(range(10_000))
    assert timer.elapsed_ms >= 0.0


# ── record_tick_performance (graceful) ───────────────────────────────────────


class _FakeMetrics:
    def __init__(self) -> None:
        self.calls = []

    def record_performance(self, rss: float, latency: float) -> None:
        self.calls.append((rss, latency))


def test_record_tick_performance_calls_metrics() -> None:
    m = _FakeMetrics()
    P.record_tick_performance(m, 5.5, rss=1000)
    assert m.calls == [(1000, 5.5)]


def test_record_tick_performance_autorss() -> None:
    m = _FakeMetrics()
    P.record_tick_performance(m, 2.0)
    assert len(m.calls) == 1 and m.calls[0][0] > 0


def test_record_tick_performance_none_metrics() -> None:
    P.record_tick_performance(None, 1.0)  # no raise


def test_record_tick_performance_bad_object() -> None:
    P.record_tick_performance(object(), 1.0)  # no record_performance attr → no raise


# ── format_profile ────────────────────────────────────────────────────────────


def test_format_profile() -> None:
    import cProfile

    pr = cProfile.Profile()
    pr.enable()
    sum(range(1000))
    pr.disable()
    text = P.format_profile(pr, limit=5)
    assert "ncalls" in text


# ── scripts ───────────────────────────────────────────────────────────────────


def test_profile_tick_dry_run_json() -> None:
    from scripts.profile_tick import main

    assert main(["--dry-run", "--ticks", "3", "--json"]) == 0


def test_profile_tick_requires_dry_run() -> None:
    from scripts.profile_tick import main

    assert main([]) == 2  # canlı mod reddedilir


def test_profile_tick_text_output(capsys: pytest.CaptureFixture[str]) -> None:
    from scripts.profile_tick import main

    assert main(["--dry-run", "--ticks", "2", "--limit", "5"]) == 0
    out = capsys.readouterr().out
    assert "tick profiling" in out and "latency" in out


def test_memory_check_runs(capsys: pytest.CaptureFixture[str]) -> None:
    from scripts.memory_check import main

    # Yüksek eşik → sızıntı kapısı tetiklenmez (deterministik geçiş).
    rc = main(["--ticks", "3", "--warmup", "1", "--threshold-mb", "100000", "--json"])
    assert rc == 0
    assert '"leak_suspected": false' in capsys.readouterr().out


# ── MetricsExporter.record_performance (PROMPT-10 gauge'ları) ──────────────────


def test_metrics_record_performance() -> None:
    from super_otonom.monitoring.metrics_exporter import MetricsExporter

    me = MetricsExporter(port=0)
    me.record_performance(123_456.0, 4.2)  # no raise; gauge set
    if me._enabled:
        assert me._gauges["memory_rss_bytes"]._value.get() == 123_456.0
        assert me._gauges["tick_latency_ms"]._value.get() == 4.2


def test_metrics_record_performance_disabled() -> None:
    from super_otonom.monitoring.metrics_exporter import MetricsExporter

    me = MetricsExporter(port=0)
    me._enabled = False
    me.record_performance(1.0, 1.0)  # no raise in disabled mode
