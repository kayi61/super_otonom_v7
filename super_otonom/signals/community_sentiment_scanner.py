"""PROMPT-4.2 — Reddit & Telegram Community Sentiment Scanner — Faz 16 feed.

Reddit ve Telegram kripto topluluklarını + Fear & Greed + Google Trends sinyallerini
tarar; `social_signal` (Faz 16) ve `sentiment_layer` analizlerini zenginleştirir.

1. **Reddit**: r/cryptocurrency, r/bitcoin, r/ethereum, r/altcoin — mention spike,
   upvote momentum, comment sentiment (bullish/bearish keyword), award anomalisi.
2. **Telegram**: büyük grup mesaj frekansı, FOMO ("pump"/"moon"/"buy now") ve
   FUD ("scam"/"dump"/"rug") keyword'leri, bot mesaj oranı (manipülasyon tespiti).
3. **Fear & Greed**: Alternative.me F&G Index (ücretsiz), 7/30g trend, Extreme Fear
   (<20) → contrarian buy, Extreme Greed (>80) → risk azaltma. F&G + whale birikim
   birlikte → güçlü sinyal.
4. **Google Trends**: "bitcoin"/"crypto"/"buy bitcoin" arama trendi — ani spike →
   retail FOMO (geç girişçiler), düşük ilgi + düşük fiyat → birikim bölgesi.

Kaynaklar: Reddit/Telegram (enjekte edilebilir veri), Alternative.me F&G API
(enjekte edilebilir ``http_get``), Google Trends (pytrends-tarzı seri).
Analiz fonksiyonları saftır (ağsız test edilir).
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

log = logging.getLogger("super_otonom.community")

HttpGet = Callable[[str, float], Optional[str]]

# Sentiment etiketleri
BULLISH = "bullish"
BEARISH = "bearish"
NEUTRAL = "neutral"

# Fear & Greed sınıfları
EXTREME_FEAR = "extreme_fear"
FEAR = "fear"
FNG_NEUTRAL = "neutral"
GREED = "greed"
EXTREME_GREED = "extreme_greed"

FNG_EXTREME_FEAR_MAX = 20.0    # < → extreme fear (contrarian buy)
FNG_FEAR_MAX = 40.0
FNG_GREED_MIN = 60.0
FNG_EXTREME_GREED_MIN = 80.0   # > → extreme greed (risk azaltma)

# Contrarian sinyal etiketleri
SIGNAL_BUY = "contrarian_buy"
SIGNAL_REDUCE = "reduce_risk"
SIGNAL_NEUTRAL = "neutral"

DEFAULT_SUBREDDITS = ("cryptocurrency", "bitcoin", "ethereum", "altcoin")

# Keyword sözlükleri
_FOMO_TERMS = (
    "pump", "moon", "mooning", "buy now", "lambo", "ath", "fomo", "100x", "1000x",
    "send it", "ape in", "aping", "breakout", "parabolic", "next gem", "easy money",
    "gonna pump", "to the moon", "lfg", "dont miss", "last chance",
)
_FUD_TERMS = (
    "scam", "dump", "dumping", "rug", "rugpull", "rug pull", "crash", "dead coin",
    "exit", "ponzi", "avoid", "selloff", "sell off", "capitulate", "capitulation",
    "bagholder", "rekt", "panic", "ban", "hack", "exploit",
)
_BULL_TERMS = (
    "bullish", "buy", "buying", "accumulate", "long", "moon", "undervalued", "hodl",
    "hold", "breakout", "support", "up only", "bottom", "bid",
)
_BEAR_TERMS = (
    "bearish", "sell", "selling", "short", "dump", "crash", "scam", "overvalued",
    "resistance", "exit", "rug", "top", "down", "rekt",
)

_WORD_RE = re.compile(r"[a-z0-9']+")
_EPS = 1e-9


def _coerce_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else float(x)


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _default_http_get(url: str, timeout: float) -> Optional[str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "super_otonom/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        log.debug("community http_get hata (%s): %s", url[:60], exc)
        return None


def _spike_ratio(current: Optional[float], baseline: Optional[float]) -> float:
    """current/baseline → 0..1 spike skoru (tanh ile yumuşatılmış)."""
    cur = _coerce_float(current)
    base = _coerce_float(baseline)
    if cur is None or cur <= 0:
        return 0.0
    if base is None or base <= _EPS:
        return 1.0 if cur > 0 else 0.0
    ratio = cur / base
    return _clamp01(math.tanh(max(0.0, ratio - 1.0) / 2.0))


def _keyword_fraction(texts: Sequence[str], terms: Sequence[str]) -> float:
    """terms'ten en az birini içeren metinlerin oranı (0..1)."""
    if not texts:
        return 0.0
    hit = 0
    for t in texts:
        if not isinstance(t, str):
            continue
        low = t.lower()
        if any(kw in low for kw in terms):
            hit += 1
    return _clamp01(hit / len(texts))


