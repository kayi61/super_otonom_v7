from __future__ import annotations

import os
from pathlib import Path


def runtime_dir() -> str:
    """Directory for mutable runtime artifacts that must not dirty the repo."""
    raw = (os.getenv("SUPER_OTONOM_RUNTIME_DIR") or "data/runtime").strip()
    return raw or "data/runtime"


def runtime_path(*parts: str) -> str:
    """Build a path under the runtime directory."""
    return str(Path(runtime_dir(), *parts))
