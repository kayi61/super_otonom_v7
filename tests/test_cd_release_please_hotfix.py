"""Hotfix: Dockerfile build context + release-please manifest."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_includes_setup_build() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY _setup_build.py" in dockerfile


def test_release_please_manifest_present() -> None:
    manifest = ROOT / ".release-please-manifest.json"
    assert manifest.is_file()
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data.get(".") == "7.0.0"
