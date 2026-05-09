from __future__ import annotations

"""
OrderEngine v1.0
─────────────────────────────────────────────────────────────────────────────
Faz 4a — Execution Safety: Idempotency + State Machine (emir gönderimi)

SORUN (önceki durum):
    Emir borsaya gönderilirken sistem çökerse ne oldu bilinmez.
    Retry'da aynı emir iki kez gidebilir (double execution).
    PENDING emirlerin akıbeti takip edilmiyor.

ÇÖZÜM:
    Her emir UUID ile damgalanır — borsaya gitmeden önce.
    State machine: PENDING → FILLED | FAILED | CANCELLED
    Bot yeniden başladığında PENDING emirler borsaya sorulur.
    Aynı UUID ile ikinci emir gönderilirse reddedilir.

Akış:
    1. intent()     → UUID üret, PENDING kaydet (disk'e yaz)
    2. confirm()    → FILLED olarak işaretle
    3. fail()       → FAILED olarak işaretle
    4. recover()    → Başlangıçta PENDING kalan emirleri borsaya sor
"""

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, asdict, field
from enum import Enum
from typing import Any, Dict, List, Optional

log = logging.getLogger("super_otonom.order_engine")

_ORDER_LOG_FILE = "data/orders.jsonl"
_PENDING_FILE   = "data/pending_orders.json"


# ── Order State ───────────────────────────────────────────────────────────────

class OrderState(str, Enum):
    PENDING   = "PENDING"    # UUID üretildi, borsaya henüz gönderilmedi / yanıt bekleniyor
    SENT      = "SENT"       # Borsaya gönderildi, fill onayı bekleniyor
    FILLED    = "FILLED"     # Borsadan onay geldi
    PARTIAL   = "PARTIAL"    # Kısmi dolum
    FAILED    = "FAILED"     # Gönderme hatası
    CANCELLED = "CANCELLED"  # İptal edildi


# ── Order Record ──────────────────────────────────────────────────────────────

@dataclass
class OrderRecord:
    """Tek bir emrin tam yaşam döngüsü kaydı."""
    order_id:        str          # super_otonom_{uuid4}
    symbol:          str
    side:            str          # BUY / SELL
    qty:             float
    price:           float
    notional:        float
    state:           str          # OrderState değeri
    created_at:      float
    updated_at:      float
    # Fill detayları
    filled_qty:      float        = 0.0
    fill_price:      float        = 0.0
    fee:             float        = 0.0
    # Exchange yanıtı
    exchange_order_id: str        = ""
    exchange_raw:    Dict[str, Any] = field(default_factory=dict)
    # Hata
    error_msg:       str          = ""
    # Retry
    retry_count:     int          = 0
    max_retries:     int          = 3


# ── OrderEngine ───────────────────────────────────────────────────────────────

