"""VR-22: Günlük Risk Raporu — Otomatik Üretim tests.

Tests cover:
  - Report generation (Markdown output with all 10 sections)
  - JSON output mode
  - CLI argument parsing
  - Section formatting (tables, bullet points, emojis)
  - Edge cases: no data, no returns, empty positions
  - PDF converter module import
  - Sentinel presence
  - var_topology_audit allowlist
  - Integration: report with real RiskEngine data
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Make scripts importable
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def sample_returns():
    """120 synthetic returns for testing."""
    import random

    rng = random.Random(42)
    return [rng.gauss(0.0005, 0.02) for _ in range(120)]


@pytest.fixture()
def sample_positions():
    return {"BTC/USDT": 0.5, "ETH/USDT": 0.3, "SOL/USDT": 0.2}


@pytest.fixture()
def tmp_data_dir(tmp_path):
    """Create temporary data directory with sample files."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # Capital journal
    journal = data_dir / "capital_journal.jsonl"
    journal.write_text(
        json.dumps({"equity": 50000.0, "free_capital": 35000.0}) + "\n",
        encoding="utf-8",
    )

    # Realized PnL
    import random

    rng = random.Random(42)
    returns = [rng.gauss(0.0005, 0.02) for _ in range(120)]
    pnl = data_dir / "realized_pnl.json"
    pnl.write_text(json.dumps({"returns": returns}), encoding="utf-8")

    # Positions
    pos = data_dir / "positions.json"
    pos.write_text(
        json.dumps({"BTC/USDT": 0.5, "ETH/USDT": 0.3}),
        encoding="utf-8",
    )

    # Empty breach log
    breach = data_dir / "breach_log.jsonl"
    breach.write_text("", encoding="utf-8")

    return data_dir


# ── Report generator import ──────────────────────────────────────────────────


class TestReportGeneration:
    """VR-22: generate_report() produces valid Markdown with all 10 sections."""

    def test_generate_report_returns_string(self):
        from generate_daily_risk_report import generate_report

        report = generate_report(report_date="2026-05-21")
        assert isinstance(report, str)
        assert len(report) > 100

    def test_report_has_header(self):
        from generate_daily_risk_report import generate_report

        report = generate_report(report_date="2026-05-21")
        assert "# Günlük Risk Raporu" in report
        assert "2026-05-21" in report

    def test_report_has_all_10_sections(self):
        from generate_daily_risk_report import generate_report

        report = generate_report(report_date="2026-05-21")
        for i in range(1, 11):
            assert f"## {i}." in report or f"## {i} " in report, (
                f"Section {i} missing from report"
            )

    def test_section_1_summary_table(self):
        from generate_daily_risk_report import generate_report

        report = generate_report(report_date="2026-05-21")
        assert "Sermaye" in report or "Equity" in report
        assert "NAV" in report
        assert "USDT" in report

    def test_section_2_var_matrix(self):
        from generate_daily_risk_report import generate_report

        report = generate_report(report_date="2026-05-21")
        assert "VaR Matrisi" in report

    def test_section_3_cvar(self):
        from generate_daily_risk_report import generate_report

        report = generate_report(report_date="2026-05-21")
        assert "CVaR" in report

    def test_section_4_stressed_var(self):
        from generate_daily_risk_report import generate_report

        report = generate_report(report_date="2026-05-21")
        assert "Stressed VaR" in report

    def test_section_7_backtest(self):
        from generate_daily_risk_report import generate_report

        report = generate_report(report_date="2026-05-21")
        assert "Backtest" in report

    def test_section_10_manual_review(self):
        from generate_daily_risk_report import generate_report

        report = generate_report(report_date="2026-05-21")
        assert "Manuel" in report

    def test_report_footer(self):
        from generate_daily_risk_report import generate_report

        report = generate_report(report_date="2026-05-21")
        assert "VR-22" in report
        assert "generate_daily_risk_report" in report


class TestReportJSON:
    """VR-22: JSON output mode."""

    def test_json_output_is_dict(self):
        from generate_daily_risk_report import generate_report_json

        data = generate_report_json(report_date="2026-05-21")
        assert isinstance(data, dict)

    def test_json_has_required_keys(self):
        from generate_daily_risk_report import generate_report_json

        data = generate_report_json(report_date="2026-05-21")
        required = {"date", "generated_at", "capital", "n_returns", "risk_metrics", "backtest"}
        assert required.issubset(set(data.keys()))

    def test_json_date_matches(self):
        from generate_daily_risk_report import generate_report_json

        data = generate_report_json(report_date="2026-05-21")
        assert data["date"] == "2026-05-21"

    def test_json_capital_has_equity(self):
        from generate_daily_risk_report import generate_report_json

        data = generate_report_json(report_date="2026-05-21")
        assert "equity" in data["capital"]
        assert isinstance(data["capital"]["equity"], float)

    def test_json_serializable(self):
        from generate_daily_risk_report import generate_report_json

        data = generate_report_json(report_date="2026-05-21")
        # Should not raise
        serialized = json.dumps(data, default=str)
        assert len(serialized) > 50


