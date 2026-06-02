"""PROMPT-1.2 — Exchange Flow Intelligence + Faz 17 ``institutional_flow_usd`` feed.

Borsa giriş/çıkış akışları, rezerv değişimi ve stablecoin mint/burn takibi;
`smart_money_tracker` (Faz 17) için kurumsal akış proxy'si üretir.

İzlenen metrikler:
- Net exchange flow (tüm borsalar toplamı) — pozitif = net giriş (satış baskısı).
- Exchange reserve değişimi (BTC / ETH / stablecoin ayrı) — 7 günlük trend.
- Stablecoin mint/burn (USDT, USDC) — alım gücü proxy'si.
- Borsa başına flow karşılaştırması (Binance / Coinbase / Bybit ...).

Sinyal mantığı:
- BTC exchange reserve 7 günlük düşüş → BULLISH (birikim).
- Stablecoin borsaya toplu giriş → BULLISH (alım hazırlığı).
- BTC borsaya toplu giriş + stablecoin çıkış → BEARISH (satış).
- USDT büyük mint ($500M+) → BULLISH (yeni likidite).

Tasarım (whale_feed_collector ile aynı): enjekte edilebilir ``http_get``,
env-driven config, saf parser'lar, API anahtarı yoksa graceful boş dönüş.

Ortam değişkenleri:
- ``CRYPTOQUANT_API_KEY`` / ``CRYPTOQUANT_API_URL``
- ``GLASSNODE_API_KEY`` / ``GLASSNODE_API_URL``
- ``ETHERSCAN_API_KEY`` / ``ETHERSCAN_API_URL`` (USDT/USDC mint event'leri)
- ``STABLE_MINT_ALERT_USD`` (vars. 500000000), ``STABLE_INFLOW_ALERT_USD`` (vars. 100000000)
- ``BTC_INFLOW_ALERT_USD`` (vars. 100000000), ``FLOW_UPDATE_INTERVAL_SEC`` (vars. 300)
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

log = logging.getLogger("super_otonom.exchange_flow")

HttpGet = Callable[[str, float], Optional[str]]

_ZERO_ADDR = "0x0000000000000000000000000000000000000000"
_STABLES = ("USDT", "USDC")

# Bilinen stablecoin kontratları (mint/burn tespiti)
STABLECOIN_CONTRACTS = {
    "0xdac17f958d2ee523a2206206994597c13d831ec7": ("USDT", 6),
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": ("USDC", 6),
}

BULLISH = "BULLISH"
BEARISH = "BEARISH"
NEUTRAL = "NEUTRAL"


def _coerce_float(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _ts_to_ms(v: Any) -> int:
    f = _coerce_float(v)
    if f <= 0:
        return int(time.time() * 1000)
    return int(f * 1000) if f < 1e11 else int(f)


def _default_http_get(url: str, timeout: float) -> Optional[str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "super_otonom/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        log.debug("exchange_flow http_get hata (%s): %s", url[:60], exc)
        return None


# ── Veri yapıları ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ExchangeFlow:
    """Borsa-varlık akış anlık değeri (USD)."""

    exchange: str
    asset: str
    inflow_usd: float
    outflow_usd: float
    ts_ms: int = 0

    @property
    def netflow_usd(self) -> float:
        """Pozitif = net giriş (satış baskısı)."""
        return float(self.inflow_usd - self.outflow_usd)

    @property
    def is_stable(self) -> bool:
        return self.asset.upper() in _STABLES


@dataclass(frozen=True)
class ReservePoint:
    """Borsa rezerv zaman serisi noktası (USD)."""

    asset: str
    reserve_usd: float
    ts_ms: int = 0


@dataclass(frozen=True)
class StablecoinEvent:
    """Stablecoin mint (yeni arz) / burn (arz azalışı) olayı."""

    asset: str
    amount_usd: float
    kind: str  # "mint" | "burn"
    ts_ms: int = 0


@dataclass(frozen=True)
class FlowSignal:
    """Exchange flow sinyali (Faz 17 köprüsü için)."""

    direction: str  # BULLISH | BEARISH | NEUTRAL
    strength: float  # 0..1
    institutional_flow_usd: float
    net_exchange_flow_usd: float
    stablecoin_net_mint_usd: float
    reasons: List[str] = field(default_factory=list)
    per_exchange_netflow: Dict[str, float] = field(default_factory=dict)


# ── Parser'lar (saf, ağsız test edilir) ──────────────────────────────────────


def parse_cryptoquant_flow(payload: Any) -> List[ExchangeFlow]:
    """CryptoQuant exchange-flow JSON → ExchangeFlow listesi.

    Beklenen biçim (esnek): ``{"result":{"data":[{exchange,symbol,inflow,outflow,
    inflow_usd,outflow_usd,timestamp}]}}`` veya düz ``{"data":[...]}``.
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return []
    if not isinstance(payload, dict):
        return []
    rows = payload.get("data")
    if rows is None:
        rows = (payload.get("result") or {}).get("data") if isinstance(payload.get("result"), dict) else None
    if not isinstance(rows, list):
        return []
    out: List[ExchangeFlow] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        inflow = _coerce_float(r.get("inflow_usd", r.get("inflow")))
        outflow = _coerce_float(r.get("outflow_usd", r.get("outflow")))
        if inflow <= 0 and outflow <= 0:
            continue
        out.append(
            ExchangeFlow(
                exchange=str(r.get("exchange", "")).lower(),
                asset=str(r.get("symbol", r.get("asset", ""))).upper(),
                inflow_usd=inflow,
                outflow_usd=outflow,
                ts_ms=_ts_to_ms(r.get("timestamp", r.get("date"))),
            )
        )
    return out