def _text_sentiment(texts: Sequence[str]) -> float:
    """Bullish/bearish keyword sayımı → -1..1."""
    if not texts:
        return 0.0
    bull = 0
    bear = 0
    for t in texts:
        if not isinstance(t, str):
            continue
        low = t.lower()
        bull += sum(1 for kw in _BULL_TERMS if kw in low)
        bear += sum(1 for kw in _BEAR_TERMS if kw in low)
    total = bull + bear
    if total == 0:
        return 0.0
    return float(_clamp((bull - bear) / total, -1.0, 1.0))


# ── 1) Reddit ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RedditAnalysis:
    mention_spike: float        # 0..1 (mention patlaması)
    upvote_momentum: float      # 0..1 (hızlı yükselen postlar)
    comment_sentiment: float    # -1..1
    award_anomaly: float        # 0..1 (award sayısı anomalisi)
    heat: float                 # 0..1 (genel topluluk ısısı)
    sentiment: float            # -1..1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mention_spike": self.mention_spike,
            "upvote_momentum": self.upvote_momentum,
            "comment_sentiment": self.comment_sentiment,
            "award_anomaly": self.award_anomaly,
            "heat": self.heat,
            "sentiment": self.sentiment,
        }


def analyze_reddit(
    *,
    mention_count: Optional[float] = None,
    mention_baseline: Optional[float] = None,
    upvote_velocity: Optional[float] = None,
    comment_texts: Optional[Sequence[str]] = None,
    award_count: Optional[float] = None,
    award_baseline: Optional[float] = None,
) -> RedditAnalysis:
    """Reddit mention spike + upvote momentum + comment sentiment + award anomalisi."""
    spike = _spike_ratio(mention_count, mention_baseline)
    upv = _clamp01(math.tanh((_coerce_float(upvote_velocity) or 0.0) / 500.0))
    sent = _text_sentiment(comment_texts or [])
    award = _spike_ratio(award_count, award_baseline)
    heat = _clamp01(0.4 * spike + 0.3 * upv + 0.3 * award)
    return RedditAnalysis(
        mention_spike=float(spike),
        upvote_momentum=float(upv),
        comment_sentiment=float(sent),
        award_anomaly=float(award),
        heat=float(heat),
        sentiment=float(sent),
    )


# ── 2) Telegram ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TelegramAnalysis:
    freq_spike: float           # 0..1 (mesaj frekansı patlaması)
    fomo_score: float           # 0..1 (FOMO keyword oranı)
    fud_score: float            # 0..1 (FUD keyword oranı)
    bot_ratio: float            # 0..1 (bot mesaj oranı)
    manipulation_risk: float    # 0..1 (yüksek bot + FOMO → pump şüphesi)
    sentiment: float            # -1..1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "freq_spike": self.freq_spike,
            "fomo_score": self.fomo_score,
            "fud_score": self.fud_score,
            "bot_ratio": self.bot_ratio,
            "manipulation_risk": self.manipulation_risk,
            "sentiment": self.sentiment,
        }


def analyze_telegram(
    *,
    message_count: Optional[float] = None,
    message_baseline: Optional[float] = None,
    message_texts: Optional[Sequence[str]] = None,
    bot_ratio: Optional[float] = None,
) -> TelegramAnalysis:
    """Telegram mesaj frekansı + FOMO/FUD keyword + bot oranı (manipülasyon)."""
    spike = _spike_ratio(message_count, message_baseline)
    texts = message_texts or []
    fomo = _keyword_fraction(texts, _FOMO_TERMS)
    fud = _keyword_fraction(texts, _FUD_TERMS)
    bot = _clamp01(_coerce_float(bot_ratio) or 0.0)
    # FOMO bullish ama bot oranı yüksekse manipülasyon (pump) şüphesi
    manip = _clamp01(0.6 * bot + 0.4 * fomo)
    sentiment = float(_clamp(fomo - fud, -1.0, 1.0))
    return TelegramAnalysis(
        freq_spike=float(spike),
        fomo_score=float(fomo),
        fud_score=float(fud),
        bot_ratio=float(bot),
        manipulation_risk=float(manip),
        sentiment=sentiment,
    )


