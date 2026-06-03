"""PROMPT-4.1 — Twitter/X Crypto KOL Tracker — Faz 16 social feed.

Kripto KOL (Key Opinion Leader) aktivitesini takip eder; `social_signal`
(Faz 16) sentiment/hype analizini KOL konsensüsüyle zenginleştirir.

1. **KOL listesi + ağırlık**: Tier 1 (market mover) / Tier 2 (crypto native) /
   Tier 3 (analist). Her KOL geçmiş doğruluk oranına göre ağırlıklandırılır.
2. **Tweet analizi (NLP)**: cashtag tespiti ($BTC, $ETH), sentiment
   (bullish/bearish/neutral), action keyword'leri (buy/accumulate/sell/short),
   retweet/like ile engagement ağırlıklandırma.
3. **KOL consensus**: 24h içinde kaç KOL aynı token'dan bahsetti, sentiment
   ortalaması, divergence (bullish↔bearish ayrışması → belirsizlik).
4. **Timing sinyali**: KOL tweet sonrası ortalama fiyat hareketi (backtest),
   tweet↔hareket gecikmesi, "buy the rumor, sell the news" pattern tespiti.

Kaynaklar: Twitter/X API v2 veya Nitter scraping alternatifi (enjekte edilebilir
``http_get``). Analiz fonksiyonları saftır (ağsız test edilir).
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

log = logging.getLogger("super_otonom.kol")

HttpGet = Callable[[str, float], Optional[str]]

# Sentiment etiketleri
BULLISH = "bullish"
BEARISH = "bearish"
NEUTRAL = "neutral"
DIVERGENT = "divergent"

# Action keyword'leri (bias yönü)
BUY = "buy"
SELL = "sell"

# Tier taban ağırlıkları (market etkisi)
TIER1 = 1
TIER2 = 2
TIER3 = 3
_TIER_BASE_WEIGHT: Dict[int, float] = {TIER1: 1.0, TIER2: 0.7, TIER3: 0.5}

# Sentiment sözlüğü (lexicon) — kripto-native ifadeler dahil
_BULLISH_TERMS = (
    "buy", "buying", "bought", "accumulate", "accumulating", "long", "bullish",
    "moon", "mooning", "pump", "breakout", "rally", "ath", "send it", "lfg",
    "undervalued", "bottom", "support", "hodl", "gm", "up only", "bid", "load",
)
_BEARISH_TERMS = (
    "sell", "selling", "sold", "short", "shorting", "bearish", "dump", "dumping",
    "crash", "rug", "scam", "overvalued", "top", "resistance", "exit", "rekt",
    "capitulation", "down", "puke", "fade", "avoid", "liquidated",
)
# Action keyword'leri (sözlükten bağımsız net emir niyeti)
_BUY_ACTIONS = ("buy", "buying", "accumulate", "accumulating", "long", "bid", "load up", "loading")
_SELL_ACTIONS = ("sell", "selling", "short", "shorting", "exit", "dump", "take profit")

# Cashtag: $BTC, $eth, $SOL2 ... (2–10 harf/rakam, baş harf zorunlu)
_CASHTAG_RE = re.compile(r"\$([A-Za-z][A-Za-z0-9]{1,9})\b")
_WORD_RE = re.compile(r"[a-z0-9']+")

# "Buy the rumor, sell the news": tweet sonrası ilk pump, ardından geri veriş.
RUMOR_PUMP_MIN = 0.015      # ilk hareket en az +%1.5 olmalı (pump sayılması için)
RUMOR_FADE_RATIO = 0.4      # final, peak'in %40'ından düşükse → fade (sell-the-news)


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


def _norm_handle(handle: Any) -> str:
    """@CZ_Binance / https://x.com/cz_binance → 'cz_binance'."""
    s = str(handle or "").strip().lower()
    if "/" in s:
        s = s.rstrip("/").rsplit("/", 1)[-1]
    return s.lstrip("@")


