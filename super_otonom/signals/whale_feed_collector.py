"""PROMPT-1.1 — Gerçek zamanlı whale wallet takip + Faz 17 feed bağlantısı.

`WhaleFeedCollector` ücretsiz on-chain veri kaynaklarından (Whale Alert,
Etherscan/BSCScan, Blockchain.com) büyük transferleri toplar, normalize eder,
borsa-yönü sınıflandırır ve `smart_money_tracker` (Faz 17) için
``smart_money_data`` üretir.

Tasarım:
- **CI-safe / mock'lanabilir**: HTTP katmanı enjekte edilebilir ``http_get``
  callable'ı üzerinden; API anahtarı yoksa kaynak sessizce boş döner. Parser'lar
  saf fonksiyonlardır (ağsız test edilir).
- **Bloke etmeyen tasarım hedefi**: `urllib` + kısa timeout; hata → boş liste.
- **Faz 17 uyumu**: ``direction`` token'ları (``to_exchange`` / ``from_exchange`` /
  ``cold_storage`` / ``internal``) `analyze_smart_money` ile birebir eşleşir.

Ortam değişkenleri:
- ``WHALE_ALERT_API_KEY`` / ``WHALE_ALERT_API_URL``
- ``ETHERSCAN_API_KEY`` / ``ETHERSCAN_API_URL``
- ``BLOCKCHAIN_BTC_API_URL``
- ``WHALE_MIN_USD`` (vars. 500000), ``WHALE_UPDATE_INTERVAL_SEC`` (vars. 300)
- ``WHALE_LARGE_ALERT_USD`` (vars. 10000000)
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

log = logging.getLogger("super_otonom.whale_feed")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_REGISTRY = _REPO_ROOT / "data" / "whale_wallets.json"

# Faz 17 direction token'ları
DIR_TO_EXCHANGE = "to_exchange"      # borsaya giriş → satış baskısı
DIR_FROM_EXCHANGE = "from_exchange"  # borsadan çıkış → birikim
DIR_COLD_STORAGE = "cold_storage"    # soğuk cüzdana → güçlü birikim
DIR_INTERNAL = "internal"            # borsa-içi / etiketsiz → nötr

_EXCHANGE_TYPES = ("exchange", "exchange_cold")
_COLD_TYPES = ("exchange_cold",)

HttpGet = Callable[[str, float], Optional[str]]


def _default_http_get(url: str, timeout: float) -> Optional[str]:
    """urllib tabanlı GET — hata/timeout durumunda None döner (bloke etmez)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "super_otonom/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:  # ağ hatası asla çağrıyı bozmamalı
        log.debug("whale http_get hata (%s): %s", url[:60], exc)
        return None


# ── Cüzdan etiket veritabanı ─────────────────────────────────────────────────


@dataclass(frozen=True)
class WalletLabel:
    label: str
    entity: str
    type: str
    chain: str

    @property
    def is_exchange(self) -> bool:
        return self.type in _EXCHANGE_TYPES

    @property
    def is_cold(self) -> bool:
        return self.type in _COLD_TYPES

    @property
    def is_fund(self) -> bool:
        return self.type == "fund"