class TestCLI:
    """VR-22: CLI argument parsing."""

    def test_main_stdout(self):
        from generate_daily_risk_report import main

        # --stdout should not write a file
        rc = main(["--date", "2026-05-21", "--stdout"])
        assert rc == 0

    def test_main_json(self, capsys):
        from generate_daily_risk_report import main

        rc = main(["--date", "2026-05-21", "--json"])
        assert rc == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["date"] == "2026-05-21"

    def test_main_file_output(self, tmp_path):
        from generate_daily_risk_report import main

        out = tmp_path / "test_report.md"
        rc = main(["--date", "2026-05-21", "--out", str(out)])
        assert rc == 0
        assert out.is_file()
        content = out.read_text(encoding="utf-8")
        assert "# Günlük Risk Raporu" in content
        assert len(content) > 200


class TestSectionFormatting:
    """VR-22: Individual section formatting."""

    def test_fmt_pct_none(self):
        from generate_daily_risk_report import _fmt_pct

        assert _fmt_pct(None) == "—"

    def test_fmt_pct_value(self):
        from generate_daily_risk_report import _fmt_pct

        assert _fmt_pct(0.0123) == "0.0123"

    def test_fmt_pct_display(self):
        from generate_daily_risk_report import _fmt_pct_display

        assert _fmt_pct_display(0.05) == "5.00%"

    def test_fmt_pct_display_none(self):
        from generate_daily_risk_report import _fmt_pct_display

        assert _fmt_pct_display(None) == "—"

    def test_section_1_with_data(self):
        from generate_daily_risk_report import _section_1_summary

        cap = {
            "equity": 50000.0,
            "nav": 50000.0,
            "free_capital": 35000.0,
            "gross_exposure": 15000.0,
            "net_exposure": 15000.0,
            "leverage": 0.3,
            "max_daily_loss_pct": 0.05,
            "max_total_drawdown": 0.20,
        }
        result = _section_1_summary(cap)
        assert "50,000.00" in result
        assert "0.30x" in result

    def test_section_5_no_positions(self):
        from generate_daily_risk_report import _section_5_positions

        result = _section_5_positions(None, {})
        assert "Açık pozisyon yok" in result

    def test_section_6_no_stress(self):
        from generate_daily_risk_report import _section_6_stress

        result = _section_6_stress([])
        assert "Senaryo verisi yok" in result

    def test_section_8_no_attribution(self):
        from generate_daily_risk_report import _section_8_pnl_attribution

        result = _section_8_pnl_attribution(None)
        assert "mevcut değil" in result

    def test_section_9_no_breaches(self):
        from generate_daily_risk_report import _section_9_breach_log

        result = _section_9_breach_log([])
        assert "ihlali yok" in result

    def test_section_10_no_flags(self):
        from generate_daily_risk_report import _section_10_manual_review

        result = _section_10_manual_review(None, {}, [])
        assert "olay yok" in result

    def test_section_9_with_breaches(self):
        from generate_daily_risk_report import _section_9_breach_log

        breaches = [
            {"timestamp": "2026-05-21T10:00:00", "type": "var_99", "detail": "VaR limit exceeded"},
            {"timestamp": "2026-05-21T11:00:00", "type": "cvar_975", "message": "CVaR breach"},
        ]
        result = _section_9_breach_log(breaches)
        assert "var_99" in result
        assert "cvar_975" in result

    def test_section_10_with_high_dispersion(self):
        from generate_daily_risk_report import _section_10_manual_review

        mock_metrics = MagicMock()
        mock_metrics.model_dispersion_pct = 0.7
        mock_metrics.stressed_var_breach = False
        mock_metrics.lvar = 0.03

        result = _section_10_manual_review(mock_metrics, {}, [])
        assert "dispersion" in result.lower()

    def test_section_10_traffic_light_red(self):
        from generate_daily_risk_report import _section_10_manual_review

        bt = {"traffic_light": {"zone": "RED", "exceedances": 12, "capital_addon": 1.0}}
        result = _section_10_manual_review(None, bt, [])
        assert "RED" in result


class TestEdgeCases:
    """VR-22: Edge cases."""

    def test_empty_returns(self):
        """Report still generates with no return data."""
        from generate_daily_risk_report import generate_report

        with patch(
            "generate_daily_risk_report._load_returns", return_value=[],
        ):
            report = generate_report(report_date="2026-05-21")
            assert "Yetersiz veri" in report

    def test_missing_data_files(self):
        """Report generates gracefully when data files are missing."""
        from generate_daily_risk_report import generate_report

        report = generate_report(report_date="2026-05-21")
        assert isinstance(report, str)
        assert len(report) > 100

    def test_var_matrix_with_none_metrics(self):
        from generate_daily_risk_report import _section_2_var_matrix

        result = _section_2_var_matrix(None)
        assert "Yetersiz veri" in result

    def test_stressed_var_with_none_metrics(self):
        from generate_daily_risk_report import _section_4_stressed_var

        result = _section_4_stressed_var(None)
        assert "Yetersiz veri" in result


