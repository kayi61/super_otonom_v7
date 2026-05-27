"""
Hard safety sözleşmesi — AI / strateji bu katmanı gevşetemez veya atlayamaz.

Bu modül **çalıştırılabilir sözleşme API'si** sağlar: ``enforce_*`` fonksiyonları gerçek
``pre_trade_gate`` / ``RISK`` üzerinden emir yolunu keser; ``audit_hard_safety_wiring()``
CI/fastrun ile doğrulanır. ``BotEngine`` giriş kapılarını buradan import etmelidir.

Uygulama noktaları (tek yönlü, konfig + piyasa/sermaye ölçüleri):
  - ``pre_trade_gate``: global trade disable, BUY slot, same-bar, giriş cooldown,
    kaldıraç tavanı (notional), spread / OB / fat-finger
  - ``unified_system_core.run_system_gate_phase`` + ``pipelines.risk_pipeline``: kill, spike
  - ``RiskManager.check_risk``: drawdown, günlük/haftalık kayıp, exposure, vol spike
  - ``HardLimitTracker``: emir hızı, fiyat sıçraması

Üstteki sabitler ve ``HARD_SAFETY_ENV_KEYS`` yalnızca indeks/dokümantasyon içindir;
**gerçek eşikler** ``config.RISK`` ve env'den okunur. AILayer bu dosyayı import ederek
limit değiştirmemelidir.

Zincir veya gate değişince PR checklist: ``docs/GOVERNANCE_CHECKLIST_TR.md`` — bölüm
**Güncelleme kuralı (PR)**.
"""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Sequence, Tuple

from super_otonom import pre_trade_gate as _ptg
from super_otonom.config import RISK

if TYPE_CHECKING:
    from super_otonom.position_sizer import PositionSizer

_REPO_ROOT = Path(__file__).resolve().parents[1]

# ── Canonical enforce API (BotEngine / risk_pipeline buradan çağırır) ─────────

gate_global_trade_disable = _ptg.gate_global_trade_disable
gate_buy_signal_and_slots = _ptg.gate_buy_signal_and_slots
gate_entry_cooldown = _ptg.gate_entry_cooldown
gate_leverage_notional = _ptg.gate_leverage_notional
gate_buy_size_and_exposure = _ptg.gate_buy_size_and_exposure
fat_finger_check = _ptg.fat_finger_check
spread_check = _ptg.spread_check
ob_depth_check = _ptg.ob_depth_check
same_bar_guard = _ptg.same_bar_guard
merge_entry_notional = _ptg.merge_entry_notional


def risk_limit(key: str, default: Any = None) -> Any:
    """Hard safety limit — yalnızca ``config.RISK`` (AILayer override yok)."""
    if key not in RISK and default is None:
        raise KeyError(f"hard_safety: RISK[{key!r}] missing")
    return RISK.get(key, default)


def enforce_global_trade_allowed() -> Tuple[bool, str]:
    """(allowed, block_code) — allowed=False → tick/giriş durmalı."""
    return gate_global_trade_disable()


def enforce_entry_signal_gates(
    signal: str,
    open_position_count: int,
    confidence: float,
) -> Tuple[bool, str]:
    return gate_buy_signal_and_slots(signal, open_position_count, float(confidence))


def enforce_entry_cooldown(
    symbol: str,
    last_entry_mono: Dict[str, float],
) -> Tuple[bool, str]:
    return gate_entry_cooldown(
        symbol,
        last_entry_mono,
        float(risk_limit("min_entry_cooldown_sec", 0.0)),
    )


def enforce_entry_leverage_cap(equity: float, order_notional: float) -> Tuple[bool, str]:
    return gate_leverage_notional(
        equity,
        order_notional,
        float(risk_limit("max_position_pct")),
        float(risk_limit("max_leverage", 1.0)),
    )


def enforce_entry_prechecks(
    symbol: str,
    signal: str,
    confidence: float,
    candles: Optional[List[Dict[str, Any]]],
    last_order_bar_ts: Dict[str, float],
    last_entry_wall_ts: Dict[str, float],
    open_position_count: int,
) -> Tuple[bool, float, str]:
    """Same-bar + BUY slot + cooldown. (ok, bar_ts, block_code)."""
    bar_ts = float(candles[-1].get("timestamp", 0)) if candles else 0.0
    ok_sb, block_sb = same_bar_guard(symbol, bar_ts, last_order_bar_ts)
    if not ok_sb:
        return False, bar_ts, block_sb
    ok_gate, block = enforce_entry_signal_gates(
        signal, int(open_position_count), float(confidence)
    )
    if not ok_gate:
        return False, bar_ts, block
    ok_cd, block_cd = enforce_entry_cooldown(symbol, last_entry_wall_ts)
    if not ok_cd:
        return False, bar_ts, block_cd
    return True, bar_ts, ""