class WalletRegistry:
    """Bilinen whale/exchange/fund cüzdan etiketleri (data/whale_wallets.json)."""

    def __init__(self, wallets: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        self._wallets: Dict[str, WalletLabel] = {}
        if wallets:
            for addr, meta in wallets.items():
                self._add(addr, meta)

    def _add(self, addr: str, meta: Dict[str, Any]) -> None:
        try:
            self._wallets[addr.strip().lower()] = WalletLabel(
                label=str(meta.get("label", "")),
                entity=str(meta.get("entity", "")),
                type=str(meta.get("type", "")).lower(),
                chain=str(meta.get("chain", "")).lower(),
            )
        except Exception as exc:
            log.debug("WalletRegistry _add hata (%s): %s", addr, exc)

    @classmethod
    def from_file(cls, path: Optional[Path] = None) -> "WalletRegistry":
        p = path or _DEFAULT_REGISTRY
        try:
            raw = json.loads(Path(p).read_text(encoding="utf-8"))
            return cls(raw.get("wallets", {}))
        except Exception as exc:
            log.warning("WalletRegistry yüklenemedi (%s): %s", p, exc)
            return cls({})

    def lookup(self, address: Optional[str]) -> Optional[WalletLabel]:
        if not address:
            return None
        return self._wallets.get(str(address).strip().lower())

    def __len__(self) -> int:
        return len(self._wallets)


# ── Normalize edilmiş transfer + alert ───────────────────────────────────────


@dataclass(frozen=True)
class WhaleTransfer:
    """Normalize edilmiş büyük transfer (Faz 17 uyumlu)."""

    tx_hash: str
    amount_usd: float
    asset: str
    chain: str
    direction: str  # to_exchange | from_exchange | cold_storage | internal
    from_label: str = ""
    to_label: str = ""
    from_entity: str = ""
    to_entity: str = ""
    ts_ms: int = 0

    def to_faz17_row(self) -> Dict[str, Any]:
        """smart_money_tracker.whale_transfers satır formatı."""
        return {
            "amount_usd": float(self.amount_usd),
            "direction": self.direction,
            "asset": self.asset,
            "chain": self.chain,
            "from": self.from_entity or self.from_label,
            "to": self.to_entity or self.to_label,
            "tx_hash": self.tx_hash,
            "ts_ms": self.ts_ms,
        }


_SEV_INFO = "INFO"
_SEV_WARNING = "WARNING"
_SEV_CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class WhaleAlert:
    """Tetiklenen whale alarmı."""

    kind: str       # LARGE_TRANSFER | TREND | SELL_PRESSURE
    severity: str   # INFO | WARNING | CRITICAL
    message: str
    amount_usd: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)


# ── Raw API parser'ları (saf, ağsız test edilir) ─────────────────────────────


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


def parse_whale_alert(payload: Any, registry: WalletRegistry) -> List[WhaleTransfer]:
    """Whale Alert ``/v1/transactions`` JSON → WhaleTransfer listesi."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return []
    if not isinstance(payload, dict):
        return []
    out: List[WhaleTransfer] = []
    for tx in payload.get("transactions", []) or []:
        if not isinstance(tx, dict):
            continue
        amount = _coerce_float(tx.get("amount_usd"))
        if amount <= 0:
            continue
        src = tx.get("from") or {}
        dst = tx.get("to") or {}
        from_owner_type = str(src.get("owner_type", "")).lower()
        to_owner_type = str(dst.get("owner_type", "")).lower()
        from_addr = src.get("address")
        to_addr = dst.get("address")
        direction = _classify_direction(
            from_owner_type, to_owner_type,
            registry.lookup(from_addr), registry.lookup(to_addr),
        )
        out.append(
            WhaleTransfer(
                tx_hash=str(tx.get("hash", "")),
                amount_usd=amount,
                asset=str(tx.get("symbol", "")).upper(),
                chain=str(tx.get("blockchain", "")).lower(),
                direction=direction,
                from_label=str(src.get("owner", "")),
                to_label=str(dst.get("owner", "")),
                from_entity=_entity(registry.lookup(from_addr), src.get("owner")),
                to_entity=_entity(registry.lookup(to_addr), dst.get("owner")),
                ts_ms=_ts_to_ms(tx.get("timestamp")),
            )
        )
    return out


def parse_etherscan_transfers(
    payload: Any,
    registry: WalletRegistry,
    *,
    asset: str = "",
    price_usd: float = 0.0,
    decimals: int = 18,
    chain: str = "ethereum",
) -> List[WhaleTransfer]:
    """Etherscan/BSCScan ``tokentx`` JSON → WhaleTransfer listesi.

    ``price_usd`` token birim fiyatı (0 ise USD hesaplanamaz, satır atlanır).
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
    out: List[WhaleTransfer] = []
    for ev in rows:
        if not isinstance(ev, dict):
            continue
        raw_val = _coerce_float(ev.get("value"))
        dec = int(ev.get("tokenDecimal") or decimals)
        qty = raw_val / (10 ** dec) if dec >= 0 else raw_val
        amount_usd = qty * price_usd
        if amount_usd <= 0:
            continue
        from_addr = ev.get("from")
        to_addr = ev.get("to")
        fl = registry.lookup(from_addr)
        tl = registry.lookup(to_addr)
        direction = _classify_direction("", "", fl, tl)
        out.append(
            WhaleTransfer(
                tx_hash=str(ev.get("hash", "")),
                amount_usd=amount_usd,
                asset=(asset or str(ev.get("tokenSymbol", ""))).upper(),
                chain=chain,
                direction=direction,
                from_label=fl.label if fl else "",
                to_label=tl.label if tl else "",
                from_entity=_entity(fl, from_addr),
                to_entity=_entity(tl, to_addr),
                ts_ms=_ts_to_ms(ev.get("timeStamp")),
            )
        )
    return out


