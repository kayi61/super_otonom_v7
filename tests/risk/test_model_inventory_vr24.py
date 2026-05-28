"""VR-24: Model Inventory + Validation Governance tests.

Tests cover:
  - MODEL_INVENTORY.md existence, model count, required columns
  - MODEL_VALIDATION_TEMPLATE.md existence, required sections
  - check_model_validation_due.py parsing, alerting, governance
  - Developer ≠ validator independence rule
  - CLI (--json, --date, --warn-days)
  - GitHub issue auto-open (mocked)
  - var_topology_audit allowlist
"""

from __future__ import annotations

import json
import sys
import textwrap
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

_ROOT = Path(__file__).resolve().parents[2]
from tests._prompt04_source import module_source_path

_PKG = _ROOT / "super_otonom"

sys.path.insert(0, str(_ROOT / "scripts"))

from check_model_validation_due import (
    ModelEntry,
    ValidationAlert,
    check_due,
    format_report,
    main,
    parse_inventory,
)

_INVENTORY = _ROOT / "docs" / "MODEL_INVENTORY.md"
_TEMPLATE = _ROOT / "docs" / "MODEL_VALIDATION_TEMPLATE.md"


# ── Inventory Document ──────────────────────────────────────────────────────


class TestModelInventoryDoc:
    """VR-24: MODEL_INVENTORY.md structure."""

    def test_file_exists(self):
        assert _INVENTORY.is_file()

    def test_has_model_registry_table(self):
        text = _INVENTORY.read_text(encoding="utf-8")
        assert "Model ID" in text
        assert "Model Name" in text
        assert "Developer" in text
        assert "Validator" in text

    def test_minimum_20_models(self):
        entries = parse_inventory(_INVENTORY)
        assert len(entries) >= 20, f"Only {len(entries)} models, need >= 20"

    def test_all_vr_modules_covered(self):
        entries = parse_inventory(_INVENTORY)
        vrs = {e.vr for e in entries}
        required = {f"VR-{i:02d}" for i in range(2, 21)}
        missing = required - vrs
        assert not missing, f"Missing VR references: {missing}"

    def test_has_model_categories(self):
        text = _INVENTORY.read_text(encoding="utf-8")
        assert "Value-at-Risk" in text
        assert "Expected Shortfall" in text or "CVaR" in text
        assert "Backtest" in text

    def test_has_validation_cycle(self):
        text = _INVENTORY.read_text(encoding="utf-8")
        assert "6 months" in text or "semi-annual" in text
        assert "30 days" in text or "30 day" in text

    def test_has_governance_roles(self):
        text = _INVENTORY.read_text(encoding="utf-8")
        assert "quant-dev" in text
        assert "risk-review" in text

    def test_developer_ne_validator_rule(self):
        text = _INVENTORY.read_text(encoding="utf-8")
        assert "developer" in text.lower() and "validator" in text.lower()
        assert "≠" in text or "!=" in text or "different" in text.lower()

    def test_all_entries_have_dates(self):
        entries = parse_inventory(_INVENTORY)
        for e in entries:
            assert e.last_validated is not None
            assert e.next_due is not None
            assert e.next_due > e.last_validated

    def test_no_self_validation(self):
        entries = parse_inventory(_INVENTORY)
        for e in entries:
            assert not e.developer_equals_validator, (
                f"{e.model_id}: developer ({e.developer}) == validator ({e.validator})"
            )

    def test_has_change_log(self):
        text = _INVENTORY.read_text(encoding="utf-8")
        assert "Change Log" in text


# ── Validation Template ─────────────────────────────────────────────────────