def parse_glassnode_reserve(payload: Any, *, asset: str = "") -> List[ReservePoint]:
    """Glassnode exchange-balance JSON → ReservePoint zaman serisi.

    Beklenen biçim: ``[{"t": unix_sec, "v": reserve_value}, ...]``.
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return []
    if not isinstance(payload, list):
        return []
    out: List[ReservePoint] = []
    for pt in payload:
        if not isinstance(pt, dict):
            continue
        val = _coerce_float(pt.get("v"))
        if val <= 0:
            continue
        out.append(
            ReservePoint(asset=asset.upper(), reserve_usd=val, ts_ms=_ts_to_ms(pt.get("t")))
        )
    out.sort(key=lambda p: p.ts_ms)
    return out


def parse_stablecoin_mint(
    payload: Any,
    *,
    price_usd: float = 1.0,
) -> List[StablecoinEvent]:
    """Etherscan ``tokentx`` JSON → mint/burn olayları.

    Mint: ``from == 0x0`` (yeni arz). Burn: ``to == 0x0`` (arz azalışı).
    Kontrat adresi STABLECOIN_CONTRACTS'ta ise asset+decimals oradan alınır.
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return []
    if not isinstance(payload, dict):
        return []
    rows = payload.get("result")
    if not isinstance(rows, list):
        return []
    out: List[StablecoinEvent] = []
    for ev in rows:
        if not isinstance(ev, dict):
            continue
        frm = str(ev.get("from", "")).lower()
        to = str(ev.get("to", "")).lower()
        is_mint = frm == _ZERO_ADDR
        is_burn = to == _ZERO_ADDR
        if not (is_mint or is_burn):
            continue
        contract = str(ev.get("contractAddress", "")).lower()
        meta = STABLECOIN_CONTRACTS.get(contract)
        if meta is not None:
            asset, dec = meta
        else:
            asset = str(ev.get("tokenSymbol", "")).upper()
            dec = int(ev.get("tokenDecimal") or 6)
        qty = _coerce_float(ev.get("value")) / (10 ** dec)
        amount_usd = qty * price_usd
        if amount_usd <= 0:
            continue
        out.append(
            StablecoinEvent(
                asset=asset,
                amount_usd=amount_usd,
                kind="mint" if is_mint else "burn",
                ts_ms=_ts_to_ms(ev.get("timeStamp")),
            )
        )
    return out


# ── Sinyal yardımcıları ──────────────────────────────────────────────────────


