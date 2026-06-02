"""PROMPT-1.3 — VC & Fund wallet takibi + Faz 17 ``vc_net_flow_usd`` feed.

Bilinen VC / fund cüzdanlarının token hareketlerini izler; `smart_money_tracker`
(Faz 17) için ``vc_net_flow_usd`` (kurumsal birikim proxy'si) üretir.

İzlenen kuruluşlar (``data/vc_fund_wallets.json``):
- a16z Crypto, Paradigm, Polychain, Pantera (VC)
- Jump Trading, Wintermute, Alameda, Galaxy Digital, Grayscale (fund)

Transfer sınıflandırma:
- ``acquire``           — VC/fund cüzdanı ALICI (birikim, +)
- ``distribute_dex``    — VC/fund → DEX (satış, −)
- ``distribute_cex``    — VC/fund → CEX (satış, −)
- ``distribute``        — VC/fund → diğer (−)

Sinyal üretimi:
- VC yeni token biriktiriyorsa → early alpha.
- VC toplu satış yapıyorsa → risk uyarısı.
- Birden fazla VC aynı token'a giriyorsa → conviction artışı.
- Token unlock sonrası dağıtım → yükseltilmiş risk (POST_UNLOCK_DUMP).

Tasarım (whale_feed_collector ile aynı): enjekte edilebilir ``http_get``,
env-driven config, saf parser'lar, API anahtarı yoksa graceful boş dönüş.

Ortam değişkenleri:
- ``ETHERSCAN_API_KEY`` / ``ETHERSCAN_API_URL``
- ``VC_MIN_USD`` (vars. 100000), ``VC_BULK_SELL_USD`` (vars. 5000000)
- ``VC_CONVICTION_MIN`` (vars. 2), ``VC_UNLOCK_WINDOW_SEC`` (vars. 259200 = 3 gün)
- ``VC_UPDATE_INTERVAL_SEC`` (vars. 300)
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

log = logging.getLogger("super_otonom.vc_fund")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_REGISTRY = _REPO_ROOT / "data" / "vc_fund_wallets.json"

HttpGet = Callable[[str, float], Optional[str]]

# Transfer yön token'ları
DIR_ACQUIRE = "acquire"
DIR_DISTRIBUTE_DEX = "distribute_dex"
DIR_DISTRIBUTE_CEX = "distribute_cex"
DIR_DISTRIBUTE = "distribute"

_DISTRIBUTE_DIRS = (DIR_DISTRIBUTE_DEX, DIR_DISTRIBUTE_CEX, DIR_DISTRIBUTE)


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
        log.debug("vc_fund http_get hata (%s): %s", url[:60], exc)
        return None


# ── Cüzdan etiket veritabanı ─────────────────────────────────────────────────


@dataclass(frozen=True)
class VcFundLabel:
    label: str
    entity: str
    type: str
    chain: str

    @property
    def is_vc(self) -> bool:
        return self.type == "vc"

    @property
    def is_fund(self) -> bool:
        return self.type == "fund"

    @property
    def is_tracked(self) -> bool:
        """İzlenen kuruluş (vc veya fund)."""
        return self.type in ("vc", "fund")

    @property
    def is_dex(self) -> bool:
        return self.type == "dex"

    @property
    def is_cex(self) -> bool:
        return self.type == "cex"


class VcFundRegistry:
    """Bilinen VC/fund cüzdanları + DEX/CEX venue etiketleri."""

    def __init__(self, wallets: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        self._wallets: Dict[str, VcFundLabel] = {}
        if wallets:
            for addr, meta in wallets.items():
                self._add(addr, meta)

    def _add(self, addr: str, meta: Dict[str, Any]) -> None:
        try:
            self._wallets[addr.strip().lower()] = VcFundLabel(
                label=str(meta.get("label", "")),
                entity=str(meta.get("entity", "")),
                type=str(meta.get("type", "")).lower(),
                chain=str(meta.get("chain", "")).lower(),
            )
        except Exception as exc:
            log.debug("VcFundRegistry _add hata (%s): %s", addr, exc)

    @classmethod
    def from_file(cls, path: Optional[Path] = None) -> "VcFundRegistry":
        p = path or _DEFAULT_REGISTRY
        try:
            raw = json.loads(Path(p).read_text(encoding="utf-8"))
            return cls(raw.get("wallets", {}))
        except Exception as exc:
            log.warning("VcFundRegistry yüklenemedi (%s): %s", p, exc)
            return cls({})

    def lookup(self, address: Optional[str]) -> Optional[VcFundLabel]:
        if not address:
            return None
        return self._wallets.get(str(address).strip().lower())

    def tracked_entities(self) -> List[str]:
        return sorted({lbl.entity for lbl in self._wallets.values() if lbl.is_tracked})

    def __len__(self) -> int:
        return len(self._wallets)


# ── Normalize edilmiş transfer + sinyal ──────────────────────────────────────


@dataclass(frozen=True)
class VcTransfer:
    """İzlenen VC/fund cüzdanı içeren normalize transfer."""

    tx_hash: str
    vc_entity: str
    vc_type: str   # vc | fund
    token: str
    amount_usd: float
    direction: str  # acquire | distribute_dex | distribute_cex | distribute
    chain: str = "ethereum"
    counterparty_entity: str = ""
    ts_ms: int = 0
    is_post_unlock: bool = False

    @property
    def is_acquire(self) -> bool:
        return self.direction == DIR_ACQUIRE

    @property
    def is_distribute(self) -> bool:
        return self.direction in _DISTRIBUTE_DIRS


@dataclass(frozen=True)
class VcFundSignal:
    """VC/fund akış sinyali (Faz 17 köprüsü)."""

    vc_net_flow_usd: float
    alpha_tokens: Dict[str, float] = field(default_factory=dict)  # token → net birikim USD
    risk_tokens: Dict[str, float] = field(default_factory=dict)   # token → net dağıtım USD
    conviction: Dict[str, int] = field(default_factory=dict)      # token → farklı VC sayısı
    reasons: List[str] = field(default_factory=list)


# ── Parser (saf, ağsız test edilir) ──────────────────────────────────────────


def parse_vc_transfers(
    payload: Any,
    registry: VcFundRegistry,
    *,
    price_usd: float = 0.0,
    decimals: int = 18,
    chain: str = "ethereum",
    unlock_events: Optional[Dict[str, int]] = None,
    unlock_window_ms: int = 3 * 86_400_000,
) -> List[VcTransfer]:
    """Etherscan ``tokentx`` JSON → izlenen VC/fund transferleri.

    Yalnızca from veya to bir VC/fund cüzdanı olan transferler döner.
    ``price_usd`` token birim fiyatı (0 ise satır atlanır).
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
    unlock_events = {k.upper(): v for k, v in (unlock_events or {}).items()}
    out: List[VcTransfer] = []
    for ev in rows:
        if not isinstance(ev, dict):
            continue
        from_lbl = registry.lookup(ev.get("from"))
        to_lbl = registry.lookup(ev.get("to"))
        from_tracked = from_lbl.is_tracked if from_lbl else False
        to_tracked = to_lbl.is_tracked if to_lbl else False
        if not (from_tracked or to_tracked):
            continue
        dec = int(ev.get("tokenDecimal") or decimals)
        qty = _coerce_float(ev.get("value")) / (10 ** dec) if dec >= 0 else _coerce_float(ev.get("value"))
        amount_usd = qty * price_usd
        if amount_usd <= 0:
            continue
        token = str(ev.get("tokenSymbol", "")).upper()
        ts_ms = _ts_to_ms(ev.get("timeStamp"))

        if to_tracked and not from_tracked:
            # VC alıcı → birikim
            entity, vctype = to_lbl.entity, to_lbl.type  # type: ignore[union-attr]
            direction = DIR_ACQUIRE
            counterparty = from_lbl.entity if from_lbl else ""
        else:
            # VC gönderici → dağıtım (hedef venue'ya göre)
            entity, vctype = from_lbl.entity, from_lbl.type  # type: ignore[union-attr]
            if to_lbl and to_lbl.is_dex:
                direction = DIR_DISTRIBUTE_DEX
            elif to_lbl and to_lbl.is_cex:
                direction = DIR_DISTRIBUTE_CEX
            else:
                direction = DIR_DISTRIBUTE
            counterparty = to_lbl.entity if to_lbl else ""

        is_post_unlock = False
        if direction in _DISTRIBUTE_DIRS and token in unlock_events:
            ut = unlock_events[token]
            is_post_unlock = 0 <= (ts_ms - ut) <= unlock_window_ms

        out.append(
            VcTransfer(
                tx_hash=str(ev.get("hash", "")),
                vc_entity=entity,
                vc_type=vctype,
                token=token,
                amount_usd=amount_usd,
                direction=direction,
                chain=chain,
                counterparty_entity=counterparty,
                ts_ms=ts_ms,
                is_post_unlock=is_post_unlock,
            )
        )
    return out


