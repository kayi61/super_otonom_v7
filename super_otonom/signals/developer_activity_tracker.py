"""PROMPT-5.3 — GitHub Developer Activity Tracker — Faz 27 developer feed.

Kripto proje geliştirici aktivitesini takip eder; `alternative_data_engine`
(Faz 27) developer bölümünü zenginleştirir.

1. **GitHub metrikleri**: commit frekansı (30/90g), unique contributor trendi,
   PR merge hızı (momentum), issue açılma/kapanma oranı, star/fork growth.
2. **Red flag**: commit sıfıra düşme (terkedilmiş), tek geliştirici (bus factor=1),
   şüpheli commit (sadece version bump), README-only (marketing).
3. **Pozitif sinyal**: mainnet/upgrade branch (yaklaşan upgrade), büyük refactor
   (olgunlaşma), yeni developer onboarding, audit firma commit'leri.
4. **Karşılaştırmalı**: aynı sektör projeleriyle dev aktivitesi; dev activity / FDV
   oranı (undervalued tespiti).

Kaynak: GitHub API (ücretsiz, 5000 req/saat; enjekte edilebilir ``http_get``).
Analiz fonksiyonları saftır (ağsız test edilir).
"""

from __future__ import annotations

import json
import logging
import math
import os
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

log = logging.getLogger("super_otonom.devactivity")

HttpGet = Callable[[str, float], Optional[str]]

# Eşikler
ABANDONED_DAYS = 60.0           # son commit'ten beri > 60g → terkedilmiş
LOW_COMMITS_30D = 3             # < → ölü/durmuş proje şüphesi


def _coerce_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else float(x)


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _truthy(v: Any) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y", "evet")
    return bool(v)


def _default_http_get(url: str, timeout: float) -> Optional[str]:
    try:
        headers = {"User-Agent": "super_otonom/1.0", "Accept": "application/vnd.github+json"}
        token = os.getenv("GITHUB_TOKEN", "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        log.debug("github http_get hata (%s): %s", url[:60], exc)
        return None


# ── 1) GitHub metrikleri ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class GithubMetrics:
    commits_30d: float
    commits_90d: float
    unique_contributors: float
    pr_merge_rate: float            # 0..1 (merged / opened)
    issue_close_ratio: float        # 0..1 (closed / opened)
    star_growth_rate: float         # oran (0.05 = %5)
    fork_growth_rate: float
    momentum: float                 # -1..1 (30g hızı vs 90g ortalaması)
    activity_score: float           # 0..1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "commits_30d": self.commits_30d,
            "commits_90d": self.commits_90d,
            "unique_contributors": self.unique_contributors,
            "pr_merge_rate": self.pr_merge_rate,
            "issue_close_ratio": self.issue_close_ratio,
            "star_growth_rate": self.star_growth_rate,
            "fork_growth_rate": self.fork_growth_rate,
            "momentum": self.momentum,
            "activity_score": self.activity_score,
        }


def analyze_github_metrics(
    *,
    commits_30d: Optional[float] = None,
    commits_90d: Optional[float] = None,
    unique_contributors: Optional[float] = None,
    pr_merged: Optional[float] = None,
    pr_opened: Optional[float] = None,
    issues_opened: Optional[float] = None,
    issues_closed: Optional[float] = None,
    star_growth_rate: Optional[float] = None,
    fork_growth_rate: Optional[float] = None,
) -> GithubMetrics:
    """Ham GitHub metriklerini aktivite skoruna + momentuma indirger."""
    c30 = max(0.0, _coerce_float(commits_30d) or 0.0)
    c90 = max(0.0, _coerce_float(commits_90d) or (c30 * 3.0))
    contrib = max(0.0, _coerce_float(unique_contributors) or 0.0)
    prm = _coerce_float(pr_merged)
    pro = _coerce_float(pr_opened)
    iso = _coerce_float(issues_opened)
    isc = _coerce_float(issues_closed)
    sg = _coerce_float(star_growth_rate) or 0.0
    fg = _coerce_float(fork_growth_rate) or 0.0

    pr_rate = _clamp01(prm / pro) if (prm is not None and pro and pro > 0) else 0.5
    issue_ratio = _clamp01(isc / iso) if (isc is not None and iso and iso > 0) else 0.5

    # Momentum: 30g hızı, 90g ortalama aylık hızına (c90/3) göre
    base_month = c90 / 3.0
    if base_month > 1e-9:
        momentum = _clamp((c30 - base_month) / base_month, -1.0, 1.0)
    else:
        momentum = 1.0 if c30 > 0 else 0.0

    s_commits = _clamp01(math.tanh(c30 / 60.0))
    s_contrib = _clamp01(math.tanh(contrib / 12.0))
    s_growth = _clamp01(math.tanh((max(0.0, sg) + max(0.0, fg)) / 0.2))
    activity = _clamp01(
        0.40 * s_commits + 0.24 * s_contrib + 0.16 * pr_rate + 0.10 * issue_ratio + 0.10 * s_growth
    )
    return GithubMetrics(
        commits_30d=float(c30),
        commits_90d=float(c90),
        unique_contributors=float(contrib),
        pr_merge_rate=float(pr_rate),
        issue_close_ratio=float(issue_ratio),
        star_growth_rate=float(sg),
        fork_growth_rate=float(fg),
        momentum=float(momentum),
        activity_score=float(activity),
    )