class TestValidationTemplate:
    """VR-24: MODEL_VALIDATION_TEMPLATE.md structure."""

    def test_file_exists(self):
        assert _TEMPLATE.is_file()

    def test_has_model_identification(self):
        text = _TEMPLATE.read_text(encoding="utf-8")
        assert "Model Identification" in text
        assert "Model ID" in text

    def test_has_personnel_section(self):
        text = _TEMPLATE.read_text(encoding="utf-8")
        assert "Personnel" in text
        assert "Developer" in text
        assert "Validator" in text

    def test_has_methodology_section(self):
        text = _TEMPLATE.read_text(encoding="utf-8")
        assert "Methodology" in text

    def test_has_statistical_validation(self):
        text = _TEMPLATE.read_text(encoding="utf-8")
        assert "Statistical Validation" in text
        assert "Backtesting" in text

    def test_has_findings(self):
        text = _TEMPLATE.read_text(encoding="utf-8")
        assert "Findings" in text
        assert "APPROVED" in text

    def test_has_sign_off(self):
        text = _TEMPLATE.read_text(encoding="utf-8")
        assert "Sign-off" in text

    def test_has_independence_rule(self):
        text = _TEMPLATE.read_text(encoding="utf-8")
        assert "≠" in text or "different" in text.lower() or "aynı kişi" in text.lower()

    def test_has_implementation_review(self):
        text = _TEMPLATE.read_text(encoding="utf-8")
        assert "Implementation Review" in text
        assert "Code Quality" in text or "Test Coverage" in text

    def test_has_data_quality(self):
        text = _TEMPLATE.read_text(encoding="utf-8")
        assert "Data Quality" in text


# ── Parsing ─────────────────────────────────────────────────────────────────


class TestParsing:
    """VR-24: Inventory parsing."""

    def test_parse_real_inventory(self):
        entries = parse_inventory(_INVENTORY)
        assert len(entries) > 0

    def test_entry_fields(self):
        entries = parse_inventory(_INVENTORY)
        e = entries[0]
        assert e.model_id.startswith("MR-")
        assert e.vr.startswith("VR-")
        assert e.developer != ""
        assert e.validator != ""

    def test_parse_synthetic(self, tmp_path):
        md = tmp_path / "inv.md"
        md.write_text(textwrap.dedent("""\
            # Model Inventory

            | Model ID | Model Name | VR | Module | Type | Developer | Validator | Last Validated | Next Due | Status |
            |----------|------------|-----|--------|------|-----------|-----------|---------------|----------|--------|
            | MR-TEST | Test Model | VR-99 | `risk/test.py` | VaR | alice | bob | 2026-01-01 | 2026-07-01 | Active |
        """), encoding="utf-8")
        entries = parse_inventory(md)
        assert len(entries) == 1
        assert entries[0].model_id == "MR-TEST"
        assert entries[0].developer == "alice"
        assert entries[0].validator == "bob"
        assert entries[0].next_due == date(2026, 7, 1)

    def test_parse_missing_file(self, tmp_path):
        entries = parse_inventory(tmp_path / "nonexistent.md")
        assert entries == []

    def test_parse_ignores_header_row(self, tmp_path):
        md = tmp_path / "inv.md"
        md.write_text(textwrap.dedent("""\
            | Model ID | Model Name | VR | Module | Type | Developer | Validator | Last Validated | Next Due | Status |
            |----------|------------|-----|--------|------|-----------|-----------|---------------|----------|--------|
            | MR-A | Alpha | VR-01 | `x.py` | VaR | dev1 | val1 | 2026-01-01 | 2026-07-01 | Active |
            | MR-B | Beta | VR-02 | `y.py` | CVaR | dev2 | val2 | 2026-02-01 | 2026-08-01 | Active |
        """), encoding="utf-8")
        entries = parse_inventory(md)
        assert len(entries) == 2


# ── Due Date Checks ─────────────────────────────────────────────────────────


