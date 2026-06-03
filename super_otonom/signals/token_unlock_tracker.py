"""PROMPT-5.1 — Token Unlock & Vesting Tracker — Faz 23/27 feed.

Token unlock takvimini ve vesting schedule'ı takip eder; `news_event_intelligence`
(Faz 23) unlock bölümünü ve `alternative_data_engine` (Faz 27) tokenomics bölümünü
zenginleştirir.

1. **Unlock takvimi**: TokenUnlocks.app / Dune Analytics verisi; yaklaşan unlock'lar
   (7/30/90 gün), unlock miktarı / circulating supply oranı. >5% supply unlock →
   yüksek satış baskısı riski.
2. **Cliff vs Linear**: cliff (tek seferde büyük) → daha tehlikeli; linear (yavaş) →
   tolere edilebilir. Team/investor unlock vs ecosystem unlock ayrımı.
3. **Geçmiş davranış**: önceki unlock'larda fiyat etkisi, team sattı mı tuttu mu,
   ortalama unlock sonrası hareket (backtest).
4. **Otomatik risk ayarı**: 7 gün içinde büyük unlock → position size küçült;
   unlock günü → trade_permission BLOCK; unlock + whale exchange transfer → acil risk.

Kaynaklar: TokenUnlocks.app / Dune Analytics (enjekte edilebilir ``http_get``).
Analiz fonksiyonları saftır (ağsız test edilir).
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

log = logging.getLogger("super_otonom.unlock")

HttpGet = Callable[[str, float], Optional[str]]

# Unlock tipi
CLIFF = "cliff"
LINEAR = "linear"
UNKNOWN_TYPE = "unknown"

# Kategori
TEAM = "team"
INVESTOR = "investor"
ECOSYSTEM = "ecosystem"
PUBLIC = "public"
COMMUNITY = "community"
UNKNOWN_CAT = "unknown"

# Eşikler
HIGH_UNLOCK_PCT = 0.05          # > %5 circulating → yüksek satış baskısı
DEFAULT_HALF_LIFE_MS = 86_400_000

_DAY_MS = 86_400_000.0
WINDOW_7D = 7.0
WINDOW_30D = 30.0
WINDOW_90D = 90.0

WHALE_INFLOW_URGENT_USD = 5_000_000.0   # unlock + bu üstü borsa girişi → acil

# Tip / kategori tehlike faktörleri
_TYPE_FACTOR = {CLIFF: 1.0, LINEAR: 0.5, UNKNOWN_TYPE: 0.75}
_CAT_FACTOR = {
    TEAM: 1.0, INVESTOR: 0.95, "private": 0.9, "vc": 0.95,
    ECOSYSTEM: 0.55, PUBLIC: 0.6, COMMUNITY: 0.5, "airdrop": 0.5,
    "staking": 0.55, "rewards": 0.55, UNKNOWN_CAT: 0.7,
}


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


def _now_ms() -> float:
    return time.time() * 1000.0


def _default_http_get(url: str, timeout: float) -> Optional[str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "super_otonom/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        log.debug("unlock http_get hata (%s): %s", url[:60], exc)
        return None


def _norm_pct(v: Optional[float]) -> Optional[float]:
    """Yüzde/oran normalize: >1 ise yüzde kabul edilir (5 → 0.05)."""
    if v is None:
        return None
    return v / 100.0 if v > 1.0 else v


def _norm_type(v: Any) -> str:
    s = str(v or "").strip().lower()
    if "cliff" in s:
        return CLIFF
    if "linear" in s or "continuous" in s or "stream" in s:
        return LINEAR
    return UNKNOWN_TYPE


def _norm_category(v: Any) -> str:
    s = str(v or "").strip().lower()
    for key in _CAT_FACTOR:
        if key in s:
            return key if key in (TEAM, INVESTOR, ECOSYSTEM, PUBLIC, COMMUNITY) else key
    if "found" in s or "core" in s:
        return TEAM
    if "seed" in s or "series" in s or "backer" in s:
        return INVESTOR
    return UNKNOWN_CAT


# ── 1) Unlock olayı ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class UnlockEvent:
    date_ms: float
    pct_of_circulating: float       # 0..1
    unlock_type: str                # cliff | linear | unknown
    category: str                   # team | investor | ecosystem | ...
    days_until: float               # negatif = geçmiş
    severity: float                 # 0..1 (intrinsik tehlike: pct × tip × kategori)
    label: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date_ms": self.date_ms,
            "pct_of_circulating": self.pct_of_circulating,
            "unlock_type": self.unlock_type,
            "category": self.category,
            "days_until": self.days_until,
            "severity": self.severity,
            "label": self.label,
        }


def event_severity(pct_of_circulating: float, unlock_type: str, category: str) -> float:
    """Intrinsik tehlike: büyüklük × (cliff/linear) × (team/ecosystem). 0..1."""
    mag = _clamp01(pct_of_circulating / 0.08)   # %8 → ~max büyüklük
    type_f = _TYPE_FACTOR.get(unlock_type, 0.75)
    cat_f = _CAT_FACTOR.get(category, 0.7)
    danger = type_f * cat_f                      # ~0.25..1.0
    return _clamp01(mag * (0.45 + 0.55 * danger))


def normalize_event(raw: Dict[str, Any], *, circulating_supply: Optional[float], now_ms: float) -> Optional[UnlockEvent]:
    """Ham unlock kaydını UnlockEvent'e çevirir. Geçersizse None."""
    if not isinstance(raw, dict):
        return None
    date_ms = _coerce_float(raw.get("date_ms"))
    if date_ms is None:
        ts = _coerce_float(raw.get("unlock_at_ms") or raw.get("ts_ms") or raw.get("timestamp"))
        if ts is not None:
            date_ms = ts if ts > 1e11 else ts * 1000.0
    if date_ms is None:
        return None

    pct = _norm_pct(_coerce_float(raw.get("pct_of_circulating") or raw.get("pct") or raw.get("supply_pct")))
    if pct is None:
        amount = _coerce_float(raw.get("amount") or raw.get("amount_tokens") or raw.get("tokens"))
        if amount is not None and circulating_supply and circulating_supply > 0:
            pct = amount / circulating_supply
    if pct is None:
        return None
    pct = _clamp01(pct)

    utype = _norm_type(raw.get("unlock_type") or raw.get("type") or raw.get("vesting"))
    cat = _norm_category(raw.get("category") or raw.get("recipient") or raw.get("allocation"))
    days_until = (date_ms - now_ms) / _DAY_MS
    sev = event_severity(pct, utype, cat)
    return UnlockEvent(
        date_ms=float(date_ms),
        pct_of_circulating=float(pct),
        unlock_type=utype,
        category=cat,
        days_until=float(days_until),
        severity=float(sev),
        label=str(raw.get("label") or raw.get("name") or ""),
    )