# ── 2) Red flag tespiti ──────────────────────────────────────────────────────


def detect_red_flags(
    *,
    commits_30d: Optional[float] = None,
    days_since_last_commit: Optional[float] = None,
    bus_factor: Optional[float] = None,
    version_bump_only: bool = False,
    readme_only: bool = False,
) -> tuple[float, List[str]]:
    """Geliştirme red flag'leri → risk (0..1) + gerekçeler."""
    reasons: List[str] = []
    risk = 0.0
    c30 = _coerce_float(commits_30d)
    days = _coerce_float(days_since_last_commit)

    if (c30 is not None and c30 <= 0) or (days is not None and days >= ABANDONED_DAYS):
        risk = max(risk, 0.8)
        reasons.append("Commit sıfıra düştü / uzun süredir commit yok → terkedilmiş proje")
    elif c30 is not None and c30 < LOW_COMMITS_30D:
        risk = max(risk, 0.45)
        reasons.append(f"Düşük commit aktivitesi (30g: {int(c30)})")

    bf = _coerce_float(bus_factor)
    if bf is not None and bf <= 1:
        risk = max(risk, 0.5)
        reasons.append("Tek geliştirici bağımlılığı (bus factor = 1)")

    if version_bump_only:
        risk = max(risk, 0.4)
        reasons.append("Şüpheli commit pattern (sadece version bump)")
    if readme_only:
        risk = max(risk, 0.42)
        reasons.append("Sadece README/marketing güncellemeleri (gerçek dev yok)")

    return _clamp01(risk), reasons


# ── 3) Pozitif sinyal tespiti ────────────────────────────────────────────────


def detect_positive_signals(
    *,
    upgrade_branch: bool = False,
    large_refactor: bool = False,
    new_contributors_30d: Optional[float] = None,
    audit_commits: bool = False,
) -> tuple[float, List[str]]:
    """Pozitif geliştirme sinyalleri → alpha (0..1) + gerekçeler."""
    reasons: List[str] = []
    alpha = 0.0
    if upgrade_branch:
        alpha += 0.30
        reasons.append("Mainnet/upgrade branch → yaklaşan upgrade")
    if large_refactor:
        alpha += 0.18
        reasons.append("Büyük refactoring → olgunlaşan proje")
    nc = _coerce_float(new_contributors_30d) or 0.0
    if nc >= 3:
        alpha += 0.20
        reasons.append(f"Yeni developer onboarding artışı ({int(nc)})")
    if audit_commits:
        alpha += 0.24
        reasons.append("Audit firma commit'leri → security audit yaklaşıyor")
    return _clamp01(alpha), reasons


# ── 4) Karşılaştırmalı analiz ────────────────────────────────────────────────


@dataclass(frozen=True)
class ComparativeStats:
    relative_rank: float            # 0..1 (peer medyanına göre)
    dev_per_fdv: Optional[float]    # commits_30d / (FDV / $1M)
    undervalued: bool               # yüksek dev/FDV + iyi aktivite

    def to_dict(self) -> Dict[str, Any]:
        return {
            "relative_rank": self.relative_rank,
            "dev_per_fdv": self.dev_per_fdv,
            "undervalued": self.undervalued,
        }


def comparative_analysis(
    activity_score: float,
    *,
    commits_30d: Optional[float] = None,
    fdv_usd: Optional[float] = None,
    peer_activities: Optional[Sequence[float]] = None,
) -> ComparativeStats:
    """Peer karşılaştırması + dev activity / FDV (undervalued tespiti)."""
    peers = [p for p in (_coerce_float(x) for x in (peer_activities or [])) if p is not None]
    if peers:
        below = sum(1 for p in peers if activity_score >= p)
        rank = _clamp01(below / len(peers))
    else:
        rank = _clamp01(activity_score)

    dev_per_fdv = None
    fdv = _coerce_float(fdv_usd)
    c30 = _coerce_float(commits_30d)
    if fdv is not None and fdv > 0 and c30 is not None:
        dev_per_fdv = c30 / (fdv / 1_000_000.0)   # commit / $1M FDV

    undervalued = bool(
        dev_per_fdv is not None and dev_per_fdv >= 1.0 and activity_score >= 0.45
    )
    return ComparativeStats(
        relative_rank=float(rank),
        dev_per_fdv=float(dev_per_fdv) if dev_per_fdv is not None else None,
        undervalued=undervalued,
    )