def _default_http_get(url: str, timeout: float) -> Optional[str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "super_otonom/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        log.debug("kol http_get hata (%s): %s", url[:60], exc)
        return None


# ── 1) KOL listesi + ağırlıklandırma ─────────────────────────────────────────


@dataclass(frozen=True)
class KOL:
    handle: str          # normalize edilmiş (lower, @ yok)
    name: str
    tier: int            # 1 | 2 | 3
    accuracy: float      # 0..1 geçmiş doğruluk oranı

    @property
    def base_weight(self) -> float:
        return _TIER_BASE_WEIGHT.get(self.tier, 0.4)

    @property
    def weight(self) -> float:
        """Taban tier ağırlığı × doğruluk düzeltmesi (0.4..1.0 çarpan)."""
        return float(self.base_weight * (0.4 + 0.6 * _clamp01(self.accuracy)))


# Varsayılan KOL kaydı (handle → KOL). accuracy = geçmiş isabet oranı proxy.
KOL_REGISTRY: Dict[str, KOL] = {
    k.handle: k
    for k in (
        # Tier 1 — market mover
        KOL("cz_binance", "CZ", TIER1, 0.68),
        KOL("vitalikbuterin", "Vitalik Buterin", TIER1, 0.62),
        KOL("saylor", "Michael Saylor", TIER1, 0.60),
        KOL("elonmusk", "Elon Musk", TIER1, 0.55),
        # Tier 2 — crypto native
        KOL("cobie", "Cobie", TIER2, 0.66),
        KOL("hsakatrades", "Hsaka", TIER2, 0.64),
        KOL("cryptocobain", "CryptoCobain", TIER2, 0.60),
        KOL("gicantrebirth", "GCR", TIER2, 0.70),
        # Tier 3 — analist
        KOL("100trillionusd", "PlanB", TIER3, 0.52),
        KOL("woonomic", "Willy Woo", TIER3, 0.56),
        KOL("intocryptoverse", "Benjamin Cowen", TIER3, 0.58),
    )
}


def get_kol(handle: Any) -> Optional[KOL]:
    """Kayıttan KOL döndürür (handle normalize edilir); bilinmiyorsa None."""
    return KOL_REGISTRY.get(_norm_handle(handle))


def resolve_kol(handle: Any, *, default_tier: int = TIER3, default_accuracy: float = 0.5) -> KOL:
    """Bilinen KOL'u döndürür; bilinmiyorsa varsayılan ağırlıkla geçici KOL üretir."""
    known = get_kol(handle)
    if known is not None:
        return known
    h = _norm_handle(handle)
    return KOL(handle=h, name=h or "unknown", tier=default_tier, accuracy=default_accuracy)


# ── 2) Tweet analizi (NLP) ───────────────────────────────────────────────────


def parse_cashtags(text: Any) -> List[str]:
    """$BTC, $eth → ['BTC', 'ETH'] (tekilleştirilmiş, sıra korunur)."""
    if not isinstance(text, str):
        return []
    out: List[str] = []
    seen = set()
    for m in _CASHTAG_RE.finditer(text):
        tok = m.group(1).upper()
        if tok not in seen:
            seen.add(tok)
            out.append(tok)
    return out


def _token_aliases(token: str) -> Tuple[str, ...]:
    """'BTC/USDT' / 'BTCUSDT' → ('BTC', 'BITCOIN'...) eşleştirme adayları."""
    t = str(token or "").upper().replace("/", "").replace("-", "")
    for quote in ("USDT", "USDC", "USD", "BUSD", "PERP"):
        if t.endswith(quote) and len(t) > len(quote):
            t = t[: -len(quote)]
            break
    aliases = {t}
    _NAMES = {"BTC": "BITCOIN", "ETH": "ETHEREUM", "SOL": "SOLANA", "DOGE": "DOGECOIN"}
    if t in _NAMES:
        aliases.add(_NAMES[t])
    return tuple(a for a in aliases if a)


def detect_action(text: Any) -> Optional[str]:
    """Net emir niyeti: BUY | SELL | None. SELL, BUY'a göre öncelikli (risk muhafazakâr)."""
    if not isinstance(text, str):
        return None
    low = text.lower()
    has_sell = any(kw in low for kw in _SELL_ACTIONS)
    has_buy = any(kw in low for kw in _BUY_ACTIONS)
    if has_sell and not has_buy:
        return SELL
    if has_buy and not has_sell:
        return BUY
    if has_sell and has_buy:
        # "don't sell, accumulate" gibi karışık → action belirsiz
        return None
    return None


def analyze_sentiment(text: Any) -> Tuple[float, str]:
    """Lexicon tabanlı sentiment → (score [-1,1], label)."""
    if not isinstance(text, str) or not text.strip():
        return 0.0, NEUTRAL
    words = _WORD_RE.findall(text.lower())
    if not words:
        return 0.0, NEUTRAL
    wset = set(words)
    bull = sum(1 for t in _BULLISH_TERMS if t in text.lower())
    bear = sum(1 for t in _BEARISH_TERMS if t in text.lower())
    # negation: "not bullish", "no pump" → yönü çevir (basit, tek-kelime önü)
    if "not" in wset or "no" in wset or "don't" in wset:
        bull, bear = bear, bull
    total = bull + bear
    if total == 0:
        return 0.0, NEUTRAL
    score = _clamp((bull - bear) / total, -1.0, 1.0)
    label = BULLISH if score > 0.15 else BEARISH if score < -0.15 else NEUTRAL
    return float(score), label


def engagement_weight(likes: Optional[float], retweets: Optional[float]) -> float:
    """Like + 2×retweet → 0..1 (log ölçek). Retweet daha güçlü viral sinyal."""
    likes = max(0.0, _coerce_float(likes) or 0.0)
    rts = max(0.0, _coerce_float(retweets) or 0.0)
    raw = likes + 2.0 * rts
    if raw <= 0:
        return 0.0
    return _clamp01(math.log1p(raw) / math.log1p(50_000.0))


@dataclass(frozen=True)
class TweetAnalysis:
    handle: str
    tokens: List[str]
    sentiment: float            # -1..1
    sentiment_label: str        # bullish | bearish | neutral
    action: Optional[str]       # buy | sell | None
    engagement: float           # 0..1
    kol_weight: float           # KOL ağırlığı (tier × accuracy)
    influence: float            # kol_weight × (0.5 + 0.5×engagement)
    ts_ms: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "handle": self.handle,
            "tokens": list(self.tokens),
            "sentiment": self.sentiment,
            "sentiment_label": self.sentiment_label,
            "action": self.action,
            "engagement": self.engagement,
            "kol_weight": self.kol_weight,
            "influence": self.influence,
            "ts_ms": self.ts_ms,
        }