# ── 2) Pencere özeti ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class WindowSummary:
    window_days: float
    count: int
    total_pct: float        # toplam unlock / circulating (0..1)
    max_pct: float          # tek en büyük unlock (0..1)
    max_severity: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "window_days": self.window_days,
            "count": self.count,
            "total_pct": self.total_pct,
            "max_pct": self.max_pct,
            "max_severity": self.max_severity,
        }


def _window_summary(events: Sequence[UnlockEvent], window_days: float) -> WindowSummary:
    rel = [e for e in events if 0.0 <= e.days_until <= window_days]
    if not rel:
        return WindowSummary(window_days, 0, 0.0, 0.0, 0.0)
    total = _clamp01(sum(e.pct_of_circulating for e in rel))
    max_pct = max(e.pct_of_circulating for e in rel)
    max_sev = max(e.severity for e in rel)
    return WindowSummary(window_days, len(rel), float(total), float(max_pct), float(max_sev))


# ── 3) Geçmiş unlock davranışı (backtest) ────────────────────────────────────


@dataclass(frozen=True)
class UnlockHistoryStats:
    sample_size: int
    avg_post_move_pct: float    # önceki unlock'lar sonrası ortalama hareket
    sold_rate: float            # team token'ı satma oranı (0..1)
    worst_drawdown_pct: float   # en kötü unlock sonrası düşüş (negatif)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sample_size": self.sample_size,
            "avg_post_move_pct": self.avg_post_move_pct,
            "sold_rate": self.sold_rate,
            "worst_drawdown_pct": self.worst_drawdown_pct,
        }


