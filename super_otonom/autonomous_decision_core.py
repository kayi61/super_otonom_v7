"""
Faz 80 — Autonomous Decision Core (final action).

Amaç:
- Faz 71-79 çıktılarından tek nihai karar üretmek:
  final_action (ENTER/WAIT/EXIT/HEDGE/HALT) + position sizing + execution profile.

Override kuralı (ENTER yasak):
- Faz 50 / 73 / 70 / 69 / 68 / 67 / 66 / 64 / 39 trade_permission BLOCK/HALT ise ENTER yasak.
  (Bu modül, bu fazların sonuçlarını opsiyonel olarak alır; yoksa mevcut olanlarla yetinir.)

Standartlar:
- trade_permission = HALT/BLOCK/ALLOW (tek bayrak)
- alpha_score + risk_score
- confidence (0-1, Faz 71-79 ile aynı ölçek) + data_health
- event_ts + half_life_ms
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, Literal, Optional


TradePermission = Literal["HALT", "BLOCK", "ALLOW"]
FinalAction = Literal["ENTER", "WAIT", "EXIT", "HEDGE", "HALT"]
ExecutionProfile = Literal["maker", "taker", "twap"]


@dataclass(frozen=True)
class AutonomousDecisionResult:
    # Faz 80 outputs (requested)
    final_action: FinalAction
    confidence: float  # 0-1 (Faz 71-79 confidence ile uyumlu)
    position_size_multiplier: float
    execution_profile: ExecutionProfile

    # System standards (requested)
    trade_permission: TradePermission
    alpha_score: int  # 0-100
    risk_score: int  # 0-100
    risk_gate: int  # 0-100 (yüksek = daha fazla risk bütçesi; Faz 79 conflict ile düşer)
    data_health: float  # 0-1
    event_ts: int  # ms
    half_life_ms: int

    # Faz 74 özeti (Seçenek 1 — doğrudan Faz 80 girdisi/çıktısı)
    route_preference: str = "unknown"
    leader_venue: str = ""

    # Optional debug
    block_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _clamp01(x: float) -> float:
    if x != x:  # NaN
        return 0.0
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def _clamp100(x: float) -> int:
    if x != x:  # NaN
        return 0
    return int(max(0, min(100, round(x))))


def _get(d: Any, key: str, default: Any = None) -> Any:
    if d is None:
        return default
    if isinstance(d, dict):
        return d.get(key, default)
    return getattr(d, key, default)


def _perm_rank(p: str) -> int:
    if p == "HALT":
        return 2
    if p == "BLOCK":
        return 1
    return 0


def _combine_trade_permission(*perms: str) -> TradePermission:
    best = "ALLOW"
    for p in perms:
        if _perm_rank(str(p)) > _perm_rank(best):
            best = str(p)
    return best  # type: ignore[return-value]


def decide_autonomously(
    *,
    symbol: str,
    # Required phases 71-75 (dict or dataclass)
    phase71: Any,
    phase72: Any,
    phase73: Any,
    phase74: Any,
    phase75: Any,
    # Optional execution / risk / alpha / MTF layers (None = pipeline 71→75→80 only)
    phase76: Any = None,
    phase77: Any = None,
    phase78: Any = None,
    phase79: Any = None,
    # Optional override-chain guards (39/50/64/66-70/68)
    phase39: Any = None,
    phase50: Any = None,
    phase64: Any = None,
    phase66: Any = None,
    phase67: Any = None,
    phase68: Any = None,
    phase69: Any = None,
    phase70: Any = None,
    event_ts: Optional[int] = None,
    half_life_ms: int = 25_000,
) -> AutonomousDecisionResult:
    """
    Combine phases into a final decision.

    Strategy:
    - trade_permission: worst-case merge across provided phases (50/73/70/69/68/67/66/64/39 + 71-79).
    - alpha_score: weighted blend of (phase75 consensus alpha) + (phase79 mtf alpha) + (phase78 freshness).
    - risk_score: weighted blend of (phase75 risk) + (phase73 manipulation) + (phase76 slippage) + (phase77 hunt risk).
    - phase76-79 omitted: neutral defaults (no MTF gating, mid freshness) so 71→75→80 chain can ENTER when consensus is clean.
    - phase74 (Seçenek 1): latency_arb_risk risk skoruna girer; route_preference/leader_venue çıktıda passthrough.
    - final_action: obey overrides; otherwise ENTER only when conviction+freshness+mtf are good and risk is acceptable.
    """
    # timestamps
    ts_candidates = [
        _get(phase71, "event_ts"),
        _get(phase72, "event_ts"),
        _get(phase73, "event_ts"),
        _get(phase74, "event_ts"),
        _get(phase75, "event_ts"),
        _get(phase76, "event_ts"),
        _get(phase77, "event_ts"),
        _get(phase78, "event_ts"),
        _get(phase79, "event_ts"),
        _get(phase50, "event_ts"),
        _get(phase66, "event_ts"),
        _get(phase67, "event_ts"),
        _get(phase68, "event_ts"),
        _get(phase69, "event_ts"),
        _get(phase70, "event_ts"),
        event_ts,
    ]
    ts_valid = [int(x) for x in ts_candidates if isinstance(x, (int, float)) and int(x) > 0]
    ts = int(max(ts_valid) if ts_valid else _now_ms())

    hl_candidates = [
        _get(phase71, "half_life_ms"),
        _get(phase72, "half_life_ms"),
        _get(phase73, "half_life_ms"),
        _get(phase74, "half_life_ms"),
        _get(phase75, "half_life_ms"),
        _get(phase76, "half_life_ms"),
        _get(phase77, "half_life_ms"),
        _get(phase78, "half_life_ms"),
        _get(phase79, "half_life_ms"),
        _get(phase50, "half_life_ms"),
        _get(phase66, "half_life_ms"),
        _get(phase67, "half_life_ms"),
        _get(phase68, "half_life_ms"),
        _get(phase69, "half_life_ms"),
        _get(phase70, "half_life_ms"),
        half_life_ms,
    ]
    hl_valid = [int(x) for x in hl_candidates if isinstance(x, (int, float)) and int(x) > 0]
    hl = int(min(hl_valid) if hl_valid else half_life_ms)
    hl = max(2_000, min(300_000, hl))

    # Data health: conservative min across phases
    dh_list = [
        _get(phase71, "data_health"),
        _get(phase72, "data_health"),
        _get(phase73, "data_health"),
        _get(phase74, "data_health"),
        _get(phase75, "data_health"),
        _get(phase76, "data_health"),
        _get(phase77, "data_health"),
        _get(phase78, "data_health"),
        _get(phase79, "data_health"),
        _get(phase66, "data_health"),
        _get(phase67, "data_health"),
        _get(phase68, "data_health"),
        _get(phase69, "data_health"),
        _get(phase70, "data_health"),
    ]
    dh_f = [_clamp01(float(x)) for x in dh_list if isinstance(x, (int, float))]
    data_health = min(dh_f) if dh_f else 0.45

    # Permissions (include override chain if provided)
    perm_50 = str(_get(phase50, "trade_permission", "ALLOW"))
    perm_73 = str(_get(phase73, "trade_permission", "ALLOW"))
    perm_66 = str(_get(phase66, "trade_permission", "ALLOW"))
    perm_67 = str(_get(phase67, "trade_permission", "ALLOW"))
    perm_68 = str(_get(phase68, "trade_permission", "ALLOW"))
    perm_69 = str(_get(phase69, "trade_permission", "ALLOW"))
    perm_70 = str(_get(phase70, "trade_permission", "ALLOW"))
    perm_64 = str(_get(phase64, "trade_permission", "ALLOW"))
    perm_39 = str(_get(phase39, "trade_permission", "ALLOW"))
    # plus other phases (so BLOCK can propagate even if guard not passed)
    perm_all = [
        perm_50,
        perm_73,
        perm_70,
        perm_69,
        perm_68,
        perm_67,
        perm_66,
        perm_64,
        perm_39,
        str(_get(phase71, "trade_permission", "ALLOW")),
        str(_get(phase72, "trade_permission", "ALLOW")),
        str(_get(phase74, "trade_permission", "ALLOW")),
        str(_get(phase75, "trade_permission", "ALLOW")),
        str(_get(phase76, "trade_permission", "ALLOW")),
        str(_get(phase77, "trade_permission", "ALLOW")),
        str(_get(phase78, "trade_permission", "ALLOW")),
        str(_get(phase79, "trade_permission", "ALLOW")),
    ]
    trade_permission = _combine_trade_permission(*perm_all)

    # Key phase metrics
    consensus_action = str(_get(phase75, "action", "WAIT"))
    consensus_conviction = _clamp100(_get(phase75, "conviction", 0))
    consensus_alpha = _clamp100(_get(phase75, "alpha_score", 0))
    consensus_risk = _clamp100(_get(phase75, "risk_score", 0))
    consensus_exec = str(_get(phase75, "execution_profile", "twap"))
    consensus_size_mult = float(_get(phase75, "max_size_multiplier", 1.0) or 1.0)

    exec_pref = str(_get(phase76, "preferred_order_type", "unknown"))
    slippage_risk = _clamp100(_get(phase76, "slippage_risk", 0))
    urgency = _clamp100(_get(phase76, "urgency_score", 0))

    hunt_risk = _clamp100(_get(phase77, "hunt_risk_score", 0))
    stop_hint = str(_get(phase77, "stop_placement_hint", "unknown"))

    freshness = _clamp100(_get(phase78, "alpha_freshness_score", 0))
    exit_urgency = _clamp100(_get(phase78, "exit_urgency", 0))

    mtf_score = _clamp100(_get(phase79, "mtf_consensus_score", 0))
    mtf_conflict = bool(_get(phase79, "conflict_flag", True))
    mtf_timing = str(_get(phase79, "entry_timing", "unknown"))

    if phase78 is None:
        freshness = 50
        exit_urgency = 0
    if phase79 is None:
        mtf_conflict = False
        mtf_timing = "ok"
        mtf_score = max(55, consensus_alpha)

    manipulation_risk = _clamp100(_get(phase73, "manipulation_risk_score", 0))
    do_not_trade = bool(_get(phase73, "do_not_trade_flag", False))
    cooldown_seconds = int(_get(phase73, "cooldown_seconds", 0) or 0)

    leadlag_lat_risk = _clamp100(_get(phase74, "latency_arb_risk", 0))
    route_pref = str(_get(phase74, "route_preference", "unknown") or "unknown")
    leader_v = str(_get(phase74, "leader_venue", "") or "")

    # Aggregate alpha/risk
    # Alpha quality: consensus + mtf + freshness (freshness gates alpha)
    alpha_score = _clamp100(
        (0.50 * consensus_alpha + 0.30 * mtf_score + 0.20 * freshness) * _clamp01(data_health)
    )
    risk_score = _clamp100(
        0.28 * consensus_risk
        + 0.20 * manipulation_risk
        + 0.18 * slippage_risk
        + 0.18 * hunt_risk
        + 0.06 * leadlag_lat_risk
        + 0.10 * max(exit_urgency, 100 - freshness)
        + 100.0 * (1.0 - _clamp01(data_health)) * 0.40
    )

    # Confidence 0-100: use min confidence across phases + consistency bonuses
    conf_list = [
        _get(phase71, "confidence"),
        _get(phase72, "confidence"),
        _get(phase73, "confidence"),
        _get(phase74, "confidence"),
        _get(phase75, "confidence"),
        _get(phase76, "confidence"),
        _get(phase77, "confidence"),
        _get(phase78, "confidence"),
        _get(phase79, "confidence"),
        _get(phase66, "confidence"),
        _get(phase67, "confidence"),
        _get(phase68, "confidence"),
        _get(phase69, "confidence"),
        _get(phase70, "confidence"),
    ]
    conf_f = [_clamp01(float(x)) for x in conf_list if isinstance(x, (int, float))]
    base_conf = min(conf_f) if conf_f else 0.40
    bonus = 0.0
    if not mtf_conflict and mtf_score >= 55:
        bonus += 0.08
    if freshness >= 60:
        bonus += 0.06
    if consensus_conviction >= 60:
        bonus += 0.06
    conf_0_1 = _clamp01(base_conf + bonus)
    confidence_0_100 = _clamp100(conf_0_1 * 100.0)

    # Faz 78: alpha freshness doğrudan güven skorunu ölçekler (stale → düşük confidence)
    if phase78 is not None:
        af = _clamp100(_get(phase78, "alpha_freshness_score", 0))
        confidence_0_100 = _clamp100(confidence_0_100 * (0.38 + 0.62 * (af / 100.0)))

    # Faz 79 conflict: risk_gate (risk bütçesi) daralır — ENTER ve sizing'de kullanılır
    risk_gate = _clamp100(max(0.0, 100.0 - 0.40 * float(risk_score)))
    if mtf_conflict:
        risk_gate = _clamp100(risk_gate * 0.68)

    confidence_01 = _clamp01(confidence_0_100 / 100.0)

    # Execution profile: prefer explicit order type if present; else use phase75
    execution_profile: ExecutionProfile = "twap"
    if exec_pref in ("maker", "taker", "twap"):
        execution_profile = exec_pref  # type: ignore[assignment]
    elif consensus_exec in ("maker", "taker", "twap"):
        execution_profile = consensus_exec  # type: ignore[assignment]

    # Position sizing: start with consensus size, downscale with risk, freshness decay, and conflict
    size_mult = float(consensus_size_mult)
    if mtf_conflict:
        size_mult *= 0.75
    if freshness < 35:
        size_mult *= 0.60
    if risk_score >= 75:
        size_mult *= 0.50
    if risk_score >= 85:
        size_mult *= 0.35
    if confidence_01 < 0.55:
        size_mult *= 0.70
    if risk_gate < 48:
        size_mult *= 0.72
    # small boost if very clean
    if alpha_score >= 70 and risk_score <= 40 and confidence_01 >= 0.70 and freshness >= 65 and not mtf_conflict:
        size_mult *= 1.10
    position_size_multiplier = float(max(0.0, min(1.50, round(size_mult, 3))))

    # Override: ENTER forbidden if any guard in chain is BLOCK/HALT.
    enter_forbidden = trade_permission in ("BLOCK", "HALT") or do_not_trade
    block_reason = ""
    if perm_50 in ("HALT", "BLOCK"):
        block_reason = "override:phase50"
    elif perm_73 in ("HALT", "BLOCK") or do_not_trade:
        block_reason = "override:phase73"
    elif perm_70 in ("HALT", "BLOCK"):
        block_reason = "override:phase70"
    elif perm_69 in ("HALT", "BLOCK"):
        block_reason = "override:phase69"
    elif perm_68 in ("HALT", "BLOCK"):
        block_reason = "override:phase68"
    elif perm_67 in ("HALT", "BLOCK"):
        block_reason = "override:phase67"
    elif perm_66 in ("HALT", "BLOCK"):
        block_reason = "override:phase66"
    elif perm_64 in ("HALT", "BLOCK"):
        block_reason = "override:phase64"
    elif perm_39 in ("HALT", "BLOCK"):
        block_reason = "override:phase39"
    elif trade_permission == "HALT":
        block_reason = "override:halt"
    elif trade_permission == "BLOCK":
        block_reason = "override:block"

    # Final action logic
    final_action: FinalAction = "WAIT"
    if trade_permission == "HALT":
        final_action = "HALT"
    elif enter_forbidden:
        # If we cannot enter, we may still recommend hedge/exit under high risk.
        if risk_score >= 85 or manipulation_risk >= 85:
            final_action = "HEDGE"
        elif exit_urgency >= 80 and freshness <= 25:
            final_action = "EXIT"
        else:
            final_action = "WAIT"
    else:
        # Not forbidden: decide ENTER / WAIT / HEDGE / EXIT
        if cooldown_seconds > 0:
            final_action = "WAIT"
            block_reason = f"cooldown:{cooldown_seconds}s"
        elif exit_urgency >= 85 and freshness <= 25:
            final_action = "EXIT"
        elif risk_score >= 80 or manipulation_risk >= 80:
            final_action = "HEDGE"
        else:
            # ENTER conditions
            ok_mtf = (not mtf_conflict) and (mtf_score >= 55) and (mtf_timing != "avoid")
            ok_fresh = freshness >= 45
            ok_alpha = alpha_score >= 45 or consensus_action in ("TRADE",)
            ok_conf = confidence_01 >= 0.55
            ok_risk = risk_score <= 70
            # Stop hint "widen" means hunt risk high -> stricter
            if stop_hint == "widen":
                ok_risk = ok_risk and (risk_score <= 62)
            if route_pref == "avoid_latency_arb" and leadlag_lat_risk >= 75:
                ok_risk = ok_risk and (risk_score <= 62)
            ok_gate = risk_gate >= 50
            if ok_mtf and ok_fresh and ok_alpha and ok_conf and ok_risk and ok_gate:
                final_action = "ENTER"
            else:
                final_action = "WAIT"

    _ = symbol
    return AutonomousDecisionResult(
        final_action=final_action,
        confidence=float(confidence_01),
        position_size_multiplier=float(position_size_multiplier),
        execution_profile=execution_profile,
        trade_permission=trade_permission,
        alpha_score=int(alpha_score),
        risk_score=int(risk_score),
        risk_gate=int(risk_gate),
        data_health=float(_clamp01(data_health)),
        event_ts=ts,
        half_life_ms=hl,
        route_preference=route_pref,
        leader_venue=leader_v,
        block_reason=block_reason,
    )