def analyze_tweet(tweet: Dict[str, Any]) -> TweetAnalysis:
    """Tek tweet dict'ini analiz eder.

    Beklenen alanlar (esnek): ``handle``/``author``/``user``, ``text``,
    ``likes``/``like_count``, ``retweets``/``retweet_count``, ``ts_ms``/``timestamp``,
    opsiyonel ``accuracy`` (KOL doğruluk override).
    """
    handle = tweet.get("handle") or tweet.get("author") or tweet.get("user") or ""
    text = tweet.get("text") or tweet.get("content") or ""
    likes = tweet.get("likes", tweet.get("like_count"))
    rts = tweet.get("retweets", tweet.get("retweet_count"))
    ts = _coerce_float(tweet.get("ts_ms", tweet.get("timestamp", tweet.get("created_ts"))))

    acc_override = _coerce_float(tweet.get("accuracy"))
    kol = resolve_kol(handle)
    if acc_override is not None:
        kol = KOL(handle=kol.handle, name=kol.name, tier=kol.tier, accuracy=_clamp01(acc_override))

    sent, label = analyze_sentiment(text)
    action = detect_action(text)
    # action net emir → sentiment'i pekiştir
    if action == BUY:
        sent = _clamp(max(sent, 0.35), -1.0, 1.0)
        label = BULLISH
    elif action == SELL:
        sent = _clamp(min(sent, -0.35), -1.0, 1.0)
        label = BEARISH

    eng = engagement_weight(likes, rts)
    influence = float(kol.weight * (0.5 + 0.5 * eng))
    return TweetAnalysis(
        handle=kol.handle,
        tokens=parse_cashtags(text),
        sentiment=float(sent),
        sentiment_label=label,
        action=action,
        engagement=float(eng),
        kol_weight=float(kol.weight),
        influence=influence,
        ts_ms=ts,
    )


