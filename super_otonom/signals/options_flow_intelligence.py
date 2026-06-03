"""PROMPT-3.3 — Options Flow Intelligence (Deribit) — Faz 27 options feed.

`alternative_data_engine` (Faz 27) options bölümünü zenginleştirir:

1. **Options flow**: Deribit BTC/ETH volume & OI, Put/Call ratio (PCR) trendi.
   - PCR > 1.2 → korku (olası dip, kontraryan bullish)
   - PCR < 0.5 → aşırı güven (olası tepe, kontraryan bearish)
2. **Whale options**: $1M+ tek trade, unusual activity (3x+ normal volume),
   yön (büyük call alımı = bullish, büyük put alımı = hedge/bearish).
3. **Max Pain**: haftalık/aylık expiry max pain fiyatı, expiry'ye yaklaşınca
   max pain'e çekilme + gamma squeeze riski.
4. **Implied Volatility**: IV skew (put vs call), term structure (kısa vs uzun),
   IV crush beklentisi, realized vs implied (vol risk premium).

Birincil kaynak: Deribit public API (anahtar gerekmez). Tüm analiz fonksiyonları
saftır (ağsız test edilir); HTTP katmanı enjekte edilebilir.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

log = logging.getLogger("super_otonom.options_flow")

HttpGet = Callable[[str, float], Optional[str]]

# PCR eşikleri
PCR_FEAR = 1.2       # > → korku (olası dip)
PCR_GREED = 0.5      # < → aşırı güven (olası tepe)
WHALE_TRADE_USD = 1_000_000.0
UNUSUAL_VOLUME_MULT = 3.0
GAMMA_SQUEEZE_HOURS = 24.0   # expiry'ye < bu kadar saat → gamma squeeze riski

SENT_FEAR = "fear"
SENT_GREED = "greed"
SENT_NEUTRAL = "neutral"

DIR_BULLISH = "bullish"
DIR_BEARISH = "bearish"
DIR_NEUTRAL = "neutral"

TERM_BACKWARDATION = "backwardation"   # kısa IV > uzun IV (stres)
TERM_CONTANGO = "contango"             # kısa IV < uzun IV (normal)
TERM_FLAT = "flat"


def _coerce_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _default_http_get(url: str, timeout: float) -> Optional[str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "super_otonom/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        log.debug("options http_get hata (%s): %s", url[:60], exc)
        return None


# ── Option contract (Deribit normalize) ──────────────────────────────────────


@dataclass(frozen=True)
class OptionContract:
    instrument: str
    strike: float
    option_type: str   # call | put
    volume: float
    open_interest: float
    mark_iv: Optional[float]      # implied volatility (%)
    underlying_price: Optional[float]
    expiry_ts: Optional[int] = None


def _parse_instrument(name: str) -> tuple[Optional[float], Optional[str]]:
    """Deribit instrument adı: ``BTC-27DEC24-50000-C`` → (50000, 'call')."""
    parts = str(name).split("-")
    if len(parts) < 4:
        return None, None
    strike = _coerce_float(parts[-2])
    t = parts[-1].upper()
    opt_type = "call" if t == "C" else "put" if t == "P" else None
    return strike, opt_type


def parse_deribit_summary(payload: Any) -> List[OptionContract]:
    """Deribit ``get_book_summary_by_currency`` (kind=option) → OptionContract listesi."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return []
    if isinstance(payload, dict):
        rows = payload.get("result", payload.get("data"))
    else:
        rows = payload
    if not isinstance(rows, list):
        return []
    out: List[OptionContract] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        name = r.get("instrument_name") or r.get("instrument") or ""
        strike, opt_type = _parse_instrument(name)
        if strike is None or opt_type is None:
            continue
        out.append(
            OptionContract(
                instrument=str(name),
                strike=strike,
                option_type=opt_type,
                volume=_coerce_float(r.get("volume")) or 0.0,
                open_interest=_coerce_float(r.get("open_interest")) or 0.0,
                mark_iv=_coerce_float(r.get("mark_iv")),
                underlying_price=_coerce_float(r.get("underlying_price") or r.get("mark_price")),
            )
        )
    return out