class TestCheckDue:
    """VR-24: Due date alert logic."""

    def _make_entry(self, model_id="MR-X", next_due="2026-07-01",
                    developer="alice", validator="bob", status="Active"):
        return ModelEntry(
            model_id=model_id, name="Test", vr="VR-99", module="x.py",
            model_type="VaR", developer=developer, validator=validator,
            last_validated=date(2026, 1, 1), next_due=date.fromisoformat(next_due),
            status=status,
        )

    def test_no_alerts_when_far(self):
        e = self._make_entry(next_due="2027-01-01")
        alerts = check_due([e], today=date(2026, 6, 1))
        assert len(alerts) == 0

    def test_alert_when_within_30_days(self):
        e = self._make_entry(next_due="2026-06-20")
        alerts = check_due([e], today=date(2026, 6, 1))
        assert len(alerts) == 1
        assert alerts[0].days_remaining == 19
        assert not alerts[0].overdue

    def test_alert_when_overdue(self):
        e = self._make_entry(next_due="2026-05-01")
        alerts = check_due([e], today=date(2026, 6, 1))
        assert len(alerts) == 1
        assert alerts[0].overdue
        assert alerts[0].days_remaining < 0

    def test_alert_on_exact_boundary(self):
        e = self._make_entry(next_due="2026-07-01")
        alerts = check_due([e], today=date(2026, 6, 1))
        assert len(alerts) == 1
        assert alerts[0].days_remaining == 30

    def test_no_alert_for_retired(self):
        e = self._make_entry(next_due="2026-06-01", status="Retired")
        alerts = check_due([e], today=date(2026, 5, 25))
        assert len(alerts) == 0

    def test_custom_warn_days(self):
        e = self._make_entry(next_due="2026-07-15")
        alerts = check_due([e], today=date(2026, 6, 1), warn_days=60)
        assert len(alerts) == 1

    def test_governance_violation_detected(self):
        e = self._make_entry(next_due="2027-01-01", developer="alice", validator="alice")
        alerts = check_due([e], today=date(2026, 1, 1))
        assert len(alerts) == 1
        assert alerts[0].governance_violation

    def test_governance_case_insensitive(self):
        e = self._make_entry(developer="Alice", validator="alice")
        alerts = check_due([e], today=date(2025, 1, 1))
        assert len(alerts) == 1
        assert alerts[0].governance_violation

    def test_multiple_alerts(self):
        entries = [
            self._make_entry("MR-A", next_due="2026-06-15"),
            self._make_entry("MR-B", next_due="2026-05-01"),
            self._make_entry("MR-C", next_due="2027-01-01"),
        ]
        alerts = check_due(entries, today=date(2026, 6, 1))
        assert len(alerts) == 2
        ids = {a.model_id for a in alerts}
        assert "MR-A" in ids
        assert "MR-B" in ids


# ── Format Report ────────────────────────────────────────────────────────────


class TestFormatReport:
    """VR-24: Report formatting."""

    def test_no_alerts_message(self):
        report = format_report([])
        assert "No action required" in report

    def test_overdue_tag(self):
        a = ValidationAlert("MR-X", "Test", date(2026, 5, 1), -10, True, False)
        report = format_report([a])
        assert "[OVERDUE]" in report

    def test_due_soon_tag(self):
        a = ValidationAlert("MR-X", "Test", date(2026, 7, 1), 15, False, False)
        report = format_report([a])
        assert "[DUE SOON]" in report

    def test_governance_tag(self):
        a = ValidationAlert("MR-X", "Test", date(2026, 7, 1), 15, False, True)
        report = format_report([a])
        assert "[GOVERNANCE]" in report


# ── GitHub Issue Creation (mocked) ───────────────────────────────────────────


