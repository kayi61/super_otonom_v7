"""PROMPT-03: backup.sh dry-run + restore.sh --verify."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def _bash_works() -> bool:
    """PATH'te bash olmasi yetmez; gercekten calismali (bozuk WSL stub'i ele)."""
    if shutil.which("bash") is None:
        return False
    try:
        proc = subprocess.run(
            ["bash", "-c", "echo ok"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0 and "ok" in (proc.stdout or "")


pytestmark = pytest.mark.skipif(
    not _bash_works(),
    reason="calisan bash gerekli (backup.sh / restore.sh Linux deploy scriptleri)",
)

ROOT = Path(__file__).resolve().parents[1]
BACKUP_SH = ROOT / "scripts" / "backup.sh"
RESTORE_SH = ROOT / "scripts" / "restore.sh"


@pytest.mark.skipif(not BACKUP_SH.is_file(), reason="backup.sh missing")
def test_backup_sh_dry_run() -> None:
    proc = subprocess.run(
        ["bash", str(BACKUP_SH), "--dry-run", "--skip-retention"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert "dry-run" in proc.stdout.lower() or "[dry-run]" in proc.stdout


def test_restore_sh_verify_minimal_fixture(tmp_path: Path) -> None:
    fix = tmp_path / "backup-fixture"
    (fix / "timescale").mkdir(parents=True)
    (fix / "data").mkdir()
    (fix / "vault").mkdir()
    (fix / "BACKUP_MANIFEST.txt").write_text("backup_utc=2026-01-01T00:00:00Z\n", encoding="utf-8")
    (fix / "data" / "capital_journal.jsonl").write_text("{}\n", encoding="utf-8")
    (fix / "timescale" / "timescale.dump").write_bytes(b"")

    proc = subprocess.run(
        ["bash", str(RESTORE_SH), "--verify", str(fix)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert "verify: PASS" in proc.stdout


def test_backup_scripts_exist() -> None:
    assert BACKUP_SH.is_file()
    assert RESTORE_SH.is_file()
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "backup:" in compose
    assert "profiles:" in compose
    assert (ROOT / ".github" / "workflows" / "nightly-backup.yml").is_file()
    assert (ROOT / "docs" / "DR_RUNBOOK.md").is_file()