# ── 1) Put/Call ratio ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PcrSignal:
    pcr: float
    sentiment: str          # fear | greed | neutral
    contrarian_bias: float  # -1..1 (fear → +bullish, greed → -bearish)
    trend: str              # rising | falling | flat | unknown


def classify_pcr(pcr: float) -> str:
    if pcr > PCR_FEAR:
        return SENT_FEAR
    if pcr < PCR_GREED:
        return SENT_GREED
    return SENT_NEUTRAL


def analyze_pcr(
    *,
    put_volume: Optional[float] = None,
    call_volume: Optional[float] = None,
    pcr: Optional[float] = None,
    pcr_history: Optional[Sequence[float]] = None,
) -> PcrSignal:
    """Put/Call ratio + sentiment + kontraryan bias + trend."""
    if pcr is None:
        pv = put_volume or 0.0
        cv = call_volume or 0.0
        pcr = pv / cv if cv > 1e-9 else 1.0
    pcr = float(pcr)
    sentiment = classify_pcr(pcr)
    # Kontraryan: korku → bullish (+), aşırı güven → bearish (-)
    if sentiment == SENT_FEAR:
        bias = _clamp((pcr - PCR_FEAR) * 1.5, 0.0, 1.0)
    elif sentiment == SENT_GREED:
        bias = -_clamp((PCR_GREED - pcr) * 2.0, 0.0, 1.0)
    else:
        bias = 0.0

    trend = "unknown"
    if pcr_history and len(pcr_history) >= 2:
        vals = [f for f in (_coerce_float(x) for x in pcr_history) if f is not None]
        if len(vals) >= 2:
            delta = vals[-1] - vals[0]
            trend = "rising" if delta > 0.05 else "falling" if delta < -0.05 else "flat"
    return PcrSignal(pcr=pcr, sentiment=sentiment, contrarian_bias=float(bias), trend=trend)


# ── 2) Whale options ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class OptionTrade:
    option_type: str   # call | put
    side: str          # buy | sell
    notional_usd: float


@dataclass(frozen=True)
class WhaleOptionsSignal:
    whale_trade_count: int
    whale_notional_usd: float
    net_direction: str          # bullish | bearish | neutral
    unusual_activity: bool      # volume > 3x avg
    volume_ratio: float


def detect_whale_options(
    trades: Sequence[Any],
    *,
    current_volume: Optional[float] = None,
    avg_volume: Optional[float] = None,
    whale_usd: float = WHALE_TRADE_USD,
) -> WhaleOptionsSignal:
    """$1M+ trade'ler + yön (call buy=bullish, put buy=bearish) + unusual activity."""
    whales: List[OptionTrade] = []
    for t in trades or []:
        if isinstance(t, OptionTrade):
            ot = t
        elif isinstance(t, dict):
            usd = _coerce_float(t.get("notional_usd") or t.get("usd") or t.get("size_usd"))
            if usd is None:
                continue
            ot = OptionTrade(
                option_type=str(t.get("option_type") or t.get("type") or "").lower(),
                side=str(t.get("side") or t.get("direction") or "buy").lower(),
                notional_usd=usd,
            )
        else:
            continue
        if ot.notional_usd >= whale_usd:
            whales.append(ot)

    # Yön skoru: call buy / put sell = bullish; put buy / call sell = bearish
    bull = 0.0
    bear = 0.0
    for w in whales:
        if (w.option_type == "call" and w.side == "buy") or (
            w.option_type == "put" and w.side == "sell"
        ):
            bull += w.notional_usd
        elif (w.option_type == "put" and w.side == "buy") or (
            w.option_type == "call" and w.side == "sell"
        ):
            bear += w.notional_usd
    if bull > bear * 1.2:
        direction = DIR_BULLISH
    elif bear > bull * 1.2:
        direction = DIR_BEARISH
    else:
        direction = DIR_NEUTRAL

    vol_ratio = 1.0
    if current_volume is not None and avg_volume and avg_volume > 1e-9:
        vol_ratio = current_volume / avg_volume
    unusual = vol_ratio >= UNUSUAL_VOLUME_MULT

    return WhaleOptionsSignal(
        whale_trade_count=len(whales),
        whale_notional_usd=float(sum(w.notional_usd for w in whales)),
        net_direction=direction,
        unusual_activity=unusual,
        volume_ratio=float(vol_ratio),
    )