def enforce_entry_size_safety(
    sizer: "PositionSizer",
    symbol: str,
    equity: float,
    size: float,
    raw_size: float,
    free_capital: float,
    open_positions: dict,
    order_book: Dict[str, Any],
) -> Tuple[bool, str]:
    """Fat-finger, spread, OB depth, exposure — tek enforce zinciri."""
    ok_sz, block_sz = gate_buy_size_and_exposure(
        sizer, symbol, equity, size, raw_size, free_capital, open_positions
    )
    if not ok_sz:
        return False, block_sz
    ok_ff, block_ff = fat_finger_check(
        size, max_notional=float(risk_limit("max_notional_per_order"))
    )
    if not ok_ff:
        return False, block_ff
    ok_sp, block_sp = spread_check(order_book)
    if not ok_sp:
        return False, block_sp
    ok_ob, block_ob = ob_depth_check(order_book, size)
    if not ok_ob:
        return False, block_ob
    return True, ""

HARD_SAFETY_CONFIG_NAMESPACE = "RISK"

HARD_SAFETY_ENV_KEYS: Tuple[str, ...] = (
    "MAX_LEVERAGE",
    "MIN_ENTRY_COOLDOWN_SEC",
    "GLOBAL_TRADE_DISABLE",
    "MAX_POSITION_PCT",
    "MAX_EXPOSURE_PCT",
    "MAX_NOTIONAL_PER_ORDER",
)

ENV_TO_RISK_KEY: Dict[str, str] = {
    "MAX_LEVERAGE": "max_leverage",
    "MIN_ENTRY_COOLDOWN_SEC": "min_entry_cooldown_sec",
    "MAX_POSITION_PCT": "max_position_pct",
    "MAX_EXPOSURE_PCT": "max_exposure_pct",
    "MAX_NOTIONAL_PER_ORDER": "max_notional_per_order",
}


@dataclass(frozen=True)
class EnforcementPoint:
    """Tek bir hard-safety kontrolünün kodda nerede uygulandığı."""

    id: str
    module: str
    callable_name: str
    class_name: str = ""
    risk_keys: Tuple[str, ...] = ()
    env_keys: Tuple[str, ...] = ()


HARD_SAFETY_ENFORCEMENT: Tuple[EnforcementPoint, ...] = (
    EnforcementPoint(
        "global_trade_disable",
        "super_otonom.pre_trade_gate",
        "gate_global_trade_disable",
        env_keys=("GLOBAL_TRADE_DISABLE",),
    ),
    EnforcementPoint(
        "buy_slots_confidence",
        "super_otonom.pre_trade_gate",
        "gate_buy_signal_and_slots",
        risk_keys=("max_open_positions", "entry_min_confidence"),
        env_keys=("ENTRY_MIN_CONFIDENCE",),
    ),
    EnforcementPoint(
        "fat_finger",
        "super_otonom.pre_trade_gate",
        "fat_finger_check",
        risk_keys=("max_notional_per_order",),
        env_keys=("MAX_NOTIONAL_PER_ORDER",),
    ),
    EnforcementPoint(
        "leverage_notional",
        "super_otonom.pre_trade_gate",
        "gate_leverage_notional",
        risk_keys=("max_leverage",),
        env_keys=("MAX_LEVERAGE",),
    ),
    EnforcementPoint(
        "entry_cooldown",
        "super_otonom.pre_trade_gate",
        "gate_entry_cooldown",
        risk_keys=("min_entry_cooldown_sec",),
        env_keys=("MIN_ENTRY_COOLDOWN_SEC",),
    ),
    EnforcementPoint(
        "portfolio_risk",
        "super_otonom.risk_manager",
        "check_risk",
        class_name="RiskManager",
        risk_keys=(
            "max_total_drawdown",
            "max_daily_loss_pct",
            "max_weekly_loss_pct",
            "max_exposure_pct",
        ),
        env_keys=(
            "MAX_TOTAL_DRAWDOWN",
            "MAX_DAILY_LOSS_PCT",
            "MAX_WEEKLY_LOSS_PCT",
            "MAX_EXPOSURE_PCT",
        ),
    ),
    EnforcementPoint(
        "hard_limit_tracker",
        "super_otonom.kill_switch",
        "HardLimitTracker",
        env_keys=("KILL_MAX_ORDERS_PER_SEC", "KILL_MAX_PRICE_JUMP_PCT"),
    ),
    EnforcementPoint(
        "system_gate",
        "super_otonom.unified_system_core",
        "run_system_gate_phase",
    ),
)


