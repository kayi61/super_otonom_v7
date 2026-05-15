"""dependency_security.py — yardimci fonksiyonlar."""

from __future__ import annotations

from scripts.dependency_security import _flatten_vulns, _load_config


def test_load_config_has_sla() -> None:
    cfg = _load_config()
    assert cfg["remediation_sla_days"]["critical"] == 7
    assert "high" in cfg["ci_fail_severities"]


def test_flatten_vulns() -> None:
    deps = [
        {
            "name": "pkg",
            "version": "1.0",
            "vulns": [{"id": "CVE-2024-1", "severity": "high", "fix_versions": ["1.1"]}],
        }
    ]
    v = _flatten_vulns(deps)
    assert len(v) == 1
    assert v[0]["severity"] == "high"
