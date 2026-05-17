"""
BotEngine god-class topolojisi — LOC ve sorumluluk alanları (audit madde 8).

Tek sınıfta tick, giriş/çıkış, risk ve state: kurumsal tek-sorumluluk iddiası varsayılan kapalı.
Kısmi delegasyon (``engine_managers``, ``pipelines``) borcu ortadan kaldırmaz.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

_REPO = Path(__file__).resolve().parents[1]
_BOT_ENGINE = _REPO / "super_otonom" / "bot_engine.py"
_DEFAULT_MANIFEST = _REPO / "data" / "bot_engine_topology_manifest.json"
_COMPOSE_MARKER = "audit 8"

FILE_LINE_CEILING = int(os.getenv("BOT_ENGINE_FILE_LINE_CEILING", "1450"))
CLASS_LINE_CEILING = int(os.getenv("BOT_ENGINE_CLASS_LINE_CEILING", "1100"))
GOD_CLASS_MIN_LINES = int(os.getenv("BOT_ENGINE_GOD_CLASS_MIN_LINES", "800"))

# Metot adı önekleri → sorumluluk alanı (çoklu eşleşme mümkün)
_RESPONSIBILITY_RULES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("tick", ("tick", "_tick_impl", "_tick_", "check_orders")),
    ("entry", ("process_signal", "apply_filters", "calculate_position", "execute_trade", "_handle_entry", "_entry_")),
    ("exit", ("_handle_exit", "_close", "close_on_strategy_change", "emergency_liquidate")),
    ("risk", ("_entry_check", "_entry_safety", "_entry_kill", "safe_mode", "_open_exposure", "_reset_daily")),
    ("state", ("_save_state", "_load_state", "status", "shutdown", "set_exchange_handler")),
)

_PARTIAL_DELEGATION_MODULES = (
    "engine_managers",
    "pipelines.execution_pipeline",
    "pipelines.signal_pipeline",
    "hard_safety_contract",
    "state_machine",
)


@dataclass(frozen=True)
class BotEngineTopology:
    file_path: str
    file_line_count: int
    file_nonempty_line_count: int
    bot_engine_class_start: int
    bot_engine_class_end: int
    bot_engine_class_line_count: int
    bot_engine_method_count: int
    methods: List[str] = field(default_factory=list)
    responsibility_domains: List[str] = field(default_factory=list)
    helper_classes: List[str] = field(default_factory=list)
    partial_delegation_modules: List[str] = field(default_factory=list)

    @property
    def god_class(self) -> bool:
        return self.bot_engine_class_line_count >= GOD_CLASS_MIN_LINES

    @property
    def institutional_single_responsibility_claim_allowed(self) -> bool:
        return False


def _line_counts(text: str) -> Tuple[int, int]:
    lines = text.splitlines()
    nonempty = sum(1 for ln in lines if ln.strip())
    return len(lines), nonempty


def _class_span(tree: ast.Module, name: str) -> Optional[Tuple[int, int, List[str]]]:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            end = node.end_lineno or node.lineno
            methods = [
                n.name
                for n in node.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            return node.lineno, end, methods
    return None


def _helper_classes(tree: ast.Module) -> List[str]:
    return [
        n.name
        for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name != "BotEngine"
    ]


def _detect_responsibilities(methods: Sequence[str]) -> List[str]:
    found: Set[str] = set()
    for domain, prefixes in _RESPONSIBILITY_RULES:
        for m in methods:
            for p in prefixes:
                if m == p or m.startswith(p):
                    found.add(domain)
                    break
    return sorted(found)


def _detect_delegation_imports(text: str) -> List[str]:
    present: List[str] = []
    if "engine_managers" in text:
        present.append("engine_managers")
    if "pipelines" in text and "super_otonom.pipelines" in text:
        present.append("pipelines")
    if "hard_safety_contract" in text:
        present.append("hard_safety_contract")
    if "state_machine" in text:
        present.append("state_machine")
    return sorted(present)


def inspect_bot_engine(path: Optional[Path] = None) -> BotEngineTopology:
    p = path or _BOT_ENGINE
    text = p.read_text(encoding="utf-8")
    tree = ast.parse(text)
    total, nonempty = _line_counts(text)
    span = _class_span(tree, "BotEngine")
    if span is None:
        raise ValueError(f"{p.as_posix()}: BotEngine class not found")
    start, end, methods = span
    class_lines = end - start + 1
    return BotEngineTopology(
        file_path=p.as_posix(),
        file_line_count=total,
        file_nonempty_line_count=nonempty,
        bot_engine_class_start=start,
        bot_engine_class_end=end,
        bot_engine_class_line_count=class_lines,
        bot_engine_method_count=len(methods),
        methods=sorted(methods),
        responsibility_domains=_detect_responsibilities(methods),
        helper_classes=_helper_classes(tree),
        partial_delegation_modules=_detect_delegation_imports(text),
    )


def build_manifest_payload(topo: BotEngineTopology) -> Dict[str, Any]:
    return {
        "audit": 8,
        "schema_version": 1,
        "file_line_count": topo.file_line_count,
        "file_nonempty_line_count": topo.file_nonempty_line_count,
        "bot_engine_class_line_count": topo.bot_engine_class_line_count,
        "bot_engine_method_count": topo.bot_engine_method_count,
        "file_line_ceiling": FILE_LINE_CEILING,
        "class_line_ceiling": CLASS_LINE_CEILING,
        "god_class_min_lines": GOD_CLASS_MIN_LINES,
        "god_class": topo.god_class,
        "institutional_single_responsibility_claim_allowed": False,
        "responsibility_domains": topo.responsibility_domains,
        "partial_delegation_modules": topo.partial_delegation_modules,
        "helper_classes_in_file": topo.helper_classes,
        "bot_engine_methods": topo.methods,
        "disclaimer_tr": (
            "BotEngine tek sınıfta tick, giriş/çıkış, risk ve state taşır (~1000+ satır). "
            "engine_managers ve pipelines kısmi delegasyondur; kurumsal tek-sorumluluk iddiası "
            "bu yapı ile uyumlu değildir. LOC manifest ve tavan ile büyüme kontrol edilir."
        ),
    }


def write_manifest(path: Optional[Path] = None, *, engine_path: Optional[Path] = None) -> Path:
    p = path or _DEFAULT_MANIFEST
    topo = inspect_bot_engine(engine_path)
    payload = build_manifest_payload(topo)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def compare_topology_to_manifest(
    topo: BotEngineTopology,
    manifest: Mapping[str, Any],
) -> List[str]:
    issues: List[str] = []
    if manifest.get("institutional_single_responsibility_claim_allowed") is not False:
        issues.append("manifest: institutional_single_responsibility_claim_allowed must be false")

    for key, live in (
        ("file_line_count", topo.file_line_count),
        ("bot_engine_class_line_count", topo.bot_engine_class_line_count),
        ("bot_engine_method_count", topo.bot_engine_method_count),
    ):
        exp = manifest.get(key)
        if exp is not None and int(exp) != live:
            issues.append(f"manifest {key}: expected {exp} live={live} — run --write-manifest")

    exp_methods = manifest.get("bot_engine_methods")
    if isinstance(exp_methods, list) and sorted(exp_methods) != topo.methods:
        added = set(topo.methods) - set(exp_methods)
        removed = set(exp_methods) - set(topo.methods)
        if added:
            issues.append(f"new BotEngine methods (update manifest): {sorted(added)}")
        if removed:
            issues.append(f"removed BotEngine methods: {sorted(removed)}")

    file_ceil = int(manifest.get("file_line_ceiling", FILE_LINE_CEILING))
    class_ceil = int(manifest.get("class_line_ceiling", CLASS_LINE_CEILING))
    if topo.file_line_count > file_ceil:
        issues.append(f"bot_engine.py lines {topo.file_line_count} > file ceiling {file_ceil}")
    if topo.bot_engine_class_line_count > class_ceil:
        issues.append(
            f"BotEngine class lines {topo.bot_engine_class_line_count} > class ceiling {class_ceil}"
        )

    required_domains = {"tick", "entry", "exit", "risk", "state"}
    missing = required_domains - set(topo.responsibility_domains)
    if missing:
        issues.append(f"BotEngine missing responsibility domains in scan: {sorted(missing)}")
    return issues


def bot_engine_disclosure(*, topo: Optional[BotEngineTopology] = None) -> Dict[str, Any]:
    t = topo or inspect_bot_engine()
    limitations: List[str] = [
        "god_class_bot_engine",
        "multi_domain_single_class",
        "partial_delegation_only",
    ]
    if t.god_class:
        limitations.append(f"class_lines_ge_{GOD_CLASS_MIN_LINES}")
    if t.file_line_count > FILE_LINE_CEILING:
        limitations.append("file_lines_above_ceiling")

    return {
        "bot_engine_topology_controlled": True,
        "institutional_single_responsibility_claim_allowed": False,
        "topology": {
            "file_line_count": t.file_line_count,
            "file_nonempty_line_count": t.file_nonempty_line_count,
            "bot_engine_class_line_count": t.bot_engine_class_line_count,
            "bot_engine_method_count": t.bot_engine_method_count,
            "god_class": t.god_class,
            "file_line_ceiling": FILE_LINE_CEILING,
            "class_line_ceiling": CLASS_LINE_CEILING,
            "responsibility_domains": list(t.responsibility_domains),
            "partial_delegation_modules": list(t.partial_delegation_modules),
            "helper_classes_in_file": list(t.helper_classes),
        },
        "limitations": limitations,
        "disclaimer_tr": build_manifest_payload(t)["disclaimer_tr"],
    }


def validate_bot_engine_topology_contract(repo_root: Optional[Path] = None) -> List[str]:
    root = repo_root or _REPO
    issues: List[str] = []

    compose = root / "docker-compose.yml"
    if compose.is_file():
        if _COMPOSE_MARKER not in compose.read_text(encoding="utf-8").lower():
            issues.append(
                f"{compose.as_posix()}: must document BotEngine god-class limits (audit 8 marker)"
            )
    else:
        issues.append(f"{compose.as_posix()}: missing")

    manifest_path = root / "data" / "bot_engine_topology_manifest.json"
    if not manifest_path.is_file():
        issues.append(
            f"{manifest_path.as_posix()}: missing — run "
            "python -m super_otonom.bot_engine_topology --write-manifest"
        )
        return issues

    engine = root / "super_otonom" / "bot_engine.py"
    if not engine.is_file():
        issues.append(f"{engine.as_posix()}: missing")
        return issues

    topo = inspect_bot_engine(engine)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        issues.append(f"{manifest_path.as_posix()}: invalid JSON: {exc}")
        return issues

    issues.extend(compare_topology_to_manifest(topo, manifest))
    return issues


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="BotEngine god-class topology / manifest.")
    p.add_argument("--write-manifest", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(list(argv) if argv is not None else None)

    if args.write_manifest:
        out = write_manifest()
        print(f"Wrote {out.as_posix()}")
        return 0

    topo = inspect_bot_engine()
    disc = bot_engine_disclosure(topo=topo)
    issues = validate_bot_engine_topology_contract()
    payload = {"ok": not issues, "issues": issues, "disclosure": disc}
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print("=== bot_engine_topology ===")
        print(
            f"file_lines={topo.file_line_count} class_lines={topo.bot_engine_class_line_count} "
            f"god_class={topo.god_class} institutional_sr={disc['institutional_single_responsibility_claim_allowed']}"
        )
        for line in issues:
            print(f"  FAIL: {line}")
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
