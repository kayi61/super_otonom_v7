"""
TWAP/VWAP yürütme topolojisi — sinyal vs emir yürütme ayrımı (audit madde 10).

VWAP: ``hft_signal_engine`` içinde sinyal/analitik metrik (yürütme değil).
TWAP: faz 75/76/80 ve ``execution_layer`` içinde metadata etiketi; canlı emir tek limit/market.
Kurumsal TWAP/VWAP algo yürütme iddiası varsayılan kapalı.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

_REPO = Path(__file__).resolve().parents[2]
_PKG = _REPO / "super_otonom"
_DEFAULT_MANIFEST = _REPO / "data" / "execution_topology_manifest.json"
_COMPOSE_MARKER = "audit 10"

# Sinyal / metadata modülleri (algo yürütme sayılmaz)
_VWAP_SIGNAL_MODULES = frozenset({"signals/hft_signal_engine.py"})
_TWAP_METADATA_MODULES = frozenset(
    {
        "regime_adaptive_execution_engine.py",
        "mm_whale_consensus_controller.py",
        "autonomous_decision_core.py",
        "pipelines/execution_pipeline.py",
    }
)
_VENUE_ROUTING_MODULES = frozenset({"smart_order_router.py"})
_ORDER_PLACEMENT_MODULES = frozenset({"engine_managers.py", "exchange_async.py", "order_engine.py"})

# Gerçek algo yürütme işaretleri (manifest'te boş kalmalı)
_ALGO_IMPLEMENTATION_MARKERS = (
    "schedule_child_order",
    "child_order_scheduler",
    "TwapVwapExecution",
    "twap_slice",
    "vwap_benchmark_execution",
    "algo_execution_engine",
    "execute_twap_schedule",
    "slice_interval_sec",
)

_ALGO_MODULE_NAME_HINTS = (
    "twap_vwap_execution",
    "algo_execution_engine",
    "child_order_scheduler",
    "order_slice_engine",
    "execution/twap",
    "execution/vwap",
    "execution/base",
)


@dataclass(frozen=True)
class ExecutionTopology:
    vwap_signal_modules: List[str] = field(default_factory=list)
    twap_metadata_modules: List[str] = field(default_factory=list)
    venue_routing_modules: List[str] = field(default_factory=list)
    order_placement_modules: List[str] = field(default_factory=list)
    twap_fingerprint_detection_modules: List[str] = field(default_factory=list)
    algo_implementation_hits: Dict[str, List[str]] = field(default_factory=dict)
    execution_profile_wired_to_trade_executor: bool = False
    trade_executor_single_shot_limit: bool = False
    preferred_venue_wired_to_exchange: bool = False

    @property
    def vwap_signal_present(self) -> bool:
        return bool(self.vwap_signal_modules)

    @property
    def twap_metadata_only(self) -> bool:
        return bool(self.twap_metadata_modules) and not self.algo_implementation_hits

    @property
    def algo_execution_present(self) -> bool:
        return bool(self.algo_implementation_hits)

    @property
    def institutional_twap_vwap_execution_claim_allowed(self) -> bool:
        return bool(self.algo_implementation_hits)


def _pkg_file(rel: str) -> Path:
    return _PKG.joinpath(*rel.split("/"))


def _file_exists(rel: str) -> bool:
    return _pkg_file(rel).is_file()


def _read_text(rel: str) -> str:
    p = _pkg_file(rel)
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8")


def scan_vwap_signal_modules(pkg_root: Optional[Path] = None) -> List[str]:
    root = pkg_root or _PKG
    found: List[str] = []
    for name in sorted(_VWAP_SIGNAL_MODULES):
        p = root / name
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8")
        if re.search(r"\bvwap\b", text, re.I) and "vwap_deviation" in text:
            found.append(name)
    return found


def scan_twap_metadata_modules(pkg_root: Optional[Path] = None) -> List[str]:
    root = pkg_root or _PKG
    found: List[str] = []
    for rel in sorted(_TWAP_METADATA_MODULES):
        p = root.joinpath(*rel.split("/"))
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8")
        if re.search(r"\btwap\b", text, re.I) or "execution_profile" in text:
            found.append(rel.replace("\\", "/"))
    return found


def scan_twap_fingerprint_modules(repo_root: Optional[Path] = None) -> List[str]:
    root = repo_root or _REPO
    hits: List[str] = []
    phase54 = root / "src" / "phases" / "phase_54" / "institutional_fingerprint_engine.py"
    if phase54.is_file() and "twap_fingerprint" in phase54.read_text(encoding="utf-8"):
        hits.append(phase54.relative_to(root).as_posix())
    return hits


def scan_algo_implementation_hits(pkg_root: Optional[Path] = None) -> Dict[str, List[str]]:
    """Gerçek TWAP/VWAP yürütme (child order, slice schedule) işaretleri."""
    root = pkg_root or _PKG
    hits: Dict[str, List[str]] = {}
    skip = _VWAP_SIGNAL_MODULES | {m.split("/")[-1] for m in _TWAP_METADATA_MODULES}
    skip |= {"execution_topology.py", "execution_topology_audit.py"}
    for p in sorted(root.rglob("*.py")):
        if not p.is_file() or p.name.startswith("test_"):
            continue
        if p.name in skip:
            continue
        rel = p.relative_to(root).as_posix()
        low = rel.lower()
        if any(h in low for h in _ALGO_MODULE_NAME_HINTS):
            hits.setdefault(rel, []).append("module_name_hint")
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        markers = [m for m in _ALGO_IMPLEMENTATION_MARKERS if m in text]
        if markers:
            hits[rel] = sorted(set(hits.get(rel, []) + markers))
    return hits


def inspect_trade_executor_wiring(pkg_root: Optional[Path] = None) -> Dict[str, bool]:
    root = pkg_root or _PKG
    em = root / "engine_managers.py"
    ex = root / "exchange_async.py"
    out = {
        "execution_profile_wired_to_trade_executor": False,
        "trade_executor_single_shot_limit": False,
        "preferred_venue_wired_to_exchange": False,
    }
    if em.is_file():
        text = em.read_text(encoding="utf-8")
        out["execution_profile_wired_to_trade_executor"] = (
            "execution_profile" in text or "preferred_order_type" in text
        )
        out["trade_executor_single_shot_limit"] = (
            'order_type="limit"' in text or "order_type='limit'" in text
        ) and "schedule_child" not in text
    if ex.is_file():
        ex_text = ex.read_text(encoding="utf-8")
        out["preferred_venue_wired_to_exchange"] = "preferred_venue" in ex_text and (
            "execution_profile" in ex_text or "twap" in ex_text.lower()
        )
    return out


def inspect_execution_topology(
    *,
    pkg_root: Optional[Path] = None,
    repo_root: Optional[Path] = None,
) -> ExecutionTopology:
    root = pkg_root or _PKG
    repo = repo_root or _REPO
    wiring = inspect_trade_executor_wiring(root)
    return ExecutionTopology(
        vwap_signal_modules=scan_vwap_signal_modules(root),
        twap_metadata_modules=scan_twap_metadata_modules(root),
        venue_routing_modules=sorted(m for m in _VENUE_ROUTING_MODULES if (root / m).is_file()),
        order_placement_modules=sorted(m for m in _ORDER_PLACEMENT_MODULES if (root / m).is_file()),
        twap_fingerprint_detection_modules=scan_twap_fingerprint_modules(repo),
        algo_implementation_hits=scan_algo_implementation_hits(root),
        execution_profile_wired_to_trade_executor=wiring[
            "execution_profile_wired_to_trade_executor"
        ],
        trade_executor_single_shot_limit=wiring["trade_executor_single_shot_limit"],
        preferred_venue_wired_to_exchange=wiring["preferred_venue_wired_to_exchange"],
    )


def build_manifest_payload(topo: ExecutionTopology) -> Dict[str, Any]:
    return {
        "audit": 10,
        "schema_version": 1,
        "vwap_signal_present": topo.vwap_signal_present,
        "vwap_signal_modules": topo.vwap_signal_modules,
        "twap_metadata_modules": topo.twap_metadata_modules,
        "venue_routing_modules": topo.venue_routing_modules,
        "order_placement_modules": topo.order_placement_modules,
        "twap_fingerprint_detection_modules": topo.twap_fingerprint_detection_modules,
        "algo_implementation_hits": topo.algo_implementation_hits,
        "algo_implementation_hits_expected_empty": not topo.algo_implementation_hits,
        "execution_profile_wired_to_trade_executor": topo.execution_profile_wired_to_trade_executor,
        "trade_executor_single_shot_limit": topo.trade_executor_single_shot_limit,
        "preferred_venue_wired_to_exchange": topo.preferred_venue_wired_to_exchange,
        "institutional_twap_vwap_execution_claim_allowed": topo.institutional_twap_vwap_execution_claim_allowed,
        "disclaimer_tr": (
            "TWAP/VWAP emir dilimleme execution/ alt paketinde implemente edilmistir. "
            "TwapScheduler esit zaman dilimlerine, VwapScheduler hacim profiline gore "
            "child order uretir. MIN_TWAP_NOTIONAL esiginin altinda tek limit/market "
            "emri gonderilir."
        ) if topo.algo_implementation_hits else (
            "VWAP yalnizca hft_signal_engine icinde sinyal/analitik metrik olarak vardir; "
            "TWAP/VWAP emir dilimleme (child order, zamanlama, VWAP benchmark yurutme) "
            "implemente edilmemistir. execution_profile ve preferred_order_type metadata "
            "etiketidir; TradeExecutor tek limit/market emri gonderir. "
            "Kurumsal algo yurutme iddiasi bu topoloji ile uyumlu degildir."
        ),
    }


def write_manifest(path: Optional[Path] = None, *, pkg_root: Optional[Path] = None) -> Path:
    p = path or _DEFAULT_MANIFEST
    topo = inspect_execution_topology(pkg_root=pkg_root)
    payload = build_manifest_payload(topo)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def compare_topology_to_manifest(
    topo: ExecutionTopology,
    manifest: Mapping[str, Any],
) -> List[str]:
    issues: List[str] = []
    expected_claim = manifest.get("institutional_twap_vwap_execution_claim_allowed")
    if expected_claim != topo.institutional_twap_vwap_execution_claim_allowed:
        issues.append(
            f"manifest: institutional_twap_vwap_execution_claim_allowed drift: "
            f"manifest={expected_claim} live={topo.institutional_twap_vwap_execution_claim_allowed}"
        )

    if manifest.get("algo_implementation_hits_expected_empty") is True:
        if topo.algo_implementation_hits:
            issues.append(f"algo execution markers detected: {topo.algo_implementation_hits}")

    exp_wired = manifest.get("execution_profile_wired_to_trade_executor")
    if exp_wired is not None and bool(exp_wired) != topo.execution_profile_wired_to_trade_executor:
        issues.append(
            "execution_profile_wired_to_trade_executor drift: "
            f"manifest={exp_wired} live={topo.execution_profile_wired_to_trade_executor}"
        )

    for key, live in (
        ("vwap_signal_modules", topo.vwap_signal_modules),
        ("twap_metadata_modules", topo.twap_metadata_modules),
        ("venue_routing_modules", topo.venue_routing_modules),
    ):
        exp = manifest.get(key)
        if isinstance(exp, list) and sorted(exp) != sorted(live):
            issues.append(f"{key} manifest drift: expected {exp}, live {live}")

    if manifest.get("vwap_signal_present") is True and not topo.vwap_signal_present:
        issues.append("vwap_signal_present: manifest true but live scan found none")

    return issues


def validate_execution_topology_contract(repo_root: Optional[Path] = None) -> List[str]:
    root = repo_root or _REPO
    issues: List[str] = []

    compose = root / "docker-compose.yml"
    if compose.is_file():
        if _COMPOSE_MARKER not in compose.read_text(encoding="utf-8").lower():
            issues.append(
                f"{compose.as_posix()}: must document TWAP/VWAP execution limits (audit 10 marker)"
            )
    else:
        issues.append(f"{compose.as_posix()}: missing")

    et = root / "super_otonom" / "execution_topology.py"
    if et.is_file() and "institutional_twap_vwap_execution_claim_allowed" not in et.read_text(
        encoding="utf-8"
    ):
        issues.append(
            "execution_topology.py: must declare institutional_twap_vwap_execution_claim_allowed"
        )

    for rel in _TWAP_METADATA_MODULES:
        if not _file_exists(rel):
            issues.append(f"expected twap metadata module missing: {rel}")

    if not _file_exists("signals/hft_signal_engine.py"):
        issues.append("signals/hft_signal_engine.py: missing (VWAP signal reference)")

    manifest_path = root / "data" / "execution_topology_manifest.json"
    if not manifest_path.is_file():
        issues.append(
            f"{manifest_path.as_posix()}: missing — run "
            "python -m super_otonom.execution_topology --write-manifest"
        )
        return issues

    topo = inspect_execution_topology(
        pkg_root=root / "super_otonom",
        repo_root=root,
    )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        issues.append(f"{manifest_path.as_posix()}: invalid JSON: {exc}")
        return issues

    issues.extend(compare_topology_to_manifest(topo, manifest))
    return issues


def execution_disclosure(*, topo: Optional[ExecutionTopology] = None) -> Dict[str, Any]:
    t = topo or inspect_execution_topology()
    limitations: List[str] = []
    if not t.algo_execution_present:
        limitations.extend([
            "vwap_signal_not_execution",
            "twap_metadata_not_algo_router",
            "no_child_order_scheduler",
            "trade_executor_single_shot_limit",
        ])
    if t.twap_fingerprint_detection_modules:
        limitations.append("twap_fingerprint_is_market_detection_only")
    if t.venue_routing_modules:
        limitations.append("smart_order_router_venue_only")
    return {
        "execution_topology_controlled": True,
        "institutional_twap_vwap_execution_claim_allowed": t.institutional_twap_vwap_execution_claim_allowed,
        "topology": {
            "vwap_signal_present": t.vwap_signal_present,
            "vwap_signal_modules": t.vwap_signal_modules,
            "twap_metadata_modules": t.twap_metadata_modules,
            "algo_implementation_hits": t.algo_implementation_hits,
            "execution_profile_wired_to_trade_executor": t.execution_profile_wired_to_trade_executor,
            "trade_executor_single_shot_limit": t.trade_executor_single_shot_limit,
        },
        "limitations": limitations,
        "disclaimer_tr": build_manifest_payload(t)["disclaimer_tr"],
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="TWAP/VWAP execution topology audit.")
    p.add_argument("--write-manifest", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(list(argv) if argv is not None else None)

    if args.write_manifest:
        out = write_manifest()
        print(f"Wrote {out.as_posix()}")
        return 0

    topo = inspect_execution_topology()
    disc = execution_disclosure(topo=topo)
    issues = validate_execution_topology_contract()
    payload = {"ok": not issues, "issues": issues, "disclosure": disc}
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print("=== execution_topology ===")
        print(
            f"vwap_signal={topo.vwap_signal_present} "
            f"twap_metadata={len(topo.twap_metadata_modules)} "
            f"algo_hits={len(topo.algo_implementation_hits)} "
            f"profile_wired={topo.execution_profile_wired_to_trade_executor}"
        )
        for line in issues:
            print(f"  FAIL: {line}")
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