# ── 3) KOL consensus ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class KolConsensus:
    token: str
    kol_count: int              # 24h içinde token'dan bahseden farklı KOL sayısı
    tweet_count: int
    avg_sentiment: float        # -1..1 (basit ortalama)
    weighted_sentiment: float   # -1..1 (influence ağırlıklı)
    divergence: float           # 0..1 (1 = tam ayrışma/belirsizlik)
    label: str                  # bullish | bearish | divergent | neutral
    bullish_kols: int
    bearish_kols: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "token": self.token,
            "kol_count": self.kol_count,
            "tweet_count": self.tweet_count,
            "avg_sentiment": self.avg_sentiment,
            "weighted_sentiment": self.weighted_sentiment,
            "divergence": self.divergence,
            "label": self.label,
            "bullish_kols": self.bullish_kols,
            "bearish_kols": self.bearish_kols,
        }


def _mentions_token(tokens: Sequence[str], token: str) -> bool:
    if not token:
        return True
    aliases = _token_aliases(token)
    up = {t.upper() for t in tokens}
    return any(a in up for a in aliases)


def compute_consensus(
    analyses: Sequence[TweetAnalysis],
    token: str,
    *,
    now_ms: Optional[float] = None,
    window_hours: float = 24.0,
) -> KolConsensus:
    """24h penceresinde token bazlı KOL konsensüsü + divergence."""
    window_ms = window_hours * 3_600_000.0
    rel: List[TweetAnalysis] = []
    for a in analyses:
        if not _mentions_token(a.tokens, token):
            continue
        if now_ms is not None and a.ts_ms is not None and (now_ms - a.ts_ms) > window_ms:
            continue
        rel.append(a)

    if not rel:
        return KolConsensus(token.upper(), 0, 0, 0.0, 0.0, 0.0, NEUTRAL, 0, 0)

    # KOL başına en güçlü (en yüksek influence) tweet'i al → spam tek KOL'u şişirmesin
    by_kol: Dict[str, TweetAnalysis] = {}
    for a in rel:
        cur = by_kol.get(a.handle)
        if cur is None or a.influence > cur.influence:
            by_kol[a.handle] = a
    uniq = list(by_kol.values())

    sentiments = [a.sentiment for a in uniq]
    avg = sum(sentiments) / len(sentiments)
    wsum = sum(a.influence for a in uniq)
    weighted = (sum(a.sentiment * a.influence for a in uniq) / wsum) if wsum > 0 else avg

    bullish = sum(1 for a in uniq if a.sentiment > 0.15)
    bearish = sum(1 for a in uniq if a.sentiment < -0.15)

    # divergence: sentiment std (yayılım) + iki kampın dengesi
    mean = avg
    var = sum((s - mean) ** 2 for s in sentiments) / len(sentiments)
    std = math.sqrt(var)
    spread = _clamp01(std)  # std ~ [0,1] aralığında (-1..1 sentiment için)
    balance = 0.0
    if (bullish + bearish) > 0:
        balance = 1.0 - abs(bullish - bearish) / (bullish + bearish)
    divergence = _clamp01(0.5 * spread + 0.5 * balance) if len(uniq) > 1 else 0.0

    if divergence >= 0.6 and bullish > 0 and bearish > 0:
        label = DIVERGENT
    elif weighted > 0.15:
        label = BULLISH
    elif weighted < -0.15:
        label = BEARISH
    else:
        label = NEUTRAL

    return KolConsensus(
        token=token.upper() if token else "",
        kol_count=len(uniq),
        tweet_count=len(rel),
        avg_sentiment=float(avg),
        weighted_sentiment=float(weighted),
        divergence=float(divergence),
        label=label,
        bullish_kols=bullish,
        bearish_kols=bearish,
    )


