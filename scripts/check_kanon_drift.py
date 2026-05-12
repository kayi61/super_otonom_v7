#!/usr/bin/env python3
"""Repo kanon drift kontrolü — CLI sarmalayıcı.

Mantık: ``super_otonom.kanon_drift_check`` (pytest ve release_gate ile paylaşılır).

Çıkış kodları: 0 = uyumlu, 1 = drift (veya --warn-only ile her zaman 0).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Paket kurulu olmasa bile (editable olmadan) repo kökünden çalışsın
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from super_otonom.kanon_drift_check import run_all_checks


def main() -> int:
    parser = argparse.ArgumentParser(description="Kanon drift kontrolü (envanter + phase_chain).")
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help="Drift olsa bile çıkış kodu 0 (yalnızca uyarı yazdır).",
    )
    args = parser.parse_args()

    ok, issues = run_all_checks()
    if not ok:
        print("KANON DRIFT — aşağıdakileri gözden geçirin:\n", file=sys.stderr)
        for i, line in enumerate(issues, 1):
            print(f"  {i}. {line}", file=sys.stderr)
        print(
            "\nReferans: docs/TERMINOLOGY_AND_KANON_TR.md, docs/REALITY_VS_REPORT_TR.md, "
            "PROMPT-FAZ-MASTER-ENVANTER.md §2",
            file=sys.stderr,
        )
        return 0 if args.warn_only else 1

    print("Kanon drift: OK (src/phases + phase_chain.update keys).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