# ── 3) Fear & Greed ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FearGreedAnalysis:
    value: float                # 0..100
    classification: str         # extreme_fear..extreme_greed
    trend_7d: float             # value - 7g ort
    trend_30d: float            # value - 30g ort
    contrarian_signal: str      # contrarian_buy | reduce_risk | neutral
    bias: float                 # -1..1 (extreme fear → +, extreme greed → -)
    risk_score: float           # 0..1 (extreme greed → yüksek)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "value": self.value,
            "classification": self.classification,
            "trend_7d": self.trend_7d,
            "trend_30d": self.trend_30d,
            "contrarian_signal": self.contrarian_signal,
            "bias": self.bias,
            "risk_score": self.risk_score,
        }


def classify_fng(value: float) -> str:
    if value < FNG_EXTREME_FEAR_MAX:
        return EXTREME_FEAR
    if value < FNG_FEAR_MAX:
        return FEAR
    if value > FNG_EXTREME_GREED_MIN:
        return EXTREME_GREED
    if value > FNG_GREED_MIN:
        return GREED
    return FNG_NEUTRAL


def analyze_fear_greed(
    value: Optional[float] = None,
    *,
    history_7d: Optional[Sequence[float]] = None,
    history_30d: Optional[Sequence[float]] = None,
) -> Optional[FearGreedAnalysis]:
    """Alternative.me F&G değeri (0..100) → contrarian bias + trend. Veri yoksa None."""
    v = _coerce_float(value)
    if v is None:
        return None
    v = _clamp(v, 0.0, 100.0)
    cls = classify_fng(v)

    def _trend(hist: Optional[Sequence[float]]) -> float:
        vals = [_coerce_float(x) for x in (hist or [])]
        vals = [x for x in vals if x is not None]
        return float(v - sum(vals) / len(vals)) if vals else 0.0

    t7 = _trend(history_7d)
    t30 = _trend(history_30d)

    # Contrarian: extreme fear → +bias (buy), extreme greed → -bias (reduce)
    if cls == EXTREME_FEAR:
        bias = _clamp01((FNG_EXTREME_FEAR_MAX - v) / FNG_EXTREME_FEAR_MAX)
        signal = SIGNAL_BUY
        risk = 0.25
    elif cls == EXTREME_GREED:
        bias = -_clamp01((v - FNG_EXTREME_GREED_MIN) / (100.0 - FNG_EXTREME_GREED_MIN))
        signal = SIGNAL_REDUCE
        risk = _clamp(0.5 + 0.5 * (v - FNG_EXTREME_GREED_MIN) / (100.0 - FNG_EXTREME_GREED_MIN), 0.5, 1.0)
    else:
        # ara bölge: hafif contrarian (50 ekseni)
        bias = _clamp((50.0 - v) / 100.0 * 0.6, -0.4, 0.4)
        signal = SIGNAL_NEUTRAL
        risk = _clamp01(0.3 + 0.3 * (v - 50.0) / 50.0) if v > 50.0 else 0.15

    return FearGreedAnalysis(
        value=float(v),
        classification=cls,
        trend_7d=float(t7),
        trend_30d=float(t30),
        contrarian_signal=signal,
        bias=float(bias),
        risk_score=float(_clamp01(risk)),
    )


def parse_alternative_me(payload: Any) -> Optional[Dict[str, Any]]:
    """Alternative.me ``/fng/`` JSON → {value, classification, history}.

    ``{"data": [{"value": "15", "value_classification": "Extreme Fear", ...}, ...]}``
    (data[0] en güncel).
    """
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", errors="replace")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return None
    if not isinstance(payload, dict):
        return None
    rows = payload.get("data")
    if not isinstance(rows, list) or not rows:
        return None
    vals: List[float] = []
    for r in rows:
        if isinstance(r, dict):
            fv = _coerce_float(r.get("value"))
            if fv is not None:
                vals.append(fv)
    if not vals:
        return None
    return {
        "value": vals[0],
        "history_7d": vals[:7],
        "history_30d": vals[:30],
    }


# ── 4) Google Trends ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TrendsAnalysis:
    interest: float             # 0..100 (mevcut arama ilgisi)
    spike: float                # 0..1 (ani yükseliş → retail FOMO)
    retail_fomo: bool           # geç girişçi FOMO başlangıcı
    accumulation_zone: bool     # düşük ilgi + düşük fiyat → birikim
    bias: float                 # -1..1 (spike → -, birikim → +)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "interest": self.interest,
            "spike": self.spike,
            "retail_fomo": self.retail_fomo,
            "accumulation_zone": self.accumulation_zone,
            "bias": self.bias,
        }


