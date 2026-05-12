"""
deploy_env_check başarı kaydı ve canlı ``main_loop`` kilidi (P0).

Dosya: ``data/reports/deploy_env_check_last_ok.json`` (repo köküne göre).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Tuple

SCHEMA_VERSION = "deploy_env_stamp/v1"
DEFAULT_RELATIVE_PATH = Path("data/reports/deploy_env_check_last_ok.json")

log = logging.getLogger("super_otonom.deploy_env_stamp")


def repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[1]


def stamp_path(repo_root: Optional[Path] = None) -> Path:
    root = repo_root or repo_root_from_here()
    return root / DEFAULT_RELATIVE_PATH


def write_last_ok(repo_root: Optional[Path] = None) -> Path:
    """Başarılı ``deploy_env_check`` sonunda çağrılır."""
    root = repo_root or repo_root_from_here()
    path = stamp_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "passed_at_unix": now,
        "passed_at_iso": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "exit_code": 0,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return path


def read_stamp(repo_root: Optional[Path] = None) -> Optional[dict[str, Any]]:
    path = stamp_path(repo_root)
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def verify_stamp_for_live_start(
    repo_root: Optional[Path] = None,
    *,
    max_age_hours: Optional[float] = None,
) -> Tuple[bool, str]:
    """
    Canlı tick öncesi: damga var mı, yaşı kabul edilebilir mi.

    ``max_age_hours``: ``DEPLOY_ENV_LOCK_MAX_AGE_HOURS`` (varsayılan 168 = 7 gün).
    """
    root = repo_root or repo_root_from_here()
    raw_max = os.getenv("DEPLOY_ENV_LOCK_MAX_AGE_HOURS", "168")
    try:
        mh = float(raw_max) if max_age_hours is None else float(max_age_hours)
    except ValueError:
        mh = 168.0
    data = read_stamp(root)
    if not data:
        return False, f"deploy_env_check başarı dosyası yok: {stamp_path(root)}"
    ts = data.get("passed_at_unix")
    if ts is None:
        return False, "damga dosyasında passed_at_unix yok"
    try:
        ts_f = float(ts)
    except (TypeError, ValueError):
        return False, "passed_at_unix okunamadı"
    age_sec = time.time() - ts_f
    max_sec = max(60.0, mh * 3600.0)
    if age_sec > max_sec:
        return (
            False,
            f"deploy_env_check kaydı eski: {age_sec / 3600:.1f} saat > izin {mh:.0f} saat — "
            f"son PASS: {data.get('passed_at_iso', '?')}",
        )
    iso = data.get("passed_at_iso", "")
    return True, f"deploy_env_check PASS kaydı OK (son: {iso})"


def enforce_live_deploy_env_lock(repo_root: Optional[Path] = None) -> None:
    """
    Canlı profilde (paper kapalı) çağrılır; başarısızsa ``sys.exit(1)``.

    ``DEPLOY_ENV_LOCK_AT_START``: ``0``/``false`` ile kilit kapalı (geliştirme).
    Varsayılan: **açık** (canlıda zorunlu).

    ``DEPLOY_ENV_LOCK_BYPASS=YES``: tek seferlik atlama — kritik log (prod önerilmez).
    """
    from super_otonom.config import GENERAL

    if GENERAL.get("paper_mode", True):
        return
    # Varsayılan kapalı — CI / yerel import kırılmasın. Üretim .env: DEPLOY_ENV_LOCK_AT_START=1
    lock_on = (os.getenv("DEPLOY_ENV_LOCK_AT_START") or "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if not lock_on:
        return

    bypass = (os.getenv("DEPLOY_ENV_LOCK_BYPASS") or "").strip().upper() == "YES"
    ok, msg = verify_stamp_for_live_start(repo_root)
    if ok:
        log.info("deploy_env_check kilidi: %s", msg)
        return
    if bypass:
        log.critical(
            "DEPLOY_ENV_LOCK_BYPASS=YES — deploy_env_check kaydı geçersiz/eski ama tick başlatılıyor: %s",
            msg,
        )
        return
    log.critical(
        "deploy_env_check kilidi — canlı tick başlatılamaz: %s "
        "Çalıştırın: python -m super_otonom.deploy_env_check (RUNBOOK #tatbikat-env).",
        msg,
    )
    sys.exit(1)
