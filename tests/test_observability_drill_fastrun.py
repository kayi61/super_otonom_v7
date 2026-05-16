"""PROMPT 3 — observability_drill (mock HTTP)."""

from __future__ import annotations

import json

import pytest
from super_otonom.observability_drill import run_drill

pytestmark = pytest.mark.fastrun


def test_drill_pass_when_metrics_and_telegram_ok(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    doc = tmp_path / "OBSERVABILITY_DRILL.md"

    def fake_get(url: str, timeout: float = 12.0):
        if "rules" in url:
            return 200, json.dumps({"data": {"groups": [{"name": "g1"}]}})
        if "metrics" in url:
            body = "bot_dependency_up 1\nbot_order_errors_total 0\nbot_circuit_breaker_open 0\n"
            return 200, body
        return 200, "ok"

    def fake_post(url: str, payload, timeout: float = 15.0):
        return 200, "ok"

    monkeypatch.setattr("super_otonom.observability_drill._http_get", fake_get)
    monkeypatch.setattr("super_otonom.observability_drill._http_post_json", fake_post)
    assert run_drill(write_doc=True, doc_path=doc) == 0
    assert "PASS" in doc.read_text(encoding="utf-8")


def test_drill_fail_without_telegram_delivery(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    doc = tmp_path / "OBSERVABILITY_DRILL.md"

    def fake_get(url: str, timeout: float = 12.0):
        if "rules" in url:
            return 200, json.dumps({"data": {"groups": [{"name": "g1"}]}})
        if "metrics" in url:
            return 200, "bot_dependency_up 1\nbot_order_errors_total 0\nbot_circuit_breaker_open 0\n"
        return 200, "ok"

    def fake_post(url: str, payload, timeout: float = 15.0):
        return 202, "no_telegram_creds"

    monkeypatch.setattr("super_otonom.observability_drill._http_get", fake_get)
    monkeypatch.setattr("super_otonom.observability_drill._http_post_json", fake_post)
    assert run_drill(write_doc=True, doc_path=doc) == 1
