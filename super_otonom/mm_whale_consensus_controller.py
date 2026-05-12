"""
Faz 75 — MM + Whale consensus controller.

Amaç:
- Faz 71-74 çıktılarını tek karara indirgemek (action + execution profile).
- trade_permission (tek bayrak) ile uyumlu üretim yapmak.

Girdi beklentisi:
- Faz 71 (dealer_intent_inference_engine) sonucu
- Faz 72 (whale_intent_microstructure_engine) sonucu
- Faz 73 (liquidity_games_detector) sonucu
- Faz 74 (cross_venue_leadlag_intelligence) sonucu

Bu modül "kontrolcü" olduğundan, kendi başına market verisi toplamaz; sadece birleşim yapar.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, Literal, Optional

TradePermission = Literal["HALT", "BLOCK", "ALLOW"]
Action = Literal["TRADE", "WAIT", "REDUCE", "HEDGE", "HALT"]
ExecutionProfile = Literal["maker", "taker", "twap"]


@dataclass(frozen=True)
class MMWhaleConsensusResult:
    # Faz 75 outputs (requested)
    action: Action
    conviction: int  # 0-100
    max_size_multiplier: float
    execution_profile: ExecutionProfile

    # System standards (requested)
    trade_permission: TradePermission
    alpha_score: int  # 0-100
    risk_score: int  # 0-100
    confidence: float  # 0-1
    data_health: float  # 0-1
    event_ts: int  # ms
    half_life_ms: int

    # Optional debug
    veto_reason: str = ""

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
    # supports dict or dataclass with attribute
    if d is None:
        return default
    if isinstance(d, dict):
        return d.get(key, default)
    return getattr(d, key, default)


def _perm_rank(p: str) -> int:
    # Higher rank = stronger restriction
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


def compute_mm_whale_consensus(
    *,
    symbol: str,
    phase71: Any,
    phase72: Any,
    phase73: Any,
    phase74: Any,
    event_ts: Optional[int] = None,
    half_life_ms: int = 22_000,
) -> MMWhaleConsensusResult:
    """
    Combine 71-74 into a single decision envelope.
    """
    # Timestamps
    ts_candidates = [
        _get(phase71, "event_ts"),
        _get(phase72, "event_ts"),
        _get(phase73, "event_ts"),
        _get(phase74, "event_ts"),
        event_ts,
    ]
    ts_valid = [int(x) for x in ts_candidates if isinstance(x, (int, float)) and int(x) > 0]
    ts = int(max(ts_valid) if ts_valid else _now_ms())

    hl_candidates = [
        _get(phase71, "half_life_ms"),
        _get(phase72, "half_life_ms"),
        _get(phase73, "half_life_ms"),
        _get(phase74, "half_life_ms"),
        half_life_ms,
    ]
    hl_valid = [int(x) for x in hl_candidates if isinstance(x, (int, float)) and int(x) > 0]
    hl = int(min(hl_valid) if hl_valid else half_life_ms)
    hl = max(2_000, min(300_000, hl))

    # Standards aggregation
    perms = [
        str(_get(phase71, "trade_permission", "ALLOW")),
        str(_get(phase72, "trade_permission", "ALLOW")),
        str(_get(phase73, "trade_permission", "ALLOW")),
        str(_get(phase74, "trade_permission", "ALLOW")),
    ]
    trade_permission = _combine_trade_permission(*perms)

    dh = [
        _get(phase71, "data_health"),
        _get(phase72, "data_health"),
        _get(phase73, "data_health"),
        _get(phase74, "data_health"),
    ]
    conf = [
        _get(phase71, "confidence"),
        _get(phase72, "confidence"),
        _get(phase73, "confidence"),
        _get(phase74, "confidence"),
    ]
    dh_f = [_clamp01(float(x)) for x in dh if isinstance(x, (int, float))]
    conf_f = [_clamp01(float(x)) for x in conf if isinstance(x, (int, float))]
    data_health = min(dh_f) if dh_f else 0.45
    confidence = min(conf_f) if conf_f else 0.40

    # Extract key signals
    dealer_pressure = _clamp100(_get(phase71, "dealer_pressure_score", 0))
    spread_regime = str(_get(phase71, "spread_regime", "unknown"))
    trap_side = str(_get(phase71, "likely_trap_side", "unknown"))

    whale_intent = str(_get(phase72, "whale_intent", "unknown"))
    absorption_score = _clamp100(_get(phase72, "absorption_score", 0))
    sweep_risk = _clamp100(_get(phase72, "sweep_risk", 0))
    entry_hint = str(_get(phase72, "entry_timing_hint", "unknown"))

    manipulation_risk = _clamp100(_get(phase73, "manipulation_risk_score", 0))
    do_not_trade = bool(_get(phase73, "do_not_trade_flag", False))
    cooldown_seconds = int(_get(phase73, "cooldown_seconds", 0) or 0)
    game_type = str(_get(phase73, "game_type", "unknown"))

    leadlag_alpha = _clamp100(_get(phase74, "leadlag_alpha_score", 0))
    latency_arb_risk = _clamp100(_get(phase74, "latency_arb_risk", 0))
    route_pref = str(_get(phase74, "route_preference", "unknown"))

    # Consensus scores
    # Alpha: prefer whale accumulate/distribute + leadlag confirmation, penalize manipulation/sweep/dealer pressure
    intent_boost = 0.0
    if whale_intent in ("accumulate", "distribute"):
        intent_boost = 18.0 + 0.18 * absorption_score
    elif whale_intent == "hunt":
        intent_boost = -12.0
    elif whale_intent == "none":
        intent_boost = -6.0

    alpha_raw = (
        0.55 * leadlag_alpha
        + 0.45 * max(0, 100 - dealer_pressure)
        + intent_boost
        - 0.50 * sweep_risk
        - 0.70 * manipulation_risk
    )
    alpha_score = _clamp100(alpha_raw * _clamp01(data_health))

    # Risk: manipulation + latency arb + sweep + dealer pressure (weighted)
    risk_raw = (
        0.38 * manipulation_risk
        + 0.22 * latency_arb_risk
        + 0.22 * sweep_risk
        + 0.18 * dealer_pressure
    )
    risk_score = _clamp100(risk_raw + 100.0 * (1.0 - _clamp01(data_health)))

    # Conviction: alpha vs risk + confidence
    conviction = _clamp100((alpha_score - 0.60 * risk_score) * 0.85 + 100.0 * confidence * 0.35)

    # Execution profile: maker if spread tight/normal and latency risk low; twap if risk mid; taker if urgency high
    execution_profile: ExecutionProfile = "maker"
    if spread_regime == "wide" or latency_arb_risk >= 70:
        execution_profile = "twap"
    if do_not_trade:
        execution_profile = "twap"
    # Entry hint "enter_now" may prefer taker in safe conditions
    if (
        entry_hint == "enter_now"
        and manipulation_risk < 55
        and latency_arb_risk < 55
        and spread_regime != "wide"
    ):
        execution_profile = "taker"

    # Max size multiplier: shrink under risk, expand under strong alpha
    max_size_multiplier = 1.0
    if risk_score >= 80 or do_not_trade:
        max_size_multiplier = 0.25
    elif risk_score >= 65:
        max_size_multiplier = 0.50
    elif conviction >= 75 and risk_score <= 45:
        max_size_multiplier = 1.25
    elif conviction >= 85 and risk_score <= 35:
        max_size_multiplier = 1.40
    max_size_multiplier *= _clamp01(0.50 + 0.50 * confidence)
    max_size_multiplier = float(max(0.0, min(1.50, round(max_size_multiplier, 3))))

    # Action selection + veto reasons
    veto_reason = ""
    action: Action = "WAIT"

    # Strongest veto: HALT
    if trade_permission == "HALT":
        action = "HALT"
        veto_reason = "trade_permission_halt"
    elif trade_permission == "BLOCK":
        action = "WAIT"
        veto_reason = "trade_permission_block"
    elif do_not_trade:
        action = "WAIT"
        veto_reason = f"do_not_trade:{game_type}"
    elif confidence < 0.45 or data_health < 0.45:
        action = "WAIT"
        veto_reason = "low_confidence_or_data_health"
    else:
        # Risk management behaviors
        if manipulation_risk >= 80 or sweep_risk >= 85:
            action = "HEDGE"
            veto_reason = "extreme_microstructure_risk"
        elif risk_score >= 70:
            action = "REDUCE"
            veto_reason = "high_risk_reduce"
        else:
            # TRADE only if conviction meaningful and not obvious trap
            trap_penalty = 1
            if trap_side in ("long", "short"):
                trap_penalty = 0
            if conviction >= 55 and alpha_score >= 45 and trap_penalty == 1:
                action = "TRADE"
                veto_reason = ""
            else:
                action = "WAIT"
                veto_reason = "low_conviction_or_trap_risk"

    # Cooldown awareness: if phase73 suggests cooldown, keep WAIT (unless HALT)
    if action in ("TRADE",) and cooldown_seconds > 0:
        action = "WAIT"
        veto_reason = f"cooldown:{cooldown_seconds}s"

    # (symbol) currently unused but reserved for logs / future policy
    _ = symbol
    _ = route_pref

    return MMWhaleConsensusResult(
        action=action,
        conviction=int(conviction),
        max_size_multiplier=float(max_size_multiplier),
        execution_profile=execution_profile,
        trade_permission=trade_permission,
        alpha_score=int(alpha_score),
        risk_score=int(risk_score),
        confidence=float(_clamp01(confidence)),
        data_health=float(_clamp01(data_health)),
        event_ts=ts,
        half_life_ms=hl,
        veto_reason=veto_reason,
    )
