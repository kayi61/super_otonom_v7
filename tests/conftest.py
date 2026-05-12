"""Shared fixtures (optional; tests stay self-contained for now)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Windows: default %TEMP%/pytest-of-<user> registers atexit cleanup that can raise
# PermissionError in _pytest/pathlib.cleanup_dead_symlinks (stat on pytest-current).
# A dedicated temproot keeps pytest's numbered dirs under the user's cache tree.
if sys.platform == "win32":
    _temproot = Path.home() / ".cache" / "super_otonom_pytest_temproot"
    try:
        _temproot.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    else:
        os.environ.setdefault("PYTEST_DEBUG_TEMPROOT", str(_temproot))
