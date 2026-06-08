"""
Paket topolojisi — düz ``super_otonom/`` modül envanteri (audit madde 7).

~100+ kök ``.py`` + yalnızca ``pipelines/`` alt paketi: kurumsal modüler sınır iddiası
varsayılan kapalı. Manifest ile büyüme tavanı denetlenir.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

_REPO = Path(__file__).resolve().parents[2]
_PKG = _REPO / "super_otonom"
_DEFAULT_MANIFEST = _REPO / "data" / "package_topology_manifest.json"
_COMPOSE_MARKER = "audit 7"

ALLOWED_SUBPACKAGES = frozenset({
    "pipelines",
    "risk",
    "execution",
    "ha",
    "infra",
    "signals",
    "core",
    "trading",
    "analysis",
    "monitoring",
    "audit",
    "research",
})
IGNORE_DIR_NAMES = frozenset(
    {".pytest_cache", ".scannerwork", "__pycache__", "data", ".mypy_cache", ".ruff_cache"}
)

FLAT_PROD_CEILING = int(os.getenv("PACKAGE_FLAT_PROD_CEILING", "125"))


@dataclass(frozen=True)
class PackageTopology:
    flat_production_modules: List[str] = field(default_factory=list)
    flat_test_modules: List[str] = field(default_factory=list)
    subpackages: List[str] = field(default_factory=list)
    pipelines_modules: List[str] = field(default_factory=list)

    @property
    def flat_production_count(self) -> int:
        return len(self.flat_production_modules)

    @property
    def flat_test_count(self) -> int:
        return len(self.flat_test_modules)

    @property
    def god_package_flat(self) -> bool:
        """Tek dizinde çok sayıda üretim modülü — bakım maliyeti yüksek."""
        return self.flat_production_count >= 80

    @property
    def institutional_modular_boundary_claim_allowed(self) -> bool:
        return False


def scan_package_topology(pkg_root: Optional[Path] = None) -> PackageTopology:
    root = pkg_root or _PKG
    flat_all = sorted(p.name for p in root.glob("*.py") if p.is_file())
    flat_prod = sorted(n for n in flat_all if not n.startswith("test_"))
    flat_test = sorted(n for n in flat_all if n.startswith("test_"))
    subpackages = sorted(
        p.name
        for p in root.iterdir()
        if p.is_dir() and p.name not in IGNORE_DIR_NAMES and not p.name.startswith(".")
    )
    pipe_mods: List[str] = []
    pipe_dir = root / "pipelines"
    if pipe_dir.is_dir():
        pipe_mods = sorted(p.name for p in pipe_dir.glob("*.py") if p.is_file())
    return PackageTopology(
        flat_production_modules=flat_prod,
        flat_test_modules=flat_test,
        subpackages=subpackages,
        pipelines_modules=pipe_mods,
    )


def load_manifest(path: Optional[Path] = None) -> Dict[str, Any]:
    p = path or _DEFAULT_MANIFEST
    return json.loads(p.read_text(encoding="utf-8"))


def build_manifest_payload(topo: PackageTopology) -> Dict[str, Any]:
    return {
        "audit": 7,
        "schema_version": 1,
        "flat_production_count": topo.flat_production_count,
        "flat_test_count": topo.flat_test_count,
        "flat_production_ceiling": FLAT_PROD_CEILING,
        "allowed_subpackages": sorted(ALLOWED_SUBPACKAGES),
        "subpackages_observed": topo.subpackages,
        "pipelines_modules": topo.pipelines_modules,
        "flat_production_modules": topo.flat_production_modules,
        "god_package_flat": topo.god_package_flat,
        "institutional_modular_boundary_claim_allowed": False,
        "disclaimer_tr": (
            "super_otonom tek düz paket altında çok sayıda modül içerir; yalnızca "
            "pipelines/ ayrılmıştır. Hedge-fund ölçeğinde modüler sınır iddiası bu "
            "topoloji ile uyumlu değildir; manifest ve tavan ile büyüme kontrol edilir."
        ),
    }


def write_manifest(path: Optional[Path] = None, *, pkg_root: Optional[Path] = None) -> Path:
    p = path or _DEFAULT_MANIFEST
    topo = scan_package_topology(pkg_root)
    payload = build_manifest_payload(topo)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def compare_topology_to_manifest(
    topo: PackageTopology,
    manifest: Mapping[str, Any],
) -> List[str]:
    issues: List[str] = []
    expected_sub = set(manifest.get("allowed_subpackages") or ALLOWED_SUBPACKAGES)
    extra_sub = set(topo.subpackages) - expected_sub
    if extra_sub:
        issues.append(f"unexpected subpackages under super_otonom/: {sorted(extra_sub)}")
    missing_sub = expected_sub - set(topo.subpackages)
    if missing_sub:
        issues.append(f"missing expected subpackages: {sorted(missing_sub)}")

    exp_prod = manifest.get("flat_production_modules")
    if isinstance(exp_prod, list):
        if sorted(exp_prod) != topo.flat_production_modules:
            added = set(topo.flat_production_modules) - set(exp_prod)
            removed = set(exp_prod) - set(topo.flat_production_modules)
            if added:
                issues.append(f"new flat production modules (update manifest): {sorted(added)}")
            if removed:
                issues.append(f"removed flat production modules: {sorted(removed)}")
    else:
        issues.append("manifest: flat_production_modules list missing")

    exp_count = manifest.get("flat_production_count")
    if exp_count is not None and int(exp_count) != topo.flat_production_count:
        issues.append(
            f"flat_production_count mismatch: manifest={exp_count} "
            f"live={topo.flat_production_count}"
        )

    ceiling = int(manifest.get("flat_production_ceiling", FLAT_PROD_CEILING))
    if topo.flat_production_count > ceiling:
        issues.append(
            f"flat production modules {topo.flat_production_count} > ceiling {ceiling}"
        )
    return issues


def package_disclosure(*, topo: Optional[PackageTopology] = None) -> Dict[str, Any]:
    t = topo or scan_package_topology()
    limitations: List[str] = [
        "flat_super_otonom_namespace",
        "only_pipelines_subpackage",
        "high_maintenance_surface",
    ]
    if t.god_package_flat:
        limitations.append("god_package_flat_ge_80_modules")
    if t.flat_production_count > FLAT_PROD_CEILING:
        limitations.append("flat_production_above_ceiling")

    return {
        "package_topology_controlled": True,
        "institutional_modular_boundary_claim_allowed": False,
        "topology": {
            "flat_production_count": t.flat_production_count,
            "flat_test_count": t.flat_test_count,
            "flat_production_ceiling": FLAT_PROD_CEILING,
            "god_package_flat": t.god_package_flat,
            "subpackages": list(t.subpackages),
            "pipelines_module_count": len(t.pipelines_modules),
        },
        "limitations": limitations,
        "disclaimer_tr": build_manifest_payload(t)["disclaimer_tr"],
    }


def validate_package_topology_contract(repo_root: Optional[Path] = None) -> List[str]:
    root = repo_root or _REPO
    issues: List[str] = []

    compose = root / "docker-compose.yml"
    if compose.is_file():
        if _COMPOSE_MARKER not in compose.read_text(encoding="utf-8").lower():
            issues.append(
                f"{compose.as_posix()}: must document god-package limits (audit 7 marker)"
            )
    else:
        issues.append(f"{compose.as_posix()}: missing")

    manifest_path = root / "data" / "package_topology_manifest.json"
    if not manifest_path.is_file():
        issues.append(
            f"{manifest_path.as_posix()}: missing — run "
            "python -m super_otonom.package_topology --write-manifest"
        )
        return issues

    topo = scan_package_topology(root / "super_otonom")
    try:
        manifest = load_manifest(manifest_path)
    except (OSError, json.JSONDecodeError) as exc:
        issues.append(f"{manifest_path.as_posix()}: invalid JSON: {exc}")
        return issues

    if manifest.get("institutional_modular_boundary_claim_allowed") is not False:
        issues.append("manifest: institutional_modular_boundary_claim_allowed must be false")

    issues.extend(compare_topology_to_manifest(topo, manifest))
    return issues


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="super_otonom package topology scan / manifest.")
    p.add_argument("--write-manifest", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(list(argv) if argv is not None else None)

    if args.write_manifest:
        out = write_manifest()
        print(f"Wrote {out.as_posix()}")
        return 0

    topo = scan_package_topology()
    disc = package_disclosure(topo=topo)
    issues = validate_package_topology_contract()
    payload = {"ok": not issues, "issues": issues, "disclosure": disc}
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print("=== package_topology ===")
        print(
            f"flat_prod={topo.flat_production_count} "
            f"god_package_flat={topo.god_package_flat} "
            f"institutional_modular={disc['institutional_modular_boundary_claim_allowed']}"
        )
        for line in issues:
            print(f"  FAIL: {line}")
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
