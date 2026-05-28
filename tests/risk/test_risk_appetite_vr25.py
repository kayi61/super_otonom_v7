"""VR-25: Risk Appetite Statement + Escalation Matrix tests.

Tests cover:
  - RISK_APPETITE.md existence, structure, required sections
  - Escalation matrix levels (AMBER/RED/CRITICAL)
  - Approval levels documented
  - Quarterly review section
  - risk_appetite_check.py parsing and consistency checks
  - VaRLimits cross-reference accuracy
  - CLI (--json)
  - var_topology_audit allowlist
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
from tests._prompt04_source import module_source_path

_PKG = _ROOT / "super_otonom"

sys.path.insert(0, str(_ROOT / "scripts"))

from risk_appetite_check import (
    AppetiteEntry,
    ConsistencyIssue,
    check_appetite_vs_limits,
    check_approval_levels,
    check_escalation_matrix,
    check_quarterly_review,
    format_report,
    main,
    parse_appetite_limits,
    run_all_checks,
)

_APPETITE = _ROOT / "docs" / "RISK_APPETITE.md"


# ── Document Structure ──────────────────────────────────────────────────────


class TestRiskAppetiteDoc:
    """VR-25: RISK_APPETITE.md structure."""

    def test_file_exists(self):
        assert _APPETITE.is_file()

    def test_has_market_risk(self):
        text = _APPETITE.read_text(encoding="utf-8")
        assert "Market Risk" in text
        assert "VaR" in text

    def test_has_liquidity_risk(self):
        text = _APPETITE.read_text(encoding="utf-8")
        assert "Liquidity Risk" in text
        assert "LVaR" in text

    def test_has_operational_risk(self):
        text = _APPETITE.read_text(encoding="utf-8")
        assert "Operational Risk" in text
        assert "Unexplained PnL" in text

    def test_has_counterparty_risk(self):
        text = _APPETITE.read_text(encoding="utf-8")
        assert "Counterparty Risk" in text

    def test_has_tolerance_levels(self):
        text = _APPETITE.read_text(encoding="utf-8")
        assert "GREEN" in text
        assert "AMBER" in text
        assert "RED" in text
        assert "CRITICAL" in text

    def test_has_specific_limits_table(self):
        text = _APPETITE.read_text(encoding="utf-8")
        assert "Specific Limits" in text
        assert "max_var_total_pct" in text
        assert "max_cvar_total_pct" in text

    def test_has_escalation_matrix(self):
        text = _APPETITE.read_text(encoding="utf-8")
        assert "Escalation Matrix" in text
        assert "emergency_stop" in text

    def test_has_approval_levels(self):
        text = _APPETITE.read_text(encoding="utf-8")
        assert "Approval" in text
        assert "< 2%" in text
        assert "> 5%" in text

    def test_has_quarterly_review(self):
        text = _APPETITE.read_text(encoding="utf-8")
        assert "Quarterly" in text or "quarterly" in text
        assert "Review" in text or "review" in text

    def test_has_change_log(self):
        text = _APPETITE.read_text(encoding="utf-8")
        assert "Change Log" in text

    def test_has_defensive_mode(self):
        text = _APPETITE.read_text(encoding="utf-8")
        assert "Defansif" in text or "defensive" in text.lower()

    def test_has_var_limits_crossref(self):
        text = _APPETITE.read_text(encoding="utf-8")
        assert "var_limits.py" in text
        assert "var_limits.yaml" in text


# ── Escalation Matrix Details ───────────────────────────────────────────────


class TestEscalationMatrix:
    """VR-25: Escalation matrix requirements."""

    def test_amber_notify(self):
        text = _APPETITE.read_text(encoding="utf-8")
        assert "on-call" in text.lower() or "on_call" in text.lower()

    def test_red_single_defensive(self):
        text = _APPETITE.read_text(encoding="utf-8")
        assert "%50" in text or "50%" in text

    def test_red_multiple_emergency_stop(self):
        text = _APPETITE.read_text(encoding="utf-8")
        assert "emergency_stop" in text

    def test_critical_halt_postmortem(self):
        text = _APPETITE.read_text(encoding="utf-8")
        assert "post-mortem" in text or "postmortem" in text.lower()
        assert "24h" in text or "24 saat" in text

    def test_l1_through_l4(self):
        text = _APPETITE.read_text(encoding="utf-8")
        assert "L1" in text
        assert "L2" in text
        assert "L3" in text
        assert "L4" in text

    def test_amber_bot_continues(self):
        text = _APPETITE.read_text(encoding="utf-8")
        lower = text.lower()
        assert "bot" in lower and ("devam" in lower or "continues" in lower)

    def test_red_no_new_pairs(self):
        text = _APPETITE.read_text(encoding="utf-8")
        assert "no_new_pairs" in text or "yeni pair" in text.lower()


# ── Parsing ─────────────────────────────────────────────────────────────────


class TestParsing:
    """VR-25: Appetite limit parsing."""

    def test_parse_real_doc(self):
        entries = parse_appetite_limits(_APPETITE)
        assert len(entries) >= 8, f"Only {len(entries)} entries parsed"

    def test_parsed_fields_match_var_limits(self):
        entries = parse_appetite_limits(_APPETITE)
        fields = {e.field for e in entries}
        required = {
            "max_var_total_pct",
            "max_cvar_total_pct",
            "max_stressed_var_total_pct",
            "max_marginal_var_per_trade_pct",
            "max_component_var_per_position_pct",
            "max_lvar_to_nav",
        }
        missing = required - fields
        assert not missing, f"Missing fields: {missing}"

    def test_parse_missing_file(self, tmp_path):
        entries = parse_appetite_limits(tmp_path / "nope.md")
        assert entries == []

    def test_parse_synthetic(self, tmp_path):
        md = tmp_path / "appetite.md"
        md.write_text(textwrap.dedent("""\
            ## 3. Specific Limits (VaR Limits Cross-Reference)

            | Limit | VaRLimits Field | Default | Appetite Zone |
            |-------|----------------|---------|---------------|
            | Portfolio VaR 99% | `max_var_total_pct` | 6% | GREEN ≤ 4% |
        """), encoding="utf-8")
        entries = parse_appetite_limits(md)
        assert len(entries) == 1
        assert entries[0].field == "max_var_total_pct"
        assert entries[0].doc_default == "6%"


# ── Consistency Checks ──────────────────────────────────────────────────────


class TestConsistencyChecks:
    """VR-25: RiskConfig ↔ RiskAppetite consistency."""

    def test_no_issues_with_real_doc(self):
        issues, summary = run_all_checks(_APPETITE)
        assert summary["ok"], f"Issues found: {issues}"

    def test_limits_defaults_match(self):
        from risk_appetite_check import _parse_pct
        from super_otonom.risk.var_limits import VaRLimits

        entries = parse_appetite_limits(_APPETITE)
        lim = VaRLimits()
        for e in entries:
            if hasattr(lim, e.field):
                code_val = getattr(lim, e.field)
                doc_val = _parse_pct(e.doc_default)
                if doc_val is None:
                    continue
                assert abs(doc_val - code_val) < 1e-6, (
                    f"{e.field}: doc={doc_val} code={code_val}"
                )

    def test_appetite_mismatch_detected(self):
        entry = AppetiteEntry(
            label="Test", field="max_var_total_pct",
            doc_default="99%", zones="whatever",
        )
        issues = check_appetite_vs_limits(
            [entry], {"max_var_total_pct": 0.06}
        )
        assert len(issues) == 1
        assert issues[0].severity == "error"

    def test_missing_field_detected(self):
        entry = AppetiteEntry(
            label="Test", field="nonexistent_field",
            doc_default="5%", zones="whatever",
        )
        issues = check_appetite_vs_limits([entry], {})
        assert len(issues) == 1
        assert "NOT FOUND" in issues[0].actual

    def test_matching_values_no_issue(self):
        entry = AppetiteEntry(
            label="Test", field="max_var_total_pct",
            doc_default="6%", zones="whatever",
        )
        issues = check_appetite_vs_limits(
            [entry], {"max_var_total_pct": 0.06}
        )
        assert len(issues) == 0

    def test_escalation_check_passes(self):
        issues = check_escalation_matrix(_APPETITE)
        assert len(issues) == 0

    def test_escalation_check_missing_keyword(self, tmp_path):
        md = tmp_path / "bad.md"
        md.write_text("# Risk Appetite\nNothing here", encoding="utf-8")
        issues = check_escalation_matrix(md)
        assert len(issues) >= 1

    def test_approval_check_passes(self):
        issues = check_approval_levels(_APPETITE)
        assert len(issues) == 0

    def test_quarterly_check_passes(self):
        issues = check_quarterly_review(_APPETITE)
        assert len(issues) == 0


# ── Format Report ────────────────────────────────────────────────────────────


class TestFormatReport:
    """VR-25: Report formatting."""

    def test_clean_report(self):
        report = format_report([], {"appetite_entries": 8, "var_limits_fields": 8, "ok": True})
        assert "PASSED" in report

    def test_error_report(self):
        issues = [ConsistencyIssue("x", "a", "b", "error")]
        report = format_report(issues, {"appetite_entries": 1, "var_limits_fields": 1, "ok": False})
        assert "ERROR" in report

    def test_warning_report(self):
        issues = [ConsistencyIssue("x", "a", "b", "warning")]
        report = format_report(issues, {"appetite_entries": 1, "var_limits_fields": 1, "ok": False})
        assert "WARNING" in report


# ── CLI ──────────────────────────────────────────────────────────────────────


class TestCLI:
    """VR-25: CLI interface."""

    def test_text_output_passes(self, capsys):
        rc = main([])
        captured = capsys.readouterr()
        assert "Appetite entries" in captured.out
        assert rc == 0

    def test_json_output(self, capsys):
        rc = main(["--json"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "ok" in data
        assert "appetite_entries" in data
        assert data["appetite_entries"] >= 8
        assert rc == 0

    def test_exit_0_on_consistent(self):
        rc = main([])
        assert rc == 0


# ── Sentinel ─────────────────────────────────────────────────────────────────


class TestSentinel:
    """VR-25: Sentinel marker."""

    def test_sentinel_present(self):
        src = _ROOT / "scripts" / "risk_appetite_check.py"
        text = src.read_text(encoding="utf-8")
        assert "risk_appetite_check_active = True" in text


# ── Audit Allowlist ──────────────────────────────────────────────────────────


class TestAuditAllowlist:
    """VR-25: var_topology_audit allowlist entries."""

    def test_test_file_in_allowlist(self):
        text = module_source_path(_PKG, "var_topology_audit").read_text(encoding="utf-8")
        assert "test_risk_appetite_vr25" in text

    def test_appetite_doc_in_allowlist(self):
        text = module_source_path(_PKG, "var_topology_audit").read_text(encoding="utf-8")
        assert "RISK_APPETITE.md" in text

    def test_script_in_allowlist(self):
        text = module_source_path(_PKG, "var_topology_audit").read_text(encoding="utf-8")
        assert "risk_appetite_check" in text