class TestBacktestIntegration:
    """VR-22: Backtest section with real calculations."""

    def test_backtest_with_returns(self, sample_returns):
        from generate_daily_risk_report import _load_backtest_results

        result = _load_backtest_results(sample_returns)
        # With 120 returns (>50), Kupiec should run
        assert result["kupiec"] is not None
        assert "p_value" in result["kupiec"]
        assert result["kupiec"]["n_obs"] > 0

    def test_backtest_insufficient_data(self):
        from generate_daily_risk_report import _load_backtest_results

        result = _load_backtest_results([0.01] * 10)
        assert result["kupiec"] is None

    def test_christoffersen_with_returns(self, sample_returns):
        from generate_daily_risk_report import _load_backtest_results

        result = _load_backtest_results(sample_returns)
        if result["christoffersen"] is not None:
            assert "cc_pvalue" in result["christoffersen"]


class TestRiskMetricsIntegration:
    """VR-22: RiskEngine integration."""

    def test_collect_risk_metrics(self, sample_returns):
        from generate_daily_risk_report import _collect_risk_metrics

        metrics = _collect_risk_metrics(sample_returns)
        assert metrics is not None
        assert hasattr(metrics, "var_99_1d")
        assert hasattr(metrics, "cvar_975_1d")
        assert metrics.var_99_1d > 0

    def test_collect_risk_metrics_insufficient_data(self):
        from generate_daily_risk_report import _collect_risk_metrics

        metrics = _collect_risk_metrics([0.01] * 5)
        assert metrics is None

    def test_full_report_with_returns(self, sample_returns):
        """Full report with real RiskEngine calculations."""
        from generate_daily_risk_report import generate_report

        with patch(
            "generate_daily_risk_report._load_returns",
            return_value=sample_returns,
        ):
            report = generate_report(report_date="2026-05-21")
            # VaR matrix should have real numbers
            assert "0." in report  # At least some decimal values
            assert "VaR Matrisi" in report


class TestPDFConverter:
    """VR-22: PDF converter module."""

    def test_pdf_module_importable(self):
        import risk_report_to_pdf

        assert hasattr(risk_report_to_pdf, "convert_md_to_pdf")
        assert hasattr(risk_report_to_pdf, "_md_to_html")

    def test_md_to_html(self):
        from risk_report_to_pdf import _md_to_html

        html = _md_to_html("# Test\n\nHello world")
        assert "<html" in html
        assert "Test" in html

    def test_find_latest_report_empty(self, tmp_path):
        from risk_report_to_pdf import _find_latest_report

        with patch("risk_report_to_pdf._ROOT", tmp_path):
            result = _find_latest_report()
            # No docs dir
            assert result is None

    def test_find_latest_report_with_files(self, tmp_path):
        from risk_report_to_pdf import _find_latest_report

        reports_dir = tmp_path / "docs" / "risk_reports"
        reports_dir.mkdir(parents=True)
        (reports_dir / "risk_2026-05-20.md").write_text("old", encoding="utf-8")
        (reports_dir / "risk_2026-05-21.md").write_text("new", encoding="utf-8")

        with patch("risk_report_to_pdf._ROOT", tmp_path):
            result = _find_latest_report()
            assert result is not None
            assert "2026-05-21" in result.name


class TestSentinel:
    """VR-22: var_topology sentinel."""

    def test_sentinel_in_report_generator(self):
        src = _ROOT / "scripts" / "generate_daily_risk_report.py"
        text = src.read_text(encoding="utf-8")
        assert "daily_risk_report_active" in text

    def test_sentinel_value(self):
        from generate_daily_risk_report import daily_risk_report_active

        assert daily_risk_report_active is True


class TestAuditAllowlist:
    """VR-22: Test file and substrings in audit allowlist."""

    def test_test_file_in_allowlist(self):
        src = _ROOT / "super_otonom" / "var_topology_audit.py"
        text = src.read_text(encoding="utf-8")
        assert "test_daily_risk_report_vr22" in text

    def test_script_files_in_allowlist(self):
        src = _ROOT / "super_otonom" / "var_topology_audit.py"
        text = src.read_text(encoding="utf-8")
        assert "generate_daily_risk_report" in text
        assert "risk_report_to_pdf" in text

    def test_substrings_in_allowlist(self):
        src = _ROOT / "super_otonom" / "var_topology_audit.py"
        text = src.read_text(encoding="utf-8")
        for s in ("daily_risk_report", "generate_report", "risk_report_to_pdf"):
            assert s in text, f"Missing allow substr: {s}"


class TestCapitalSnapshot:
    """VR-22: Capital data collection."""

    def test_default_capital(self):
        from generate_daily_risk_report import _collect_capital_snapshot

        cap = _collect_capital_snapshot()
        assert "equity" in cap
        assert "nav" in cap
        assert "leverage" in cap
        assert cap["equity"] > 0

    def test_capital_with_journal(self, tmp_data_dir):
        from generate_daily_risk_report import _collect_capital_snapshot

        with patch("generate_daily_risk_report._ROOT", tmp_data_dir.parent):
            cap = _collect_capital_snapshot()
            assert cap["equity"] == 50000.0
            assert cap["free_capital"] == 35000.0
