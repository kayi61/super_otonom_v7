"""
Faz 68 — Safety policy engine.

Amaç:
- Haber / volatilite devreleri, pozisyon tavanı ve manuel onay ihtiyacını tek
  `trade_permission` bayrağında birleştirmek (Faz 80 override zinciri ile uyumlu).

Girdi (analysis, best-effort):
- news_kill_switch: bool — dış haber/sentiment kill (True = işlem durdur)
- volatility, volatility_kill_threshold: float — eşik aşımında vol devresi
- exp_pct, max_gross_exposure_pct: float — açık risk % (nav bazlı) vs tavan
- approval_required: bool — operatör onayı bekleniyor

Standartlar:
- trade_permission = HALT/BLOCK/ALLOW
- alpha_score + risk_score
- confidence + data_health
- event_ts + half_life_ms
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, Literal, Optional

TradePermission = Literal["HALT", "BLOCK", "ALLOW"]


@dataclass(frozen=True)
class SafetyPolicyResult:
    # Faz 68 outputs (requested)
    max_position_check: bool
    news_kill_switch: bool
    volatility_kill_switch: bool
    approval_required: bool

    # System standards (requested)
    trade_permission: TradePermission
    alpha_score: int  # 0-100
    risk_score: int  # 0-100
    confidence: float  # 0-1
    data_health: float  # 0-1
    event_ts: int  # ms
    half_life_ms: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _clamp01(x: float) -> float:
    if x != x:
        return 0.0
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def _clamp100(x: float) -> int:
    if x != x:
        return 0
    return int(max(0, min(100, round(x))))


def _now_ms() -> int:
    return int(time.time() * 1000)


def _try_float(x: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if x is None:
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


def evaluate_safety_policy(
    *,
    symbol: str,
    analysis: Optional[Dict[str, Any]] = None,
    event_ts: Optional[int] = None,
    half_life_ms: int = 45_000,
) -> SafetyPolicyResult:
    """
    Faz 68 — güvenlik politikası özeti.
    """
    a = analysis or {}
    ts = (
        int(event_ts)
        if isinstance(event_ts, (int, float)) and int(event_ts) > 0
        else int(a.get("event_ts") or _now_ms())
    )
    hl = int(a.get("half_life_ms") or half_life_ms)
    hl = max(2_000, min(300_000, hl))

    news_kill_switch = bool(a.get("news_kill_switch", False))

    vol = _try_float(a.get("volatility"), 0.02) or 0.02
    vol_thr = _try_float(a.get("volatility_kill_threshold"), 0.15) or 0.15
    volatility_kill_switch = vol >= max(vol_thr, 1e-9)

    max_exp = _try_float(a.get("max_gross_exposure_pct"), 0.95) or 0.95
    max_exp = _clamp01(max_exp)
    exp_pct = _try_float(a.get("exp_pct"), 0.0)
    if exp_pct is None:
        exp_pct = 0.0
    exp_pct = max(0.0, min(2.0, float(exp_pct)))
    max_position_check = exp_pct <= max_exp + 1e-9

    approval_required = bool(a.get("approval_required", False))

    # trade_permission: öncelik HALT (haber) → BLOCK (vol / poz / onay) → ALLOW
    trade_permission: TradePermission = "ALLOW"
    if news_kill_switch:
        trade_permission = "HALT"
    elif volatility_kill_switch or (not max_position_check) or approval_required:
        trade_permission = "BLOCK"

    # risk_score: bayraklar ve vol katkısı
    risk_score = _clamp100(
        18.0 * (1.0 if news_kill_switch else 0.0)
        + 22.0 * (1.0 if volatility_kill_switch else 0.0)
        + 20.0 * (0.0 if max_position_check else 1.0)
        + 15.0 * (1.0 if approval_required else 0.0)
        + 25.0 * _clamp01(vol / 0.25)
    )

    # alpha_score: politika katmanı — temiz yolda düşük-orta (bilgi amaçlı)
    alpha_score = _clamp100(
        72.0
        - 25.0 * (1.0 if news_kill_switch else 0.0)
        - 18.0 * (1.0 if volatility_kill_switch else 0.0)
        - 15.0 * (0.0 if max_position_check else 1.0)
        - 12.0 * (1.0 if approval_required else 0.0)
    )

    # data_health: girdi eksikliği
    data_health = 0.88
    if a.get("volatility") is None:
        data_health = min(data_health, 0.72)
    if a.get("exp_pct") is None and a.get("open_exposure_notional") is not None:
        data_health = min(data_health, 0.80)
    data_health = float(_clamp01(data_health))

    confidence = _clamp01(0.22 + 0.58 * data_health + 0.20 * (1.0 - risk_score / 130.0))
    if news_kill_switch:
        confidence = min(confidence, 0.45)

    _ = symbol
    return SafetyPolicyResult(
        max_position_check=max_position_check,
        news_kill_switch=news_kill_switch,
        volatility_kill_switch=volatility_kill_switch,
        approval_required=approval_required,
        trade_permission=trade_permission,
        alpha_score=int(alpha_score),
        risk_score=int(risk_score),
        confidence=float(confidence),
        data_health=float(data_health),
        event_ts=ts,
        half_life_ms=hl,
    )