def parse_blockchain_btc(
    payload: Any,
    registry: WalletRegistry,
    *,
    price_usd: float = 0.0,
) -> List[WhaleTransfer]:
    """Blockchain.com unconfirmed/large BTC transfer JSON → WhaleTransfer listesi."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return []
    if not isinstance(payload, dict):
        return []
    out: List[WhaleTransfer] = []
    for tx in payload.get("txs", []) or []:
        if not isinstance(tx, dict):
            continue
        sats = sum(_coerce_float(o.get("value")) for o in (tx.get("out") or []) if isinstance(o, dict))
        btc = sats / 1e8
        amount_usd = btc * price_usd
        if amount_usd <= 0:
            continue
        in_addrs = [
            (i.get("prev_out") or {}).get("addr")
            for i in (tx.get("inputs") or [])
            if isinstance(i, dict)
        ]
        out_addrs = [o.get("addr") for o in (tx.get("out") or []) if isinstance(o, dict)]
        fl = next((registry.lookup(a) for a in in_addrs if registry.lookup(a)), None)
        tl = next((registry.lookup(a) for a in out_addrs if registry.lookup(a)), None)
        direction = _classify_direction("", "", fl, tl)
        out.append(
            WhaleTransfer(
                tx_hash=str(tx.get("hash", "")),
                amount_usd=amount_usd,
                asset="BTC",
                chain="bitcoin",
                direction=direction,
                from_label=fl.label if fl else "",
                to_label=tl.label if tl else "",
                from_entity=_entity(fl, in_addrs[0] if in_addrs else None),
                to_entity=_entity(tl, out_addrs[0] if out_addrs else None),
                ts_ms=_ts_to_ms(tx.get("time")),
            )
        )
    return out


def _entity(label: Optional[WalletLabel], fallback: Any) -> str:
    if label is not None and label.entity:
        return label.entity
    return str(fallback or "")


def _classify_direction(
    from_owner_type: str,
    to_owner_type: str,
    from_label: Optional[WalletLabel],
    to_label: Optional[WalletLabel],
) -> str:
    """Borsa-yönü sınıflandırma (Faz 17 token'ları).

    Öncelik: yerel registry etiketi > API owner_type. Soğuk cüzdana gidiş
    ``cold_storage`` (güçlü birikim) olarak işaretlenir.
    """
    from_ex = (from_label.is_exchange if from_label else False) or from_owner_type == "exchange"
    to_ex = (to_label.is_exchange if to_label else False) or to_owner_type == "exchange"
    to_cold = to_label.is_cold if to_label else False

    if to_cold and not from_ex:
        return DIR_COLD_STORAGE
    if to_ex and not from_ex:
        return DIR_TO_EXCHANGE
    if from_ex and not to_ex:
        return DIR_FROM_EXCHANGE
    return DIR_INTERNAL


# ── Collector ────────────────────────────────────────────────────────────────


class WhaleFeedCollector:
    """Çoklu kaynaktan whale transfer toplar; Faz 17 ``smart_money_data`` üretir."""

    def __init__(
        self,
        *,
        registry: Optional[WalletRegistry] = None,
        http_get: Optional[HttpGet] = None,
        min_usd: Optional[float] = None,
        large_alert_usd: Optional[float] = None,
        update_interval_sec: Optional[float] = None,
        timeout_sec: float = 5.0,
        alert_manager: Any = None,
    ) -> None:
        self.registry = registry or WalletRegistry.from_file()
        self._http_get: HttpGet = http_get or _default_http_get
        self.min_usd = float(
            min_usd if min_usd is not None else os.getenv("WHALE_MIN_USD", "500000") or 500_000
        )
        self.large_alert_usd = float(
            large_alert_usd
            if large_alert_usd is not None
            else os.getenv("WHALE_LARGE_ALERT_USD", "10000000") or 10_000_000
        )
        self.update_interval_sec = float(
            update_interval_sec
            if update_interval_sec is not None
            else os.getenv("WHALE_UPDATE_INTERVAL_SEC", "300") or 300
        )
        self._timeout = float(timeout_sec)
        self._alert_manager = alert_manager
        self._last_update_ms = 0
        self._recent: List[WhaleTransfer] = []

    # ── Kaynak fetch (mock'lanabilir) ────────────────────────────────────────
    def _fetch_whale_alert(self) -> List[WhaleTransfer]:
        key = os.getenv("WHALE_ALERT_API_KEY", "")
        base = os.getenv("WHALE_ALERT_API_URL", "https://api.whale-alert.io/v1/transactions")
        if not key:
            return []
        url = f"{base}?api_key={key}&min_value={int(self.min_usd)}"
        body = self._http_get(url, self._timeout)
        return parse_whale_alert(body, self.registry) if body else []

    def _fetch_etherscan(self, *, asset: str = "", price_usd: float = 0.0) -> List[WhaleTransfer]:
        key = os.getenv("ETHERSCAN_API_KEY", "")
        base = os.getenv("ETHERSCAN_API_URL", "")
        if not key or not base or price_usd <= 0:
            return []
        url = f"{base}?apikey={key}"
        body = self._http_get(url, self._timeout)
        return (
            parse_etherscan_transfers(body, self.registry, asset=asset, price_usd=price_usd)
            if body
            else []
        )

    def _fetch_blockchain_btc(self, *, price_usd: float = 0.0) -> List[WhaleTransfer]:
        base = os.getenv("BLOCKCHAIN_BTC_API_URL", "")
        if not base or price_usd <= 0:
            return []
        body = self._http_get(base, self._timeout)
        return parse_blockchain_btc(body, self.registry, price_usd=price_usd) if body else []

    # ── Orkestrasyon ─────────────────────────────────────────────────────────
    def collect(
        self,
        *,
        eth_price_usd: float = 0.0,
        btc_price_usd: float = 0.0,
        eth_asset: str = "ETH",
    ) -> List[WhaleTransfer]:
        """Tüm kaynaklardan topla, ≥ min_usd filtrele, zamana göre sırala."""
        transfers: List[WhaleTransfer] = []
        for fetch in (
            lambda: self._fetch_whale_alert(),
            lambda: self._fetch_etherscan(asset=eth_asset, price_usd=eth_price_usd),
            lambda: self._fetch_blockchain_btc(price_usd=btc_price_usd),
        ):
            try:
                transfers.extend(fetch())
            except Exception as exc:
                log.debug("whale collect kaynak hata: %s", exc)
        filtered = [t for t in transfers if t.amount_usd >= self.min_usd]
        filtered.sort(key=lambda t: t.ts_ms)
        return filtered

    def should_update(self, *, now_ms: Optional[int] = None) -> bool:
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        return (now - self._last_update_ms) >= int(self.update_interval_sec * 1000)

    def update(
        self,
        *,
        eth_price_usd: float = 0.0,
        btc_price_usd: float = 0.0,
        emit_alerts: bool = True,
    ) -> Dict[str, Any]:
        """5 dakikalık döngü adımı: topla → alert → ``smart_money_data`` üret."""
        transfers = self.collect(eth_price_usd=eth_price_usd, btc_price_usd=btc_price_usd)
        self._recent = transfers
        self._last_update_ms = int(time.time() * 1000)
        alerts = self.detect_alerts(transfers)
        if emit_alerts and alerts:
            self._dispatch_alerts(alerts)
        data = self.to_smart_money_data(transfers)
        data["whale_alerts"] = [a.kind for a in alerts]
        return data

    # ── Faz 17 köprüsü ───────────────────────────────────────────────────────
    @staticmethod
    def compute_exchange_netflow_usd(transfers: Sequence[WhaleTransfer]) -> float:
        """Net borsa akışı (USD): pozitif = net giriş (satış baskısı)."""
        inflow = sum(t.amount_usd for t in transfers if t.direction == DIR_TO_EXCHANGE)
        outflow = sum(
            t.amount_usd
            for t in transfers
            if t.direction in (DIR_FROM_EXCHANGE, DIR_COLD_STORAGE)
        )
        return float(inflow - outflow)

    def to_smart_money_data(self, transfers: Sequence[WhaleTransfer]) -> Dict[str, Any]:
        """`analyze_smart_money` girdisi: whale_transfers + exchange_netflow_usd."""
        return {
            "whale_transfers": [t.to_faz17_row() for t in transfers],
            "exchange_netflow_usd": self.compute_exchange_netflow_usd(transfers),
            "whale_transfer_count": len(transfers),
        }

    # ── Alert sistemi ────────────────────────────────────────────────────────
    def detect_alerts(
        self,
        transfers: Sequence[WhaleTransfer],
        *,
        trend_window_ms: int = 3_600_000,
        trend_min_count: int = 3,
    ) -> List[WhaleAlert]:
        """3 kural: $10M+ tek transfer, 1 saatte 3+ aynı yön, borsaya toplu giriş."""
        alerts: List[WhaleAlert] = []

        # 1) $10M+ tek transfer
        for t in transfers:
            if t.amount_usd >= self.large_alert_usd:
                alerts.append(
                    WhaleAlert(
                        kind="LARGE_TRANSFER",
                        severity=_SEV_CRITICAL,
                        message=(
                            f"${t.amount_usd / 1e6:.1f}M {t.asset} {t.direction} "
                            f"({t.from_entity or '?'}→{t.to_entity or '?'})"
                        ),
                        amount_usd=t.amount_usd,
                        details={"direction": t.direction, "asset": t.asset},
                    )
                )

        # 2) 1 saatte 3+ büyük transfer aynı yöne
        if transfers:
            now = max(t.ts_ms for t in transfers)
            recent = [t for t in transfers if now - t.ts_ms <= trend_window_ms]
            for direction in (DIR_TO_EXCHANGE, DIR_FROM_EXCHANGE, DIR_COLD_STORAGE):
                same = [t for t in recent if t.direction == direction]
                if len(same) >= trend_min_count:
                    total = sum(t.amount_usd for t in same)
                    alerts.append(
                        WhaleAlert(
                            kind="TREND",
                            severity=_SEV_WARNING,
                            message=(
                                f"{len(same)} büyük {direction} transferi/1s "
                                f"(toplam ${total / 1e6:.1f}M)"
                            ),
                            amount_usd=total,
                            details={"direction": direction, "count": len(same)},
                        )
                    )

        # 3) Borsaya toplu giriş → SELL pressure
        netflow = self.compute_exchange_netflow_usd(transfers)
        if netflow >= self.large_alert_usd:
            alerts.append(
                WhaleAlert(
                    kind="SELL_PRESSURE",
                    severity=_SEV_WARNING,
                    message=f"Borsaya net giriş ${netflow / 1e6:.1f}M — SELL pressure",
                    amount_usd=netflow,
                    details={"netflow_usd": netflow},
                )
            )
        return alerts

    def _dispatch_alerts(self, alerts: Sequence[WhaleAlert]) -> None:
        am = self._alert_manager
        if am is None:
            return
        send = getattr(am, "system", None)
        if not callable(send):
            return
        for a in alerts:
            try:
                send(f"WHALE_{a.kind}", a.message, a.severity)
            except Exception as exc:
                log.debug("whale alert dispatch hata: %s", exc)


def run_whale_phase(
    symbol: str,
    collector: WhaleFeedCollector,
    analysis: Optional[Dict[str, Any]] = None,
    *,
    eth_price_usd: float = 0.0,
    btc_price_usd: float = 0.0,
    attach_to_analysis: bool = True,
) -> Dict[str, Any]:
    """Whale feed → Faz 17 ``analyze_smart_money`` → standart çıktı (alpha/risk/perm)."""
    from super_otonom.smart_money_tracker import analyze_smart_money

    data = collector.update(eth_price_usd=eth_price_usd, btc_price_usd=btc_price_usd)
    return analyze_smart_money(
        symbol, data, analysis, attach_to_analysis=attach_to_analysis
    )


__all__ = [
    "DIR_COLD_STORAGE",
    "DIR_FROM_EXCHANGE",
    "DIR_INTERNAL",
    "DIR_TO_EXCHANGE",
    "WalletLabel",
    "WalletRegistry",
    "WhaleAlert",
    "WhaleFeedCollector",
    "WhaleTransfer",
    "parse_blockchain_btc",
    "parse_etherscan_transfers",
    "parse_whale_alert",
    "run_whale_phase",
]
