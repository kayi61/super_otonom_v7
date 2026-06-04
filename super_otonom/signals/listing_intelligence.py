"""PROMPT-5.2 — Exchange Listing & Delisting Detector — Faz 23 feed.

Borsa listing/delisting olaylarını erken tespit eder; `news_event_intelligence`
(Faz 23) `is_exchange_listing` bayrağıyla entegre çalışır.

1. **Listing sinyalleri (erken tespit)**: borsa cüzdanına yeni token transfer'i
   (on-chain), test wallet'ta görünme, API'de yeni symbol, blog/announcement,
   birden fazla Tier-2 listing → Tier-1 yakında.
2. **Delisting sinyalleri**: volume ani düşüş, delisting duyurusu, compliance/
   regulatory (SEC), proje durması + volume kuruması.
3. **Listing impact modeli**: Tier-1 (Binance/Coinbase) → ort. +30–80% (backtest),
   listing sonrası dump timing (24–72h), "buy the rumor" window.
4. **Otomatik trade sinyali**: yüksek olasılıklı listing → küçük pozisyon;
   onaylandığında → büyüt/kâr al; delisting riski → pozisyon kapat.

Kaynaklar: on-chain / borsa API / announcement (enjekte edilebilir ``http_get``).
Analiz fonksiyonları saftır (ağsız test edilir).
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

log = logging.getLogger("super_otonom.listing")

HttpGet = Callable[[str, float], Optional[str]]

# Aksiyonlar
OPEN_SMALL = "open_small"
SCALE_UP = "scale_up"
TAKE_PROFIT = "take_profit"
CLOSE = "close"
HOLD = "hold"

# Eşikler
LISTING_PROB_HIGH = 0.65        # yüksek olasılıklı listing → küçük pozisyon
DELISTING_RISK_HIGH = 0.6       # → pozisyon kapat

# Tier-1 / Tier-2 borsalar
_TIER1_EXCHANGES = {"binance", "coinbase", "coinbase pro", "upbit"}
_TIER2_EXCHANGES = {
    "kucoin", "okx", "bybit", "gate", "gate.io", "mexc", "kraken", "bitget",
    "huobi", "htx", "crypto.com", "bitfinex",
}

# Tier başına ortalama listing etkisi (backtest proxy)
_TIER_IMPACT = {1: 0.50, 2: 0.15, 3: 0.05}   # +%50 / +%15 / +%5
DUMP_WINDOW_HOURS = 48.0         # listing sonrası dump genellikle 24–72h

_LISTING_KW = re.compile(
    r"\b(will list|lists|listing|added|now available|new listing|perpetual|spot trading)\b",
    re.IGNORECASE,
)
_DELISTING_KW = re.compile(
    r"\b(delist|delisting|will remove|removal of|cease trading|trading suspended|suspend)\b",
    re.IGNORECASE,
)


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


def _truthy(v: Any) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y", "evet")
    return bool(v)


def _default_http_get(url: str, timeout: float) -> Optional[str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "super_otonom/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        log.debug("listing http_get hata (%s): %s", url[:60], exc)
        return None


def classify_exchange_tier(name: Any) -> int:
    """Borsa adından tier (1/2/3). Bilinmiyorsa 3."""
    s = str(name or "").strip().lower()
    if not s:
        return 3
    if any(ex in s for ex in _TIER1_EXCHANGES):
        return 1
    if any(ex in s for ex in _TIER2_EXCHANGES):
        return 2
    return 3


# ── 1) Listing olasılığı (erken tespit) ──────────────────────────────────────


def listing_probability(
    *,
    exchange_wallet_inflow: bool = False,
    test_wallet_detected: bool = False,
    api_symbol_added: bool = False,
    announcement_detected: bool = False,
    tier2_listing_count: float = 0.0,
    confirmed_listing: bool = False,
) -> tuple[float, List[str]]:
    """Erken listing sinyallerini olasılığa indirger (0..1) + gerekçeler."""
    reasons: List[str] = []
    prob = 0.0
    if announcement_detected:
        prob += 0.45
        reasons.append("Borsa duyurusu tespit edildi")
    if api_symbol_added:
        prob += 0.32
        reasons.append("Borsa API'sinde yeni symbol")
    if exchange_wallet_inflow:
        prob += 0.26
        reasons.append("Borsa cüzdanına token transferi (on-chain)")
    if test_wallet_detected:
        prob += 0.22
        reasons.append("Borsa test wallet'ında token")
    n2 = _coerce_float(tier2_listing_count) or 0.0
    if n2 >= 2:
        prob += 0.28
        reasons.append(f"{int(n2)} Tier-2 borsada listeli → Tier-1 yakında")
    elif n2 >= 1:
        prob += 0.12

    if confirmed_listing:
        prob = max(prob, 0.95)
        reasons.append("Listing onaylandı")
    return _clamp01(prob), reasons


# ── 2) Delisting riski ───────────────────────────────────────────────────────


def delisting_risk(
    *,
    volume_drop_pct: Optional[float] = None,
    delisting_announced: bool = False,
    regulatory_action: bool = False,
    dev_inactive: bool = False,
    volume_dry: bool = False,
) -> tuple[float, List[str]]:
    """Delisting sinyallerini riske indirger (0..1) + gerekçeler."""
    reasons: List[str] = []
    risk = 0.0
    if delisting_announced:
        risk = max(risk, 0.9)
        reasons.append("Delisting duyurusu")
    if regulatory_action:
        risk = max(risk, 0.8)
        reasons.append("Regulatory/compliance (ör. SEC) aksiyonu")
    vd = _coerce_float(volume_drop_pct)
    if vd is not None and vd > 0:
        # vd: hacim düşüş oranı (0.7 = %70 düşüş)
        risk = max(risk, _clamp01(vd))
        if vd >= 0.6:
            reasons.append(f"Volume %{vd * 100:.0f} ani düşüş")
    if dev_inactive and volume_dry:
        risk = max(risk, 0.5)
        reasons.append("Proje durması + volume kuruması")
    return _clamp01(risk), reasons


# ── 3) Listing impact modeli ─────────────────────────────────────────────────


@dataclass(frozen=True)
class ListingImpact:
    tier: int
    expected_move_pct: float        # backtest proxy (ör. 0.50 = +%50)
    dump_window_hours: float        # listing sonrası dump zamanı
    buy_rumor_window: bool          # "buy the rumor" penceresi açık mı (pre-listing)


def listing_impact(
    tier: int,
    *,
    confirmed: bool = False,
    history: Optional[Sequence[Dict[str, Any]]] = None,
) -> ListingImpact:
    """Tier + geçmiş → beklenen hareket + dump timing + buy-rumor penceresi."""
    expected = _TIER_IMPACT.get(int(tier), 0.05)
    moves: List[float] = []
    for h in history or []:
        if isinstance(h, dict):
            mv = _coerce_float(h.get("post_move_pct") or h.get("move_pct"))
            if mv is not None:
                moves.append(mv)
    if moves:
        expected = sum(moves) / len(moves)
    return ListingImpact(
        tier=int(tier),
        expected_move_pct=float(expected),
        dump_window_hours=DUMP_WINDOW_HOURS,
        buy_rumor_window=not confirmed,
    )


# ── 4) Birleşik sinyal + otomatik trade ──────────────────────────────────────


@dataclass(frozen=True)
class ListingSignal:
    listing_probability: float          # 0..1
    delisting_risk: float               # 0..1
    predicted_tier: int
    expected_impact_pct: float
    action: str                         # open_small | scale_up | take_profit | close | hold
    position_size_hint: float           # 0..1
    alpha_bias: float                   # -1..1
    risk_score: float                   # 0..1
    trade_permission: str               # ALLOW | BLOCK | HALT
    urgent: bool
    buy_rumor_window: bool
    confirmed: bool
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "listing_probability": self.listing_probability,
            "delisting_risk": self.delisting_risk,
            "predicted_tier": self.predicted_tier,
            "expected_impact_pct": self.expected_impact_pct,
            "action": self.action,
            "position_size_hint": self.position_size_hint,
            "listing_alpha_bias": self.alpha_bias,
            "listing_risk_score": self.risk_score,
            "trade_permission": self.trade_permission,
            "urgent": self.urgent,
            "buy_rumor_window": self.buy_rumor_window,
            "confirmed": self.confirmed,
            "listing_reasons": list(self.reasons),
        }


def analyze_listing(
    *,
    exchange: Any = None,
    exchange_wallet_inflow: bool = False,
    test_wallet_detected: bool = False,
    api_symbol_added: bool = False,
    announcement_detected: bool = False,
    tier2_listing_count: float = 0.0,
    confirmed_listing: bool = False,
    volume_drop_pct: Optional[float] = None,
    delisting_announced: bool = False,
    regulatory_action: bool = False,
    dev_inactive: bool = False,
    volume_dry: bool = False,
    history: Optional[Sequence[Dict[str, Any]]] = None,
    post_listing_hours: Optional[float] = None,
) -> Optional[ListingSignal]:
    """Listing/delisting sinyallerini birleştirir → aksiyon/alpha/risk. Sinyal yoksa None."""
    has_listing = (
        exchange_wallet_inflow or test_wallet_detected or api_symbol_added
        or announcement_detected or (_coerce_float(tier2_listing_count) or 0) >= 1
        or confirmed_listing
    )
    has_delisting = (
        delisting_announced or regulatory_action
        or (_coerce_float(volume_drop_pct) or 0) > 0 or (dev_inactive and volume_dry)
    )
    if not (has_listing or has_delisting):
        return None

    prob, l_reasons = listing_probability(
        exchange_wallet_inflow=exchange_wallet_inflow,
        test_wallet_detected=test_wallet_detected,
        api_symbol_added=api_symbol_added,
        announcement_detected=announcement_detected,
        tier2_listing_count=tier2_listing_count,
        confirmed_listing=confirmed_listing,
    )
    drisk, d_reasons = delisting_risk(
        volume_drop_pct=volume_drop_pct,
        delisting_announced=delisting_announced,
        regulatory_action=regulatory_action,
        dev_inactive=dev_inactive,
        volume_dry=volume_dry,
    )

    # Tier tahmini
    if exchange is not None:
        tier = classify_exchange_tier(exchange)
    elif (_coerce_float(tier2_listing_count) or 0) >= 2:
        tier = 1  # birden fazla Tier-2 → Tier-1 yakında
    else:
        tier = 2

    impact = listing_impact(tier, confirmed=confirmed_listing, history=history)
    reasons = list(l_reasons) + list(d_reasons)

    urgent = bool(delisting_announced or regulatory_action)
    perm = "ALLOW"
    action = HOLD
    pos_hint = 0.0
    alpha = 0.0
    risk = drisk

    if drisk >= DELISTING_RISK_HIGH:
        # Delisting riski → pozisyon kapat
        action = CLOSE
        pos_hint = 0.0
        alpha = -_clamp01(drisk)
        perm = "HALT" if urgent else "BLOCK"
    elif confirmed_listing:
        post_h = _coerce_float(post_listing_hours)
        if post_h is not None and 0 <= post_h <= impact.dump_window_hours:
            # Listing sonrası dump penceresi → kâr al
            action = TAKE_PROFIT
            pos_hint = 0.25
            alpha = _clamp(impact.expected_move_pct * 0.2, -0.3, 0.3)
            risk = max(risk, 0.5)
            reasons.append(f"Listing sonrası dump penceresi (≤{impact.dump_window_hours:.0f}h) → kâr al")
        else:
            # Onaylı listing, buy-rumor öncesi → büyüt
            action = SCALE_UP
            pos_hint = 0.7
            alpha = _clamp01(0.4 + 0.6 * impact.expected_move_pct)
            reasons.append("Listing onaylı → pozisyon büyüt")
    elif prob >= LISTING_PROB_HIGH:
        # Yüksek olasılıklı listing (buy the rumor) → küçük pozisyon
        action = OPEN_SMALL
        pos_hint = 0.3
        alpha = _clamp01(prob * (0.4 + 0.6 * impact.expected_move_pct))
        reasons.append("Yüksek olasılıklı listing (buy the rumor) → küçük pozisyon")
    elif prob > 0:
        alpha = _clamp01(0.25 * prob)

    return ListingSignal(
        listing_probability=float(prob),
        delisting_risk=float(drisk),
        predicted_tier=int(tier),
        expected_impact_pct=float(impact.expected_move_pct),
        action=action,
        position_size_hint=float(pos_hint),
        alpha_bias=float(_clamp(alpha, -1.0, 1.0)),
        risk_score=float(_clamp01(risk)),
        trade_permission=perm,
        urgent=urgent,
        buy_rumor_window=bool(impact.buy_rumor_window and prob >= 0.4 and not confirmed_listing),
        confirmed=bool(confirmed_listing),
        reasons=reasons,
    )


def analyze_listing_data(data: Dict[str, Any]) -> Optional[ListingSignal]:
    """Düz dict köprüsü (news_event_intelligence Faz 23).

    ``listing`` / ``delisting`` alt dict'leri veya düz sinyal anahtarları +
    ``is_exchange_listing`` bayrağı (onay).
    """
    if not isinstance(data, dict):
        return None
    listing_blk = data.get("listing") if isinstance(data.get("listing"), dict) else {}
    delist_blk = data.get("delisting") if isinstance(data.get("delisting"), dict) else {}
    src: Dict[str, Any] = {**data, **listing_blk, **delist_blk}

    # Aktivasyon: yalnız yapılandırılmış listing/delisting sinyali varsa çalışır.
    # Yalın ``is_exchange_listing`` bayrağı tek başına tetiklemez (eski Faz 23 korunur).
    _STRUCTURED_KEYS = (
        "exchange_wallet_inflow", "exchange_inflow", "test_wallet_detected", "test_wallet",
        "api_symbol_added", "new_symbol", "announcement_detected", "listing_announced",
        "tier2_listing_count", "tier2_count", "listing_confirmed", "confirmed_listing",
        "post_listing_hours", "hours_since_listing", "volume_drop_pct", "volume_drop",
        "delisting_announced", "is_delisting", "regulatory_action", "sec_action",
        "compliance_issue", "dev_inactive", "development_stalled", "volume_dry",
        "volume_dried_up", "listing_history",
    )
    if not (listing_blk or delist_blk or any(k in data for k in _STRUCTURED_KEYS)):
        return None

    def g(*keys: str) -> Any:
        for k in keys:
            if k in src and src[k] is not None:
                return src[k]
        return None

    confirmed = _truthy(g("is_exchange_listing", "listing_confirmed", "confirmed_listing"))

    return analyze_listing(
        exchange=g("exchange", "exchange_name"),
        exchange_wallet_inflow=_truthy(g("exchange_wallet_inflow", "exchange_inflow")),
        test_wallet_detected=_truthy(g("test_wallet_detected", "test_wallet")),
        api_symbol_added=_truthy(g("api_symbol_added", "new_symbol")),
        announcement_detected=_truthy(g("announcement_detected", "listing_announced")),
        tier2_listing_count=_coerce_float(g("tier2_listing_count", "tier2_count")) or 0.0,
        confirmed_listing=confirmed,
        volume_drop_pct=_coerce_float(g("volume_drop_pct", "volume_drop")),
        delisting_announced=_truthy(g("delisting_announced", "is_delisting")),
        regulatory_action=_truthy(g("regulatory_action", "sec_action", "compliance_issue")),
        dev_inactive=_truthy(g("dev_inactive", "development_stalled")),
        volume_dry=_truthy(g("volume_dry", "volume_dried_up")),
        history=g("listing_history", "history"),
        post_listing_hours=_coerce_float(g("post_listing_hours", "hours_since_listing")),
    )


# ── Parser'lar ───────────────────────────────────────────────────────────────


def parse_announcement(text: Any) -> Dict[str, bool]:
    """Borsa blog/announcement metni → {listing_announced, delisting_announced}."""
    if isinstance(text, (bytes, bytearray)):
        text = text.decode("utf-8", errors="replace")
    if not isinstance(text, str):
        return {"listing_announced": False, "delisting_announced": False}
    return {
        "listing_announced": bool(_LISTING_KW.search(text)),
        "delisting_announced": bool(_DELISTING_KW.search(text)),
    }


def detect_new_symbols(current: Sequence[str], known: Sequence[str]) -> List[str]:
    """API symbol listesi diff → yeni eklenen sembol(ler)."""
    known_set = {str(s).upper() for s in (known or [])}
    out: List[str] = []
    seen = set()
    for s in current or []:
        u = str(s).upper()
        if u not in known_set and u not in seen:
            seen.add(u)
            out.append(u)
    return out


# ── Collector ────────────────────────────────────────────────────────────────


class ListingCollector:
    """Borsa API symbol listesi + announcement toplayıcı (mock'lanabilir)."""

    def __init__(self, *, http_get: Optional[HttpGet] = None, timeout_sec: float = 6.0) -> None:
        self._http_get: HttpGet = http_get or _default_http_get
        self._timeout = float(timeout_sec)

    def fetch_announcement(self, url: str) -> Dict[str, bool]:
        body = self._http_get(url, self._timeout)
        return parse_announcement(body) if body else {"listing_announced": False, "delisting_announced": False}

    def fetch_exchange_symbols(self) -> List[str]:
        """Binance exchangeInfo tarzı symbol listesi (mock'lanabilir)."""
        base = os.getenv("EXCHANGE_SYMBOLS_URL", "https://api.binance.com/api/v3/exchangeInfo")
        body = self._http_get(base, self._timeout)
        if not body:
            return []
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return []
        syms = payload.get("symbols") if isinstance(payload, dict) else None
        if not isinstance(syms, list):
            return []
        return [str(s.get("symbol")) for s in syms if isinstance(s, dict) and s.get("symbol")]


__all__ = [
    "CLOSE",
    "DELISTING_RISK_HIGH",
    "HOLD",
    "LISTING_PROB_HIGH",
    "OPEN_SMALL",
    "SCALE_UP",
    "TAKE_PROFIT",
    "ListingCollector",
    "ListingImpact",
    "ListingSignal",
    "analyze_listing",
    "analyze_listing_data",
    "classify_exchange_tier",
    "delisting_risk",
    "detect_new_symbols",
    "listing_impact",
    "listing_probability",
    "parse_announcement",
]
