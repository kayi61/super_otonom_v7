"""
Test dosya yerleşimi — paket içi ``test_*.py`` envanteri (audit madde 9).

``tests/`` kanonik pytest kökü; ``super_otonom/test_*.py`` kuruluma girmemeli (build_py exclude).
Kurumsal temiz paket iddiası varsayılan kapalı — dosyalar repoda geçiş borcu olarak kalabilir.
"""

from __future__ import annotations

import argparse
import json
import os
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

_REPO = Path(__file__).resolve().parents[1]
_PKG = _REPO / "super_otonom"
_DEFAULT_MANIFEST = _REPO / "data" / "test_layout_manifest.json"
_COMPOSE_MARKER = "audit 9"
_PYPROJECT = _REPO / "pyproject.toml"
_CANONICAL_TEST_DIR = "tests"

IN_PACKAGE_TEST_CEILING = int(os.getenv("IN_PACKAGE_TEST_MODULE_CEILING", "35"))


@dataclass(frozen=True)
class TestLayoutTopology:
    in_package_test_modules: List[str] = field(default_factory=list)
    canonical_test_dir: str = _CANONICAL_TEST_DIR
    canonical_test_file_count: int = 0
    wheel_test_module_count: int = -1

    @property
    def in_package_test_count(self) -> int:
        return len(self.in_package_test_modules)

    @property
    def institutional_production_test_layout_claim_allowed(self) -> bool:
        return False


def scan_in_package_test_modules(pkg_root: Optional[Path] = None) -> List[str]:
    root = pkg_root or _PKG
    return sorted(p.name for p in root.glob("test_*.py") if p.is_file())


def count_canonical_tests(tests_root: Optional[Path] = None) -> int:
    root = tests_root or (_REPO / _CANONICAL_TEST_DIR)
    if not root.is_dir():
        return 0
    return sum(1 for p in root.rglob("test_*.py") if p.is_file())


def count_wheel_test_modules(wheel_path: Path) -> int:
    if not wheel_path.is_file():
        return -1
    with zipfile.ZipFile(wheel_path) as zf:
        return sum(
            1
            for n in zf.namelist()
            if n.startswith("super_otonom/test_") and n.endswith(".py")
        )


def build_wheel_for_audit(*, out_dir: Optional[Path] = None) -> Path:
    import subprocess
    import sys

    out = out_dir or (_REPO / "build" / "audit9_wheel")
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", str(_REPO), "-w", str(out), "--no-deps", "-q"],
        check=True,
        cwd=str(_REPO),
    )
    wheels = sorted(out.glob("super_otonom-*.whl"), key=lambda p: p.stat().st_mtime)
    if not wheels:
        raise FileNotFoundError(f"No wheel in {out.as_posix()}")
    return wheels[-1]


def inspect_test_layout(
    *,
    pkg_root: Optional[Path] = None,
    build_wheel: bool = False,
) -> TestLayoutTopology:
    in_pkg = scan_in_package_test_modules(pkg_root)
    wheel_count = -1
    if build_wheel:
        try:
            whl = build_wheel_for_audit()
            wheel_count = count_wheel_test_modules(whl)
        except OSError:
            wheel_count = -1
    return TestLayoutTopology(
        in_package_test_modules=in_pkg,
        canonical_test_file_count=count_canonical_tests(),
        wheel_test_module_count=wheel_count,
    )


def build_manifest_payload(topo: TestLayoutTopology) -> Dict[str, Any]:
    return {
        "audit": 9,
        "schema_version": 1,
        "in_package_test_count": topo.in_package_test_count,
        "in_package_test_ceiling": IN_PACKAGE_TEST_CEILING,
        "in_package_test_modules": topo.in_package_test_modules,
        "canonical_test_dir": topo.canonical_test_dir,
        "canonical_test_file_count": topo.canonical_test_file_count,
        "wheel_test_module_count_expected": 0,
        "institutional_production_test_layout_claim_allowed": False,
        "disclaimer_tr": (
            f"Pytest kanonik kökü {topo.canonical_test_dir}/; super_otonom/test_*.py "
            "geçiş dönemi borcudur ve pip wheel'e dahil edilmemelidir. "
            "Kurumsal 'temiz paket' iddiası tüm testler tests/ altına taşınana kadar uygun değildir."
        ),
    }


