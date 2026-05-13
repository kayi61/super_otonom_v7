"""Second polish pass to push toward 95%."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict

import pytest


@pytest.fixture
def _isolate_bot_state_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import super_otonom.bot_engine as be
    monkeypatch.setattr(be, "_STATE_FILE", str(tmp_path / "bot_state.json"))
    yield


def test_benchmark_mock_smoke(_isolate_bot_state_2, capsys: pytest.CaptureFixture[str]) -> None:
    from super_otonom.benchmark_katman_a import _run_mock_benchmark

    asyncio.run(
        _run_mock_benchmark(
            iterations=1,
            warmup=0,
            scenario="normal",
            symbol="BTC/USDT",
        )
    )
    out = capsys.readouterr().out
    assert "Katman A" in out or "prep_local" in out


def test_benchmark_run_benchmark_routes_to_mock(
    _isolate_bot_state_2, capsys: pytest.CaptureFixture[str]
) -> None:
    from super_otonom.benchmark_katman_a import _run_benchmark

    asyncio.run(
        _run_benchmark(
            iterations=1,
            warmup=0,
            scenario="normal",
            symbol="BTC/USDT",
            live_ob=False,
            exchange_id="binance",
        )
    )
    out = capsys.readouterr().out
    assert "Katman A" in out


def test_benchmark_percentile_helpers() -> None:
    from super_otonom.benchmark_katman_a import _percentile, _print_omega_micro, _summarize

    assert _percentile([], 50) == 0.0
    arr = [1.0, 2.0, 3.0, 4.0, 5.0]
    p50 = _percentile(arr, 50)
    p95 = _percentile(arr, 95)
    assert 1.0 <= p50 <= 5.0
    assert 1.0 <= p95 <= 5.0
    _summarize("test", [10.0, 20.0, 30.0])
    _print_omega_micro()


def test_override_bridge_blocked_entry_scale_perm39() -> None:
    from super_otonom.pipelines.override_phase_bridge import attach_override_phases_to_analysis

    class _Risk:
        emergency_stop = False

    class _Engine:
        risk = _Risk()

    analysis: Dict[str, Any] = {"entry_scale": "blocked", "symbol": "BTC/USDT"}
    attach_override_phases_to_analysis(
        analysis,
        engine=_Engine(),
        dctx=None,
        out={},
        symbol="BTC/USDT",
    )
    assert analysis["phase39"]["trade_permission"] == "BLOCK"


def test_override_bridge_dctx_int_conversion_error() -> None:
    from super_otonom.pipelines.override_phase_bridge import attach_override_phases_to_analysis

    class _Risk:
        emergency_stop = False

    class _Engine:
        risk = _Risk()

    class _Dctx:
        entry_blocked = None
        adj_signal_quality = "not-a-number"
        effective_quality_min = "also-bad"

    analysis: Dict[str, Any] = {"symbol": "BTC/USDT"}
    attach_override_phases_to_analysis(
        analysis,
        engine=_Engine(),
        dctx=_Dctx(),
        out={},
        symbol="BTC/USDT",
    )
    assert "phase64" in analysis


def test_override_bridge_force_all_close_in_fill_governance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from super_otonom.pipelines.override_phase_bridge import fill_governance_phases_if_missing

    monkeypatch.setenv("FORCE_ALL_CLOSE", "1")
    analysis: Dict[str, Any] = {"symbol": "BTC/USDT"}
    fill_governance_phases_if_missing(analysis, "BTC/USDT")
    assert analysis["phase68"]["trade_permission"] == "HALT"
    assert "force_all_close" in analysis["phase68"]["source"]


def test_override_bridge_emergency_stop_perm50_halt() -> None:
    from super_otonom.pipelines.override_phase_bridge import attach_override_phases_to_analysis

    class _Risk:
        emergency_stop = True

    class _Engine:
        risk = _Risk()

    analysis: Dict[str, Any] = {"symbol": "BTC/USDT"}
    attach_override_phases_to_analysis(
        analysis,
        engine=_Engine(),
        dctx=None,
        out={},
        symbol="BTC/USDT",
    )
    assert analysis["phase50"]["trade_permission"] == "HALT"


def test_override_bridge_dctx_entry_blocked_perm39_block() -> None:
    from super_otonom.pipelines.override_phase_bridge import attach_override_phases_to_analysis

    class _Risk:
        emergency_stop = False

    class _Engine:
        risk = _Risk()

    class _Dctx:
        entry_blocked = "fat_finger"
        adj_signal_quality = None
        effective_quality_min = None

    analysis: Dict[str, Any] = {"symbol": "BTC/USDT"}
    attach_override_phases_to_analysis(
        analysis,
        engine=_Engine(),
        dctx=_Dctx(),
        out={},
        symbol="BTC/USDT",
    )
    assert analysis["phase39"]["trade_permission"] == "BLOCK"