class TestGitHubIssue:
    """VR-24: GitHub issue auto-open."""

    @patch("check_model_validation_due.subprocess.run")
    def test_overdue_issue(self, mock_run):
        from check_model_validation_due import _open_github_issue
        mock_run.return_value = MagicMock(returncode=0)
        a = ValidationAlert("MR-X", "Test", date(2026, 5, 1), -10, True, False)
        ok = _open_github_issue(a)
        assert ok
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "OVERDUE" in cmd[cmd.index("--title") + 1]

    @patch("check_model_validation_due.subprocess.run")
    def test_due_soon_issue(self, mock_run):
        from check_model_validation_due import _open_github_issue
        mock_run.return_value = MagicMock(returncode=0)
        a = ValidationAlert("MR-X", "Test", date(2026, 7, 1), 20, False, False)
        ok = _open_github_issue(a)
        assert ok
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "DUE SOON" in cmd[cmd.index("--title") + 1]

    @patch("check_model_validation_due.subprocess.run")
    def test_governance_issue(self, mock_run):
        from check_model_validation_due import _open_github_issue
        mock_run.return_value = MagicMock(returncode=0)
        a = ValidationAlert("MR-X", "Test", date(2026, 7, 1), 20, False, True)
        ok = _open_github_issue(a)
        assert ok
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "GOVERNANCE" in cmd[cmd.index("--title") + 1]

    @patch("check_model_validation_due.subprocess.run", side_effect=FileNotFoundError)
    def test_issue_failure_gh_missing(self, mock_run):
        from check_model_validation_due import _open_github_issue
        a = ValidationAlert("MR-X", "Test", date(2026, 5, 1), -10, True, False)
        ok = _open_github_issue(a)
        assert not ok

    @patch("check_model_validation_due.subprocess.run")
    def test_issue_has_risk_label(self, mock_run):
        from check_model_validation_due import _open_github_issue
        mock_run.return_value = MagicMock(returncode=0)
        a = ValidationAlert("MR-X", "Test", date(2026, 5, 1), -10, True, False)
        _open_github_issue(a)
        cmd = mock_run.call_args[0][0]
        label_idx = cmd.index("--label")
        assert "risk" in cmd[label_idx + 1]


# ── CLI ──────────────────────────────────────────────────────────────────────


class TestCLI:
    """VR-24: CLI interface."""

    def test_json_output(self, capsys):
        rc = main(["--json", "--date", "2025-01-01"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "ok" in data
        assert "total_models" in data
        assert data["total_models"] >= 20
        assert rc == 0

    def test_text_output_no_alerts(self, capsys):
        rc = main(["--date", "2025-01-01"])
        captured = capsys.readouterr()
        assert "No action required" in captured.out
        assert rc == 0

    def test_exit_code_1_on_alerts(self):
        rc = main(["--date", "2026-09-25"])
        assert rc == 1

    def test_custom_warn_days(self, capsys):
        rc = main(["--json", "--date", "2026-08-15", "--warn-days", "60"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert len(data["alerts"]) > 0
        assert rc == 1

    @patch("check_model_validation_due._open_github_issue", return_value=True)
    def test_ci_flag_opens_issues(self, mock_issue, capsys):
        rc = main(["--ci", "--date", "2026-09-25"])
        assert mock_issue.called
        assert rc == 1


# ── Sentinel ─────────────────────────────────────────────────────────────────


class TestSentinel:
    """VR-24: Sentinel marker."""

    def test_sentinel_present(self):
        src = _ROOT / "scripts" / "check_model_validation_due.py"
        text = src.read_text(encoding="utf-8")
        assert "model_validation_governance_active = True" in text


# ── Audit Allowlist ──────────────────────────────────────────────────────────


class TestAuditAllowlist:
    """VR-24: var_topology_audit allowlist entries."""

    def test_test_file_in_allowlist(self):
        text = module_source_path(_PKG, "var_topology_audit").read_text(encoding="utf-8")
        assert "test_model_inventory_vr24" in text

    def test_inventory_doc_in_allowlist(self):
        text = module_source_path(_PKG, "var_topology_audit").read_text(encoding="utf-8")
        assert "MODEL_INVENTORY.md" in text

    def test_template_doc_in_allowlist(self):
        text = module_source_path(_PKG, "var_topology_audit").read_text(encoding="utf-8")
        assert "MODEL_VALIDATION_TEMPLATE.md" in text

    def test_script_in_allowlist(self):
        text = module_source_path(_PKG, "var_topology_audit").read_text(encoding="utf-8")
        assert "check_model_validation_due" in text
