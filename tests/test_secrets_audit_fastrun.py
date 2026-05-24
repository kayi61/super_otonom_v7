"""PROMPT 2 — secrets_audit duman (sir yazilmaz)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from super_otonom.infra.secrets_audit import _scan_dotenv_key_names, run_audit

pytestmark = pytest.mark.fastrun

_ROOT = Path(__file__).resolve().parents[1]


def test_scan_dotenv_key_names_detects_names_only(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("BINANCE_API_KEY=secret-value\nDRY_RUN=true\n", encoding="utf-8")
    found = _scan_dotenv_key_names(env, ["BINANCE_API_KEY", "BINANCE_API_SECRET"])
    assert found == ["BINANCE_API_KEY"]
    assert "secret-value" not in str(found)


def test_run_audit_writes_doc_without_secret_patterns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    doc = tmp_path / "SECRETS_AUDIT_LAST.md"
    monkeypatch.chdir(_ROOT)
    code = run_audit(write_doc=True, doc_path=doc)
    assert doc.is_file()
    body = doc.read_text(encoding="utf-8")
    assert "BINANCE_API_KEY=" not in body
    assert re.search(r"api_key\s*=\s*['\"][^'\"]+['\"]", body) is None
    assert "Checklist" in body
    assert code in (0, 1, 2)