def write_manifest(path: Optional[Path] = None, *, pkg_root: Optional[Path] = None) -> Path:
    p = path or _DEFAULT_MANIFEST
    topo = inspect_test_layout(pkg_root=pkg_root, build_wheel=False)
    payload = build_manifest_payload(topo)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def compare_layout_to_manifest(
    topo: TestLayoutTopology,
    manifest: Mapping[str, Any],
) -> List[str]:
    issues: List[str] = []
    if manifest.get("institutional_production_test_layout_claim_allowed") is not False:
        issues.append("manifest: institutional_production_test_layout_claim_allowed must be false")

    exp_list = manifest.get("in_package_test_modules")
    if isinstance(exp_list, list):
        if sorted(exp_list) != topo.in_package_test_modules:
            added = set(topo.in_package_test_modules) - set(exp_list)
            removed = set(exp_list) - topo.in_package_test_modules
            if added:
                issues.append(f"new in-package test modules (update manifest): {sorted(added)}")
            if removed:
                issues.append(f"removed in-package test modules: {sorted(removed)}")
    else:
        issues.append("manifest: in_package_test_modules list missing")

    exp_count = manifest.get("in_package_test_count")
    if exp_count is not None and int(exp_count) != topo.in_package_test_count:
        issues.append(
            f"in_package_test_count mismatch manifest={exp_count} live={topo.in_package_test_count}"
        )

    ceiling = int(manifest.get("in_package_test_ceiling", IN_PACKAGE_TEST_CEILING))
    if topo.in_package_test_count > ceiling:
        issues.append(
            f"in-package test modules {topo.in_package_test_count} > ceiling {ceiling}"
        )
    return issues


def validate_pyproject_packaging(repo_root: Optional[Path] = None) -> List[str]:
    root = repo_root or _REPO
    issues: List[str] = []
    pp = root / "pyproject.toml"
    if not pp.is_file():
        issues.append(f"{pp.as_posix()}: missing")
        return issues
    text = pp.read_text(encoding="utf-8")
    if "BuildPyExcludeInPackageTests" not in text:
        issues.append(
            f"{pp.as_posix()}: must register _setup_build.BuildPyExcludeInPackageTests"
        )
    if 'testpaths = ["tests"]' not in text.replace("'", '"'):
        if 'testpaths = ["tests"]' not in text:
            issues.append(f"{pp.as_posix()}: pytest testpaths must be tests/")
    if "super_otonom/test_*.py" not in text and "super_otonom/test_" not in text:
        issues.append(f"{pp.as_posix()}: coverage omit should reference super_otonom/test_*.py")
    return issues


def validate_test_layout_contract(
    repo_root: Optional[Path] = None,
    *,
    verify_wheel: bool = False,
) -> List[str]:
    root = repo_root or _REPO
    issues: List[str] = []

    compose = root / "docker-compose.yml"
    if compose.is_file():
        if _COMPOSE_MARKER not in compose.read_text(encoding="utf-8").lower():
            issues.append(
                f"{compose.as_posix()}: must document test layout limits (audit 9 marker)"
            )
    else:
        issues.append(f"{compose.as_posix()}: missing")

    issues.extend(validate_pyproject_packaging(root))

    manifest_path = root / "data" / "test_layout_manifest.json"
    if not manifest_path.is_file():
        issues.append(
            f"{manifest_path.as_posix()}: missing — run "
            "python -m super_otonom.layout_topology --write-manifest"
        )
        return issues

    topo = inspect_test_layout(pkg_root=root / "super_otonom", build_wheel=verify_wheel)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        issues.append(f"{manifest_path.as_posix()}: invalid JSON: {exc}")
        return issues

    issues.extend(compare_layout_to_manifest(topo, manifest))

    if verify_wheel and topo.wheel_test_module_count != 0:
        issues.append(
            f"wheel contains {topo.wheel_test_module_count} super_otonom/test_*.py modules "
            "(expected 0 after BuildPyExcludeInPackageTests)"
        )
    return issues


def layout_disclosure(*, topo: Optional[TestLayoutTopology] = None) -> Dict[str, Any]:
    t = topo or inspect_test_layout(build_wheel=False)
    limitations: List[str] = [
        "in_package_test_modules_present",
        "canonical_tests_under_tests_dir",
        "wheel_must_exclude_package_tests",
    ]
    if t.in_package_test_count > 0:
        limitations.append("migration_debt_super_otonom_test_files")
    return {
        "test_layout_controlled": True,
        "institutional_production_test_layout_claim_allowed": False,
        "topology": {
            "in_package_test_count": t.in_package_test_count,
            "in_package_test_ceiling": IN_PACKAGE_TEST_CEILING,
            "canonical_test_dir": t.canonical_test_dir,
            "canonical_test_file_count": t.canonical_test_file_count,
            "wheel_test_module_count": t.wheel_test_module_count,
        },
        "limitations": limitations,
        "disclaimer_tr": build_manifest_payload(t)["disclaimer_tr"],
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Test layout / in-package test module audit.")
    p.add_argument("--write-manifest", action="store_true")
    p.add_argument("--verify-wheel", action="store_true", help="Build wheel and assert 0 test_ in wheel")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(list(argv) if argv is not None else None)

    if args.write_manifest:
        out = write_manifest()
        print(f"Wrote {out.as_posix()}")
        return 0

    topo = inspect_test_layout(build_wheel=args.verify_wheel)
    disc = layout_disclosure(topo=topo)
    issues = validate_test_layout_contract(verify_wheel=args.verify_wheel)
    payload = {"ok": not issues, "issues": issues, "disclosure": disc}
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print("=== test_layout_topology ===")
        print(
            f"in_package_tests={topo.in_package_test_count} "
            f"canonical_tests={topo.canonical_test_file_count} "
            f"wheel_test_modules={topo.wheel_test_module_count}"
        )
        for line in issues:
            print(f"  FAIL: {line}")
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
