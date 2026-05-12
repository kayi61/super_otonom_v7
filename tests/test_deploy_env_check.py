"""deploy_env_check — temiz ortamda subprocess (config tekil import)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _subenv(**extra: str) -> dict[str, str]:
    base = {k: v for k, v in os.environ.items() if k in ("SYSTEMROOT", "PATH", "WINDIR", "PATHEXT")}
    base["PYTHONPATH"] = str(_ROOT)
    base.update(extra)
    return base


def test_deploy_env_check_ok_paper_advisory_loose():
    r = subprocess.run(
        [sys.executable, "-m", "super_otonom.deploy_env_check"],
        env=_subenv(
            META_REGIME_MODE="advisory",
            META_ADVISORY_LOOSE="1",
            PAPER_MODE="true",
            DRY_RUN="true",
        ),
        cwd=str(_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr


def test_deploy_env_check_fails_live_advisory_loose():
    r = subprocess.run(
        [sys.executable, "-m", "super_otonom.deploy_env_check"],
        env=_subenv(
            META_REGIME_MODE="advisory",
            META_ADVISORY_LOOSE="1",
            PAPER_MODE="false",
            DRY_RUN="false",
        ),
        cwd=str(_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 1
    assert "META_ADVISORY_LOOSE" in (r.stderr or "")


def test_deploy_env_check_fails_live_advisory_missing_ack(tmp_path):
    ack = tmp_path / "missing_ack_marker"
    r = subprocess.run(
        [sys.executable, "-m", "super_otonom.deploy_env_check"],
        env=_subenv(
            META_REGIME_MODE="advisory",
            META_ADVISORY_LOOSE="0",
            PAPER_MODE="false",
            DRY_RUN="false",
            LIVE_CONFIRM="YES",
            META_ADVISORY_DEFAULT_ACK_FILE=str(ack),
        ),
        cwd=str(_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 1
    assert "ACK" in (r.stderr or "") or "ack" in (r.stderr or "").lower()


def test_deploy_env_check_fails_live_without_live_confirm():
    r = subprocess.run(
        [sys.executable, "-m", "super_otonom.deploy_env_check"],
        env=_subenv(
            META_REGIME_MODE="shadow",
            PAPER_MODE="false",
            DRY_RUN="false",
            LIVE_CONFIRM="",
        ),
        cwd=str(_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 1
    assert "LIVE_CONFIRM" in (r.stderr or "")


def test_deploy_env_check_ok_live_shadow_with_confirm():
    r = subprocess.run(
        [sys.executable, "-m", "super_otonom.deploy_env_check"],
        env=_subenv(
            META_REGIME_MODE="shadow",
            PAPER_MODE="false",
            DRY_RUN="false",
            LIVE_CONFIRM="YES",
        ),
        cwd=str(_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    assert "LIVE_CONFIRM='YES'" in (r.stdout or "") or "LIVE_CONFIRM=" in (r.stdout or "")
    assert "max_daily_loss_pct" in (r.stdout or "")
    assert "P0 - INSTITUTIONAL" in (r.stdout or "") or "sect.1 alignment" in (r.stdout or "")
    assert "deploy_env_check_last_ok" in (r.stdout or "") or "zaman damgası" in (r.stdout or "") or "basari" in (r.stdout or "").lower()
