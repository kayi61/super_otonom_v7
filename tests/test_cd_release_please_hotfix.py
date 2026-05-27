"""Hotfix: Dockerfile build context + release-please manifest + CD workflow."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_includes_setup_build() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY _setup_build.py" in dockerfile


def test_release_please_manifest_present() -> None:
    manifest = ROOT / ".release-please-manifest.json"
    assert manifest.is_file()
    data = json.loads(manifest.read_text(encoding="utf-8"))
    version = data.get(".")
    assert version, "manifest must have root version key"
    assert re.match(r"^\d+\.\d+\.\d+$", str(version)), f"invalid semver: {version}"


def test_cd_workflow_tag_filter_valid() -> None:
    text = (ROOT / ".github" / "workflows" / "cd.yml").read_text(encoding="utf-8")
    assert 'tags: ["v*.*.*"]' not in text
    assert re.search(r'tags:\s*\n\s*-\s+"v\*"', text) or 'tags:\n      - "v*"' in text


def test_release_please_workflow_permissions() -> None:
    text = (ROOT / ".github" / "workflows" / "release-please.yml").read_text(
        encoding="utf-8"
    )
    assert "pull-requests: write" in text
    assert "contents: write" in text