# ── 4) Timing sinyali (backtest) ─────────────────────────────────────────────


@dataclass(frozen=True)
class TimingSignal:
    sample_size: int
    avg_move_pct: float             # tweet sonrası ortalama hareket
    avg_lag_minutes: float          # tweet ↔ tepe hareket gecikmesi
    hit_rate: float                 # sentiment yönü ile hareket yönü uyumu (0..1)
    buy_rumor_sell_news: bool       # pump-then-fade pattern baskın mı
    rumor_fade_rate: float          # bullish event'lerde fade oranı (0..1)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sample_size": self.sample_size,
            "avg_move_pct": self.avg_move_pct,
            "avg_lag_minutes": self.avg_lag_minutes,
            "hit_rate": self.hit_rate,
            "buy_rumor_sell_news": self.buy_rumor_sell_news,
            "rumor_fade_rate": self.rumor_fade_rate,
        }


def detect_buy_rumor_sell_news(peak_pct: float, final_pct: float) -> bool:
    """Tek event: belirgin pump (peak) sonrası geri veriş → 'sell the news'."""
    if peak_pct < RUMOR_PUMP_MIN:
        return False
    return final_pct < peak_pct * RUMOR_FADE_RATIO


def backtest_kol_timing(events: Sequence[Dict[str, Any]]) -> TimingSignal:
    """KOL tweet'i sonrası fiyat tepkisini backtest eder.

    Her event (esnek alanlar):
      - ``sentiment``: -1..1 (tweet yönü)
      - ``move_pct``: tweet sonrası net hareket (örn. +0.03 = %3)
      - ``peak_pct``: pencere içi en yüksek hareket (opsiyonel; yoksa move_pct)
      - ``final_pct``: pencere sonu hareket (opsiyonel; yoksa move_pct)
      - ``lag_minutes``: tweet ↔ tepe gecikmesi (opsiyonel)
    """
    moves: List[float] = []
    lags: List[float] = []
    hits = 0
    hit_total = 0
    fade_bull = 0
    bull_events = 0

    for ev in events:
        mv = _coerce_float(ev.get("move_pct"))
        if mv is None:
            continue
        moves.append(mv)
        sent = _coerce_float(ev.get("sentiment"))
        lag = _coerce_float(ev.get("lag_minutes"))
        if lag is not None:
            lags.append(lag)
        if sent is not None and abs(sent) > 0.15:
            hit_total += 1
            if (sent > 0 and mv > 0) or (sent < 0 and mv < 0):
                hits += 1
        peak = _coerce_float(ev.get("peak_pct"))
        final = _coerce_float(ev.get("final_pct"))
        if peak is None:
            peak = mv
        if final is None:
            final = mv
        if sent is not None and sent > 0.15:
            bull_events += 1
            if detect_buy_rumor_sell_news(peak, final):
                fade_bull += 1

    if not moves:
        return TimingSignal(0, 0.0, 0.0, 0.0, False, 0.0)

    avg_move = sum(moves) / len(moves)
    avg_lag = (sum(lags) / len(lags)) if lags else 0.0
    hit_rate = (hits / hit_total) if hit_total else 0.0
    fade_rate = (fade_bull / bull_events) if bull_events else 0.0
    brsn = bull_events >= 2 and fade_rate >= 0.5

    return TimingSignal(
        sample_size=len(moves),
        avg_move_pct=float(avg_move),
        avg_lag_minutes=float(avg_lag),
        hit_rate=float(hit_rate),
        buy_rumor_sell_news=bool(brsn),
        rumor_fade_rate=float(fade_rate),
    )


