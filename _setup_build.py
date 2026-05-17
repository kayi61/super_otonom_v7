"""PEP 517 build_py hook (audit 9) — repo kökü; wheel'de paketlenmez."""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from setuptools.command.build_py import build_py


def _keep_module(mod: str) -> bool:
    return not mod.startswith("test_") and mod != "setuptools_build"


class BuildPyExcludeInPackageTests(build_py):
    def run(self) -> None:
        super().run()

    def find_modules(self) -> List[Tuple[str, str, str]]:
        return [
            (pkg, mod, path)
            for pkg, mod, path in super().find_modules()
            if _keep_module(mod)
        ]

    def find_package_modules(
        self, package: str, package_dir: str
    ) -> List[Tuple[str, str, str]]:
        modules = super().find_package_modules(package, package_dir)
        if package != "super_otonom":
            return modules
        return [(pkg, mod, path) for pkg, mod, path in modules if _keep_module(mod)]

    def get_source_files(self) -> List[str]:
        return [f for f in super().get_source_files() if _keep_module(Path(f).stem)]
