"""Koordinasyon ve kaos-dayanıklılık — tek programatik giriş (`SYSTEM_LONGEVITY_DESIGN_TR`).

Tick içi EMERGENCY / circuit breaker / kill-switch davranışı değiştirilmez; bu modül:

- Kanon drift sonucunu üretir veya doğrular (yapı ile doküman ayrışmasını erken yakalar).
- Büyük kaos / operasyon baskısında bakılacak **çıkış yollarını** tek sözlükte toplar (iletişim ve triyaj için).

Gerçek güvenlik eylemleri: ``GLOBAL_TRADE_DISABLE``, Faz 50, ``risk_pipeline``, ``main_loop`` CB — mevcut kodda kalır.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from super_otonom.kanon_drift_check import run_all_checks

# Kaos / acil durumda önce bakılacak yerler (davranış değiştirmez; navigasyon)
RESILIENCE_EXIT_PATHS: Mapping[str, str] = {
    "global_trade_kill": "Ortam: GLOBAL_TRADE_DISABLE=1 → tüm işlem yolu kapanır (pre_trade_gate / state_machine).",
    "system_gate": "Faz 50: unified_system_core.run_system_gate_phase — kill/risk ile tick erken çıkar.",
    "kill_hard_limits": "BotEngine._entry_kill_switch_check + kill_switch.HardLimitTracker",
    "circuit_breaker_exchange": "main_loop: circuit_breaker_status; sembol bazlı OPEN → tick atlanır.",
    "rate_storm": "apply_storm_trip_to_risk — 429 / limit fırtınasında emergency",
    "triage_repro": "docs/DEFECT_TRIAGE_A13.md — kırmızı test / prod sapması repro sırası",
    "governance_single_door": "docs/GOVERNANCE_CHECKLIST_TR.md §0.1 — tek kapı zinciri",
    "terminology_index": "docs/TERMINOLOGY_AND_KANON_TR.md — iki ağaç + üç kanon",
    "complexity_budget": "docs/COMPLEXITY_BUDGET_A10.md — karmaşa azaltma önerisi (insan onayı)",
    "weekly_attribution": "docs/ATTRIBUTION_WEEKLY_A5.md — faz katkısı gözlemi",
}


def coordination_snapshot(repo_root: Path | None = None) -> dict[str, Any]:
    """Kanon uyumu + çıkış yolu haritası (log / dashboard / debug için)."""
    ok, issues = run_all_checks(repo_root)
    return {
        "kanon_ok": ok,
        "kanon_issues": issues,
        "resilience_exit_paths": dict(RESILIENCE_EXIT_PATHS),
    }


def assert_coordination_invariants(repo_root: Path | None = None) -> None:
    """Release veya test: yapı-doküman uyumu yoksa AssertionError."""
    ok, issues = run_all_checks(repo_root)
    if not ok:
        detail = "\n".join(f"  - {m}" for m in issues)
        raise AssertionError(f"Kanon / koordinasyon drift:\n{detail}")
