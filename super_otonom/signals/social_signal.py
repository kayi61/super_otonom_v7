"""
Faz 16 — Sosyal sinyal / hype döngüsü.

Platform sentiment (Twitter / Reddit / Telegram), mention momentum, engagement,
hype aşaması (FOMO / PEAK / CAPITULATION / RECOVERY), trend yönü.

FOMO ve PEAK aşamalarında trade_permission BLOCK (üst katman risk ile birleşir).
CAPITULATION → contrarian alpha fırsatı proxy (yüksek alpha_score eğilimi).

Çıktı Faz 18/21/25 ile uyumlu: alpha/risk 0–1, score_type, phase16/faz16.
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any, Dict, Literal, Optional

from super_otonom.standard_phase_output import attach_phase_alias

log = logging.getLogger("super_otonom.social")

ScoreType = Literal["ALPHA", "RISK", "QUALITY"]
TradePermission = Literal["ALLOW", "BLOCK", "HALT"]
HypeStage = Literal["FOMO", "PEAK", "CAPITULATION", "RECOVERY", "NEUTRAL"]

_EPS = 1e-12


def _now_ms() -> int:
    return int(time.time() * 1000)


def _clamp01(x: float) -> float:
    if x != x:
        return 0.0
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else float(x)


def _try_ts_ms(analysis: Dict[str, Any]) -> int:
    v = analysis.get("event_ts") or analysis.get("candle_ts")
    try:
        if v is None:
            return _now_ms()
        fv = float(v)
        if fv < 1e11:
            return int(fv * 1000.0)
        return int(fv)
    except (TypeError, ValueError):
        return _now_ms()


def _pick_score_type(data_health: float, risk_01: float) -> ScoreType:
    if data_health < 0.42:
        return "QUALITY"
    if risk_01 >= 0.72:
        return "RISK"
    return "ALPHA"


def _get_num(d: Dict[str, Any], *keys: str, default: Optional[float] = None) -> Optional[float]:
    for k in keys:
        if k in d and d[k] is not None:
            try:
                return float(d[k])
            except (TypeError, ValueError):
                continue
    return default


def _normalize_social(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return dict(raw)


def _aggregate_sentiment(d: Dict[str, Any]) -> tuple[float, Dict[str, Optional[float]]]:
    """
    Birleşik sentiment [-1, 1].
    Tek alan sentiment_score / composite_sentiment veya platform ortalaması.
    """
    single = _get_num(d, "sentiment_score", "composite_sentiment", "social_sentiment")
    tw = _get_num(d, "twitter_sentiment", "twitter_score", "x_sentiment")
    rd = _get_num(d, "reddit_sentiment", "reddit_score")
    tg = _get_num(d, "telegram_sentiment", "telegram_score", "tg_sentiment")

    parts: list[float] = []
    plat = {"twitter": tw, "reddit": rd, "telegram": tg}
    for v in (tw, rd, tg):
        if v is not None:
            x = float(v)
            if x > 1.0 or x < -1.0:
                x = max(-1.0, min(1.0, x))
            elif 0.0 <= x <= 1.0 and x != 0.0:
                x = x * 2.0 - 1.0
            parts.append(x)

    if single is not None:
        x = float(single)
        if 0.0 <= x <= 1.0:
            comp = x * 2.0 - 1.0
        elif -1.0 <= x <= 1.0:
            comp = x
        else:
            comp = max(-1.0, min(1.0, x))
        if parts:
            comp = 0.55 * comp + 0.45 * (sum(parts) / len(parts))
        return float(max(-1.0, min(1.0, comp))), plat

    if parts:
        return float(sum(parts) / len(parts)), plat

    return 0.0, plat


def _mention_momentum(d: Dict[str, Any]) -> tuple[float, Optional[float]]:
    """0–1 momentum; ham değişim oranı veya None."""
    m0 = _get_num(d, "mention_count", "mentions", "social_mentions")
    m1 = _get_num(d, "mention_count_prev", "mentions_prev", "mention_prev")
    mp = _get_num(d, "mention_momentum", "mention_change_pct", "mentions_change_pct")
    if mp is not None:
        chg = max(-1.0, min(1.0, float(mp)))
        return _clamp01((chg + 1.0) / 2.0), float(mp)
    if m0 is not None and m1 is not None and m1 > _EPS:
        chg = (float(m0) - float(m1)) / float(m1)
        chg = max(-0.75, min(0.75, chg))
        return _clamp01((chg + 0.75) / 1.5), float(chg)
    if m0 is not None:
        return _clamp01(min(1.0, math.log1p(float(m0)) / 14.0)), None
    return 0.45, None


def _engagement(d: Dict[str, Any]) -> float:
    e = _get_num(d, "engagement_rate", "engagement", "social_engagement")
    if e is None:
        return 0.4
    x = float(e)
    if x > 1.0:
        x = x / 100.0
    return _clamp01(x)


def _sentiment_trend_label(d: Dict[str, Any]) -> Literal["up", "down", "flat"]:
    t = d.get("sentiment_trend") or d.get("trend")
    if isinstance(t, str):
        tl = t.lower()
        if tl in ("up", "rising", "bullish", "higher"):
            return "up"
        if tl in ("down", "falling", "bearish", "lower"):
            return "down"
    tv = _get_num(d, "sentiment_trend_score", "trend_slope")
    if tv is not None:
        if tv > 0.08:
            return "up"
        if tv < -0.08:
            return "down"
    return "flat"


def _detect_hype_stage(
    composite: float,
    mom_01: float,
    engagement: float,
    trend: Literal["up", "down", "flat"],
) -> HypeStage:
    """Heuristik hype döngüsü etiketi."""
    if composite <= -0.52:
        return "CAPITULATION"
    if trend == "up" and -0.48 < composite < -0.08:
        return "RECOVERY"
    if composite >= 0.62 and mom_01 >= 0.78 and engagement >= 0.72:
        return "PEAK"
    if composite >= 0.48 and (mom_01 >= 0.68 or engagement >= 0.70):
        return "FOMO"
    if composite >= 0.55 and mom_01 >= 0.55:
        return "FOMO"
    if trend == "up" and composite >= 0.15:
        return "RECOVERY"
    return "NEUTRAL"


def _alpha_from_stage(
    stage: HypeStage,
    composite: float,
    signal_hint: str,
) -> float:
    """CAPITULATION contrarian alpha; FOMO/PEAK düşük alpha."""
    s = str(signal_hint or "HOLD").upper()
    base = _clamp01((composite + 1.0) / 2.0)

    if stage == "CAPITULATION":
        base = _clamp01(0.62 + 0.28 * (1.0 - base))
    elif stage in ("FOMO", "PEAK"):
        base = _clamp01(base * 0.42 + 0.18)
    elif stage == "RECOVERY":
        base = _clamp01(0.48 + 0.38 * base)

    if s == "BUY" and stage == "CAPITULATION":
        base = _clamp01(base + 0.08)
    if s == "SELL" and stage in ("FOMO", "PEAK"):
        base = _clamp01(base + 0.10)

    return _clamp01(base)


def _risk_from_social(
    composite: float,
    mom_01: float,
    engagement: float,
    stage: HypeStage,
) -> float:
    hype_risk = _clamp01(0.55 * mom_01 + 0.45 * engagement)
    polar = _clamp01(abs(composite))
    stage_boost = 0.22 if stage in ("FOMO", "PEAK") else 0.08 if stage == "CAPITULATION" else 0.12
    return _clamp01(0.26 * hype_risk + 0.28 * polar + 0.22 * mom_01 + stage_boost)


def analyze_social_signal(
    symbol: str,
    social_data: Any,
    analysis: Optional[Dict[str, Any]] = None,
    *,
    attach_to_analysis: bool = True,
    half_life_ms: int = 48_000,
    event_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Sosyal metrikleri birleştirir; `analysis['phase16']` / `['faz16']` yazar.
    """
    _ = symbol
    a = analysis if analysis is not None else {}
    ts = int(event_ts) if event_ts is not None else _try_ts_ms(a)
    d = _normalize_social(social_data)

    if not d:
        payload = _empty_phase16(ts, half_life_ms, "no_social_data")
        if attach_to_analysis:
            attach_phase_alias(a, "16", payload)
        return payload

    composite, platforms = _aggregate_sentiment(d)
    mom_01, mom_raw = _mention_momentum(d)
    engagement = _engagement(d)
    trend = _sentiment_trend_label(d)
    stage = _detect_hype_stage(composite, mom_01, engagement, trend)

    signal_hint = str(a.get("signal", "HOLD"))
    alpha_01 = _alpha_from_stage(stage, composite, signal_hint)
    risk_01 = _risk_from_social(composite, mom_01, engagement, stage)

    # PROMPT-4.1: KOL (Twitter/X) konsensüsü — varsa alpha/risk'i ayarlar.
    kol_sig = _deep_kol_analysis(d, symbol, ts)
    if kol_sig is not None:
        alpha_01 = _clamp01(alpha_01 + 0.15 * kol_sig.alpha_bias)
        risk_01 = _clamp01(max(risk_01, kol_sig.risk_score))

    fields_ok = sum(
        1
        for v in (
            _get_num(d, "sentiment_score", "composite_sentiment"),
            _get_num(d, "mention_count", "mentions"),
            _get_num(d, "engagement_rate", "engagement"),
        )
        if v is not None and v == v
    )
    plat_ok = sum(1 for _k, v in platforms.items() if v is not None)
    conf = _clamp01(0.20 + 0.14 * fields_ok + 0.10 * plat_ok + 0.18 * mom_01)
    dh = _clamp01(0.26 + 0.12 * fields_ok + 0.14 * plat_ok + 0.12 * (1.0 - abs(composite)))

    perm: TradePermission = "ALLOW"
    if engagement >= 0.92 and risk_01 >= 0.88:
        perm = "HALT"
    elif risk_01 >= 0.88:
        perm = "BLOCK"
    elif risk_01 >= 0.72:
        perm = "BLOCK"

    if stage in ("FOMO", "PEAK") and perm != "HALT":
        perm = "BLOCK"

    st = _pick_score_type(dh, risk_01)

    payload: Dict[str, Any] = {
        "trade_permission": perm,
        "alpha_score": float(alpha_01),
        "risk_score": float(risk_01),
        "confidence": float(conf),
        "data_health": float(dh),
        "event_ts": float(ts),
        "half_life_ms": int(half_life_ms),
        "score_type": st,
        "phase": "16",
        "source": "social_signal",
        "social": {
            "composite_sentiment": float(composite),
            "platform_sentiments": {k: platforms[k] for k in ("twitter", "reddit", "telegram")},
            "mention_momentum": float(mom_01),
            "mention_change": mom_raw,
            "engagement_rate": float(engagement),
            "sentiment_trend": trend,
            "hype_cycle_stage": stage,
        },
    }

    if kol_sig is not None:
        payload["social"]["kol"] = kol_sig.to_dict()

    if attach_to_analysis:
        attach_phase_alias(a, "16", payload)

    return payload