def backtest_unlock_impact(history: Sequence[Dict[str, Any]]) -> UnlockHistoryStats:
    """Geçmiş unlock'ların fiyat etkisi.

    Her kayıt (esnek): ``post_move_pct`` (veya ``price_before``+``price_after``),
    ``team_sold`` (bool/0-1), ``drawdown_pct``.
    """
    moves: List[float] = []
    sold = 0
    sold_total = 0
    drawdowns: List[float] = []
    for h in history or []:
        if not isinstance(h, dict):
            continue
        mv = _coerce_float(h.get("post_move_pct"))
        if mv is None:
            pb = _coerce_float(h.get("price_before"))
            pa = _coerce_float(h.get("price_after"))
            if pb is not None and pa is not None and pb > 0:
                mv = (pa - pb) / pb
        if mv is not None:
            moves.append(mv)
        ts = h.get("team_sold")
        if ts is not None:
            sold_total += 1
            if bool(ts) is True or _coerce_float(ts) == 1.0:
                sold += 1
        dd = _coerce_float(h.get("drawdown_pct"))
        if dd is not None:
            drawdowns.append(dd)

    if not moves and not drawdowns:
        return UnlockHistoryStats(0, 0.0, 0.0, 0.0)
    avg_move = sum(moves) / len(moves) if moves else 0.0
    sold_rate = (sold / sold_total) if sold_total else 0.0
    worst_dd = min(drawdowns) if drawdowns else (min(moves) if moves else 0.0)
    return UnlockHistoryStats(
        sample_size=len(moves),
        avg_post_move_pct=float(avg_move),
        sold_rate=float(sold_rate),
        worst_drawdown_pct=float(worst_dd),
    )


# ── 4) Birleşik sinyal + otomatik risk ayarı ─────────────────────────────────


@dataclass(frozen=True)
class UnlockSignal:
    events: List[UnlockEvent]
    window_7d: WindowSummary
    window_30d: WindowSummary
    window_90d: WindowSummary
    history: Optional[UnlockHistoryStats]
    next_unlock_days: Optional[float]
    next_unlock_pct: Optional[float]
    risk_score: float                   # 0..1
    alpha_bias: float                   # -1..1 (yaklaşan ağır unlock → negatif)
    position_size_multiplier: float     # 0..1 (büyük unlock → küçült)
    trade_permission: str               # ALLOW | BLOCK | HALT
    urgent: bool                        # unlock + whale exchange transfer
    high_sell_pressure: bool            # >5% supply unlock yaklaşıyor
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "next_unlock_days": self.next_unlock_days,
            "next_unlock_pct": self.next_unlock_pct,
            "unlock_risk_score": self.risk_score,
            "unlock_alpha_bias": self.alpha_bias,
            "position_size_multiplier": self.position_size_multiplier,
            "trade_permission": self.trade_permission,
            "urgent": self.urgent,
            "high_sell_pressure": self.high_sell_pressure,
            "unlock_reasons": list(self.reasons),
            "window_7d": self.window_7d.to_dict(),
            "window_30d": self.window_30d.to_dict(),
            "window_90d": self.window_90d.to_dict(),
        }
        if self.history is not None:
            out["history"] = self.history.to_dict()
        return out


def _prox_factor(days_until: float) -> float:
    if days_until < 0:
        return 0.05
    if days_until <= 1.0:
        return 1.0
    if days_until <= WINDOW_7D:
        return 0.9
    if days_until <= WINDOW_30D:
        return 0.6
    if days_until <= WINDOW_90D:
        return 0.35
    return 0.1


