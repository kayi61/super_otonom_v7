"""
Faz 23 — Haber / olay zekâsı (makro, listing, unlock, güvenlik, NLP proxy).

Girdi `news_data` (esnek dict):
- headline, summary / body / text
- published_at_ms | published_ts_ms | event_ts (ms veya saniye)
- categories | tags | event_type (liste veya string)
- flags: is_exchange_listing, is_token_unlock, is_hack_or_exploit
- hours_until_unlock | unlock_in_hours
- nlp_sentiment | sentiment_score (-1…1 veya 0…1, opsiyonel önceden hesap)

Metin: deterministik anahtar kelime skoru (harici NLP API yok).

Çıktı Faz 16/17/18 ile uyumlu; phase23 / faz23.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Literal, Optional, Set

from super_otonom.standard_phase_output import attach_phase_alias

ScoreType = Literal["ALPHA", "RISK", "QUALITY"]
TradePermission = Literal["ALLOW", "BLOCK", "HALT"]

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


def _normalize_news(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return dict(raw)


def _combined_text(d: Dict[str, Any]) -> str:
    parts: List[str] = []
    for k in ("headline", "title", "summary", "body", "text", "description"):
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
    return " \n ".join(parts).lower()


_HACK_PATTERNS = (
    r"\bhack(ed|ing|er)?\b",
    r"\bexploit\b",
    r"\bsecurity breach\b",
    r"\bbridge exploit\b",
    r"\brug\s*(pull)?\b",
    r"\bdrained\b",
    r"\bcompromised\b",
)
_UNLOCK_HINT = re.compile(
    r"\b(token unlock|vesting unlock|cliff unlock|emission|circulating supply unlock)\b",
    re.I,
)
_LISTING_HINT = re.compile(
    r"\b(listing|listed on|new pair|spot listing|perp listing|launch on)\b",
    re.I,
)
_MACRO_FED_CPI = re.compile(
    r"\b(fed|fomc|cpi|inflation|interest rate|macro|nfp|jobs report)\b",
    re.I,
)


def _regex_any(text: str, patterns: tuple) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


def _flag_truthy(d: Dict[str, Any], *keys: str) -> bool:
    for k in keys:
        v = d.get(k)
        if v is True:
            return True
        if isinstance(v, (int, float)) and float(v) != 0.0:
            return True
        if isinstance(v, str) and v.strip().lower() in ("1", "true", "yes", "on"):
            return True
    return False


def _published_ms(d: Dict[str, Any]) -> Optional[float]:
    v = _get_num(
        d,
        "published_at_ms",
        "published_ts_ms",
        "event_ts_ms",
        "news_ts_ms",
    )
    if v is not None:
        return float(v)
    vs = _get_num(d, "published_at", "published_ts", "event_ts")
    if vs is None:
        return None
    x = float(vs)
    if x < 1e11:
        return x * 1000.0
    return x


def _news_age_hours(published_ms: Optional[float]) -> Optional[float]:
    if published_ms is None:
        return None
    return max(0.0, (_now_ms() - float(published_ms)) / 3_600_000.0)


def _hours_until_unlock(d: Dict[str, Any]) -> Optional[float]:
    h = _get_num(d, "hours_until_unlock", "unlock_in_hours", "hours_to_unlock")
    if h is not None:
        return float(h)
    unlock_ts = _get_num(d, "unlock_at_ms", "token_unlock_ts_ms")
    if unlock_ts is None:
        return None
    ut = float(unlock_ts)
    if ut < 1e11:
        ut *= 1000.0
    rem_ms = ut - _now_ms()
    if rem_ms <= 0:
        return 0.0
    return rem_ms / 3_600_000.0


def _nlp_keyword_sentiment(text: str) -> float:
    """
    Basit polarite [-1, 1]: pozitif / negatif anahtar kelime dengesi.
    Hack/listing/makro ayrı katmanlarda işlenir.
    """
    if not text.strip():
        return 0.0
    pos = sum(
        text.count(w)
        for w in (
            "bullish",
            "approval",
            "partnership",
            "upgrade",
            "growth",
            "beat",
            "surge",
            "adoption",
            "launch",
            "breakthrough",
        )
    )
    neg = sum(
        text.count(w)
        for w in (
            "bearish",
            "lawsuit",
            "ban",
            "crackdown",
            "selloff",
            "collapse",
            "default",
            "bankruptcy",
            "sec charges",
            "investigation",
        )
    )
    tot = pos + neg + 3
    return max(-1.0, min(1.0, (pos - neg) / float(tot)))


def _nlp_sentiment_01(d: Dict[str, Any], text: str) -> float:
    raw = _get_num(d, "nlp_sentiment", "sentiment_score", "news_sentiment")
    if raw is not None:
        x = float(raw)
        if -1.0 <= x <= 1.0:
            return _clamp01((x + 1.0) / 2.0)
        if 0.0 <= x <= 1.0:
            return _clamp01(x)
        return _clamp01(x / 100.0)
    kw = _nlp_keyword_sentiment(text)
    return _clamp01((kw + 1.0) / 2.0)


def _macro_risk_score(text: str, categories: Set[str]) -> float:
    hit = bool(_MACRO_FED_CPI.search(text)) or bool(
        categories & {"fed", "cpi", "macro", "fomc", "inflation"}
    )
    return 0.72 if hit else 0.22


def _categories_set(d: Dict[str, Any]) -> Set[str]:
    out: Set[str] = set()
    for key in ("categories", "tags", "event_type", "kind"):
        v = d.get(key)
        if isinstance(v, str):
            out.update(x.strip().lower() for x in v.replace(",", " ").split() if x.strip())
        elif isinstance(v, list):
            for x in v:
                if isinstance(x, str):
                    out.add(x.strip().lower())
    return out


def _freshness_confidence_factor(age_h: Optional[float]) -> float:
    """Eski haber → güven düşer."""
    if age_h is None:
        return 0.82
    if age_h <= 0.5:
        return 1.0
    return _clamp01(1.0 - min(0.88, age_h / 120.0))


def _half_life_from_freshness(age_h: Optional[float], base_ms: int) -> int:
    """Taze haber daha uzun yarı ömür; stale → kısa."""
    if age_h is None:
        return int(base_ms)
    if age_h <= 2.0:
        return int(min(base_ms, 72_000))
    if age_h <= 24.0:
        return int(base_ms)
    if age_h <= 72.0:
        return max(10_000, int(base_ms * 0.55))
    return max(6_000, int(base_ms * 0.35))


def analyze_news_event(
    symbol: str,
    news_data: Any,
    analysis: Optional[Dict[str, Any]] = None,
    *,
    attach_to_analysis: bool = True,
    half_life_ms: int = 48_000,
    event_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Haber olaylarını skorlar; `analysis['phase23']` / `['faz23']` yazar.
    """
    _ = symbol
    a = analysis if analysis is not None else {}
    ts = int(event_ts) if event_ts is not None else _try_ts_ms(a)
    d = _normalize_news(news_data)

    if not d:
        payload = _empty_phase23(ts, half_life_ms, "no_news_data")
        if attach_to_analysis:
            attach_phase_alias(a, "23", payload)
        return payload

    text = _combined_text(d)
    if not text.strip():
        payload = _empty_phase23(ts, half_life_ms, "no_headline_or_text")
        if attach_to_analysis:
            attach_phase_alias(a, "23", payload)
        return payload

    cats = _categories_set(d)
    pub_ms = _published_ms(d)
    age_h = _news_age_hours(pub_ms)
    hu_unlock = _hours_until_unlock(d)

    hack_txt = _regex_any(text, _HACK_PATTERNS) or _flag_truthy(
        d, "is_hack_or_exploit", "is_hack", "is_exploit", "security_incident"
    )
    hack_cat = bool(cats & {"hack", "exploit", "breach", "security"})

    listing = (
        _flag_truthy(d, "is_exchange_listing", "listing", "is_listing")
        or bool(_LISTING_HINT.search(text))
        or bool(cats & {"listing", "exchange_listing", "new_listing"})
    )

    unlock_story = (
        _flag_truthy(d, "is_token_unlock", "token_unlock")
        or bool(_UNLOCK_HINT.search(text))
        or bool(cats & {"unlock", "token_unlock", "vesting"})
    )

    sent_01 = _nlp_sentiment_01(d, text)
    macro_r = _macro_risk_score(text, cats)

    unlock_risk = 0.25
    if hu_unlock is not None:
        if 0 < hu_unlock <= 72.0:
            unlock_risk = _clamp01(1.0 - hu_unlock / 96.0)
        elif unlock_story and hu_unlock is None:
            unlock_risk = 0.55

    listing_boost = 0.72 if listing else 0.0

    signal_hint = str(a.get("signal", "HOLD")).upper()
    alpha_01 = _clamp01(
        0.42 * sent_01
        + 0.28 * listing_boost
        + 0.12 * (1.0 - macro_r * 0.35)
        + 0.18 * (0.55 if signal_hint == "BUY" and listing else sent_01)
    )
    if listing:
        alpha_01 = _clamp01(alpha_01 + 0.14)

    risk_01 = _clamp01(
        0.30 * macro_r
        + 0.35 * unlock_risk
        + 0.22 * (1.0 - sent_01)
        + 0.13 * (1.0 if hack_txt or hack_cat else 0.35)
    )

    stale_f = _freshness_confidence_factor(age_h)
    base_conf = _clamp01(0.26 + 0.55 * sent_01 + 0.14 * (1.0 - macro_r * 0.3))
    conf = _clamp01(base_conf * stale_f)

    dh = _clamp01(0.30 + 0.35 * stale_f + 0.20 * (1.0 if pub_ms else 0.0) + 0.15 * sent_01)

    eff_half_life = _half_life_from_freshness(age_h, half_life_ms)

    perm: TradePermission = "ALLOW"
    if hack_txt or hack_cat:
        perm = "HALT"
    elif hu_unlock is not None and 0 < hu_unlock <= 72.0:
        perm = "BLOCK"
    elif unlock_story and hu_unlock is not None and hu_unlock <= 96.0:
        perm = "BLOCK"
    elif risk_01 >= 0.88:
        perm = "BLOCK"
    elif risk_01 >= 0.72:
        perm = "BLOCK"

    st = _pick_score_type(dh, risk_01)

    payload: Dict[str, Any] = {
        "trade_permission": perm,
        "alpha_score": float(alpha_01),
        "risk_score": float(risk_01),
        "confidence": float(conf),
        "data_health": float(dh),
        "event_ts": float(ts),
        "half_life_ms": int(eff_half_life),
        "score_type": st,
        "phase": "23",
        "source": "news_event_intelligence",
        "news": {
            "nlp_sentiment_01": float(sent_01),
            "macro_event_risk": float(macro_r),
            "exchange_listing_detected": bool(listing),
            "token_unlock_story": bool(unlock_story),
            "hours_until_unlock": hu_unlock,
            "unlock_proximity_risk": float(unlock_risk),
            "hack_or_exploit_flag": bool(hack_txt or hack_cat),
            "news_age_hours": age_h,
            "published_ts_ms": pub_ms,
            "freshness_confidence_factor": float(stale_f),
            "categories": sorted(cats),
        },
    }

    if attach_to_analysis:
        attach_phase_alias(a, "23", payload)

    return payload


def run_news_event_phase(
    symbol: str,
    news_data: Any,
    analysis: Optional[Dict[str, Any]] = None,
    *,
    attach_to_analysis: bool = True,
    half_life_ms: int = 48_000,
    event_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """Pipeline girişi — `analyze_news_event` ile aynı."""
    return analyze_news_event(
        symbol,
        news_data,
        analysis,
        attach_to_analysis=attach_to_analysis,
        half_life_ms=half_life_ms,
        event_ts=event_ts,
    )


def _empty_phase23(ts: int, half_life_ms: int, reason: str) -> Dict[str, Any]:
    return {
        "trade_permission": "BLOCK",
        "alpha_score": 0.0,
        "risk_score": 1.0,
        "confidence": 0.0,
        "data_health": 0.0,
        "event_ts": float(ts),
        "half_life_ms": int(half_life_ms),
        "score_type": "QUALITY",
        "phase": "23",
        "source": "news_event_intelligence",
        "empty_reason": reason,
        "news": {},
    }