# ── 3) Max Pain ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MaxPainAnalysis:
    max_pain_price: Optional[float]
    spot: Optional[float]
    distance_pct: Optional[float]    # (max_pain - spot) / spot
    pull_strength: float             # 0..1 (expiry yaklaşınca artar)
    gamma_squeeze_risk: float        # 0..1


def compute_max_pain(chain: Sequence[Dict[str, Any]]) -> Optional[float]:
    """Option zincirinden max pain strike (option holder toplam ödemesini minimize eden)."""
    strikes: Dict[float, Dict[str, float]] = {}
    for row in chain or []:
        if not isinstance(row, dict):
            continue
        k = _coerce_float(row.get("strike"))
        if k is None or k <= 0:
            continue
        call_oi = _coerce_float(row.get("call_oi") or row.get("call_open_interest")) or 0.0
        put_oi = _coerce_float(row.get("put_oi") or row.get("put_open_interest")) or 0.0
        ent = strikes.setdefault(k, {"call_oi": 0.0, "put_oi": 0.0})
        ent["call_oi"] += call_oi
        ent["put_oi"] += put_oi
    if not strikes:
        return None
    candidates = sorted(strikes)
    best_strike = None
    best_payout = None
    for s in candidates:
        payout = 0.0
        for k, oi in strikes.items():
            payout += oi["call_oi"] * max(0.0, s - k)   # call holder kazancı
            payout += oi["put_oi"] * max(0.0, k - s)    # put holder kazancı
        if best_payout is None or payout < best_payout:
            best_payout = payout
            best_strike = s
    return best_strike


def analyze_max_pain(
    chain: Sequence[Dict[str, Any]],
    *,
    spot: Optional[float] = None,
    hours_to_expiry: Optional[float] = None,
) -> MaxPainAnalysis:
    """Max pain fiyatı + spot uzaklığı + expiry yakınlığına bağlı çekim/gamma squeeze."""
    mp = compute_max_pain(chain)
    dist = None
    if mp is not None and spot is not None and spot > 0:
        dist = (mp - spot) / spot

    # Expiry yaklaştıkça çekim güçlenir
    pull = 0.0
    gamma = 0.0
    if hours_to_expiry is not None:
        h = max(0.0, float(hours_to_expiry))
        # 7 gün (168h) → 0, expiry'de → 1
        pull = _clamp(1.0 - h / 168.0, 0.0, 1.0)
        if h <= GAMMA_SQUEEZE_HOURS:
            gamma = _clamp(1.0 - h / GAMMA_SQUEEZE_HOURS, 0.0, 1.0)

    return MaxPainAnalysis(
        max_pain_price=mp,
        spot=spot,
        distance_pct=dist,
        pull_strength=float(pull),
        gamma_squeeze_risk=float(gamma),
    )


# ── 4) Implied Volatility ────────────────────────────────────────────────────


@dataclass(frozen=True)
class IvAnalysis:
    iv_skew: Optional[float]            # put_iv - call_iv (pozitif = downside korku)
    term_structure: str                # backwardation | contango | flat
    term_spread: Optional[float]       # short_iv - long_iv
    vol_risk_premium: Optional[float]  # implied - realized (pozitif = pahalı opsiyon)
    iv_crush_risk: float               # 0..1