def analyze_token_unlock(
    events: Sequence[Dict[str, Any]],
    *,
    circulating_supply: Optional[float] = None,
    history: Optional[Sequence[Dict[str, Any]]] = None,
    whale_exchange_inflow_usd: Optional[float] = None,
    now_ms: Optional[float] = None,
) -> Optional[UnlockSignal]:
    """Unlock takvimi + geçmiş + whale girişi → risk/alpha/pozisyon ayarı. Veri yoksa None."""
    if not events:
        return None
    now = float(now_ms) if now_ms is not None else _now_ms()
    parsed = [
        e for e in (normalize_event(r, circulating_supply=circulating_supply, now_ms=now) for r in events)
        if e is not None
    ]
    if not parsed:
        return None
    parsed.sort(key=lambda e: e.date_ms)

    w7 = _window_summary(parsed, WINDOW_7D)
    w30 = _window_summary(parsed, WINDOW_30D)
    w90 = _window_summary(parsed, WINDOW_90D)

    upcoming = [e for e in parsed if e.days_until >= 0.0]
    nxt = upcoming[0] if upcoming else None

    hist_stats = backtest_unlock_impact(history) if history else None

    reasons: List[str] = []

    # Risk: yaklaşan olayların proximity-ağırlıklı severity max'ı + 30g toplam baskı
    risk = 0.0
    for e in upcoming:
        risk = max(risk, e.severity * _prox_factor(e.days_until))
    risk = max(risk, 0.6 * w30.total_pct / max(HIGH_UNLOCK_PCT, 1e-9) * 0.5)
    risk = _clamp01(risk)

    high_sell = (w7.max_pct >= HIGH_UNLOCK_PCT) or (w30.max_pct >= HIGH_UNLOCK_PCT * 1.5)
    if w7.max_pct >= HIGH_UNLOCK_PCT:
        reasons.append(f"7 gün içinde %{w7.max_pct * 100:.1f} unlock → yüksek satış baskısı")
        risk = _clamp01(max(risk, 0.6))
    elif w30.max_pct >= HIGH_UNLOCK_PCT:
        reasons.append(f"30 gün içinde %{w30.max_pct * 100:.1f} unlock")

    if nxt is not None and nxt.unlock_type == CLIFF and nxt.pct_of_circulating >= 0.03:
        reasons.append(f"Cliff unlock ({nxt.category}) → tek seferde büyük arz")

    # Geçmiş davranış: önceki unlock'larda dump olduysa risk + negatif alpha
    if hist_stats is not None and hist_stats.sample_size >= 2:
        if hist_stats.avg_post_move_pct <= -0.02:
            risk = _clamp01(max(risk, 0.55))
            reasons.append(
                f"Geçmiş unlock'larda ort. {hist_stats.avg_post_move_pct * 100:.1f}% düşüş"
            )
        if hist_stats.sold_rate >= 0.6:
            reasons.append(f"Team geçmişte unlock'ları sattı (oran {hist_stats.sold_rate:.0%})")
            risk = _clamp01(max(risk, 0.45))

    # Otomatik pozisyon küçültme
    pos_mult = 1.0
    if w7.max_pct >= HIGH_UNLOCK_PCT or w7.max_severity >= 0.5:
        pos_mult = 0.5
    elif w30.max_pct >= HIGH_UNLOCK_PCT or w30.max_severity >= 0.5:
        pos_mult = 0.75

    # Acil risk: unlock yakın + büyük borsa girişi (whale transfer)
    whale_in = _coerce_float(whale_exchange_inflow_usd) or 0.0
    urgent = bool(
        whale_in >= WHALE_INFLOW_URGENT_USD
        and nxt is not None
        and 0.0 <= nxt.days_until <= WINDOW_7D
    )
    if urgent:
        reasons.append("Yaklaşan unlock + büyük borsa girişi (whale) → ACİL risk")
        risk = _clamp01(max(risk, 0.85))
        pos_mult = min(pos_mult, 0.4)

    # trade_permission
    perm = "ALLOW"
    if urgent:
        perm = "HALT"
    elif nxt is not None and 0.0 <= nxt.days_until <= 1.0 and nxt.pct_of_circulating >= 0.02:
        perm = "BLOCK"
        reasons.append("Unlock günü (≤24s) → BLOCK")
    elif w7.max_pct >= HIGH_UNLOCK_PCT:
        perm = "BLOCK"

    alpha_bias = -_clamp01(risk) * 0.85
    if hist_stats is not None and hist_stats.avg_post_move_pct <= -0.02:
        alpha_bias = _clamp(alpha_bias - 0.1, -1.0, 0.0)

    return UnlockSignal(
        events=parsed,
        window_7d=w7,
        window_30d=w30,
        window_90d=w90,
        history=hist_stats,
        next_unlock_days=float(nxt.days_until) if nxt else None,
        next_unlock_pct=float(nxt.pct_of_circulating) if nxt else None,
        risk_score=float(_clamp01(risk)),
        alpha_bias=float(_clamp(alpha_bias, -1.0, 1.0)),
        position_size_multiplier=float(pos_mult),
        trade_permission=perm,
        urgent=urgent,
        high_sell_pressure=bool(high_sell),
        reasons=reasons,
    )


def analyze_unlock_data(data: Dict[str, Any]) -> Optional[UnlockSignal]:
    """Düz dict köprüsü (news_event_intelligence / alternative_data_engine).

    Beklenen: ``token_unlock`` alt dict (``schedule``/``events`` listesi +
    ``circulating_supply``/``history``/``whale_exchange_inflow_usd``/``now_ms``)
    veya düz ``unlock_schedule`` listesi.
    """
    if not isinstance(data, dict):
        return None
    block = data.get("token_unlock") if isinstance(data.get("token_unlock"), dict) else {}
    events = block.get("schedule") or block.get("events") or data.get("unlock_schedule")
    if not isinstance(events, list) or not events:
        return None
    return analyze_token_unlock(
        events,
        circulating_supply=_coerce_float(
            block.get("circulating_supply") or data.get("circulating_supply")
        ),
        history=block.get("history") or data.get("unlock_history"),
        whale_exchange_inflow_usd=_coerce_float(
            block.get("whale_exchange_inflow_usd") or data.get("whale_exchange_inflow_usd")
        ),
        now_ms=_coerce_float(block.get("now_ms") or data.get("now_ms")),
    )