def reserve_trend_7d(points: Sequence[ReservePoint], *, window_ms: int = 7 * 86_400_000) -> float:
    """Son `window_ms` içindeki rezerv yüzde değişimi (negatif = düşüş/birikim).

    Yetersiz veri → 0.0.
    """
    if len(points) < 2:
        return 0.0
    ordered = sorted(points, key=lambda p: p.ts_ms)
    last_ts = ordered[-1].ts_ms
    window = [p for p in ordered if last_ts - p.ts_ms <= window_ms]
    if len(window) < 2:
        window = ordered
    first = window[0].reserve_usd
    last = window[-1].reserve_usd
    if first <= 0:
        return 0.0
    return float((last - first) / first)


def net_exchange_flow_usd(flows: Sequence[ExchangeFlow]) -> float:
    """Tüm borsalar net akışı (pozitif = net giriş = satış baskısı)."""
    return float(sum(f.netflow_usd for f in flows))


def stablecoin_net_mint_usd(events: Sequence[StablecoinEvent]) -> float:
    """Net stablecoin arz değişimi (pozitif = net mint = yeni likidite)."""
    mint = sum(e.amount_usd for e in events if e.kind == "mint")
    burn = sum(e.amount_usd for e in events if e.kind == "burn")
    return float(mint - burn)


def per_exchange_netflow(flows: Sequence[ExchangeFlow]) -> Dict[str, float]:
    """Borsa başına net akış (Binance vs Coinbase vs Bybit ...)."""
    agg: Dict[str, float] = {}
    for f in flows:
        agg[f.exchange] = agg.get(f.exchange, 0.0) + f.netflow_usd
    return agg


# ── Ana motor ────────────────────────────────────────────────────────────────