def analyze_iv(
    *,
    put_iv: Optional[float] = None,
    call_iv: Optional[float] = None,
    short_iv: Optional[float] = None,
    long_iv: Optional[float] = None,
    realized_vol: Optional[float] = None,
    hours_to_expiry: Optional[float] = None,
    flat_eps: float = 1.0,
) -> IvAnalysis:
    """IV skew + term structure + vol risk premium + IV crush riski."""
    skew = None
    if put_iv is not None and call_iv is not None:
        skew = float(put_iv) - float(call_iv)

    term = TERM_FLAT
    spread = None
    if short_iv is not None and long_iv is not None:
        spread = float(short_iv) - float(long_iv)
        if spread > flat_eps:
            term = TERM_BACKWARDATION
        elif spread < -flat_eps:
            term = TERM_CONTANGO

    vrp = None
    atm_iv = short_iv if short_iv is not None else (
        ((put_iv + call_iv) / 2.0) if (put_iv is not None and call_iv is not None) else None
    )
    if atm_iv is not None and realized_vol is not None:
        vrp = float(atm_iv) - float(realized_vol)

    # IV crush: yüksek IV + yakın expiry → expiry sonrası vol düşüşü
    crush = 0.0
    if atm_iv is not None and hours_to_expiry is not None:
        h = max(0.0, float(hours_to_expiry))
        near = _clamp(1.0 - h / 72.0, 0.0, 1.0)            # 3 gün içinde artar
        iv_high = _clamp((float(atm_iv) - 50.0) / 100.0, 0.0, 1.0)  # IV > %50 → yüksek
        crush = _clamp(near * (0.5 + 0.5 * iv_high), 0.0, 1.0)

    return IvAnalysis(
        iv_skew=skew,
        term_structure=term,
        term_spread=spread,
        vol_risk_premium=vrp,
        iv_crush_risk=float(crush),
    )


# ── Birleşik analiz ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class OptionsFlowSignal:
    pcr: Optional[PcrSignal]
    whale: Optional[WhaleOptionsSignal]
    max_pain: Optional[MaxPainAnalysis]
    iv: Optional[IvAnalysis]
    alpha_bias: float          # -1..1
    risk_score: float          # 0..1
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "options_alpha_bias": self.alpha_bias,
            "options_risk_score": self.risk_score,
            "options_reasons": list(self.reasons),
        }
        if self.pcr is not None:
            out["pcr"] = self.pcr.pcr
            out["pcr_sentiment"] = self.pcr.sentiment
            out["pcr_trend"] = self.pcr.trend
        if self.whale is not None:
            out["whale_trade_count"] = self.whale.whale_trade_count
            out["whale_notional_usd"] = self.whale.whale_notional_usd
            out["whale_direction"] = self.whale.net_direction
            out["unusual_activity"] = self.whale.unusual_activity
        if self.max_pain is not None:
            out["max_pain_price"] = self.max_pain.max_pain_price
            out["max_pain_distance_pct"] = self.max_pain.distance_pct
            out["max_pain_pull"] = self.max_pain.pull_strength
            out["gamma_squeeze_risk"] = self.max_pain.gamma_squeeze_risk
        if self.iv is not None:
            out["iv_skew"] = self.iv.iv_skew
            out["iv_term_structure"] = self.iv.term_structure
            out["vol_risk_premium"] = self.iv.vol_risk_premium
            out["iv_crush_risk"] = self.iv.iv_crush_risk
        return out