# ── Parser'lar ───────────────────────────────────────────────────────────────


def parse_token_unlocks_app(payload: Any) -> List[Dict[str, Any]]:
    """TokenUnlocks.app tarzı JSON → normalize unlock kaydı listesi.

    ``{"unlocks": [{"timestamp": ..., "percentOfCirculating": ..., "type": ...,
    "category": ...}, ...]}`` (veya doğrudan liste).
    """
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", errors="replace")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return []
    rows = payload.get("unlocks") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    out: List[Dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        out.append({
            "unlock_at_ms": r.get("timestamp") or r.get("date") or r.get("unlockDate"),
            "pct_of_circulating": r.get("percentOfCirculating") or r.get("pct") or r.get("supplyPct"),
            "amount": r.get("amount") or r.get("tokens"),
            "unlock_type": r.get("type") or r.get("unlockType"),
            "category": r.get("category") or r.get("allocation") or r.get("recipient"),
            "label": r.get("name") or r.get("label"),
        })
    return out


def parse_dune(payload: Any) -> List[Dict[str, Any]]:
    """Dune Analytics ``execution/results`` JSON → normalize unlock kaydı listesi.

    ``{"result": {"rows": [{"unlock_date": ..., "unlock_pct": ..., ...}, ...]}}``.
    """
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", errors="replace")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return []
    if not isinstance(payload, dict):
        return []
    result = payload.get("result")
    rows = result.get("rows") if isinstance(result, dict) else payload.get("rows")
    if not isinstance(rows, list):
        return []
    out: List[Dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        out.append({
            "unlock_at_ms": r.get("unlock_date_ms") or r.get("unlock_date") or r.get("date"),
            "pct_of_circulating": r.get("unlock_pct") or r.get("pct_of_circulating"),
            "amount": r.get("unlock_amount") or r.get("amount"),
            "unlock_type": r.get("unlock_type") or r.get("type"),
            "category": r.get("category") or r.get("allocation"),
            "label": r.get("project") or r.get("label"),
        })
    return out


# ── Collector ────────────────────────────────────────────────────────────────


class UnlockCollector:
    """TokenUnlocks.app / Dune Analytics unlock toplayıcı (mock'lanabilir)."""

    def __init__(self, *, http_get: Optional[HttpGet] = None, timeout_sec: float = 6.0) -> None:
        self._http_get: HttpGet = http_get or _default_http_get
        self._timeout = float(timeout_sec)

    def fetch_token_unlocks(self, symbol: str) -> List[Dict[str, Any]]:
        base = os.getenv("TOKEN_UNLOCKS_API_URL", "")
        if not base:
            return []
        sym = str(symbol or "").split("/")[0].upper()
        sep = "&" if "?" in base else "?"
        body = self._http_get(f"{base}{sep}symbol={sym}", self._timeout)
        return parse_token_unlocks_app(body) if body else []

    def fetch_dune(self, query_id: str) -> List[Dict[str, Any]]:
        api_key = os.getenv("DUNE_API_KEY", "")
        if not api_key:
            return []
        base = os.getenv("DUNE_API_URL", "https://api.dune.com/api/v1")
        body = self._http_get(f"{base}/query/{query_id}/results?api_key={api_key}", self._timeout)
        return parse_dune(body) if body else []


__all__ = [
    "CLIFF",
    "COMMUNITY",
    "ECOSYSTEM",
    "HIGH_UNLOCK_PCT",
    "INVESTOR",
    "LINEAR",
    "PUBLIC",
    "TEAM",
    "UNKNOWN_CAT",
    "UNKNOWN_TYPE",
    "UnlockCollector",
    "UnlockEvent",
    "UnlockHistoryStats",
    "UnlockSignal",
    "WindowSummary",
    "analyze_token_unlock",
    "analyze_unlock_data",
    "backtest_unlock_impact",
    "event_severity",
    "normalize_event",
    "parse_dune",
    "parse_token_unlocks_app",
]
