"""
PROMPT-A11 — Self-feedback loop kontrolü.

Amaç: Model A→B→C→A tipi **aynı tick içinde** geri beslemeyi kesmek (donmuş girdi,
tek yönlü DAG, konsensus tek tur).

Kod sözleşmesi (özet)::

    OHLCV / OB → ``MarketAnalyzer`` → ``analysis`` (çekirdek alanlar) →
    ``BotEngine.tick`` (tek tur: signal → fusion → filtreler → execution fazları)
    → ``out`` / emir. ``tick`` içinden ``analyzer.analyze*`` çağrılmaz;
    ``tick`` içinden yine ``tick`` çağrılmamalı (reentrancy guard).

Bu modül: ``analysis`` üzerinde çekirdek alanların tick sonuna kadar değişmediğini
izler; ``BotEngine`` üzerinde ``tick`` derinliği 1'i aşmamalıdır.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

A11_SCHEMA = "a11/v1"

# Analyzer kök çıktısı — tick içinde downstream fazlar bunları **yeniden yazmamalı**
# (yeni sinyal ``out["final_signal"]`` ile taşınır; A11 ihlali riski = buraya geri yazım).
FROZEN_CORE_KEYS: Tuple[str, ...] = ("signal", "regime", "hurst", "volatility")


def attach_tick_frozen_mark(
    analysis: Dict[str, Any],
    *,
    tick_id: int,
    symbol: str,
) -> None:
    """``analysis['_a11']`` ile donmuş çekirdek anlık görüntüsü (tek tick)."""
    core = {k: analysis.get(k) for k in FROZEN_CORE_KEYS}
    analysis["_a11"] = {
        "schema": A11_SCHEMA,
        "tick_id": int(tick_id),
        "symbol": str(symbol),
        "core_snapshot": core,
    }


def audit_intratick_frozen_core(analysis: Optional[Dict[str, Any]]) -> Optional[str]:
    """
    Tick sonunda çağrılır. Çekirdek alanlar snapshot'tan sapmışsa kısa uyarı metni.

    Dönüş ``None`` ise sorun yok.
    """
    if not isinstance(analysis, dict):
        return None
    meta = analysis.get("_a11")
    if not isinstance(meta, dict) or meta.get("schema") != A11_SCHEMA:
        return None
    snap = meta.get("core_snapshot")
    if not isinstance(snap, dict):
        return None
    for k in FROZEN_CORE_KEYS:
        if analysis.get(k) != snap.get(k):
            return (
                f"frozen core mutated intra-tick: field={k!r} "
                f"was={snap.get(k)!r} now={analysis.get(k)!r}"
            )
    return None


__all__ = (
    "A11_SCHEMA",
    "FROZEN_CORE_KEYS",
    "attach_tick_frozen_mark",
    "audit_intratick_frozen_core",
)
