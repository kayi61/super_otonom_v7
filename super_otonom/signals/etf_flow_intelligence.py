"""PROMPT-7.1 — Bitcoin/Ethereum ETF Flow Tracker + Faz 17 ``etf_net_flow_usd``.

Kripto spot ETF akışlarını takip eder; `smart_money_tracker` (Faz 17) için
``etf_net_flow_usd`` (kurumsal talep proxy'si) üretir.

1. **BTC Spot ETF**: günlük net flow (GBTC/IBIT/FBTC/ARKB/BITB...), AUM trendi,
   ETF bazında karşılaştırma, GBTC outflow vs IBIT inflow dinamiği.
2. **ETH Spot ETF**: aynı metrikler (ETHA/FETH/ETHE...).
3. **Kurumsal pozisyon**: CME futures OI (proxy), Grayscale premium/discount, 13F.
4. **Sinyal**:
   - 5+ gün üst üste net inflow → güçlü kurumsal talep
   - GBTC büyük outflow + diğerleri inflow → rotation (nötr)
   - Tüm ETF'ler outflow → kurumsal satış baskısı
   - ETF volume spike → kurumsal ilgi artışı

Kaynak: SoSoValue API / farside.co (enjekte edilebilir ``http_get``, anahtar
opsiyonel). Tüm parser/analiz fonksiyonları saftır (ağsız test edilir).

Ortam değişkenleri: ``SOSOVALUE_API_URL`` / ``SOSOVALUE_API_KEY`` / ``FARSIDE_API_URL``,
``ETF_INFLOW_STREAK_DAYS`` (vars. 5), ``ETF_VOLUME_SPIKE_MULT`` (vars. 2),
``ETF_UPDATE_INTERVAL_SEC`` (vars. 3600).
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

log = logging.getLogger("super_otonom.etf_flow")

HttpGet = Callable[[str, float], Optional[str]]

# Bilinen spot ETF ticker'ları
BTC_ETFS = frozenset({"GBTC", "IBIT", "FBTC", "ARKB", "BITB", "BTCO", "EZBC", "BRRR", "HODL", "BTCW"})
ETH_ETFS = frozenset({"ETHA", "FETH", "ETHW", "CETH", "ETHV", "EZET", "QETH", "ETHE", "ETH"})
GRAYSCALE_ETFS = frozenset({"GBTC", "ETHE"})  # legacy, yüksek ücret → outflow eğilimi

# Sinyaller
DEMAND_STRONG = "strong_institutional_demand"
ROTATION = "rotation"
SELLING_PRESSURE = "institutional_selling"
VOLUME_SPIKE = "volume_spike"
NEUTRAL = "neutral"


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
        log.debug("etf http_get hata (%s): %s", url[:60], exc)
        return None


def classify_asset(ticker: str) -> Optional[str]:
    t = ticker.strip().upper()
    if t in BTC_ETFS:
        return "BTC"
    if t in ETH_ETFS:
        return "ETH"
    return None


# ── Veri yapıları ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class EtfFlow:
    ticker: str
    asset: str            # BTC | ETH
    net_flow_usd: float   # pozitif = inflow
    aum_usd: float = 0.0
    volume_usd: float = 0.0
    ts_ms: int = 0

    @property
    def is_grayscale(self) -> bool:
        return self.ticker.upper() in GRAYSCALE_ETFS


@dataclass(frozen=True)
class EtfFlowSignal:
    asset: str
    total_net_flow_usd: float
    total_aum_usd: float
    per_etf: Dict[str, float]            # ticker → net flow
    inflow_streak_days: int
    signal: str                          # demand_strong | rotation | selling | volume_spike | neutral
    grayscale_premium_pct: Optional[float]
    cme_oi_usd: Optional[float]
    alpha_bias: float                    # -1..1
    reasons: List[str] = field(default_factory=list)

    @property
    def etf_net_flow_usd(self) -> float:
        return self.total_net_flow_usd


# ── Parser'lar (saf, ağsız test edilir) ──────────────────────────────────────


def _ts_to_ms(v: Any) -> int:
    f = _coerce_float(v)
    if f is None or f <= 0:
        return int(time.time() * 1000)
    return int(f * 1000) if f < 1e11 else int(f)


def parse_sosovalue(payload: Any) -> List[EtfFlow]:
    """SoSoValue benzeri ETF flow JSON → EtfFlow listesi.

    Beklenen (esnek): ``{"data":[{ticker,asset?,net_flow_usd,aum_usd?,volume_usd?,date?}]}``.
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return []
    if isinstance(payload, dict):
        rows = payload.get("data") or payload.get("result") or payload.get("etfs")
    else:
        rows = payload
    if not isinstance(rows, list):
        return []
    out: List[EtfFlow] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        ticker = str(r.get("ticker") or r.get("symbol") or "").upper()
        if not ticker:
            continue
        asset = str(r.get("asset") or "").upper() or classify_asset(ticker)
        if asset not in ("BTC", "ETH"):
            continue
        nf = _coerce_float(r.get("net_flow_usd") or r.get("net_flow") or r.get("flow_usd"))
        if nf is None:
            continue
        out.append(
            EtfFlow(
                ticker=ticker,
                asset=asset,
                net_flow_usd=nf,
                aum_usd=_coerce_float(r.get("aum_usd") or r.get("aum")) or 0.0,
                volume_usd=_coerce_float(r.get("volume_usd") or r.get("volume")) or 0.0,
                ts_ms=_ts_to_ms(r.get("date") or r.get("timestamp")),
            )
        )
    return out


