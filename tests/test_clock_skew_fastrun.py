"""Audit 6 — clock skew ölçümü, metrik sözleşmesi ve mum sırası."""

from __future__ import annotations

import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from super_otonom.clock_skew import (
    check_candle_timestamps_monotonic,
    clock_skew_disclosure,
    evaluate_skew,
    probe_host_ntp_sync,
    read_ccxt_skew_ms,
    validate_clock_skew_wiring,
)
from super_otonom.clock_skew_audit import audit_clock_skew_claims
from super_otonom.clock_skew_audit import main as clock_audit_main

pytestmark = pytest.mark.fastrun


def test_evaluate_skew_levels() -> None:
    assert evaluate_skew(100).level == "ok"
    assert evaluate_skew(600).level == "warning"
    assert evaluate_skew(-2500).level == "critical"


def test_read_ccxt_skew_ms() -> None:
    ex = SimpleNamespace(options={"timeDifference": 123})
    assert read_ccxt_skew_ms(ex) == 123
    assert read_ccxt_skew_ms(SimpleNamespace(options={})) is None


def test_candle_monotonic_detects_violation() -> None:
    candles = [
        {"timestamp": 1000},
        {"timestamp": 900},
    ]
    issues = check_candle_timestamps_monotonic(candles)
    assert issues and "non-monotonic" in issues[0]


def test_disclosure_no_institutional_ntp() -> None:
    d = clock_skew_disclosure(last_skew_ms=42, ntp_sync=None)
    assert d["institutional_ntp_claim_allowed"] is False
    assert d["clock_skew_controlled"] is True
    assert "bot_clock_skew_abs_ms" in d["metrics"]


def test_validate_wiring_on_repo() -> None:
    assert validate_clock_skew_wiring() == []


def test_audit_repo_clean() -> None:
    assert audit_clock_skew_claims() == []


def test_clock_audit_cli_json() -> None:
    buf = StringIO()
    with redirect_stdout(buf):
        assert clock_audit_main(["--json"]) == 0
    payload = json.loads(buf.getvalue())
    assert payload["ok"] is True


def test_forbidden_ntp_claim_detected(tmp_path: Path) -> None:
    (tmp_path / "bad.md").write_text("We offer NTP synchronized trading.\n", encoding="utf-8")
    issues = audit_clock_skew_claims(root=tmp_path)
    assert any("forbidden" in i for i in issues)


def test_probe_host_ntp_returns_optional_bool() -> None:
    with patch("super_otonom.clock_skew.subprocess.run") as run:
        run.return_value = SimpleNamespace(returncode=0, stdout="yes\n", stderr="")
        with patch("super_otonom.clock_skew.platform.system", return_value="Linux"):
            assert probe_host_ntp_sync() is True


def test_metrics_exporter_record_clock_skew() -> None:
    from super_otonom.metrics_exporter import MetricsExporter

    m = MetricsExporter(port=0, namespace="test_cs2")
    if not m.is_active:
        pytest.skip("prometheus_client not installed")
    m.record_clock_skew("binance", 750)
    m.record_host_ntp(False)
    m.record_host_ntp(None)


def test_read_ccxt_skew_invalid() -> None:
    ex = SimpleNamespace(options={"timeDifference": "bad"})
    assert read_ccxt_skew_ms(ex) is None
    assert read_ccxt_skew_ms(None) is None


def test_monotonic_check_age_ms() -> None:
    from super_otonom.clock_skew import monotonic_check_age_ms

    assert monotonic_check_age_ms([]) == -1
    age = monotonic_check_age_ms([{"timestamp": int(__import__("time").time() * 1000)}])
    assert age >= 0


def test_validate_wiring_missing_files(tmp_path: Path) -> None:
    issues = validate_clock_skew_wiring(tmp_path)
    assert any("missing" in i for i in issues)


def test_probe_windows_branch() -> None:
    with patch("super_otonom.clock_skew.subprocess.run") as run:
        run.return_value = SimpleNamespace(
            returncode=0,
            stdout="Leap Indicator: 0\nLast Successful Sync Time: ...\n",
            stderr="",
        )
        with patch("super_otonom.clock_skew.platform.system", return_value="Windows"):
            assert probe_host_ntp_sync() is True


def test_disclosure_ntp_not_sync() -> None:
    d = clock_skew_disclosure(last_skew_ms=3000, ntp_sync=False)
    assert "host_ntp_not_synchronized" in d["limitations"]
    assert d["last_skew_level"] == "critical"


def test_clock_audit_text_ok(capsys: pytest.CaptureFixture[str]) -> None:
    assert clock_audit_main([]) == 0
    assert "OK: True" in capsys.readouterr().out


def test_probe_linux_not_sync() -> None:
    with patch("super_otonom.clock_skew.subprocess.run") as run:
        run.return_value = SimpleNamespace(returncode=0, stdout="no\n", stderr="")
        with patch("super_otonom.clock_skew.platform.system", return_value="Linux"):
            assert probe_host_ntp_sync() is False


def test_probe_subprocess_failure() -> None:
    with patch("super_otonom.clock_skew.subprocess.run", side_effect=OSError("nope")):
        assert probe_host_ntp_sync() is None


def test_probe_windows_cmos() -> None:
    with patch("super_otonom.clock_skew.subprocess.run") as run:
        run.return_value = SimpleNamespace(
            returncode=0,
            stdout="Source: Local CMOS Clock\n",
            stderr="",
        )
        with patch("super_otonom.clock_skew.platform.system", return_value="Windows"):
            assert probe_host_ntp_sync() is False


def test_candle_invalid_timestamp() -> None:
    issues = check_candle_timestamps_monotonic([{"timestamp": "x"}])
    assert any("invalid" in i for i in issues)


def test_validate_compose_missing_marker(tmp_path: Path) -> None:
    (tmp_path / "docker-compose.yml").write_text("# no marker\n", encoding="utf-8")
    issues = validate_clock_skew_wiring(tmp_path)
    assert any("audit 6" in i for i in issues)


def test_probe_windows_leap_unsync() -> None:
    with patch("super_otonom.clock_skew.subprocess.run") as run:
        run.return_value = SimpleNamespace(
            returncode=0,
            stdout="Leap Indicator: 3\n",
            stderr="",
        )
        with patch("super_otonom.clock_skew.platform.system", return_value="Windows"):
            assert probe_host_ntp_sync() is False


def test_probe_linux_unknown_value() -> None:
    with patch("super_otonom.clock_skew.subprocess.run") as run:
        run.return_value = SimpleNamespace(returncode=0, stdout="maybe\n", stderr="")
        with patch("super_otonom.clock_skew.platform.system", return_value="Linux"):
            assert probe_host_ntp_sync() is None


def test_audit_missing_institutional_flag(tmp_path: Path) -> None:
    pkg = tmp_path / "super_otonom"
    pkg.mkdir()
    (pkg / "clock_skew.py").write_text("# stub\n", encoding="utf-8")
    issues = audit_clock_skew_claims(root=tmp_path)
    assert any("institutional_ntp_claim_allowed" in i for i in issues)
