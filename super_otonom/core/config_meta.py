"""Config meta-regime advisory — lazy init (PROMPT-09)."""

from __future__ import annotations

import logging
import os

_META_ADVISORY_LOGGED = False


def _log_meta_advisory_env_at_import() -> None:
    """Canlı/paper ile A9 env uyumu (runbook: META_ORCHESTRATOR_A9)."""
    mode = (os.getenv("META_REGIME_MODE") or "shadow").strip().lower()
    if mode != "advisory":
        return
    loose = (os.getenv("META_ADVISORY_LOOSE") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    log = logging.getLogger("super_otonom.config")
    import super_otonom.core.config as _cfg

    live_like = not _cfg._effective_paper
    if live_like and loose:
        log.warning(
            "META_ADVISORY_LOOSE etkin ve paper/dry-run kapalı — A9 ölçüm kilidi devre dışı. "
            "Üretimde kaldırın; geliştirici .env kopyalamayın. Bkz. docs/META_ORCHESTRATOR_A9.md"
        )
        return
    if not live_like:
        return
    from super_otonom.meta_regime_orchestrator import advisory_ack_path_for_gate

    path = advisory_ack_path_for_gate("advisory")
    if path is None:
        return
    try:
        ok = os.path.isfile(path) and os.path.getsize(path) > 0
    except OSError:
        ok = False
    if not ok:
        log.warning(
            "META_REGIME_MODE=advisory, ölçüm ACK yok veya boş (%s) — güven çarpanı uygulanmaz. "
            'python -m super_otonom.meta_regime_orchestrator --message "…" veya '
            "scripts/write_meta_advisory_ack.ps1",
            path,
        )
    else:
        log.info("META_REGIME_MODE=advisory, ölçüm ACK mevcut: %s", path)


def ensure_meta_advisory_env_logged() -> None:
    """İlk risk/config erişiminde bir kez çalışır; import anında değil."""
    global _META_ADVISORY_LOGGED
    if _META_ADVISORY_LOGGED:
        return
    _log_meta_advisory_env_at_import()
    _META_ADVISORY_LOGGED = True


def reset_meta_advisory_log_flag() -> None:
    """Test isolation."""
    global _META_ADVISORY_LOGGED
    _META_ADVISORY_LOGGED = False
