"""Kanon drift — `src/phases` envanteri ve `phase_chain.update` anahtarları.

`scripts/check_kanon_drift.py` ve release_gate testleri aynı mantığı kullanır.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Tuple


def repo_root_from_package() -> Path:
    """Bu dosya `super_otonom/kanon_drift_check.py` iken depo kökü."""
    return Path(__file__).resolve().parents[1]


def expected_phase_dirs_from_docs() -> frozenset[str]:
    """PROMPT-FAZ-MASTER-ENVANTER §2 — `src/phases` altında olması beklenen klasörler."""
    return frozenset(
        f"phase_{n}"
        for n in (
            38,
            39,
            40,
            41,
            42,
            43,
            44,
            46,
            48,
            49,
            51,
            52,
            53,
            54,
            55,
        )
    )


def forbidden_phase_dirs() -> frozenset[str]:
    """REALITY_VS_REPORT — bu numaralar çekirdek pakette; src/phases altında olmamalı."""
    return frozenset(("phase_45", "phase_47", "phase_50"))


def scan_actual_phase_dirs(phases_root: Path) -> frozenset[str]:
    if not phases_root.is_dir():
        return frozenset()
    return frozenset(
        p.name for p in phases_root.iterdir() if p.is_dir() and p.name.startswith("phase_")
    )


def parse_phase_chain_keys_from_pipeline(pipeline_path: Path) -> frozenset[str] | None:
    """execution_pipeline içindeki phase_chain.update({...}) sözlük anahtarlarını çıkar."""
    try:
        src = pipeline_path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "update":
            continue
        if not isinstance(node.func.value, ast.Attribute):
            continue
        if node.func.value.attr != "phase_chain":
            continue
        if len(node.args) != 1 or not isinstance(node.args[0], ast.Dict):
            continue
        d = node.args[0]
        keys: set[str] = set()
        for k in d.keys:
            if k is None:
                continue
            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                keys.add(k.value)
        return frozenset(keys)
    return None


def canonical_phase_chain_keys() -> frozenset[str]:
    """execute_trade_phase giriş dalı ile uyumlu beklenen küme."""
    return frozenset(
        [f"faz{n}" for n in range(66, 71)] + [f"faz{n}" for n in range(71, 80)] + ["faz47", "faz80"]
    )


def run_all_checks(repo_root: Path | None = None) -> Tuple[bool, list[str]]:
    """
    Tüm kontrolleri çalıştırır.

    Dönüş: (True, []) uyumlu; (False, [...]) drift veya parse hatası mesajları.
    """
    root = repo_root if repo_root is not None else repo_root_from_package()
    phases_root = root / "src" / "phases"
    pipeline = root / "super_otonom" / "pipelines" / "execution_pipeline.py"

    issues: list[str] = []

    expected_dirs = expected_phase_dirs_from_docs()
    actual_dirs = scan_actual_phase_dirs(phases_root)
    forbidden = forbidden_phase_dirs()

    missing_dirs = sorted(expected_dirs - actual_dirs)
    extra_dirs = sorted(actual_dirs - expected_dirs)
    forbidden_present = sorted(actual_dirs & forbidden)

    if missing_dirs:
        issues.append(f"src/phases eksik klasör (dokümana göre): {', '.join(missing_dirs)}")
    if extra_dirs:
        issues.append(
            f"src/phases beklenmeyen ek klasör: {', '.join(extra_dirs)} — envanter/PROMPT güncellenmeli"
        )
    if forbidden_present:
        issues.append(
            f"src/phases altında olmaması gereken (45/47/50 çekirdek pakette): {', '.join(forbidden_present)}"
        )

    parsed_keys = parse_phase_chain_keys_from_pipeline(pipeline)
    if parsed_keys is None:
        issues.append(
            "execution_pipeline.py içinde phase_chain.update({...}) parse edilemedi — dosya yapısı değişmiş olabilir"
        )
    else:
        canonical_chain = canonical_phase_chain_keys()
        if parsed_keys != canonical_chain:
            only_pipe = sorted(parsed_keys - canonical_chain)
            only_canon = sorted(canonical_chain - parsed_keys)
            if only_pipe or only_canon:
                issues.append(
                    "phase_chain anahtarları beklenen kümeden farklı: "
                    f"pipeline fazlası={only_pipe or '—'}, beklenen eksikleri={only_canon or '—'}"
                )

    return (len(issues) == 0, issues)
