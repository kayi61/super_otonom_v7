#!/usr/bin/env python3
"""CI: mutmut kill-rate gate (mutmut 2.x result-ids)."""

from __future__ import annotations

import argparse
import subprocess
import sys


def _ids(status: str) -> list[str]:
    proc = subprocess.run(
        ["mutmut", "result-ids", status],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return []
    return proc.stdout.split()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--min", type=float, default=80.0, help="Minimum kill rate percent")
    args = p.parse_args()

    killed = _ids("killed")
    survived = _ids("survived")
    timeout = _ids("timeout")
    suspicious = _ids("suspicious")

    tested = len(killed) + len(survived) + len(timeout) + len(suspicious)
    if tested == 0:
        print(
            "FAIL: no mutants tested — coverage context missing? "
            "Use --cov=super_otonom.MODULE (dot notation) with --cov-context=test"
        )
        return 1

    rate = 100.0 * len(killed) / tested
    print(
        f"Mutation kill rate: {rate:.1f}% "
        f"(killed={len(killed)} survived={len(survived)} "
        f"timeout={len(timeout)} suspicious={len(suspicious)})"
    )
    if rate < args.min:
        print(f"FAIL: {rate:.1f}% < {args.min}%")
        if survived:
            print("Survived (first 15):", ", ".join(survived[:15]))
        return 1
    print(f"PASS: {rate:.1f}% >= {args.min}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
