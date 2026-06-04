"""PROMPT-5.3 — GitHub Developer Activity Tracker + Faz 27 entegrasyonu."""

from __future__ import annotations

import json

import pytest
from super_otonom.signals.alternative_data_engine import analyze_alternative_data
from super_otonom.signals.developer_activity_tracker import (
    GithubCollector,
    analyze_developer_activity,
    analyze_developer_data,
    analyze_github_metrics,
    comparative_analysis,
    detect_positive_signals,
    detect_red_flags,
    parse_github_commit_count,
    parse_github_repo,
)

# ── 1) GitHub metrikleri ─────────────────────────────────────────────────────


def test_github_metrics_activity() -> None:
    m = analyze_github_metrics(
        commits_30d=80, commits_90d=180, unique_contributors=15,
        pr_merged=18, pr_opened=20, issues_opened=30, issues_closed=25,
        star_growth_rate=0.05, fork_growth_rate=0.03,
    )
    assert 0.0 < m.activity_score <= 1.0
    assert m.pr_merge_rate == pytest.approx(0.9)
    assert m.issue_close_ratio == pytest.approx(25 / 30)


def test_github_momentum_accelerating() -> None:
    # 30g hızı (60), 90g aylık ortalaması (90/3=30) → momentum pozitif
    m = analyze_github_metrics(commits_30d=60, commits_90d=90)
    assert m.momentum > 0


def test_github_momentum_declining() -> None:
    m = analyze_github_metrics(commits_30d=10, commits_90d=120)
    assert m.momentum < 0


# ── 2) Red flag ──────────────────────────────────────────────────────────────


def test_red_flag_abandoned() -> None:
    risk, reasons = detect_red_flags(commits_30d=0)
    assert risk >= 0.8
    assert any("terkedilmiş" in r for r in reasons)


def test_red_flag_stale_days() -> None:
    risk, _ = detect_red_flags(days_since_last_commit=90)
    assert risk >= 0.8


def test_red_flag_bus_factor() -> None:
    risk, reasons = detect_red_flags(commits_30d=20, bus_factor=1)
    assert risk >= 0.5
    assert any("bus factor" in r for r in reasons)


def test_red_flag_version_bump_and_readme() -> None:
    assert detect_red_flags(commits_30d=10, version_bump_only=True)[0] >= 0.4
    assert detect_red_flags(commits_30d=10, readme_only=True)[0] >= 0.4


def test_red_flag_none_when_healthy() -> None:
    risk, reasons = detect_red_flags(commits_30d=50, bus_factor=8)
    assert risk == 0.0 and reasons == []


# ── 3) Pozitif sinyal ────────────────────────────────────────────────────────


def test_positive_upgrade_branch() -> None:
    alpha, reasons = detect_positive_signals(upgrade_branch=True)
    assert alpha >= 0.3 and any("upgrade" in r for r in reasons)


def test_positive_audit_commits() -> None:
    alpha, reasons = detect_positive_signals(audit_commits=True)
    assert alpha >= 0.2 and any("audit" in r.lower() for r in reasons)


def test_positive_onboarding() -> None:
    alpha, _ = detect_positive_signals(new_contributors_30d=5)
    assert alpha >= 0.2


def test_positive_none() -> None:
    assert detect_positive_signals()[0] == 0.0


# ── 4) Karşılaştırmalı ───────────────────────────────────────────────────────


def test_comparative_undervalued() -> None:
    comp = comparative_analysis(0.6, commits_30d=100, fdv_usd=50_000_000)
    assert comp.dev_per_fdv == pytest.approx(2.0)  # 100 commit / $50M = 2/$1M
    assert comp.undervalued is True


def test_comparative_rank() -> None:
    comp = comparative_analysis(0.8, peer_activities=[0.3, 0.5, 0.6])
    assert comp.relative_rank == pytest.approx(1.0)


def test_comparative_no_fdv() -> None:
    comp = comparative_analysis(0.5)
    assert comp.dev_per_fdv is None and comp.undervalued is False


# ── Birleşik analiz ──────────────────────────────────────────────────────────