class ExchangeFlowIntelligence:
    """Exchange flow/reserve/stablecoin takibi → Faz 17 ``institutional_flow_usd``."""

    def __init__(
        self,
        *,
        http_get: Optional[HttpGet] = None,
        stable_mint_alert_usd: Optional[float] = None,
        stable_inflow_alert_usd: Optional[float] = None,
        btc_inflow_alert_usd: Optional[float] = None,
        update_interval_sec: Optional[float] = None,
        timeout_sec: float = 5.0,
        alert_manager: Any = None,
    ) -> None:
        self._http_get: HttpGet = http_get or _default_http_get
        self.stable_mint_alert_usd = float(
            stable_mint_alert_usd
            if stable_mint_alert_usd is not None
            else os.getenv("STABLE_MINT_ALERT_USD", "500000000") or 500_000_000
        )
        self.stable_inflow_alert_usd = float(
            stable_inflow_alert_usd
            if stable_inflow_alert_usd is not None
            else os.getenv("STABLE_INFLOW_ALERT_USD", "100000000") or 100_000_000
        )
        self.btc_inflow_alert_usd = float(
            btc_inflow_alert_usd
            if btc_inflow_alert_usd is not None
            else os.getenv("BTC_INFLOW_ALERT_USD", "100000000") or 100_000_000
        )
        self.update_interval_sec = float(
            update_interval_sec
            if update_interval_sec is not None
            else os.getenv("FLOW_UPDATE_INTERVAL_SEC", "300") or 300
        )
        self._timeout = float(timeout_sec)
        self._alert_manager = alert_manager
        self._last_update_ms = 0

    # ── Kaynak fetch (mock'lanabilir) ────────────────────────────────────────
    def _fetch_cryptoquant(self) -> List[ExchangeFlow]:
        key = os.getenv("CRYPTOQUANT_API_KEY", "")
        base = os.getenv("CRYPTOQUANT_API_URL", "")
        if not key or not base:
            return []
        body = self._http_get(f"{base}?token={key}", self._timeout)
        return parse_cryptoquant_flow(body) if body else []

    def _fetch_glassnode_reserve(self, *, asset: str) -> List[ReservePoint]:
        key = os.getenv("GLASSNODE_API_KEY", "")
        base = os.getenv("GLASSNODE_API_URL", "")
        if not key or not base:
            return []
        body = self._http_get(f"{base}?a={asset}&api_key={key}", self._timeout)
        return parse_glassnode_reserve(body, asset=asset) if body else []

    def _fetch_stablecoin_mint(self) -> List[StablecoinEvent]:
        key = os.getenv("ETHERSCAN_API_KEY", "")
        base = os.getenv("ETHERSCAN_API_URL", "")
        if not key or not base:
            return []
        body = self._http_get(f"{base}?apikey={key}", self._timeout)
        return parse_stablecoin_mint(body) if body else []

    # ── Sinyal analizi ───────────────────────────────────────────────────────
    def analyze(
        self,
        flows: Sequence[ExchangeFlow],
        reserves_by_asset: Optional[Dict[str, Sequence[ReservePoint]]] = None,
        stable_events: Optional[Sequence[StablecoinEvent]] = None,
    ) -> FlowSignal:
        """4 kuralı uygular; FlowSignal + institutional_flow_usd üretir."""
        reserves_by_asset = reserves_by_asset or {}
        stable_events = stable_events or []

        net_flow = net_exchange_flow_usd(flows)
        net_mint = stablecoin_net_mint_usd(stable_events)
        per_ex = per_exchange_netflow(flows)

        # stablecoin borsa giriş (pozitif netflow, stable asset)
        stable_inflow = sum(f.netflow_usd for f in flows if f.is_stable)
        # BTC borsa giriş
        btc_inflow = sum(f.netflow_usd for f in flows if f.asset.upper() == "BTC")
        btc_trend = reserve_trend_7d(reserves_by_asset.get("BTC", []))
        max_mint = max(
            (e.amount_usd for e in stable_events if e.kind == "mint"), default=0.0
        )

        reasons: List[str] = []
        score = 0.0

        # 1) BTC reserve 7 günlük düşüş → BULLISH
        if btc_trend < 0:
            reasons.append(f"BTC rezerv 7g düşüş {btc_trend * 100:.1f}% (birikim)")
            score += min(0.30, abs(btc_trend) * 6.0)

        # 2) Stablecoin borsaya toplu giriş → BULLISH
        if stable_inflow >= self.stable_inflow_alert_usd:
            reasons.append(f"Stablecoin borsa girişi ${stable_inflow / 1e6:.0f}M (alım hazırlığı)")
            score += 0.25

        # 4) USDT büyük mint → BULLISH
        if max_mint >= self.stable_mint_alert_usd:
            reasons.append(f"Büyük stablecoin mint ${max_mint / 1e6:.0f}M (yeni likidite)")
            score += 0.25
        elif net_mint > 0:
            score += min(0.15, net_mint / max(self.stable_mint_alert_usd, 1.0) * 0.15)

        # 3) BTC borsaya toplu giriş + stablecoin çıkış → BEARISH
        bearish = 0.0
        if btc_inflow >= self.btc_inflow_alert_usd and stable_inflow < 0:
            reasons.append(
                f"BTC borsa girişi ${btc_inflow / 1e6:.0f}M + stablecoin çıkışı (satış)"
            )
            bearish += 0.45
        elif net_flow >= self.btc_inflow_alert_usd:
            reasons.append(f"Net borsa girişi ${net_flow / 1e6:.0f}M (satış baskısı)")
            bearish += min(0.30, net_flow / max(self.btc_inflow_alert_usd, 1.0) * 0.15)

        # institutional_flow_usd: pozitif = birikim/bullish
        institutional_flow_usd = net_mint - net_flow

        net_score = score - bearish
        if net_score >= 0.15:
            direction = BULLISH
        elif net_score <= -0.15:
            direction = BEARISH
        else:
            direction = NEUTRAL
        strength = min(1.0, abs(net_score))

        return FlowSignal(
            direction=direction,
            strength=float(strength),
            institutional_flow_usd=float(institutional_flow_usd),
            net_exchange_flow_usd=float(net_flow),
            stablecoin_net_mint_usd=float(net_mint),
            reasons=reasons,
            per_exchange_netflow=per_ex,
        )

    # ── Orkestrasyon ─────────────────────────────────────────────────────────
    def should_update(self, *, now_ms: Optional[int] = None) -> bool:
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        return (now - self._last_update_ms) >= int(self.update_interval_sec * 1000)

    def update(self, *, emit_alerts: bool = True) -> Dict[str, Any]:
        """5 dakikalık döngü: fetch → analiz → ``smart_money_data`` üret."""
        flows: List[ExchangeFlow] = []
        try:
            flows = self._fetch_cryptoquant()
        except Exception as exc:
            log.debug("cryptoquant fetch hata: %s", exc)
        reserves: Dict[str, List[ReservePoint]] = {}
        for asset in ("BTC", "ETH"):
            try:
                reserves[asset] = self._fetch_glassnode_reserve(asset=asset)
            except Exception as exc:
                log.debug("glassnode %s fetch hata: %s", asset, exc)
        stable_events: List[StablecoinEvent] = []
        try:
            stable_events = self._fetch_stablecoin_mint()
        except Exception as exc:
            log.debug("stablecoin mint fetch hata: %s", exc)

        signal = self.analyze(flows, reserves, stable_events)
        self._last_update_ms = int(time.time() * 1000)
        alerts = self.detect_alerts(signal, stable_events)
        if emit_alerts and alerts:
            self._dispatch_alerts(alerts)
        return self.to_smart_money_data(signal, alerts=alerts)

    def to_smart_money_data(
        self, signal: FlowSignal, *, alerts: Optional[Sequence[str]] = None
    ) -> Dict[str, Any]:
        """`analyze_smart_money` girdisi: institutional_flow_usd + exchange_netflow_usd."""
        return {
            "institutional_flow_usd": signal.institutional_flow_usd,
            "exchange_netflow_usd": signal.net_exchange_flow_usd,
            "stablecoin_net_mint_usd": signal.stablecoin_net_mint_usd,
            "flow_direction": signal.direction,
            "flow_strength": signal.strength,
            "per_exchange_netflow": signal.per_exchange_netflow,
            "flow_reasons": list(signal.reasons),
            "flow_alerts": list(alerts or []),
        }

    # ── Alert sistemi ────────────────────────────────────────────────────────
    def detect_alerts(
        self, signal: FlowSignal, stable_events: Sequence[StablecoinEvent]
    ) -> List[str]:
        alerts: List[str] = []
        max_mint = max((e.amount_usd for e in stable_events if e.kind == "mint"), default=0.0)
        if max_mint >= self.stable_mint_alert_usd:
            alerts.append("STABLE_MINT")
        if signal.net_exchange_flow_usd >= self.btc_inflow_alert_usd:
            alerts.append("EXCHANGE_INFLOW_SURGE")
        if signal.direction == BEARISH and signal.strength >= 0.4:
            alerts.append("SELL_PRESSURE")
        if signal.direction == BULLISH and signal.strength >= 0.4:
            alerts.append("ACCUMULATION")
        return alerts

    def _dispatch_alerts(self, alerts: Sequence[str]) -> None:
        am = self._alert_manager
        if am is None:
            return
        send = getattr(am, "system", None)
        if not callable(send):
            return
        for kind in alerts:
            sev = "WARNING" if kind in ("SELL_PRESSURE", "STABLE_MINT") else "INFO"
            try:
                send(f"FLOW_{kind}", kind, sev)
            except Exception as exc:
                log.debug("flow alert dispatch hata: %s", exc)


def run_exchange_flow_phase(
    symbol: str,
    engine: ExchangeFlowIntelligence,
    analysis: Optional[Dict[str, Any]] = None,
    *,
    attach_to_analysis: bool = True,
) -> Dict[str, Any]:
    """Exchange flow → Faz 17 ``analyze_smart_money`` → alpha/risk/perm."""
    from super_otonom.smart_money_tracker import analyze_smart_money

    data = engine.update()
    return analyze_smart_money(symbol, data, analysis, attach_to_analysis=attach_to_analysis)


__all__ = [
    "BEARISH",
    "BULLISH",
    "NEUTRAL",
    "STABLECOIN_CONTRACTS",
    "ExchangeFlow",
    "ExchangeFlowIntelligence",
    "FlowSignal",
    "ReservePoint",
    "StablecoinEvent",
    "net_exchange_flow_usd",
    "parse_cryptoquant_flow",
    "parse_glassnode_reserve",
    "parse_stablecoin_mint",
    "per_exchange_netflow",
    "reserve_trend_7d",
    "run_exchange_flow_phase",
    "stablecoin_net_mint_usd",
]