def _deep_kol_analysis(d: Dict[str, Any], symbol: str, now_ms: float) -> Any:
    """PROMPT-4.1 — KOL tweet konsensüsü. İlgili veri yoksa None.

    Girdi: ``kol`` alt dict (``tweets`` listesi + opsiyonel ``token``,
    ``timing_events``, ``window_hours``) veya düz ``kol_tweets`` listesi.
    """
    block = d.get("kol") if isinstance(d.get("kol"), dict) else {}
    tweets = block.get("tweets")
    if not isinstance(tweets, list):
        tweets = d.get("kol_tweets")
    if not isinstance(tweets, list) or not tweets:
        return None

    token = block.get("token") or d.get("kol_token") or symbol
    timing_events = block.get("timing_events") or d.get("kol_timing_events")
    try:
        window_hours = float(block.get("window_hours", 24.0))
    except (TypeError, ValueError):
        window_hours = 24.0

    try:
        from super_otonom.signals.kol_tracker import analyze_kol

        return analyze_kol(
            tweets,
            token,
            now_ms=now_ms,
            window_hours=window_hours,
            timing_events=timing_events,
        )
    except Exception:  # KOL analizi asla Faz 16'yı bozmamalı
        log.debug("kol analiz hata", exc_info=True)
        return None


def run_social_signal_phase(
    symbol: str,
    social_data: Any,
    analysis: Optional[Dict[str, Any]] = None,
    *,
    attach_to_analysis: bool = True,
    half_life_ms: int = 48_000,
    event_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """Pipeline girişi — `analyze_social_signal` ile aynı."""
    return analyze_social_signal(
        symbol,
        social_data,
        analysis,
        attach_to_analysis=attach_to_analysis,
        half_life_ms=half_life_ms,
        event_ts=event_ts,
    )


def _empty_phase16(ts: int, half_life_ms: int, reason: str) -> Dict[str, Any]:
    return {
        "trade_permission": "BLOCK",
        "alpha_score": 0.0,
        "risk_score": 1.0,
        "confidence": 0.0,
        "data_health": 0.0,
        "event_ts": float(ts),
        "half_life_ms": int(half_life_ms),
        "score_type": "QUALITY",
        "phase": "16",
        "source": "social_signal",
        "empty_reason": reason,
        "social": {},
    }
