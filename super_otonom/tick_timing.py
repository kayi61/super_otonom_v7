"""İsteğe bağlı tick faz süreleri — canlı mantığı değiştirmez.

``SUPER_OTONOM_TICK_TIMING=1`` (veya ``true``/``yes``) iken ``analysis`` içine
``_tick_phase_ms`` (ms) yazılır. Varsayılan: kapalı → ``span`` yalnızca ``yield``
eder; ek maliyet ihmal edilebilir düzeyde.

HF tarzı ölçüm: bölüm bazlı gecikme bütçesi / trend takibi için; emir kararını
etkilemez.
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, MutableMapping, Optional

_ENV_KEY = "SUPER_OTONOM_TICK_TIMING"
_enabled_cache: Optional[bool] = None


def is_tick_timing_enabled() -> bool:
    """İlk çağrıda env okunur; süreç boyunca sabit (performans için cache)."""
    global _enabled_cache
    if _enabled_cache is None:
        v = os.getenv(_ENV_KEY, "").strip().lower()
        _enabled_cache = v in ("1", "true", "yes", "on")
    return _enabled_cache


def reset_tick_timing_cache_for_tests() -> None:
    """Yalnızca test: env değişimini simüle etmek için."""
    global _enabled_cache
    _enabled_cache = None


@contextmanager
def span(analysis: MutableMapping[str, Any], phase: str) -> Iterator[None]:
    """Açıkken ``analysis['_tick_phase_ms'][phase]`` = süre (ms). Kapalıyken no-op."""
    if not is_tick_timing_enabled():
        yield
        return
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dt_ms = (time.perf_counter() - t0) * 1000.0
        if not isinstance(analysis, dict):
            return
        bucket: Dict[str, float] = analysis.setdefault("_tick_phase_ms", {})  # type: ignore[assignment]
        bucket[str(phase)] = round(float(dt_ms), 3)


def phase_count_from_chain(dctx: object) -> int:
    """``DecisionContext.phase_chain`` içindeki anahtar sayısı (gözlem)."""
    pc = getattr(dctx, "phase_chain", None)
    if not isinstance(pc, dict):
        return 0
    return len(pc)