# ── Birleşik analiz ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class KolSignal:
    consensus: KolConsensus
    timing: Optional[TimingSignal]
    sentiment: float            # -1..1 (consensus weighted_sentiment)
    alpha_bias: float           # -1..1
    risk_score: float           # 0..1 (divergence/aşırılık → risk)
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "kol_sentiment": self.sentiment,
            "kol_alpha_bias": self.alpha_bias,
            "kol_risk_score": self.risk_score,
            "kol_count": self.consensus.kol_count,
            "kol_divergence": self.consensus.divergence,
            "kol_label": self.consensus.label,
            "kol_reasons": list(self.reasons),
            "consensus": self.consensus.to_dict(),
        }
        if self.timing is not None:
            out["timing"] = self.timing.to_dict()
        return out


def analyze_kol(
    tweets: Sequence[Dict[str, Any]],
    token: str,
    *,
    now_ms: Optional[float] = None,
    window_hours: float = 24.0,
    timing_events: Optional[Sequence[Dict[str, Any]]] = None,
) -> Optional[KolSignal]:
    """Tweet listesi → KOL consensus + timing → alpha bias / risk. Veri yoksa None."""
    if not tweets:
        return None
    analyses = [analyze_tweet(t) for t in tweets if isinstance(t, dict)]
    if not analyses:
        return None

    cons = compute_consensus(analyses, token, now_ms=now_ms, window_hours=window_hours)
    if cons.kol_count == 0:
        return None

    timing = backtest_kol_timing(timing_events) if timing_events else None

    reasons: List[str] = []
    alpha = float(cons.weighted_sentiment)
    risk = 0.0

    # Konsensüs gücü → KOL sayısı arttıkça sinyal güveni artar (max ~1.0)
    conviction = _clamp01(cons.kol_count / 5.0)
    alpha *= 0.5 + 0.5 * conviction

    if cons.label == BULLISH:
        reasons.append(f"{cons.kol_count} KOL bullish konsensüs ({cons.weighted_sentiment:.2f})")
    elif cons.label == BEARISH:
        reasons.append(f"{cons.kol_count} KOL bearish konsensüs ({cons.weighted_sentiment:.2f})")
        risk = max(risk, 0.3 + 0.4 * conviction)
    elif cons.label == DIVERGENT:
        reasons.append(f"KOL ayrışması (divergence {cons.divergence:.2f}) → belirsizlik")
        risk = max(risk, 0.45)
        alpha *= 0.4  # belirsizlikte konviksiyonu kıs

    # Divergence her durumda risk'e katkı verir
    risk = max(risk, 0.5 * cons.divergence)

    # "Buy the rumor, sell the news" → bullish konsensüs olsa bile alpha'yı kıs + risk
    if timing is not None and timing.buy_rumor_sell_news and alpha > 0:
        alpha *= 0.35
        risk = max(risk, 0.4 + 0.3 * timing.rumor_fade_rate)
        reasons.append("'Buy the rumor, sell the news' pattern → alpha kısıldı")

    alpha = _clamp(alpha, -1.0, 1.0)
    return KolSignal(
        consensus=cons,
        timing=timing,
        sentiment=float(cons.weighted_sentiment),
        alpha_bias=float(alpha),
        risk_score=float(_clamp01(risk)),
        reasons=reasons,
    )


# ── Parser'lar (kaynak normalize) ────────────────────────────────────────────