def test_analyze_healthy_project() -> None:
    sig = analyze_developer_activity(
        commits_30d=70, commits_90d=180, unique_contributors=12,
        upgrade_branch=True, new_contributors_30d=4,
    )
    assert sig.health > 0.4
    assert sig.alpha_bias > 0
    assert sig.risk_score == 0.0
    assert any("upgrade" in s for s in sig.positive_signals)


def test_analyze_abandoned_project() -> None:
    sig = analyze_developer_activity(commits_30d=0, days_since_last_commit=120, bus_factor=1)
    assert sig.risk_score >= 0.8
    assert sig.alpha_bias < 0
    assert len(sig.red_flags) >= 2


def test_analyze_undervalued_boosts_alpha() -> None:
    base = analyze_developer_activity(commits_30d=80, commits_90d=200, unique_contributors=10)
    uv = analyze_developer_activity(
        commits_30d=80, commits_90d=200, unique_contributors=10, fdv_usd=40_000_000,
    )
    assert uv.comparative.undervalued is True
    assert uv.alpha_bias > base.alpha_bias


# ── Köprü (analyze_developer_data) ───────────────────────────────────────────


def test_developer_data_activates_on_extended() -> None:
    sig = analyze_developer_data({"commits_30d": 60, "unique_contributors": 10, "upgrade_branch": True})
    assert sig is not None and sig.activity_score > 0


def test_developer_data_bare_basic_no_activation() -> None:
    """Yalın commits_30d/pr_count → yeni modül tetiklenmez (eski Faz 27 korunur)."""
    assert analyze_developer_data({"commits_30d": 50, "pr_count": 10}) is None


def test_developer_data_empty_none() -> None:
    assert analyze_developer_data({}) is None
    assert analyze_developer_data("nope") is None


# ── Parser + Collector ───────────────────────────────────────────────────────


def test_parse_github_repo() -> None:
    payload = {"stargazers_count": 1200, "forks_count": 300, "open_issues_count": 45}
    out = parse_github_repo(json.dumps(payload))
    assert out["stars"] == 1200 and out["forks"] == 300


def test_parse_github_commit_count() -> None:
    assert parse_github_commit_count(json.dumps([{"sha": "a"}, {"sha": "b"}])) == 2
    assert parse_github_commit_count("not json") == 0


def test_collector_repo() -> None:
    payload = json.dumps({"stargazers_count": 500, "forks_count": 100})
    col = GithubCollector(http_get=lambda u, t: payload)
    out = col.fetch_repo("foo/bar")
    assert out["stars"] == 500


def test_collector_none_graceful() -> None:
    col = GithubCollector(http_get=lambda u, t: None)
    assert col.fetch_repo("foo/bar") == {}
    assert col.fetch_commit_count("foo/bar") == 0


# ── Faz 27 (alternative_data_engine) entegrasyonu ────────────────────────────


def test_faz27_developer_deep_attached() -> None:
    alt = {"developer": {
        "commits_30d": 70, "commits_90d": 180, "unique_contributors": 12,
        "upgrade_branch": True, "fdv_usd": 40_000_000,
    }}
    out = analyze_alternative_data("ARB/USDT", alt, {"signal": "BUY"})
    assert "developer_deep" in out["alternative_data"]
    assert out["alternative_data"]["developer_deep"]["developer_activity_score"] > 0


def test_faz27_abandoned_raises_risk() -> None:
    healthy = {"developer": {"commits_30d": 70, "commits_90d": 180, "unique_contributors": 12}}
    dead = {"developer": {"commits_30d": 0, "days_since_last_commit": 120, "bus_factor": 1}}
    r_ok = analyze_alternative_data("X/USDT", healthy, {"signal": "BUY"})
    r_dead = analyze_alternative_data("X/USDT", dead, {"signal": "BUY"})
    assert r_dead["risk_score"] > r_ok["risk_score"]


def test_faz27_backward_compat_basic_developer() -> None:
    """Yalın commits_30d → developer_deep eklenmez, eski davranış korunur."""
    out = analyze_alternative_data("X/USDT", {"developer": {"commits_30d": 50}}, {"signal": "BUY"})
    assert "developer_deep" not in out["alternative_data"]


def test_faz27_backward_compat_no_developer() -> None:
    out = analyze_alternative_data("X/USDT", {"adoption": {"active_users": 1e6}}, {"signal": "BUY"})
    assert "developer_deep" not in out["alternative_data"]
