"""Shared fixtures: ``gate_check`` (legacy ``check()``), fabrikalar, Windows pytest temproot."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


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


# Windows: pytest atexit may raise PermissionError on stat(pytest-current) under
# %TEMP% or ~/.cache (AV / OneDrive / junction). Use repo-local temproot unless
# the caller already set PYTEST_DEBUG_TEMPROOT.
if sys.platform == "win32":
    _repo_root = Path(__file__).resolve().parents[1]
    _temproot = _repo_root / "build" / "pytest-temproot"
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