def parse_twitter_api_v2(payload: Any) -> List[Dict[str, Any]]:
    """Twitter/X API v2 ``/tweets`` JSON → normalize tweet dict listesi.

    ``data`` listesi + opsiyonel ``includes.users`` (author_id → username).
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return []
    if not isinstance(payload, dict):
        return []
    rows = payload.get("data")
    if not isinstance(rows, list):
        return []
    users: Dict[str, str] = {}
    inc = payload.get("includes")
    if isinstance(inc, dict) and isinstance(inc.get("users"), list):
        for u in inc["users"]:
            if isinstance(u, dict) and u.get("id"):
                users[str(u["id"])] = str(u.get("username", ""))
    out: List[Dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        metrics = r.get("public_metrics") or {}
        handle = r.get("username") or users.get(str(r.get("author_id", "")), "")
        out.append({
            "handle": handle,
            "text": r.get("text", ""),
            "likes": metrics.get("like_count"),
            "retweets": metrics.get("retweet_count"),
            "ts_ms": _iso_to_ms(r.get("created_at")),
        })
    return out


def parse_nitter_rss(payload: Any) -> List[Dict[str, Any]]:
    """Nitter RSS/XML → normalize tweet dict listesi (regex tabanlı, bağımlılıksız).

    ``<item>`` blokları içinde ``<title>``/``<description>`` (metin) ve
    ``<dc:creator>``/``<creator>`` (handle) çıkarılır.
    """
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", errors="replace")
    if not isinstance(payload, str) or "<item" not in payload:
        return []
    out: List[Dict[str, Any]] = []
    for item in re.findall(r"<item\b[^>]*>(.*?)</item>", payload, re.DOTALL | re.IGNORECASE):
        text = _xml_tag(item, "title") or _xml_tag(item, "description") or ""
        creator = _xml_tag(item, "dc:creator") or _xml_tag(item, "creator") or ""
        out.append({
            "handle": creator,
            "text": _strip_html(text),
            "ts_ms": None,
        })
    return out


def _xml_tag(block: str, tag: str) -> str:
    m = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", block, re.DOTALL | re.IGNORECASE)
    if not m:
        return ""
    val = m.group(1).strip()
    cdata = re.match(r"<!\[CDATA\[(.*?)\]\]>", val, re.DOTALL)
    return cdata.group(1).strip() if cdata else val


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", " ", s).replace("&amp;", "&").strip()


def _iso_to_ms(s: Any) -> Optional[float]:
    """ISO-8601 (örn. '2026-06-03T12:00:00.000Z') → unix ms. Hata olursa None."""
    if not isinstance(s, str) or not s:
        return None
    try:
        import datetime as _dt
        s2 = s.replace("Z", "+00:00")
        return _dt.datetime.fromisoformat(s2).timestamp() * 1000.0
    except (ValueError, TypeError):
        return None


# ── Collector ────────────────────────────────────────────────────────────────


class KolCollector:
    """Twitter/X API v2 veya Nitter scraping toplayıcı (mock'lanabilir)."""

    def __init__(self, *, http_get: Optional[HttpGet] = None, timeout_sec: float = 5.0) -> None:
        self._http_get: HttpGet = http_get or _default_http_get
        self._timeout = float(timeout_sec)

    def fetch_twitter_api(self, query: str) -> List[Dict[str, Any]]:
        """Twitter/X API v2 recent search. Token yoksa boş liste."""
        token = os.getenv("TWITTER_BEARER_TOKEN", "")
        base = os.getenv("TWITTER_API_URL", "https://api.twitter.com/2/tweets/search/recent")
        if not token:
            return []
        url = (
            f"{base}?query={urllib.parse.quote(query)}"
            "&tweet.fields=public_metrics,created_at,author_id"
            "&expansions=author_id&user.fields=username&max_results=50"
        )
        body = self._http_get(url, self._timeout)
        return parse_twitter_api_v2(body) if body else []

    def fetch_nitter(self, handle: str) -> List[Dict[str, Any]]:
        """Nitter RSS alternatifi (API'siz scraping)."""
        base = os.getenv("NITTER_BASE_URL", "https://nitter.net")
        h = _norm_handle(handle)
        body = self._http_get(f"{base}/{h}/rss", self._timeout)
        return parse_nitter_rss(body) if body else []


__all__ = [
    "BEARISH",
    "BULLISH",
    "BUY",
    "DIVERGENT",
    "KOL",
    "KOL_REGISTRY",
    "NEUTRAL",
    "SELL",
    "TIER1",
    "TIER2",
    "TIER3",
    "KolCollector",
    "KolConsensus",
    "KolSignal",
    "TimingSignal",
    "TweetAnalysis",
    "analyze_kol",
    "analyze_sentiment",
    "analyze_tweet",
    "backtest_kol_timing",
    "compute_consensus",
    "detect_action",
    "detect_buy_rumor_sell_news",
    "engagement_weight",
    "get_kol",
    "parse_cashtags",
    "parse_nitter_rss",
    "parse_twitter_api_v2",
    "resolve_kol",
]
