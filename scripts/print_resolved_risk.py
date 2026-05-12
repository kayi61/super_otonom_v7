#!/usr/bin/env python3
"""
Çözümlenmiş RISK + PAIRS yazdırır (API sırrı yok). Repo kökünde çalıştırın;
mevcut dizindeki .env load_dotenv ile yüklenir (super_otonom.config ile aynı).

Kullanım (canlı/staging):
  python scripts/print_resolved_risk.py
  python scripts/print_resolved_risk.py --summary

INSTITUTIONAL_CONTROL_CHECKLIST_TR.md §1 ile satır satır karşılaştırma için.

Özet satır sırası tek kaynak: ``super_otonom.risk_institutional_summary.SECT1_SUMMARY_SPEC``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from super_otonom.risk_institutional_summary import SECT1_SUMMARY_SPEC as _SUMMARY_SPEC


def _open_positions_env_source() -> str:
    if os.getenv("MAX_OPEN_POSITIONS") is not None:
        return "env:MAX_OPEN_POSITIONS"
    if os.getenv("MAX_POSITION_COUNT") is not None:
        return "env:MAX_POSITION_COUNT"
    return "default"


def _env_source(env_names: str) -> str:
    if "|" in env_names:
        for name in env_names.split("|"):
            if os.getenv(name) is not None:
                return f"env:{name}"
        return "default"
    if os.getenv(env_names) is not None:
        return f"env:{env_names}"
    return "default"


def _fmt_val(kind: str, v: object) -> str:
    if kind == "pct" and isinstance(v, (int, float)):
        return f"{float(v)} (~%{float(v) * 100:.4g})"
    if kind == "bool":
        return "true" if v else "false"
    return str(v)


def _print_summary(risk: dict[str, object]) -> None:
    print("# P0 - INSTITUTIONAL sect.1 alignment (resolved RISK; no secrets)")
    print("# Compare each line to INSTITUTIONAL_CONTROL_CHECKLIST_TR.md section 1 table.")
    print()
    for key, env_key, kind in _SUMMARY_SPEC:
        v = risk.get(key)
        if key == "max_open_positions":
            src = _open_positions_env_source()
        else:
            src = _env_source(env_key)
        pct_note = ""
        if kind == "pct" and isinstance(v, (int, float)):
            pct_note = f" | table row: %{float(v) * 100:g} policy wording must match"
        print(f"- {key} = {_fmt_val(kind, v)}  [source: {src}]{pct_note}")
    print()
    print(
        "# One-line verification example (internal note / PR): "
        '"max_daily_loss_pct=0.05 (~%5), INSTITUTIONAL sect.1 daily loss %5 - OK" '
        "or fix table / env / commit."
    )


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    parser = argparse.ArgumentParser(description="Çözümlenmiş RISK çıktısı (sırlar yok).")
    parser.add_argument(
        "--summary",
        action="store_true",
        help="§1 ile karşılaştırma için kısa madde listesi + kaynak (env/default).",
    )
    args = parser.parse_args()

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if root not in sys.path:
        sys.path.insert(0, root)
    os.chdir(root)

    from super_otonom.config import PAIRS, RISK

    if args.summary:
        _print_summary(dict(RISK))
        print()
        print(f"PAIRS ({len(PAIRS)}): {', '.join(PAIRS)}")
        return 0

    out = {
        "cwd": os.getcwd(),
        "RISK": dict(RISK),
        "PAIRS": list(PAIRS),
    }
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
