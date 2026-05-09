"""
Faz 79 — Multi-timeframe consensus engine.

Amaç:
- 1m/5m/15m/1h/4h/1d gibi çoklu zaman dilimi sinyallerini birleştirip
  tek bir konsensüs skoru üretmek.
- Çatışma varsa conflict_flag yükseltmek ve entry_timing önerisi vermek.

Standartlar:
- trade_permission = HALT/BLOCK/ALLOW
- alpha_score + risk_score
- confidence + data_health
- event_ts + half_life_ms
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, Literal, Optional, Tuple


TradePermission = Literal["HALT", "BLOCK", "ALLOW"]
EntryTiming = Literal["enter_now", "wait_confirm", "wait_pullback", "avoid", "unknown"]


@dataclass(frozen=True)
class MTFConsensusResult:
    # Faz 79 outputs (requested)
    mtf_consensus_score: int  # 0-100
    dominant_timeframe: str
    conflict_flag: bool
    entry_timing: EntryTiming

    # System standards (requested)
    trade_permission: TradePermission
    alpha_score: int  # 0-100
    risk_score: int  # 0-100
    confidence: float  # 0-1
    data_health: float  # 0-1
    event_ts: int  # ms
    half_life_ms: int

    # Optional debug
    timeframes_seen: int = 0

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


def _try_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def _norm_signal(sig: Any) -> str:
    s = str(sig or "").strip().upper()
    if s in ("BUY", "LONG", "UP"):
        return "BUY"
    if s in ("SELL", "SHORT", "DOWN"):
        return "SELL"
    if s in ("HOLD", "NONE", "NEUTRAL"):
        return "HOLD"
    return "UNKNOWN"


def _tf_weights() -> Dict[str, float]:
    # Lower TF is faster/noisier; higher TF is slower/stronger.
    return {
        "1m": 0.70,
        "3m": 0.75,
        "5m": 0.80,
        "15m": 0.90,
        "30m": 0.95,
        "1h": 1.05,
        "2h": 1.10,
        "4h": 1.20,
        "6h": 1.25,
        "12h": 1.30,
        "1d": 1.40,
    }


def _parse_mtf(analysis: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Accept flexible shapes:
    - analysis["mtf"] = {"1m":{"signal":"BUY","score":...}, "5m":"SELL", ...}
    - analysis["timeframes"] = same
    """
    mtf = analysis.get("mtf")
    if isinstance(mtf, dict):
        return {str(k): (v if isinstance(v, dict) else {"signal": v}) for k, v in mtf.items()}
    tfs = analysis.get("timeframes")
    if isinstance(tfs, dict):
        return {str(k): (v if isinstance(v, dict) else {"signal": v}) for k, v in tfs.items()}
    return {}