def analyze_google_trends(
    *,
    interest: Optional[float] = None,
    interest_baseline: Optional[float] = None,
    price_low: bool = False,
) -> Optional[TrendsAnalysis]:
    """Arama ilgisi → retail FOMO spike veya birikim bölgesi. Veri yoksa None."""
    cur = _coerce_float(interest)
    if cur is None:
        return None
    spike = _spike_ratio(cur, interest_baseline)
    base = _coerce_float(interest_baseline)
    low_interest = base is not None and base > _EPS and cur < 0.7 * base

    retail_fomo = spike >= 0.6
    accumulation = bool(low_interest and price_low)

    bias = 0.0
    if retail_fomo:
        bias -= 0.5 * spike      # geç girişçi → contrarian negatif
    if accumulation:
        bias += 0.4              # düşük ilgi + düşük fiyat → birikim fırsatı
    return TrendsAnalysis(
        interest=float(_clamp(cur, 0.0, 100.0)),
        spike=float(spike),
        retail_fomo=bool(retail_fomo),
        accumulation_zone=accumulation,
        bias=float(_clamp(bias, -1.0, 1.0)),
    )


# ── Birleşik analiz ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CommunitySignal:
    reddit: Optional[RedditAnalysis]
    telegram: Optional[TelegramAnalysis]
    fear_greed: Optional[FearGreedAnalysis]
    trends: Optional[TrendsAnalysis]
    sentiment: float            # -1..1 (birleşik)
    alpha_bias: float           # -1..1
    risk_score: float           # 0..1
    manipulation_risk: float    # 0..1
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "community_sentiment": self.sentiment,
            "community_alpha_bias": self.alpha_bias,
            "community_risk_score": self.risk_score,
            "manipulation_risk": self.manipulation_risk,
            "community_reasons": list(self.reasons),
        }
        if self.reddit is not None:
            out["reddit"] = self.reddit.to_dict()
        if self.telegram is not None:
            out["telegram"] = self.telegram.to_dict()
        if self.fear_greed is not None:
            out["fear_greed"] = self.fear_greed.to_dict()
        if self.trends is not None:
            out["google_trends"] = self.trends.to_dict()
        return out


def analyze_community(
    *,
    reddit: Optional[RedditAnalysis] = None,
    telegram: Optional[TelegramAnalysis] = None,
    fear_greed: Optional[FearGreedAnalysis] = None,
    trends: Optional[TrendsAnalysis] = None,
    whale_accumulation: Optional[float] = None,
) -> Optional[CommunitySignal]:
    """Tüm topluluk sinyallerini sentiment + alpha bias + risk'e indirger. Veri yoksa None."""
    if reddit is None and telegram is None and fear_greed is None and trends is None:
        return None

    reasons: List[str] = []
    sent_parts: List[float] = []
    alpha = 0.0
    risk = 0.0
    manip = 0.0

    if reddit is not None:
        sent_parts.append(reddit.sentiment)
        alpha += 0.25 * reddit.sentiment
        if reddit.mention_spike > 0.7:
            reasons.append(f"Reddit mention patlaması ({reddit.mention_spike:.2f})")
            risk = max(risk, 0.3 * reddit.mention_spike)

    if telegram is not None:
        sent_parts.append(telegram.sentiment)
        alpha += 0.2 * telegram.sentiment
        manip = max(manip, telegram.manipulation_risk)
        if telegram.manipulation_risk > 0.6:
            reasons.append(f"Telegram manipülasyon şüphesi (bot/FOMO {telegram.manipulation_risk:.2f})")
            risk = max(risk, telegram.manipulation_risk)
            alpha -= 0.15 * telegram.fomo_score  # pump FOMO → contrarian temkin
        if telegram.fud_score > 0.5:
            reasons.append(f"Telegram FUD yoğun ({telegram.fud_score:.2f})")

    if fear_greed is not None:
        sent_parts.append(fear_greed.bias)
        alpha += 0.4 * fear_greed.bias
        risk = max(risk, fear_greed.risk_score)
        if fear_greed.classification == EXTREME_FEAR:
            reasons.append(f"Extreme Fear (F&G {fear_greed.value:.0f}) → contrarian buy")
        elif fear_greed.classification == EXTREME_GREED:
            reasons.append(f"Extreme Greed (F&G {fear_greed.value:.0f}) → risk azaltma")

    if trends is not None:
        sent_parts.append(trends.bias)
        alpha += 0.2 * trends.bias
        if trends.retail_fomo:
            reasons.append(f"Google Trends spike → retail FOMO (geç girişçi, {trends.spike:.2f})")
            risk = max(risk, 0.3 + 0.3 * trends.spike)
        if trends.accumulation_zone:
            reasons.append("Düşük arama ilgisi + düşük fiyat → birikim bölgesi")

    # F&G + whale birikim birlikte → güçlü sinyal
    wacc = _clamp01(_coerce_float(whale_accumulation) or 0.0)
    if fear_greed is not None and wacc > 0.5 and fear_greed.classification in (EXTREME_FEAR, FEAR):
        boost = 0.25 * wacc
        alpha = _clamp(alpha + boost, -1.0, 1.0)
        reasons.append(f"Fear + whale birikim ({wacc:.2f}) → güçlü contrarian buy")

    sentiment = float(sum(sent_parts) / len(sent_parts)) if sent_parts else 0.0
    return CommunitySignal(
        reddit=reddit,
        telegram=telegram,
        fear_greed=fear_greed,
        trends=trends,
        sentiment=sentiment,
        alpha_bias=float(_clamp(alpha, -1.0, 1.0)),
        risk_score=float(_clamp01(risk)),
        manipulation_risk=float(manip),
        reasons=reasons,
    )


