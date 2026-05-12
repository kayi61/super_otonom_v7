"""PROMPT-A12: release öncesi smoke — `pytest -m release_gate` ile aynı komut satırı."""

from __future__ import annotations

import subprocess
import sys


def main(argv: list[str] | None = None) -> int:
    """Çalıştır: ``python -m super_otonom.release_gate`` veya ``super-otonom-release-gate``."""
    args = list(argv) if argv is not None else sys.argv[1:]
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-m",
        "release_gate",
        "-q",
        "--tb=short",
        *args,
    ]
    return int(subprocess.call(cmd))


if __name__ == "__main__":
    raise SystemExit(main())