# ── Birleşik sinyal ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DeveloperSignal:
    metrics: GithubMetrics
    comparative: ComparativeStats
    activity_score: float           # 0..1
    momentum: float                 # -1..1
    health: float                   # 0..1
    risk_score: float               # 0..1 (red flags)
    alpha_bias: float               # -1..1
    bus_factor: Optional[float]
    red_flags: List[str] = field(default_factory=list)
    positive_signals: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "developer_activity_score": self.activity_score,
            "developer_momentum": self.momentum,
            "developer_health": self.health,
            "developer_risk_score": self.risk_score,
            "developer_alpha_bias": self.alpha_bias,
            "bus_factor": self.bus_factor,
            "red_flags": list(self.red_flags),
            "positive_signals": list(self.positive_signals),
            "metrics": self.metrics.to_dict(),
            "comparative": self.comparative.to_dict(),
        }


def analyze_developer_activity(
    *,
    commits_30d: Optional[float] = None,
    commits_90d: Optional[float] = None,
    unique_contributors: Optional[float] = None,
    pr_merged: Optional[float] = None,
    pr_opened: Optional[float] = None,
    issues_opened: Optional[float] = None,
    issues_closed: Optional[float] = None,
    star_growth_rate: Optional[float] = None,
    fork_growth_rate: Optional[float] = None,
    days_since_last_commit: Optional[float] = None,
    bus_factor: Optional[float] = None,
    version_bump_only: bool = False,
    readme_only: bool = False,
    upgrade_branch: bool = False,
    large_refactor: bool = False,
    new_contributors_30d: Optional[float] = None,
    audit_commits: bool = False,
    fdv_usd: Optional[float] = None,
    peer_activities: Optional[Sequence[float]] = None,
) -> DeveloperSignal:
    """Tüm GitHub geliştirici metriklerini sağlık/risk/alpha sinyaline indirger."""
    metrics = analyze_github_metrics(
        commits_30d=commits_30d, commits_90d=commits_90d,
        unique_contributors=unique_contributors, pr_merged=pr_merged, pr_opened=pr_opened,
        issues_opened=issues_opened, issues_closed=issues_closed,
        star_growth_rate=star_growth_rate, fork_growth_rate=fork_growth_rate,
    )
    risk, red_flags = detect_red_flags(
        commits_30d=commits_30d, days_since_last_commit=days_since_last_commit,
        bus_factor=bus_factor, version_bump_only=version_bump_only, readme_only=readme_only,
    )
    pos_alpha, positive_signals = detect_positive_signals(
        upgrade_branch=upgrade_branch, large_refactor=large_refactor,
        new_contributors_30d=new_contributors_30d, audit_commits=audit_commits,
    )
    comp = comparative_analysis(
        metrics.activity_score, commits_30d=commits_30d,
        fdv_usd=fdv_usd, peer_activities=peer_activities,
    )

    health = _clamp01(metrics.activity_score * (1.0 - 0.6 * risk))
    alpha = pos_alpha + 0.25 * metrics.momentum - 0.5 * risk
    if comp.undervalued:
        alpha += 0.15
        positive_signals.append("Yüksek dev/FDV oranı → undervalued")
    alpha = _clamp(alpha, -1.0, 1.0)

    return DeveloperSignal(
        metrics=metrics,
        comparative=comp,
        activity_score=float(metrics.activity_score),
        momentum=float(metrics.momentum),
        health=float(health),
        risk_score=float(risk),
        alpha_bias=float(alpha),
        bus_factor=_coerce_float(bus_factor),
        red_flags=red_flags,
        positive_signals=positive_signals,
    )


# Köprü aktivasyonu için genişletilmiş anahtarlar (temel commits_30d/pr_count hariç —
# onlar _developer_scores'ta zaten işleniyor; çift işlemeyi önler, eski davranış korunur).
_EXTENDED_KEYS = (
    "commits_90d", "unique_contributors", "contributor_trend", "pr_merged", "pr_opened",
    "issues_opened", "issues_closed", "star_growth_rate", "fork_growth_rate",
    "bus_factor", "version_bump_only", "readme_only", "upgrade_branch", "large_refactor",
    "new_contributors_30d", "audit_commits", "fdv_usd", "peer_activities",
)