def infer_mtf_consensus(
    *,
    symbol: str,
    analysis: Optional[Dict[str, Any]] = None,
    event_ts: Optional[int] = None,
    half_life_ms: int = 40_000,
) -> MTFConsensusResult:
    """
    Minimal, deterministic Faz-79 consensus.

    Computes a signed vote score from timeframes:
    - BUY => +1, SELL => -1, HOLD => 0
    Uses weights per timeframe and optional per-tf confidence/score if provided.
    """
    a = analysis or {}
    ts = int(event_ts if event_ts is not None else a.get("event_ts") or _now_ms())
    hl = int(a.get("half_life_ms") or half_life_ms)
    hl = max(2_000, min(300_000, hl))

    mtf = _parse_mtf(a)
    wmap = _tf_weights()
    if not mtf:
        # Unknown -> do not pretend score=0; use unknown timing semantics via low health/confidence.
        data_health = 0.45
        confidence = 0.40
        return MTFConsensusResult(
            mtf_consensus_score=0,
            dominant_timeframe="unknown",
            conflict_flag=True,
            entry_timing="unknown",
            trade_permission="ALLOW",
            alpha_score=0,
            risk_score=_clamp100(100.0 * (1.0 - data_health)),
            confidence=confidence,
            data_health=data_health,
            event_ts=ts,
            half_life_ms=hl,
            timeframes_seen=0,
        )

    total_w = 0.0
    signed = 0.0
    buy_w = 0.0
    sell_w = 0.0
    hold_w = 0.0

    # Dominant timeframe: highest absolute "vote contribution"
    dom_tf = "unknown"
    dom_abs = -1.0

    for tf, obj in mtf.items():
        sig = _norm_signal(obj.get("signal") if isinstance(obj, dict) else obj)
        base_w = float(wmap.get(tf, 0.90))
        tf_conf = _try_float(obj.get("confidence")) if isinstance(obj, dict) else None
        tf_score = _try_float(obj.get("score")) if isinstance(obj, dict) else None
        # Map tf_score (0-100) to 0.5..1.0 multiplier if present
        score_mult = 1.0
        if tf_score is not None:
            score_mult = 0.50 + 0.50 * _clamp01(tf_score / 100.0)
        conf_mult = 1.0
        if tf_conf is not None:
            conf_mult = 0.60 + 0.40 * _clamp01(tf_conf)

        w = base_w * score_mult * conf_mult
        total_w += w

        v = 0.0
        if sig == "BUY":
            v = 1.0
            buy_w += w
        elif sig == "SELL":
            v = -1.0
            sell_w += w
        elif sig == "HOLD":
            v = 0.0
            hold_w += w
        else:
            # unknown signal -> reduce health later
            v = 0.0
            hold_w += (w * 0.5)

        contrib = v * w
        signed += contrib
        if abs(contrib) > dom_abs:
            dom_abs = abs(contrib)
            dom_tf = tf

    if total_w <= 0:
        total_w = 1.0

    # Consensus magnitude: |signed| / total weights
    mag = abs(signed) / total_w  # 0..1
    mtf_consensus_score = _clamp100(100.0 * mag)

    # Conflict: both sides have meaningful weight
    # Example: if minority side > 35% of directional weight.
    dir_w = buy_w + sell_w
    if dir_w <= 0:
        conflict_flag = True
        minority_ratio = 1.0
    else:
        minority = min(buy_w, sell_w)
        minority_ratio = minority / dir_w
        conflict_flag = bool(minority_ratio >= 0.35 or mtf_consensus_score < 35)

    # Entry timing hint
    if conflict_flag and mtf_consensus_score < 50:
        entry_timing = "wait_confirm"
    elif mtf_consensus_score >= 75 and not conflict_flag:
        entry_timing = "enter_now"
    elif mtf_consensus_score >= 55 and not conflict_flag:
        entry_timing = "wait_pullback"
    elif conflict_flag and mtf_consensus_score >= 60:
        entry_timing = "avoid"
    else:
        entry_timing = "unknown"

    # Data health: number of TFs + unknown share
    tfs_seen = len(mtf)
    coverage = _clamp01((tfs_seen - 1) / 5.0)  # 2TF=>0.2, 6TF=>1.0
    # Penalize if conflict is high (uncertainty) but not too much (it's a real signal)
    data_health = _clamp01(0.55 + 0.35 * coverage - 0.10 * minority_ratio)

    # Confidence: health + consensus
    confidence = _clamp01(0.20 + 0.55 * data_health + 0.25 * (mtf_consensus_score / 100.0))
    if conflict_flag:
        confidence = min(confidence, 0.80)

    # Scores: alpha reflects consensus strength; risk reflects conflict + low health.
    alpha_score = _clamp100(mtf_consensus_score * _clamp01(data_health))
    risk_score = _clamp100(100.0 * minority_ratio * 0.85 + 100.0 * (1.0 - data_health) * 0.50)

    trade_permission: TradePermission = "ALLOW"
    # If extremely conflicting and low health, block entries (not halt).
    if data_health < 0.35:
        trade_permission = "BLOCK"
    elif conflict_flag and mtf_consensus_score < 30 and confidence >= 0.55:
        trade_permission = "BLOCK"

    _ = symbol
    return MTFConsensusResult(
        mtf_consensus_score=int(mtf_consensus_score),
        dominant_timeframe=str(dom_tf),
        conflict_flag=bool(conflict_flag),
        entry_timing=entry_timing,
        trade_permission=trade_permission,
        alpha_score=int(alpha_score),
        risk_score=int(risk_score),
        confidence=float(confidence),
        data_health=float(data_health),
        event_ts=ts,
        half_life_ms=hl,
        timeframes_seen=int(tfs_seen),
    )

