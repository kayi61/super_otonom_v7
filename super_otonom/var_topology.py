"""
VaR / CVaR topolojisi — faz modülü vs canlı tick yolu (audit madde 11).

``portfolio_risk_engine``: tarihsel / parametrik / MC VaR + CVaR (faz 24).
Canlı bot: ``risk_ontology`` / ``risk_manager`` — PnL yüzdelik VaR (min 100 örnek).
Rejim, likidite ayarı, kurumsal stres gridi yok — iddia varsayılan kapalı.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

_REPO = Path(__file__).resolve().parents[1]
_PKG = _REPO / "super_otonom"
_DEFAULT_MANIFEST = _REPO / "data" / "var_topology_manifest.json"
_COMPOSE_MARKER = "audit 11"

_PORTFOLIO_RISK_MODULE = "portfolio_risk_engine.py"
_LIVE_VAR_MODULES = frozenset({"risk_ontology.py", "risk_manager.py"})

_EXPECTED_VAR_FUNCTIONS = (
    "var_parametric",
    "var_historical",
    "var_monte_carlo",
    "cvar_expected_shortfall",
)

_INSTITUTIONAL_GAP_MARKERS = (
    "regime_conditional_var",
    "liquidity_adjusted_var",
    "stress_scenario_grid",
    "stress_grid_var",
    "copula_var",
    "filtered_historical_simulation",
)

_LIVE_TICK_PORTFOLIO_RISK_IMPORT_MARKERS = (
    "from super_otonom.portfolio_risk_engine import",
    "import portfolio_risk_engine",
    "analyze_portfolio_risk(",
    "run_portfolio_risk_phase(",
)


@dataclass(frozen=True)
class VarTopology:
    portfolio_risk_module: str = _PORTFOLIO_RISK_MODULE
    var_methods_present: List[str] = field(default_factory=list)
    live_var_modules: List[str] = field(default_factory=list)
    live_tick_uses_portfolio_risk_engine: bool = False
    regime_conditional_var_present: bool = False
    liquidity_adjusted_var_present: bool = False
    institutional_stress_grid_present: bool = False
    stress_heuristic_in_portfolio_risk: bool = False
    institutional_gap_hits: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def phase24_var_suite_present(self) -> bool:
        return len(self.var_methods_present) >= 4

    @property
    def institutional_var_claim_allowed(self) -> bool:
        return False


def _pkg_file(rel: str) -> Path:
    return _PKG.joinpath(*rel.split("/"))


def _read_pkg(rel: str) -> str:
    p = _pkg_file(rel)
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def scan_var_methods_in_portfolio_risk(pkg_root: Optional[Path] = None) -> List[str]:
    root = pkg_root or _PKG
    p = root / _PORTFOLIO_RISK_MODULE
    if not p.is_file():
        return []
    text = p.read_text(encoding="utf-8")
    found: List[str] = []
    if re.search(r"def\s+var_parametric\s*\(", text):
        found.append("parametric")
    if re.search(r"def\s+var_historical\s*\(", text):
        found.append("historical")
    if re.search(r"def\s+var_monte_carlo\s*\(", text):
        found.append("monte_carlo")
    if re.search(r"def\s+cvar_expected_shortfall\s*\(", text):
        found.append("cvar")
    return found


def scan_live_var_modules(pkg_root: Optional[Path] = None) -> List[str]:
    root = pkg_root or _PKG
    out: List[str] = []
    for name in sorted(_LIVE_VAR_MODULES):
        p = root / name
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8")
        if "_calc_var" in text or "calculate_var" in text or "var_1d" in text:
            out.append(name)
    return out


def scan_institutional_gap_hits(pkg_root: Optional[Path] = None) -> Dict[str, List[str]]:
    root = pkg_root or _PKG
    hits: Dict[str, List[str]] = {}
    skip = {"var_topology.py", "var_topology_audit.py", _PORTFOLIO_RISK_MODULE}
    skip_dirs = {"risk"}
    for p in sorted(root.rglob("*.py")):
        if not p.is_file() or p.name.startswith("test_"):
            continue
        if p.name in skip or any(part in skip_dirs for part in p.relative_to(root).parts[:-1]):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        markers = [m for m in _INSTITUTIONAL_GAP_MARKERS if m in text]
        if markers:
            hits[p.relative_to(root).as_posix()] = sorted(set(markers))
    return hits


def portfolio_risk_has_stress_heuristic(pkg_root: Optional[Path] = None) -> bool:
    text = (
        _read_pkg(_PORTFOLIO_RISK_MODULE)
        if pkg_root is None
        else (pkg_root / _PORTFOLIO_RISK_MODULE).read_text(encoding="utf-8")
        if (pkg_root / _PORTFOLIO_RISK_MODULE).is_file()
        else ""
    )
    return "_stress_max_loss_pct" in text and "stress_scenarios" in text


def live_tick_imports_portfolio_risk_engine(pkg_root: Optional[Path] = None) -> bool:
    """BotEngine tick yolu faz-24 VaR motorunu çağırıyor mu?"""
    root = pkg_root or _PKG
    check_files = (
        "bot_engine.py",
        "engine_managers.py",
        "pipelines/risk_pipeline.py",
        "main_loop.py",
    )
    for rel in check_files:
        p = root.joinpath(*rel.split("/"))
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8")
        if any(m in text for m in _LIVE_TICK_PORTFOLIO_RISK_IMPORT_MARKERS):
            return True
    return False


def _risk_pkg_has(pkg_root: Path, marker: str) -> bool:
    """Check whether the risk/ subpackage contains a real implementation of *marker*."""
    risk_dir = pkg_root / "risk"
    if not risk_dir.is_dir():
        return False
    for p in risk_dir.rglob("*.py"):
        if not p.is_file() or p.name.startswith("test_"):
            continue
        try:
            if marker in p.read_text(encoding="utf-8"):
                return True
        except OSError:
            continue
    return False


def inspect_var_topology(
    *,
    pkg_root: Optional[Path] = None,
) -> VarTopology:
    root = pkg_root or _PKG
    gap_hits = scan_institutional_gap_hits(root)
    return VarTopology(
        var_methods_present=scan_var_methods_in_portfolio_risk(root),
        live_var_modules=scan_live_var_modules(root),
        live_tick_uses_portfolio_risk_engine=live_tick_imports_portfolio_risk_engine(root),
        regime_conditional_var_present=(
            _risk_pkg_has(root, "regime_conditional_var")
            or any("regime_conditional" in str(v) for v in gap_hits.values())
        ),
        liquidity_adjusted_var_present=(
            _risk_pkg_has(root, "liquidity_adjusted_var")
            or any("liquidity_adjusted" in str(v) for v in gap_hits.values())
        ),
        institutional_stress_grid_present=any(
            "stress_grid" in str(v) or "stress_scenario_grid" in str(v) for v in gap_hits.values()
        ),
        stress_heuristic_in_portfolio_risk=portfolio_risk_has_stress_heuristic(root),
        institutional_gap_hits=gap_hits,
    )


def build_manifest_payload(topo: VarTopology) -> Dict[str, Any]:
    return {
        "audit": 11,
        "schema_version": 1,
        "portfolio_risk_module": topo.portfolio_risk_module,
        "var_methods_present": topo.var_methods_present,
        "phase24_var_suite_present": topo.phase24_var_suite_present,
        "live_var_modules": topo.live_var_modules,
        "live_tick_var_source": "risk_ontology_percentile_pnl",
        "live_tick_uses_portfolio_risk_engine": topo.live_tick_uses_portfolio_risk_engine,
        "regime_conditional_var_present": topo.regime_conditional_var_present,
        "liquidity_adjusted_var_present": topo.liquidity_adjusted_var_present,
        "institutional_stress_grid_present": topo.institutional_stress_grid_present,
        "stress_heuristic_in_portfolio_risk": topo.stress_heuristic_in_portfolio_risk,
        "institutional_gap_hits_expected_empty": True,
        "institutional_var_claim_allowed": False,
        "disclaimer_tr": (
            "portfolio_risk_engine faz-24 icin parametrik/tarihsel/MC VaR ve CVaR sunar; "
            "canli tick risk_ontology uzerinden tek tarihsel yuzdelik VaR kullanir. "
            "Rejim kosullu VaR (VR-10) risk paketinde uygulanmistir; "
            "kurumsal stres gridi yoktur — "
            "stres yalnizca sezgisel flash/bear heuristik veya ozel stress_scenarios dict. "
            "Kurumsal risk motoru iddiasi bu topoloji ile uyumlu degildir; "
            "'yetersiz' ifadesi 'hic yok' ifadesinden daha dogrudur."
        ),
    }


def write_manifest(path: Optional[Path] = None, *, pkg_root: Optional[Path] = None) -> Path:
    p = path or _DEFAULT_MANIFEST
    topo = inspect_var_topology(pkg_root=pkg_root)
    payload = build_manifest_payload(topo)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def compare_topology_to_manifest(
    topo: VarTopology,
    manifest: Mapping[str, Any],
) -> List[str]:
    issues: List[str] = []
    if manifest.get("institutional_var_claim_allowed") is not False:
        issues.append("manifest: institutional_var_claim_allowed must be false")

    if (
        manifest.get("institutional_gap_hits_expected_empty") is True
        and topo.institutional_gap_hits
    ):
        issues.append(f"institutional VaR gap markers detected: {topo.institutional_gap_hits}")

    exp_methods = manifest.get("var_methods_present")
    if isinstance(exp_methods, list) and sorted(exp_methods) != sorted(topo.var_methods_present):
        issues.append(
            f"var_methods_present drift: manifest={exp_methods} live={topo.var_methods_present}"
        )

    exp_live = manifest.get("live_tick_uses_portfolio_risk_engine")
    if exp_live is not None and bool(exp_live) != topo.live_tick_uses_portfolio_risk_engine:
        issues.append(
            "live_tick_uses_portfolio_risk_engine drift: "
            f"manifest={exp_live} live={topo.live_tick_uses_portfolio_risk_engine}"
        )

    if manifest.get("phase24_var_suite_present") is True and not topo.phase24_var_suite_present:
        issues.append("phase24_var_suite_present: manifest true but live scan incomplete")

    return issues


def validate_var_topology_contract(repo_root: Optional[Path] = None) -> List[str]:
    root = repo_root or _REPO
    issues: List[str] = []

    compose = root / "docker-compose.yml"
    if compose.is_file():
        if _COMPOSE_MARKER not in compose.read_text(encoding="utf-8").lower():
            issues.append(f"{compose.as_posix()}: must document VaR limits (audit 11 marker)")
    else:
        issues.append(f"{compose.as_posix()}: missing")

    vt = root / "super_otonom" / "var_topology.py"
    if vt.is_file() and "institutional_var_claim_allowed" not in vt.read_text(encoding="utf-8"):
        issues.append("var_topology.py: must set institutional_var_claim_allowed=False")

    pre = root / "super_otonom" / _PORTFOLIO_RISK_MODULE
    if not pre.is_file():
        issues.append(f"{_PORTFOLIO_RISK_MODULE}: missing")
    else:
        text = pre.read_text(encoding="utf-8")
        for fn in _EXPECTED_VAR_FUNCTIONS:
            if f"def {fn}" not in text:
                issues.append(f"{_PORTFOLIO_RISK_MODULE}: missing {fn}")

    manifest_path = root / "data" / "var_topology_manifest.json"
    if not manifest_path.is_file():
        issues.append(
            f"{manifest_path.as_posix()}: missing — run "
            "python -m super_otonom.var_topology --write-manifest"
        )
        return issues

    topo = inspect_var_topology(pkg_root=root / "super_otonom")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        issues.append(f"{manifest_path.as_posix()}: invalid JSON: {exc}")
        return issues

    issues.extend(compare_topology_to_manifest(topo, manifest))
    return issues


def var_disclosure(*, topo: Optional[VarTopology] = None) -> Dict[str, Any]:
    t = topo or inspect_var_topology()
    limitations: List[str] = [
        "phase24_var_not_live_tick_default",
        "live_var_historical_percentile_only",
        "no_institutional_stress_grid",
    ]
    if not t.regime_conditional_var_present:
        limitations.append("no_regime_conditional_var")
    if not t.liquidity_adjusted_var_present:
        limitations.append("no_liquidity_adjusted_var")
    if t.stress_heuristic_in_portfolio_risk:
        limitations.append("stress_heuristic_flash_bear_only")
    if t.phase24_var_suite_present:
        limitations.append("parametric_historical_mc_cvar_in_phase24")
    return {
        "var_topology_controlled": True,
        "institutional_var_claim_allowed": False,
        "topology": {
            "var_methods_present": t.var_methods_present,
            "phase24_var_suite_present": t.phase24_var_suite_present,
            "live_var_modules": t.live_var_modules,
            "live_tick_uses_portfolio_risk_engine": t.live_tick_uses_portfolio_risk_engine,
            "stress_heuristic_in_portfolio_risk": t.stress_heuristic_in_portfolio_risk,
            "institutional_gap_hits": t.institutional_gap_hits,
        },
        "limitations": limitations,
        "disclaimer_tr": build_manifest_payload(t)["disclaimer_tr"],
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="VaR / CVaR topology audit.")
    p.add_argument("--write-manifest", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(list(argv) if argv is not None else None)

    if args.write_manifest:
        out = write_manifest()
        print(f"Wrote {out.as_posix()}")
        return 0

    topo = inspect_var_topology()
    disc = var_disclosure(topo=topo)
    issues = validate_var_topology_contract()
    payload = {"ok": not issues, "issues": issues, "disclosure": disc}
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print("=== var_topology ===")
        print(
            f"phase24_methods={topo.var_methods_present} "
            f"live_modules={topo.live_var_modules} "
            f"faz24_in_tick={topo.live_tick_uses_portfolio_risk_engine} "
            f"institutional={disc['institutional_var_claim_allowed']}"
        )
        for line in issues:
            print(f"  FAIL: {line}")
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