def analyze_developer_data(developer: Dict[str, Any]) -> Optional[DeveloperSignal]:
    """``developer`` alt dict köprüsü (alternative_data_engine Faz 27).

    Yalnız genişletilmiş GitHub metrikleri varsa aktive olur (yalın commits_30d
    eski Faz 27 developer skorlamasında kalır).
    """
    if not isinstance(developer, dict) or not developer:
        return None
    if not any(k in developer for k in _EXTENDED_KEYS):
        return None

    def g(*keys: str) -> Any:
        for k in keys:
            if k in developer and developer[k] is not None:
                return developer[k]
        return None

    return analyze_developer_activity(
        commits_30d=_coerce_float(g("commits_30d", "commit_count_30d")),
        commits_90d=_coerce_float(g("commits_90d", "commit_count_90d")),
        unique_contributors=_coerce_float(g("unique_contributors", "contributors")),
        pr_merged=_coerce_float(g("pr_merged", "merged_prs_30d")),
        pr_opened=_coerce_float(g("pr_opened", "opened_prs_30d")),
        issues_opened=_coerce_float(g("issues_opened")),
        issues_closed=_coerce_float(g("issues_closed")),
        star_growth_rate=_coerce_float(g("star_growth_rate")),
        fork_growth_rate=_coerce_float(g("fork_growth_rate")),
        days_since_last_commit=_coerce_float(g("days_since_last_commit", "staleness_days")),
        bus_factor=_coerce_float(g("bus_factor")),
        version_bump_only=_truthy(g("version_bump_only")),
        readme_only=_truthy(g("readme_only")),
        upgrade_branch=_truthy(g("upgrade_branch", "mainnet_branch")),
        large_refactor=_truthy(g("large_refactor")),
        new_contributors_30d=_coerce_float(g("new_contributors_30d")),
        audit_commits=_truthy(g("audit_commits")),
        fdv_usd=_coerce_float(g("fdv_usd", "fdv")),
        peer_activities=g("peer_activities", "peer_dev_activity"),
    )


# ── Parser + Collector ───────────────────────────────────────────────────────


def parse_github_repo(payload: Any) -> Dict[str, float]:
    """GitHub ``/repos/{owner}/{repo}`` JSON → {stars, forks, open_issues}."""
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", errors="replace")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return {}
    if not isinstance(payload, dict):
        return {}
    out: Dict[str, float] = {}
    for src, dst in (
        ("stargazers_count", "stars"),
        ("forks_count", "forks"),
        ("open_issues_count", "open_issues"),
        ("subscribers_count", "watchers"),
    ):
        v = _coerce_float(payload.get(src))
        if v is not None:
            out[dst] = v
    return out


def parse_github_commit_count(payload: Any) -> int:
    """GitHub commits listesi JSON → commit sayısı."""
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", errors="replace")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return 0
    return len(payload) if isinstance(payload, list) else 0


class GithubCollector:
    """GitHub API toplayıcı (ücretsiz; GITHUB_TOKEN ile 5000 req/saat; mock'lanabilir)."""

    def __init__(self, *, http_get: Optional[HttpGet] = None, timeout_sec: float = 6.0) -> None:
        self._http_get: HttpGet = http_get or _default_http_get
        self._timeout = float(timeout_sec)

    def fetch_repo(self, owner_repo: str) -> Dict[str, float]:
        base = os.getenv("GITHUB_API_URL", "https://api.github.com")
        body = self._http_get(f"{base}/repos/{owner_repo}", self._timeout)
        return parse_github_repo(body) if body else {}

    def fetch_commit_count(self, owner_repo: str, *, since_iso: str = "") -> int:
        base = os.getenv("GITHUB_API_URL", "https://api.github.com")
        url = f"{base}/repos/{owner_repo}/commits?per_page=100"
        if since_iso:
            url += f"&since={since_iso}"
        body = self._http_get(url, self._timeout)
        return parse_github_commit_count(body) if body else 0


__all__ = [
    "ABANDONED_DAYS",
    "LOW_COMMITS_30D",
    "ComparativeStats",
    "DeveloperSignal",
    "GithubCollector",
    "GithubMetrics",
    "analyze_developer_activity",
    "analyze_developer_data",
    "analyze_github_metrics",
    "comparative_analysis",
    "detect_positive_signals",
    "detect_red_flags",
    "parse_github_commit_count",
    "parse_github_repo",
]