def parse_farside(payload: Any, *, asset: str = "BTC") -> List[EtfFlow]:
    """farside.co tablo formatı → EtfFlow listesi.

    Beklenen (esnek): ``{"rows":[{ticker,flow}], "asset":...}`` veya
    ``[{"ticker":..,"flow":..}]`` (flow milyon USD ise ``flow_unit='M'``).
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return []
    unit = 1.0
    if isinstance(payload, dict):
        rows = payload.get("rows") or payload.get("data")
        asset = str(payload.get("asset") or asset).upper()
        if str(payload.get("flow_unit", "")).upper() == "M":
            unit = 1e6
    else:
        rows = payload
    if not isinstance(rows, list):
        return []
    out: List[EtfFlow] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        ticker = str(r.get("ticker") or r.get("etf") or "").upper()
        flow = _coerce_float(r.get("flow") or r.get("net_flow") or r.get("flow_usd"))
        if not ticker or flow is None:
            continue
        a = classify_asset(ticker) or asset
        out.append(
            EtfFlow(
                ticker=ticker,
                asset=a,
                net_flow_usd=flow * unit,
                aum_usd=(_coerce_float(r.get("aum")) or 0.0) * (unit if unit > 1 else 1.0),
                volume_usd=(_coerce_float(r.get("volume")) or 0.0),
                ts_ms=_ts_to_ms(r.get("date")),
            )
        )
    return out


# ── Sinyal yardımcıları ──────────────────────────────────────────────────────


def compute_etf_net_flow_usd(flows: Sequence[EtfFlow]) -> float:
    """Toplam net ETF akışı (pozitif = inflow)."""
    return float(sum(f.net_flow_usd for f in flows))


def inflow_streak(daily_net_flows: Sequence[float]) -> int:
    """Son ardışık pozitif net inflow gün sayısı."""
    streak = 0
    for v in reversed([f for f in (_coerce_float(x) for x in daily_net_flows) if f is not None]):
        if v > 0:
            streak += 1
        else:
            break
    return streak


def detect_rotation(flows: Sequence[EtfFlow]) -> bool:
    """GBTC (Grayscale) büyük outflow + diğerlerinde inflow → rotation."""
    gs_out = sum(f.net_flow_usd for f in flows if f.is_grayscale and f.net_flow_usd < 0)
    others_in = sum(f.net_flow_usd for f in flows if not f.is_grayscale and f.net_flow_usd > 0)
    return gs_out < 0 and others_in > 0 and others_in >= abs(gs_out) * 0.5


# ── Ana motor ────────────────────────────────────────────────────────────────


class EtfFlowTracker:
    """BTC/ETH spot ETF flow takibi → Faz 17 ``etf_net_flow_usd``."""

    def __init__(
        self,
        *,
        http_get: Optional[HttpGet] = None,
        inflow_streak_days: Optional[int] = None,
        volume_spike_mult: Optional[float] = None,
        update_interval_sec: Optional[float] = None,
        timeout_sec: float = 5.0,
        alert_manager: Any = None,
    ) -> None:
        self._http_get: HttpGet = http_get or _default_http_get
        self.inflow_streak_days = int(
            inflow_streak_days
            if inflow_streak_days is not None
            else os.getenv("ETF_INFLOW_STREAK_DAYS", "5") or 5
        )
        self.volume_spike_mult = float(
            volume_spike_mult
            if volume_spike_mult is not None
            else os.getenv("ETF_VOLUME_SPIKE_MULT", "2") or 2
        )
        self.update_interval_sec = float(
            update_interval_sec
            if update_interval_sec is not None
            else os.getenv("ETF_UPDATE_INTERVAL_SEC", "3600") or 3600
        )
        self._timeout = float(timeout_sec)
        self._alert_manager = alert_manager
        self._last_update_ms = 0

    # ── Fetch (mock'lanabilir) ───────────────────────────────────────────────
    def _fetch_sosovalue(self) -> List[EtfFlow]:
        base = os.getenv("SOSOVALUE_API_URL", "")
        if not base:
            return []
        key = os.getenv("SOSOVALUE_API_KEY", "")
        url = f"{base}?apikey={key}" if key else base
        body = self._http_get(url, self._timeout)
        return parse_sosovalue(body) if body else []

    def _fetch_farside(self, *, asset: str = "BTC") -> List[EtfFlow]:
        base = os.getenv("FARSIDE_API_URL", "")
        if not base:
            return []
        body = self._http_get(f"{base}?asset={asset}", self._timeout)
        return parse_farside(body, asset=asset) if body else []

    def collect(self) -> List[EtfFlow]:
        flows: List[EtfFlow] = []
        for fetch in (self._fetch_sosovalue, lambda: self._fetch_farside(asset="BTC"),
                      lambda: self._fetch_farside(asset="ETH")):
            try:
                flows.extend(fetch())
            except Exception as exc:
                log.debug("etf collect kaynak hata: %s", exc)
        return flows

    # ── Sinyal analizi ───────────────────────────────────────────────────────
    def analyze(
        self,
        flows: Sequence[EtfFlow],
        *,
        asset: str = "BTC",
        daily_net_flow_history: Optional[Sequence[float]] = None,
        avg_volume_usd: Optional[float] = None,
        grayscale_premium_pct: Optional[float] = None,
        cme_oi_usd: Optional[float] = None,
    ) -> EtfFlowSignal:
        """4 sinyal kuralı + net flow + streak + kurumsal proxy'ler."""
        asset_flows = [f for f in flows if f.asset == asset.upper()]
        total_net = compute_etf_net_flow_usd(asset_flows)
        total_aum = sum(f.aum_usd for f in asset_flows)
        per_etf = {f.ticker: f.net_flow_usd for f in asset_flows}
        streak = inflow_streak(daily_net_flow_history or [])

        total_vol = sum(f.volume_usd for f in asset_flows)
        vol_spike = (
            avg_volume_usd is not None
            and avg_volume_usd > 1e-9
            and total_vol >= avg_volume_usd * self.volume_spike_mult
        )

        reasons: List[str] = []
        alpha = 0.0
        signal = NEUTRAL

        all_outflow = (
            bool(asset_flows)
            and total_net < 0
            and all(f.net_flow_usd <= 0 for f in asset_flows)
        )
        rotation = detect_rotation(asset_flows)

        if streak >= self.inflow_streak_days:
            signal = DEMAND_STRONG
            alpha = _clamp(0.4 + 0.05 * (streak - self.inflow_streak_days), 0.0, 1.0)
            reasons.append(f"{streak} gün üst üste net inflow (güçlü kurumsal talep)")
        elif all_outflow:
            signal = SELLING_PRESSURE
            alpha = -0.5
            reasons.append("Tüm ETF'lerde outflow (kurumsal satış baskısı)")
        elif rotation:
            signal = ROTATION
            alpha = 0.0
            reasons.append("GBTC outflow + diğerlerinde inflow (rotation, nötr)")
        elif total_net > 0:
            alpha = _clamp(total_net / 5e8, 0.0, 0.4)
        elif total_net < 0:
            alpha = _clamp(total_net / 5e8, -0.4, 0.0)

        if vol_spike:
            if signal == NEUTRAL:
                signal = VOLUME_SPIKE
            reasons.append("ETF volume spike (kurumsal ilgi artışı)")

        # Grayscale discount (negatif premium) → potansiyel birikim, hafif pozitif
        if grayscale_premium_pct is not None and grayscale_premium_pct < -0.05:
            alpha = _clamp(alpha + 0.1, -1.0, 1.0)
            reasons.append(f"Grayscale discount {grayscale_premium_pct * 100:.1f}%")

        return EtfFlowSignal(
            asset=asset.upper(),
            total_net_flow_usd=float(total_net),
            total_aum_usd=float(total_aum),
            per_etf=per_etf,
            inflow_streak_days=streak,
            signal=signal,
            grayscale_premium_pct=grayscale_premium_pct,
            cme_oi_usd=cme_oi_usd,
            alpha_bias=float(alpha),
            reasons=reasons,
        )

    # ── Orkestrasyon ─────────────────────────────────────────────────────────
    def should_update(self, *, now_ms: Optional[int] = None) -> bool:
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        return (now - self._last_update_ms) >= int(self.update_interval_sec * 1000)

    def update(
        self,
        *,
        asset: str = "BTC",
        daily_net_flow_history: Optional[Sequence[float]] = None,
        avg_volume_usd: Optional[float] = None,
        grayscale_premium_pct: Optional[float] = None,
        cme_oi_usd: Optional[float] = None,
        emit_alerts: bool = True,
    ) -> Dict[str, Any]:
        """Günlük döngü adımı: topla → analiz → ``smart_money_data`` üret."""
        flows = self.collect()
        signal = self.analyze(
            flows, asset=asset, daily_net_flow_history=daily_net_flow_history,
            avg_volume_usd=avg_volume_usd, grayscale_premium_pct=grayscale_premium_pct,
            cme_oi_usd=cme_oi_usd,
        )
        self._last_update_ms = int(time.time() * 1000)
        if emit_alerts and signal.signal in (DEMAND_STRONG, SELLING_PRESSURE):
            self._dispatch(signal)
        return self.to_smart_money_data(signal)

    def to_smart_money_data(self, signal: EtfFlowSignal) -> Dict[str, Any]:
        """`analyze_smart_money` girdisi: etf_net_flow_usd + meta."""
        return {
            "etf_net_flow_usd": signal.etf_net_flow_usd,
            "etf_asset": signal.asset,
            "etf_signal": signal.signal,
            "etf_inflow_streak_days": signal.inflow_streak_days,
            "etf_total_aum_usd": signal.total_aum_usd,
            "etf_per_etf_flow": dict(signal.per_etf),
            "etf_reasons": list(signal.reasons),
        }

    def _dispatch(self, signal: EtfFlowSignal) -> None:
        am = self._alert_manager
        if am is None:
            return
        send = getattr(am, "system", None)
        if not callable(send):
            return
        sev = "WARNING" if signal.signal == SELLING_PRESSURE else "INFO"
        try:
            send(f"ETF_{signal.signal.upper()}", "; ".join(signal.reasons), sev)
        except Exception as exc:
            log.debug("etf alert dispatch hata: %s", exc)


def run_etf_flow_phase(
    symbol: str,
    tracker: EtfFlowTracker,
    analysis: Optional[Dict[str, Any]] = None,
    *,
    asset: str = "BTC",
    daily_net_flow_history: Optional[Sequence[float]] = None,
    attach_to_analysis: bool = True,
) -> Dict[str, Any]:
    """ETF feed → Faz 17 ``analyze_smart_money`` → alpha/risk/perm."""
    from super_otonom.smart_money_tracker import analyze_smart_money

    data = tracker.update(asset=asset, daily_net_flow_history=daily_net_flow_history)
    return analyze_smart_money(symbol, data, analysis, attach_to_analysis=attach_to_analysis)


__all__ = [
    "BTC_ETFS",
    "DEMAND_STRONG",
    "ETH_ETFS",
    "GRAYSCALE_ETFS",
    "NEUTRAL",
    "ROTATION",
    "SELLING_PRESSURE",
    "VOLUME_SPIKE",
    "EtfFlow",
    "EtfFlowSignal",
    "EtfFlowTracker",
    "classify_asset",
    "compute_etf_net_flow_usd",
    "detect_rotation",
    "inflow_streak",
    "parse_farside",
    "parse_sosovalue",
    "run_etf_flow_phase",
]
