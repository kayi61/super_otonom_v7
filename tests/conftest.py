"""Shared fixtures: ``gate_check`` (legacy ``check()``), fabrikalar, Windows pytest temproot."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# ── Standalone script'ler (pytest testi değil) — collection'dan hariç tut ────
collect_ignore = [
    "test_5000.py",
    "test_10000.py",
    "test_capital_engine.py",
    "test_capital_engine_v2_fixes.py",
    "test_capital_engine_v3_fixes.py",
    "test_core_modules.py",
    "test_coverage_boost.py",
    "test_faz2_fixes.py",
    "test_order_reconciliation.py",
    "test_fake_order_book_scenarios.py",
    "test_override_phase_bridge.py",
    "test_smart_order_router.py",
    "test_execution_pipeline_faz80_chain.py",
]


class _GateCheck:
    """Script ``check(label, ok, detail)`` ile aynı sözleşme; anında ``assert`` (pytest traceback)."""

    __slots__ = ()

    @staticmethod
    def check(label: str, ok: object, detail: str = "") -> None:
        __tracebackhide__ = True
        assert ok, label + (f" | {detail}" if detail else "")

    def __call__(self, label: str, ok: object, detail: str = "") -> None:
        self.check(label, ok, detail)


@pytest.fixture
def gate_check() -> _GateCheck:
    """Eski gate ``check(label, ok, detail)`` / ``bulk_check.check`` → pytest DI. ``gate_check(...)`` veya ``.check(...)``."""
    return _GateCheck()


# Windows: pytest atexit may raise PermissionError on stat(pytest-current)
# (AV / OneDrive / kilitli junction). Temproot repoda degil — %TEMP% altinda.
if sys.platform == "win32":
    import tempfile

    import _pytest.pathlib as _pytest_pathlib

    _orig_cleanup_numbered_dir = _pytest_pathlib.cleanup_numbered_dir

    def _safe_cleanup_numbered_dir(root, prefix, keep, consider_lock_dead_if_created_before):
        try:
            _orig_cleanup_numbered_dir(
                root, prefix, keep, consider_lock_dead_if_created_before
            )
        except PermissionError:
            pass

    _pytest_pathlib.cleanup_numbered_dir = _safe_cleanup_numbered_dir

    _temproot = Path(tempfile.gettempdir()) / "super_otonom_pytest"
    try:
        _temproot.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    else:
        os.environ.setdefault("PYTEST_DEBUG_TEMPROOT", str(_temproot))


@pytest.fixture
def capital_engine_factory(tmp_path: Path):
    """Her çağrıda ayrı journal dizini (super_otonom legacy ``make_ce``)."""
    from super_otonom.capital_engine import CapitalEngine

    counter = {"n": 0}

    def _make(cap: float = 10000.0):
        counter["n"] += 1
        sub = tmp_path / f"ce_{counter['n']}"
        sub.mkdir(exist_ok=True)
        return CapitalEngine(
            cap,
            journal_file=str(sub / "j.jsonl"),
            reserve_pct=0.0,
            max_position_pct=1.0,
        )

    return _make


@pytest.fixture
def risk_manager_factory():
    from super_otonom.risk_manager import RiskManager

    def _make(cap: float = 10000.0):
        return RiskManager(initial_capital=cap)

    return _make