def snapshot_active_limits(
    *,
    risk: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Çalışma anındaki ``config.RISK`` değerleri (tek kaynak özeti)."""
    src = risk if risk is not None else RISK
    keys = sorted(
        {
            rk
            for ep in HARD_SAFETY_ENFORCEMENT
            for rk in ep.risk_keys
        }
        | set(ENV_TO_RISK_KEY.values())
    )
    return {k: src.get(k) for k in keys if k in src}


def _bot_engine_audit_path() -> Path:
    """PROMPT-04: gerçek kaynak ``core/bot_engine.py``; kök dosya shim olabilir."""
    core = _REPO_ROOT / "super_otonom" / "core" / "bot_engine.py"
    if core.is_file():
        return core
    return _REPO_ROOT / "super_otonom" / "bot_engine.py"


def audit_bot_engine_uses_contract() -> List[str]:
    """BotEngine doğrudan pre_trade_gate import etmemeli."""
    path = _bot_engine_audit_path()
    try:
        src = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"bot_engine: read error: {exc}"]
    issues: List[str] = []
    if "from super_otonom.hard_safety_contract import" not in src:
        issues.append("bot_engine: must import gates from hard_safety_contract")
    if "from super_otonom.pre_trade_gate import" in src:
        issues.append("bot_engine: direct pre_trade_gate import forbidden")
    if "enforce_entry_prechecks" not in src and "_entry_check_gates" in src:
        issues.append("bot_engine: entry path should use enforce_entry_prechecks")
    return issues


def audit_hard_safety_wiring(
    *,
    risk: Optional[Mapping[str, Any]] = None,
) -> List[str]:
    """Boş liste = tüm enforcement noktaları kodda ve RISK anahtarlarında mevcut."""
    src = risk if risk is not None else RISK
    issues: List[str] = list(audit_bot_engine_uses_contract())
    for ep in HARD_SAFETY_ENFORCEMENT:
        try:
            mod = importlib.import_module(ep.module)
        except ImportError as exc:
            issues.append(f"{ep.id}: cannot import {ep.module}: {exc}")
            continue
        if ep.class_name:
            cls = getattr(mod, ep.class_name, None)
            target = getattr(cls, ep.callable_name, None) if cls is not None else None
            label = f"{ep.module}.{ep.class_name}.{ep.callable_name}"
        else:
            target = getattr(mod, ep.callable_name, None)
            label = f"{ep.module}.{ep.callable_name}"
        if ep.callable_name == "HardLimitTracker" and not ep.class_name:
            if not isinstance(target, type):
                issues.append(f"{ep.id}: HardLimitTracker class missing in {ep.module}")
        elif not callable(target):
            issues.append(f"{ep.id}: missing callable {label}")
        for rk in ep.risk_keys:
            if rk not in src:
                issues.append(f"{ep.id}: RISK missing key {rk!r}")
        for ek in ep.env_keys:
            if ek not in HARD_SAFETY_ENV_KEYS and ek not in (
                "ENTRY_MIN_CONFIDENCE",
                "MAX_DAILY_LOSS_PCT",
                "MAX_WEEKLY_LOSS_PCT",
                "MAX_TOTAL_DRAWDOWN",
                "KILL_MAX_ORDERS_PER_SEC",
                "KILL_MAX_PRICE_JUMP_PCT",
            ):
                mapped = ENV_TO_RISK_KEY.get(ek)
                if mapped and mapped not in src:
                    issues.append(f"{ep.id}: env {ek} maps to missing RISK[{mapped!r}]")
    return issues


def assert_hard_safety_wired(**kwargs: Any) -> None:
    issues = audit_hard_safety_wiring(**kwargs)
    if issues:
        raise RuntimeError("hard_safety wiring failed:\n  - " + "\n  - ".join(issues))


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Hard safety wiring audit (enforce map vs RISK).")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(list(argv) if argv is not None else None)

    issues = audit_hard_safety_wiring()
    payload = {
        "ok": not issues,
        "issues": issues,
        "enforcement_points": [ep.id for ep in HARD_SAFETY_ENFORCEMENT],
        "active_limits": snapshot_active_limits(),
        "config_namespace": HARD_SAFETY_CONFIG_NAMESPACE,
        "doc_only_constants": list(HARD_SAFETY_ENV_KEYS),
    }
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print("=== hard_safety_contract audit ===")
        print(f"OK: {payload['ok']} | enforcement points: {len(payload['enforcement_points'])}")
        if issues:
            for line in issues:
                print(f"  FAIL: {line}")
        print("active_limits (RISK):", json.dumps(payload["active_limits"], ensure_ascii=False))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
