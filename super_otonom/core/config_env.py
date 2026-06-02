"""Shared env helpers — import-time side effect yok."""

from __future__ import annotations

import os


def env_trim(val: str | None) -> str:
    if val is None:
        return ""
    s = str(val).strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        s = s[1:-1].strip()
    return s


def env_pick(*keys: str, default: str = "") -> str:
    for k in keys:
        v = env_trim(os.getenv(k, ""))
        if v:
            return v
    return default


def env_truthy(name: str, default: str = "false") -> bool:
    return env_trim(os.getenv(name, default)).lower() in ("1", "true", "yes", "on")


_dry = env_trim(os.getenv("DRY_RUN", "")).lower() in ("1", "true", "yes", "on")
_paper = env_trim(os.getenv("PAPER_MODE", "true")).lower() == "true"
effective_paper = True if _dry else _paper

# Geriye uyumluluk — testler monkeypatch eder
_effective_paper = effective_paper