def analyze_options_flow(
    *,
    pcr: Optional[PcrSignal] = None,
    whale: Optional[WhaleOptionsSignal] = None,
    max_pain: Optional[MaxPainAnalysis] = None,
    iv: Optional[IvAnalysis] = None,
) -> OptionsFlowSignal:
    """Tüm options metriklerini alpha bias + risk + reasons'a indirger."""
    reasons: List[str] = []
    alpha = 0.0
    risk = 0.0

    if pcr is not None:
        alpha += 0.5 * pcr.contrarian_bias
        if pcr.sentiment == SENT_FEAR:
            risk = max(risk, 0.45)
            reasons.append(f"PCR {pcr.pcr:.2f} korku (olası dip)")
        elif pcr.sentiment == SENT_GREED:
            risk = max(risk, 0.40)
            reasons.append(f"PCR {pcr.pcr:.2f} aşırı güven (olası tepe)")

    if whale is not None and whale.whale_trade_count > 0:
        if whale.net_direction == DIR_BULLISH:
            alpha += 0.3
            reasons.append(f"Whale bullish options ${whale.whale_notional_usd / 1e6:.1f}M")
        elif whale.net_direction == DIR_BEARISH:
            alpha -= 0.3
            reasons.append(f"Whale bearish/hedge options ${whale.whale_notional_usd / 1e6:.1f}M")
        if whale.unusual_activity:
            risk = max(risk, 0.5)
            reasons.append(f"Unusual options activity ({whale.volume_ratio:.1f}x)")

    if max_pain is not None:
        risk = max(risk, max_pain.gamma_squeeze_risk)
        if max_pain.gamma_squeeze_risk > 0.5:
            reasons.append(f"Gamma squeeze riski (expiry yakın, {max_pain.gamma_squeeze_risk:.2f})")
        # Magnet: spot max pain'in altındaysa yukarı çekim (pull güçlüyse)
        if max_pain.distance_pct is not None and max_pain.pull_strength > 0.5:
            alpha += 0.15 * (1.0 if max_pain.distance_pct > 0 else -1.0) * max_pain.pull_strength
            reasons.append(
                f"Max pain {max_pain.max_pain_price} ({(max_pain.distance_pct or 0) * 100:+.1f}%)"
            )

    if iv is not None:
        risk = max(risk, iv.iv_crush_risk)
        if iv.term_structure == TERM_BACKWARDATION:
            risk = max(risk, 0.45)
            reasons.append("IV backwardation (stres)")
        if iv.iv_crush_risk > 0.5:
            reasons.append(f"IV crush beklentisi ({iv.iv_crush_risk:.2f})")

    alpha = _clamp(alpha, -1.0, 1.0)
    return OptionsFlowSignal(
        pcr=pcr, whale=whale, max_pain=max_pain, iv=iv,
        alpha_bias=float(alpha), risk_score=float(_clamp(risk, 0.0, 1.0)), reasons=reasons,
    )


# ── Deribit collector (mock'lanabilir) ───────────────────────────────────────


class OptionsFlowCollector:
    """Deribit public API'den option book summary toplar (anahtar gerekmez)."""

    def __init__(
        self,
        *,
        http_get: Optional[HttpGet] = None,
        timeout_sec: float = 5.0,
        base_url: Optional[str] = None,
    ) -> None:
        self._http_get: HttpGet = http_get or _default_http_get
        self._timeout = float(timeout_sec)
        self._base = base_url or os.getenv(
            "DERIBIT_API_URL", "https://www.deribit.com/api/v2/public/get_book_summary_by_currency"
        )

    def fetch_contracts(self, currency: str = "BTC") -> List[OptionContract]:
        url = f"{self._base}?currency={currency}&kind=option"
        body = self._http_get(url, self._timeout)
        return parse_deribit_summary(body) if body else []

    @staticmethod
    def aggregate_pcr(contracts: Sequence[OptionContract]) -> PcrSignal:
        put_vol = sum(c.volume for c in contracts if c.option_type == "put")
        call_vol = sum(c.volume for c in contracts if c.option_type == "call")
        return analyze_pcr(put_volume=put_vol, call_volume=call_vol)


def smart_money_options_payload(signal: OptionsFlowSignal) -> Dict[str, Any]:
    """Faz 27 ``options_flow`` girdisi için zenginleştirilmiş alanlar."""
    d = signal.to_dict()
    if signal.pcr is not None:
        d["put_call_ratio"] = signal.pcr.pcr
    return d


__all__ = [
    "DIR_BEARISH",
    "DIR_BULLISH",
    "DIR_NEUTRAL",
    "PCR_FEAR",
    "PCR_GREED",
    "SENT_FEAR",
    "SENT_GREED",
    "SENT_NEUTRAL",
    "TERM_BACKWARDATION",
    "TERM_CONTANGO",
    "TERM_FLAT",
    "IvAnalysis",
    "MaxPainAnalysis",
    "OptionContract",
    "OptionTrade",
    "OptionsFlowCollector",
    "OptionsFlowSignal",
    "PcrSignal",
    "WhaleOptionsSignal",
    "analyze_iv",
    "analyze_max_pain",
    "analyze_options_flow",
    "analyze_pcr",
    "classify_pcr",
    "compute_max_pain",
    "detect_whale_options",
    "parse_deribit_summary",
    "smart_money_options_payload",
]