# ── Sinyal yardımcıları ──────────────────────────────────────────────────────


def compute_vc_net_flow_usd(transfers: Sequence[VcTransfer]) -> float:
    """Net VC akışı (USD): pozitif = birikim (bullish)."""
    acquire = sum(t.amount_usd for t in transfers if t.is_acquire)
    distribute = sum(t.amount_usd for t in transfers if t.is_distribute)
    return float(acquire - distribute)


def token_conviction(transfers: Sequence[VcTransfer]) -> Dict[str, int]:
    """Token → net birikim yapan farklı VC/fund kuruluş sayısı."""
    by_token: Dict[str, Dict[str, float]] = {}
    for t in transfers:
        ent = by_token.setdefault(t.token, {})
        ent[t.vc_entity] = ent.get(t.vc_entity, 0.0) + (
            t.amount_usd if t.is_acquire else -t.amount_usd
        )
    return {
        token: sum(1 for v in ents.values() if v > 0)
        for token, ents in by_token.items()
    }


# ── Tracker ──────────────────────────────────────────────────────────────────


class VcFundTracker:
    """VC/fund transfer takibi → Faz 17 ``vc_net_flow_usd``."""

    def __init__(
        self,
        *,
        registry: Optional[VcFundRegistry] = None,
        http_get: Optional[HttpGet] = None,
        min_usd: Optional[float] = None,
        bulk_sell_usd: Optional[float] = None,
        conviction_min: Optional[int] = None,
        unlock_window_sec: Optional[float] = None,
        update_interval_sec: Optional[float] = None,
        timeout_sec: float = 5.0,
        alert_manager: Any = None,
    ) -> None:
        self.registry = registry or VcFundRegistry.from_file()
        self._http_get: HttpGet = http_get or _default_http_get
        self.min_usd = float(
            min_usd if min_usd is not None else os.getenv("VC_MIN_USD", "100000") or 100_000
        )
        self.bulk_sell_usd = float(
            bulk_sell_usd
            if bulk_sell_usd is not None
            else os.getenv("VC_BULK_SELL_USD", "5000000") or 5_000_000
        )
        self.conviction_min = int(
            conviction_min
            if conviction_min is not None
            else os.getenv("VC_CONVICTION_MIN", "2") or 2
        )
        self.unlock_window_ms = int(
            float(
                unlock_window_sec
                if unlock_window_sec is not None
                else os.getenv("VC_UNLOCK_WINDOW_SEC", "259200") or 259_200
            )
            * 1000
        )
        self.update_interval_sec = float(
            update_interval_sec
            if update_interval_sec is not None
            else os.getenv("VC_UPDATE_INTERVAL_SEC", "300") or 300
        )
        self._timeout = float(timeout_sec)
        self._alert_manager = alert_manager
        self._last_update_ms = 0

    # ── Fetch (mock'lanabilir) ───────────────────────────────────────────────
    def _fetch_transfers(
        self,
        *,
        price_usd: float = 0.0,
        unlock_events: Optional[Dict[str, int]] = None,
    ) -> List[VcTransfer]:
        key = os.getenv("ETHERSCAN_API_KEY", "")
        base = os.getenv("ETHERSCAN_API_URL", "")
        if not key or not base or price_usd <= 0:
            return []
        body = self._http_get(f"{base}?apikey={key}", self._timeout)
        if not body:
            return []
        return parse_vc_transfers(
            body,
            self.registry,
            price_usd=price_usd,
            unlock_events=unlock_events,
            unlock_window_ms=self.unlock_window_ms,
        )

    # ── Sinyal analizi ───────────────────────────────────────────────────────
    def analyze(self, transfers: Sequence[VcTransfer]) -> VcFundSignal:
        """3 sinyal kuralı + net akış + conviction üretir."""
        net_flow = compute_vc_net_flow_usd(transfers)
        conviction = token_conviction(transfers)

        alpha_tokens: Dict[str, float] = {}
        risk_tokens: Dict[str, float] = {}
        for t in transfers:
            if t.is_acquire:
                alpha_tokens[t.token] = alpha_tokens.get(t.token, 0.0) + t.amount_usd
            elif t.is_distribute:
                risk_tokens[t.token] = risk_tokens.get(t.token, 0.0) + t.amount_usd

        reasons: List[str] = []
        # 1) VC yeni token biriktiriyor → early alpha
        for token, usd in alpha_tokens.items():
            if usd >= self.min_usd:
                reasons.append(f"VC birikim {token} ${usd / 1e6:.1f}M (early alpha)")
        # 2) VC toplu satış → risk
        for token, usd in risk_tokens.items():
            if usd >= self.bulk_sell_usd:
                reasons.append(f"VC toplu satış {token} ${usd / 1e6:.1f}M (risk)")
        # 3) Birden fazla VC aynı token → conviction
        for token, n in conviction.items():
            if n >= self.conviction_min:
                reasons.append(f"{n} farklı VC {token} biriktiriyor (conviction)")

        return VcFundSignal(
            vc_net_flow_usd=float(net_flow),
            alpha_tokens=alpha_tokens,
            risk_tokens=risk_tokens,
            conviction=conviction,
            reasons=reasons,
        )

    # ── Orkestrasyon ─────────────────────────────────────────────────────────
    def should_update(self, *, now_ms: Optional[int] = None) -> bool:
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        return (now - self._last_update_ms) >= int(self.update_interval_sec * 1000)

    def update(
        self,
        *,
        price_usd: float = 0.0,
        unlock_events: Optional[Dict[str, int]] = None,
        emit_alerts: bool = True,
    ) -> Dict[str, Any]:
        """5 dakikalık döngü: fetch → analiz → ``smart_money_data`` üret."""
        transfers = self._fetch_transfers(price_usd=price_usd, unlock_events=unlock_events)
        signal = self.analyze(transfers)
        self._last_update_ms = int(time.time() * 1000)
        alerts = self.detect_alerts(signal, transfers)
        if emit_alerts and alerts:
            self._dispatch_alerts(alerts)
        return self.to_smart_money_data(signal, alerts=alerts)

    def to_smart_money_data(
        self, signal: VcFundSignal, *, alerts: Optional[Sequence[str]] = None
    ) -> Dict[str, Any]:
        """`analyze_smart_money` girdisi: vc_net_flow_usd + meta."""
        return {
            "vc_net_flow_usd": signal.vc_net_flow_usd,
            "vc_alpha_tokens": dict(signal.alpha_tokens),
            "vc_risk_tokens": dict(signal.risk_tokens),
            "vc_conviction": dict(signal.conviction),
            "vc_reasons": list(signal.reasons),
            "vc_alerts": list(alerts or []),
        }

    # ── Alert sistemi ────────────────────────────────────────────────────────
    def detect_alerts(
        self, signal: VcFundSignal, transfers: Sequence[VcTransfer]
    ) -> List[str]:
        alerts: List[str] = []
        if any(usd >= self.min_usd for usd in signal.alpha_tokens.values()):
            alerts.append("EARLY_ALPHA")
        if any(usd >= self.bulk_sell_usd for usd in signal.risk_tokens.values()):
            alerts.append("VC_BULK_SELL")
        if any(n >= self.conviction_min for n in signal.conviction.values()):
            alerts.append("CONVICTION")
        if any(t.is_post_unlock for t in transfers):
            alerts.append("POST_UNLOCK_DUMP")
        return alerts

    def _dispatch_alerts(self, alerts: Sequence[str]) -> None:
        am = self._alert_manager
        if am is None:
            return
        send = getattr(am, "system", None)
        if not callable(send):
            return
        for kind in alerts:
            sev = "WARNING" if kind in ("VC_BULK_SELL", "POST_UNLOCK_DUMP") else "INFO"
            try:
                send(f"VC_{kind}", kind, sev)
            except Exception as exc:
                log.debug("vc alert dispatch hata: %s", exc)


def run_vc_fund_phase(
    symbol: str,
    tracker: VcFundTracker,
    analysis: Optional[Dict[str, Any]] = None,
    *,
    price_usd: float = 0.0,
    unlock_events: Optional[Dict[str, int]] = None,
    attach_to_analysis: bool = True,
) -> Dict[str, Any]:
    """VC/fund feed → Faz 17 ``analyze_smart_money`` → alpha/risk/perm."""
    from super_otonom.smart_money_tracker import analyze_smart_money

    data = tracker.update(price_usd=price_usd, unlock_events=unlock_events)
    return analyze_smart_money(symbol, data, analysis, attach_to_analysis=attach_to_analysis)


__all__ = [
    "DIR_ACQUIRE",
    "DIR_DISTRIBUTE",
    "DIR_DISTRIBUTE_CEX",
    "DIR_DISTRIBUTE_DEX",
    "VcFundLabel",
    "VcFundRegistry",
    "VcFundSignal",
    "VcFundTracker",
    "VcTransfer",
    "compute_vc_net_flow_usd",
    "parse_vc_transfers",
    "run_vc_fund_phase",
    "token_conviction",
]
