"""
PROMPT-A12 — Release kapısı smoke (marker: ``release_gate``).

Çalıştırma::

    python -m pytest -m release_gate -q

veya ``scripts/release_gate.ps1`` / ``scripts/release_gate.sh``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.release_gate

_ROOT = Path(__file__).resolve().parents[1]


def test_release_gate_execution_pipeline_faz71_to_80_chain() -> None:
    """Faz 71→…→80 + 47 kritik yol (gerçek ``execute_trade_phase`` zinciri)."""
    from super_otonom import test_execution_pipeline_faz80_chain as m

    m.test_execution_pipeline_runs_faz_71_to_79_then_47_80_chain()


def test_release_gate_deploy_env_check_suite() -> None:
    """A9/A12 ortam kontrolü (subprocess — temiz import)."""
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(_ROOT / "tests" / "test_deploy_env_check.py"),
            "-q",
            "--tb=line",
        ],
        cwd=str(_ROOT),
        check=False,
    )
    assert r.returncode == 0, "deploy_env_check suite failed"


def test_release_gate_self_feedback_frozen_core() -> None:
    """PROMPT-A11 donmuş çekirdek yolu."""
    from super_otonom.self_feedback_guard import (
        attach_tick_frozen_mark,
        audit_intratick_frozen_core,
    )

    a = {
        "signal": "HOLD",
        "regime": "RANGING",
        "hurst": 0.5,
        "volatility": 0.02,
    }
    attach_tick_frozen_mark(a, tick_id=1, symbol="BTC/USDT")
    assert audit_intratick_frozen_core(a) is None


def test_release_gate_config_and_hard_safety_import() -> None:
    """Uygulama konfig + kill-switch modülü import (bağımlılık / sözdizimi)."""
    import super_otonom.config as cfg  # noqa: F401
    from super_otonom.kill_switch import HardLimitTracker  # noqa: F401

    assert getattr(cfg, "GENERAL", None) is not None
    assert HardLimitTracker.from_config() is not None


def test_release_gate_coordination_kanon_invariants() -> None:
    """SYSTEM_LONGEVITY — yapı/doküman uyumu + koordinasyon (kanon drift paket içi)."""
    from super_otonom.coordination_resilience import assert_coordination_invariants

    assert_coordination_invariants()


def test_release_gate_coordination_snapshot_has_exit_paths() -> None:
    """Kaos navigasyon haritası boş / kırık olmasın."""
    from super_otonom.coordination_resilience import coordination_snapshot

    snap = coordination_snapshot()
    assert snap["kanon_ok"] is True
    assert isinstance(snap["kanon_issues"], list)
    paths = snap["resilience_exit_paths"]
    assert "triage_repro" in paths
    assert "global_trade_kill" in paths