class OrderEngine:
    """
    UUID tabanlı idempotent emir yönetimi.

    Kullanım (BotEngine içinde):
        # Başlatma
        self.order_engine = OrderEngine()

        # Emir niyeti — borsaya gitmeden önce
        order_id = self.order_engine.intent(symbol, "BUY", qty, price)

        # Borsaya gönder
        try:
            result = await exchange.create_order(..., params={"clientOrderId": order_id})
            self.order_engine.sent(order_id, exchange_order_id=result["id"])
            self.order_engine.confirm(order_id, filled_qty, fill_price, fee)
        except Exception as e:
            self.order_engine.fail(order_id, str(e))

        # Bot başlarken recovery
        await self.order_engine.recover(exchange_handler)
    """

    def __init__(
        self,
        order_log_file: str = _ORDER_LOG_FILE,
        pending_file:   str = _PENDING_FILE,
        max_retries:    int = 3,
        max_memory:     int = 1000,
        batch_mode:     bool = False,  # True → disk yazımını geciktir (test/perf)
    ):
        self._order_log_file = order_log_file
        self._pending_file   = pending_file
        self._max_retries    = max_retries
        self._max_memory     = max_memory
        self._batch_mode     = batch_mode
        self._orders: Dict[str, OrderRecord] = {}

        os.makedirs(os.path.dirname(order_log_file) or ".", exist_ok=True)
        self._load_pending()
        log.info(
            "OrderEngine başlatıldı | pending=%d",
            len([o for o in self._orders.values() if o.state == OrderState.PENDING])
        )

    # ── State machine ─────────────────────────────────────────────────────────

    def intent(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        fee_estimate: float = 0.0,
    ) -> str:
        """
        Emir niyeti: UUID üret, PENDING kaydet.
        Dönüş: order_id (borsaya clientOrderId olarak iletilecek)
        """
        order_id = f"so_{uuid.uuid4().hex}"
        now = time.time()
        record = OrderRecord(
            order_id=order_id,
            symbol=symbol,
            side=side.upper(),
            qty=float(qty),
            price=float(price),
            notional=float(qty) * float(price),
            state=OrderState.PENDING,
            created_at=now,
            updated_at=now,
            fee=fee_estimate,
            max_retries=self._max_retries,
        )
        self._orders[order_id] = record
        # Bellek sınırı — sadece PENDING/SENT olanlar korunur, eskiler atılır
        if len(self._orders) > self._max_memory:
            # Tamamlanmış emirleri sil (FILLED/CANCELLED/FAILED)
            completed = [
                oid for oid, r in self._orders.items()
                if r.state in (OrderState.FILLED, OrderState.CANCELLED, OrderState.FAILED)
            ]
            for oid in completed[:len(completed)//2]:
                del self._orders[oid]
        self._write_log(record, "INTENT")
        self._save_pending()

        log.info(
            "ORDER | INTENT | %s | %s | qty=%.6f price=%.4f | id=%s",
            symbol, side, qty, price, order_id,
        )
        return order_id

    def sent(self, order_id: str, exchange_order_id: str = "") -> bool:
        """Borsaya gönderildi — SENT olarak işaretle."""
        rec = self._orders.get(order_id)
        if rec is None:
            log.error("ORDER | SENT | bilinmeyen id=%s", order_id)
            return False
        if rec.state not in (OrderState.PENDING, OrderState.FAILED):
            log.warning("ORDER | SENT | geçersiz state=%s id=%s", rec.state, order_id)
            return False
        rec.state             = OrderState.SENT
        rec.exchange_order_id = exchange_order_id
        rec.updated_at        = time.time()
        self._write_log(rec, "SENT")
        self._save_pending()
        return True

    def confirm(
        self,
        order_id: str,
        filled_qty: float,
        fill_price: float,
        fee: float = 0.0,
        exchange_raw: Optional[Dict] = None,
    ) -> bool:
        """
        Fill onayı geldi — FILLED olarak işaretle.
        Dönüş: True → başarılı | False → bilinmeyen ID
        """
        rec = self._orders.get(order_id)
        if rec is None:
            log.error("ORDER | CONFIRM | bilinmeyen id=%s", order_id)
            return False

        # Idempotency: zaten FILLED ise tekrar işleme
        if rec.state == OrderState.FILLED:
            log.warning("ORDER | CONFIRM | zaten FILLED | id=%s (idempotent, skip)", order_id)
            return True

        rec.state      = OrderState.FILLED
        rec.filled_qty = float(filled_qty)
        rec.fill_price = float(fill_price)
        rec.fee        = float(fee)
        rec.updated_at = time.time()
        if exchange_raw:
            rec.exchange_raw = exchange_raw
        self._write_log(rec, "FILLED")
        self._save_pending()

        log.info(
            "ORDER | FILLED | %s | filled_qty=%.6f fill_price=%.4f fee=%.4f | id=%s",
            rec.symbol, filled_qty, fill_price, fee, order_id,
        )
        return True

    def partial(
        self,
        order_id: str,
        filled_qty: float,
        fill_price: float,
        fee: float = 0.0,
    ) -> bool:
        """Kısmi dolum."""
        rec = self._orders.get(order_id)
        if rec is None:
            return False
        rec.state      = OrderState.PARTIAL
        rec.filled_qty = float(filled_qty)
        rec.fill_price = float(fill_price)
        rec.fee        += float(fee)
        rec.updated_at = time.time()
        self._write_log(rec, "PARTIAL")
        self._save_pending()
        log.info(
            "ORDER | PARTIAL | %s | filled=%.6f/%.6f | id=%s",
            rec.symbol, filled_qty, rec.qty, order_id,
        )
        return True

    def fail(self, order_id: str, error_msg: str = "") -> bool:
        """Gönderme hatası — FAILED olarak işaretle. Terminal state'leri değiştirmez."""
        rec = self._orders.get(order_id)
        if rec is None:
            log.error("ORDER | FAIL | bilinmeyen id=%s", order_id)
            return False
        # Terminal state koruması — FILLED/CANCELLED değiştirilemez
        if rec.state in (OrderState.FILLED, OrderState.CANCELLED):
            log.debug("ORDER | FAIL | terminal state=%s değiştirilemez | id=%s", rec.state, order_id)
            return False
        rec.state     = OrderState.FAILED
        rec.error_msg = error_msg
        rec.retry_count += 1
        rec.updated_at = time.time()
        self._write_log(rec, "FAILED")
        self._save_pending()
        log.warning(
            "ORDER | FAILED | %s | hata=%s | retry=%d/%d | id=%s",
            rec.symbol, error_msg, rec.retry_count, rec.max_retries, order_id,
        )
        return True

    def cancel(self, order_id: str, reason: str = "") -> bool:
        """Emir iptal edildi. FILLED state değiştirilemez."""
        rec = self._orders.get(order_id)
        if rec is None:
            return False
        # Terminal state koruması
        if rec.state == OrderState.FILLED:
            log.debug("ORDER | CANCEL | FILLED değiştirilemez | id=%s", order_id)
            return False
        rec.state     = OrderState.CANCELLED
        rec.error_msg = reason
        rec.updated_at = time.time()
        self._write_log(rec, "CANCELLED")
        self._save_pending()
        log.info("ORDER | CANCELLED | %s | id=%s | sebep=%s", rec.symbol, order_id, reason)
        return True

    # ── Duplicate koruması ────────────────────────────────────────────────────

    def is_duplicate(self, order_id: str) -> bool:
        """Aynı ID ile ikinci emir gönderilmeye çalışılıyorsa True döner."""
        rec = self._orders.get(order_id)
        if rec is None:
            return False
        if rec.state in (OrderState.FILLED, OrderState.SENT):
            log.warning("ORDER | DUPLICATE | id=%s state=%s | reddedildi", order_id, rec.state)
            return True
        return False

    def can_retry(self, order_id: str) -> bool:
        """FAILED emir yeniden denenebilir mi?"""
        rec = self._orders.get(order_id)
        if rec is None:
            return False
        return rec.state == OrderState.FAILED and rec.retry_count < rec.max_retries

    # ── Recovery (startup) ────────────────────────────────────────────────────

    async def recover(self, exchange_handler: Any) -> List[str]:
        """
        Bot yeniden başladığında PENDING/SENT emirleri borsaya sor.

        Dönüş: işlem yapılan order_id listesi
        """
        pending = [
            r for r in self._orders.values()
            if r.state in (OrderState.PENDING, OrderState.SENT)
        ]
        if not pending:
            log.info("OrderEngine | recovery | PENDING emir yok")
            return []

        log.warning(
            "OrderEngine | recovery | %d PENDING emir bulundu — borsaya sorgulanıyor",
            len(pending),
        )

        recovered = []
        for rec in pending:
            try:
                result = await self._query_exchange(rec, exchange_handler)
                recovered.append(rec.order_id)
                log.info(
                    "OrderEngine | recovery | %s | %s → %s",
                    rec.symbol, rec.order_id, result,
                )
            except Exception as exc:
                log.error(
                    "OrderEngine | recovery | sorgu hatası | %s | %s",
                    rec.order_id, exc,
                )

        return recovered

    async def _fetch_order_from_exchange(
        self, rec: OrderRecord, handler: Any
    ) -> Optional[Any]:
        """Exchange'den order verisini çeker. None → sorgu metodu yok."""
        if hasattr(handler, "fetch_order_by_client_id"):
            return await handler.fetch_order_by_client_id(rec.symbol, rec.order_id)
        if hasattr(handler, "exchange") and hasattr(handler.exchange, "fetch_order"):
            return await handler.exchange.fetch_order(
                rec.exchange_order_id or rec.order_id, rec.symbol
            )
        log.warning(
            "OrderEngine | recovery | exchange_handler sorgu metodu yok | id=%s",
            rec.order_id,
        )
        return None

    def _process_order_status(self, rec: OrderRecord, order: Any) -> str:
        """Exchange order verisine göre state günceller."""
        status = str(order.get("status", "")).lower()
        if status in ("closed", "filled"):
            filled_qty = float(order.get("filled", rec.qty))
            fill_price = float(order.get("average", rec.price) or rec.price)
            fee        = float((order.get("fee") or {}).get("cost", 0.0))
            self.confirm(rec.order_id, filled_qty, fill_price, fee, order)
            return "FILLED"
        if status in ("canceled", "cancelled", "expired"):
            self.cancel(rec.order_id, reason=f"exchange_status:{status}")
            return "CANCELLED"
        if status in ("open", "partially_filled"):
            self.partial(
                rec.order_id,
                float(order.get("filled", 0)),
                float(order.get("average", rec.price) or rec.price),
            )
            return "PARTIAL"
        self.fail(rec.order_id, f"unknown_exchange_status:{status}")
        return "FAILED"

    async def _query_exchange(self, rec: OrderRecord, handler: Any) -> str:
        """
        Borsada bu ID var mı?
        Var → FILLED/PARTIAL
        Yok → FAILED (hiç gitmemiş veya iptal)
        """
        try:
            order = await self._fetch_order_from_exchange(rec, handler)
            if order is None:
                return "SKIPPED"
            return self._process_order_status(rec, order)
        except Exception as exc:
            msg = str(exc).lower()
            if "not found" in msg or "does not exist" in msg:
                self.fail(rec.order_id, "not_found_on_exchange")
                return "NOT_FOUND"
            raise

    # ── Sorgulama ─────────────────────────────────────────────────────────────

    def get(self, order_id: str) -> Optional[OrderRecord]:
        return self._orders.get(order_id)

    def pending_orders(self) -> List[OrderRecord]:
        return [r for r in self._orders.values()
                if r.state in (OrderState.PENDING, OrderState.SENT)]

    def failed_retryable(self) -> List[OrderRecord]:
        return [r for r in self._orders.values() if self.can_retry(r.order_id)]

    def snapshot(self) -> Dict[str, Any]:
        counts: Dict[str, int] = {}
        for r in self._orders.values():
            counts[r.state] = counts.get(r.state, 0) + 1
        return {
            "total_orders":   len(self._orders),
            "by_state":       counts,
            "pending_count":  counts.get(OrderState.PENDING, 0),
            "filled_count":   counts.get(OrderState.FILLED, 0),
            "failed_count":   counts.get(OrderState.FAILED, 0),
        }

    # ── Persistence ───────────────────────────────────────────────────────────

    def _write_log(self, rec: OrderRecord, event: str) -> None:
        """Her state değişikliği append-only log'a yazılır."""
        if self._batch_mode:
            return  # batch modda disk yazımı atlanır
        entry = {"event": event, "ts": time.time(), **asdict(rec)}
        try:
            with open(self._order_log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:
            log.error("OrderEngine | log yazma hatası: %s", exc)

    def _save_pending(self) -> None:
        """
        Sadece PENDING/SENT emirleri ayrı dosyaya yaz.
        Bot restart'ta bu dosyadan recovery yapılır.
        Atomic write: önce .tmp'ye yaz, sonra rename.
        """
        if self._batch_mode:
            return  # batch modda disk yazımı atlanır
        pending = {
            oid: asdict(rec)
            for oid, rec in self._orders.items()
            if rec.state in (OrderState.PENDING, OrderState.SENT, OrderState.PARTIAL)
        }
        tmp = self._pending_file + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(pending, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._pending_file)   # atomic rename
        except Exception as exc:
            log.error("OrderEngine | pending kaydetme hatası: %s", exc)

    def _load_pending(self) -> None:
        """Bot başlarken PENDING emirleri diskten yükle."""
        if not os.path.exists(self._pending_file):
            return
        try:
            with open(self._pending_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for oid, rec_dict in data.items():
                # exchange_raw dict olarak gelir
                if isinstance(rec_dict.get("exchange_raw"), str):
                    rec_dict["exchange_raw"] = {}
                self._orders[oid] = OrderRecord(**rec_dict)
            log.info(
                "OrderEngine | %d PENDING emir diskten yüklendi", len(data)
            )
        except Exception as exc:
            log.error("OrderEngine | pending yükleme hatası: %s", exc)