def analyze_community_data(data: Dict[str, Any]) -> Optional[CommunitySignal]:
    """Düz dict girdiden topluluk sinyali üretir (social_signal köprüsü).

    Beklenen (hepsi opsiyonel): ``reddit`` / ``telegram`` / ``fear_greed`` /
    ``google_trends`` alt dict'leri + ``whale_accumulation``.
    """
    if not isinstance(data, dict):
        return None

    rd = data.get("reddit")
    reddit = analyze_reddit(**_pick(rd, (
        "mention_count", "mention_baseline", "upvote_velocity",
        "comment_texts", "award_count", "award_baseline",
    ))) if isinstance(rd, dict) and rd else None

    tg = data.get("telegram")
    telegram = analyze_telegram(**_pick(tg, (
        "message_count", "message_baseline", "message_texts", "bot_ratio",
    ))) if isinstance(tg, dict) and tg else None

    fg = data.get("fear_greed", data.get("fng"))
    fear_greed = None
    if isinstance(fg, dict) and fg:
        fear_greed = analyze_fear_greed(
            fg.get("value"),
            history_7d=fg.get("history_7d"),
            history_30d=fg.get("history_30d"),
        )
    elif _coerce_float(fg) is not None:
        fear_greed = analyze_fear_greed(fg)

    gt = data.get("google_trends", data.get("trends"))
    trends = analyze_google_trends(**_pick(gt, (
        "interest", "interest_baseline", "price_low",
    ))) if isinstance(gt, dict) and gt else None

    return analyze_community(
        reddit=reddit,
        telegram=telegram,
        fear_greed=fear_greed,
        trends=trends,
        whale_accumulation=data.get("whale_accumulation"),
    )


def _pick(d: Any, keys: Sequence[str]) -> Dict[str, Any]:
    """Dict'ten yalnızca verilen anahtarları (None olmayan) seçer."""
    if not isinstance(d, dict):
        return {}
    return {k: d[k] for k in keys if k in d and d[k] is not None}


# ── Collector ────────────────────────────────────────────────────────────────


class CommunityCollector:
    """Alternative.me F&G toplayıcı (ücretsiz, key'siz; mock'lanabilir)."""

    def __init__(self, *, http_get: Optional[HttpGet] = None, timeout_sec: float = 5.0) -> None:
        self._http_get: HttpGet = http_get or _default_http_get
        self._timeout = float(timeout_sec)

    def fetch_fear_greed(self, *, limit: int = 30) -> Optional[Dict[str, Any]]:
        base = os.getenv("FEAR_GREED_API_URL", "https://api.alternative.me/fng/")
        sep = "&" if "?" in base else "?"
        body = self._http_get(f"{base}{sep}limit={int(limit)}", self._timeout)
        return parse_alternative_me(body) if body else None


__all__ = [
    "BEARISH",
    "BULLISH",
    "DEFAULT_SUBREDDITS",
    "EXTREME_FEAR",
    "EXTREME_GREED",
    "FEAR",
    "FNG_NEUTRAL",
    "GREED",
    "NEUTRAL",
    "SIGNAL_BUY",
    "SIGNAL_NEUTRAL",
    "SIGNAL_REDUCE",
    "CommunityCollector",
    "CommunitySignal",
    "FearGreedAnalysis",
    "RedditAnalysis",
    "TelegramAnalysis",
    "TrendsAnalysis",
    "analyze_community",
    "analyze_community_data",
    "analyze_fear_greed",
    "analyze_google_trends",
    "analyze_reddit",
    "analyze_telegram",
    "classify_fng",
    "parse_alternative_me",
]
