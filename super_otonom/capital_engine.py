from __future__ import annotations

"""
CapitalEngine v1.0
─────────────────────────────────────────────────────────────────────────────
Kurumsal sermaye muhasebesi modülü.

BotEngine'deki tek `free_capital` değişkeninin yerini alır.
Her trade için çift kayıt (double-entry) prensibiyle ledger güncellenir.

Hesap yapısı:
    cash              → kasadaki nakit (pozisyon açılmamış sermaye)
    margin_used       → açık pozisyonlar için rezerve edilen notional
    unrealized_pnl    → açık pozisyonların anlık kar/zarar
    realized_pnl      → kapanan işlemlerden gelen kesinleşmiş kar/zarar
    fees_paid         → toplam ödenen komisyon/ücret
    nav               → Net Asset Value = cash + margin_used + unrealized_pnl
    available_cash    → yeni pozisyon için kullanılabilir nakit (cash - rezerv)

Invariant (her işlem sonrası doğrulanır):
    nav == initial_capital + realized_pnl + unrealized_pnl - fees_paid

Journal:
    Her ledger değişikliği JournalEntry olarak kaydedilir.
    Son 1000 entry bellekte tutulur; tamamı audit log dosyasına yazılır.
    İsteğe bağlı ``journal_sink`` ile aynı satır TimescaleDB vb. hedefe çoğaltılabilir (ölçek).
"""

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("super_otonom.capital")

_JOURNAL_FILE = "data/capital_journal.jsonl"
_INVARIANT_TOLERANCE = 0.01  # yuvarlama toleransı (kuruş)
_JOURNAL_MAX_BYTES = 50 * 1024 * 1024  # 50 MB — üstünde rotate


# ── Journal Entry ─────────────────────────────────────────────────────────────


@dataclass
class JournalEntry:
    """
    Tek bir ledger olayını temsil eder.
    Çift kayıt: debit_account borçlandırılır, credit_account alacaklandırılır.
    """

    ts: float
    event: str  # OPEN, CLOSE, UNREALIZED_UPDATE, FEE, DEPOSIT, WITHDRAWAL
    symbol: str
    debit_account: str  # hangi hesap azaldı
    credit_account: str  # hangi hesap arttı
    amount: float  # mutlak değer
    order_id: str
    note: str = ""
    # Snapshot — entry anındaki ledger durumu
    snap_cash: float = 0.0
    snap_margin_used: float = 0.0
    snap_unrealized_pnl: float = 0.0
    snap_realized_pnl: float = 0.0
    snap_fees_paid: float = 0.0
    snap_nav: float = 0.0


# ── Position Ledger ──────────────────────────────────────────────────────────


@dataclass
class PositionLedger:
    """Açık bir pozisyonun muhasebesel kaydı."""

    symbol: str
    order_id: str
    entry_price: float
    qty: float
    notional: float  # açılışta rezerve edilen tutar (margin_used'a eklenen)
    peak_price: float = 0.0
    unrealized: float = 0.0
    opened_at: float = field(default_factory=time.time)

    def update_unrealized(self, current_price: float) -> float:
        """Anlık fiyata göre unrealized PnL güncelle. Delta döndürür."""
        new_unrealized = (current_price - self.entry_price) * self.qty
        delta = new_unrealized - self.unrealized
        self.unrealized = new_unrealized
        if current_price > self.peak_price:
            self.peak_price = current_price
        return delta


# ── Capital Engine ────────────────────────────────────────────────────────────


class CapitalEngine:
    """
    Kurumsal sermaye muhasebesi.

    BotEngine ile entegrasyon:
        engine.capital = CapitalEngine(initial_capital)

        Açılış:  engine.capital.open_position(...)
        Kapanış: engine.capital.close_position(...)
        Tick:    engine.capital.update_unrealized(...)
        Durum:   engine.capital.snapshot()

    Geriye dönük uyumluluk için property'ler:
        .equity        → nav
        .free_capital  → available_cash
    """

    def __init__(
        self,
        initial_capital: float,
        journal_file: str = _JOURNAL_FILE,
        max_position_pct: float = 0.95,  # available_cash'in max bu kadarı tek pozisyona
        reserve_pct: float = 0.05,  # nakit rezervi — bu kadarı hiç kullanılmaz
        journal_sink: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.initial_capital = float(initial_capital)
        self._journal_file = journal_file
        self._journal_sink = journal_sink
        self._max_position_pct = float(max_position_pct)
        self._reserve_pct = float(reserve_pct)

        # ── Ledger hesapları ──────────────────────────────────────────────────
        self._cash = float(initial_capital)
        self._margin_used = 0.0
        self._reserved_margin = 0.0  # in-flight: gönderildi ama fill gelmedi
        self._unrealized_pnl = 0.0
        self._realized_pnl = 0.0
        self._fees_paid = 0.0
        # FIX-1: deposit/withdrawal invariant tracker
        # Invariant: nav == initial_capital + _net_deposits + realized + unrealized - fees
        self._net_deposits = 0.0

        # ── Pozisyon defteri ──────────────────────────────────────────────────
        self._positions: Dict[str, PositionLedger] = {}

        # ── Journal ───────────────────────────────────────────────────────────
        self._journal: List[JournalEntry] = []
        self._journal_max = 1000

        os.makedirs(os.path.dirname(journal_file) or ".", exist_ok=True)
        log.info(
            "CapitalEngine başlatıldı | initial=%.2f | reserve=%.1f%%",
            initial_capital,
            reserve_pct * 100,
        )

    # ── Hesaplanan alanlar ────────────────────────────────────────────────────

    @property
    def nav(self) -> float:
        """Net Asset Value — gerçek portföy değeri."""
        return self._cash + self._margin_used + self._unrealized_pnl

    @property
    def available_cash(self) -> float:
        """
        Yeni pozisyon için kullanılabilir nakit.
        Rezerv + in-flight emirler ayrıldıktan sonra kalan.
        """
        reserve = self.nav * self._reserve_pct
        return max(0.0, self._cash - reserve - self._reserved_margin)

    def reserve_margin(self, order_id: str, notional: float) -> bool:
        """
        Emir borsaya gönderilmeden önce notional'i bloke et.
        Çift harcama ve zombi emir riskini önler.
        Dönüş: True → rezerve edildi | False → yetersiz nakit
        """
        if notional > self.available_cash:
            log.warning(
                "reserve_margin | yetersiz nakit | notional=%.2f available=%.2f",
                notional,
                self.available_cash,
            )
            return False
        self._reserved_margin += notional
        self._record(
            event="RESERVE",
            symbol="—",
            order_id=order_id,
            debit_account="available_for_orders",
            credit_account="reserved_inflight",
            amount=float(notional),
            note="margin reservation (pending fill)",
        )
        log.debug(
            "reserve_margin | order=%s notional=%.2f reserved_total=%.2f",
            order_id,
            notional,
            self._reserved_margin,
        )
        return True

    def release_reservation(self, order_id: str, notional: float) -> None:
        """
        Fill geldi veya timeout oldu — rezervasyonu serbest bırak.
        open_position() fill sonrası zaten cash düşüyor, bu sadece rezervi kaldırır.
        """
        self._reserved_margin = max(0.0, self._reserved_margin - notional)
        self._record(
            event="RELEASE",
            symbol="—",
            order_id=order_id,
            debit_account="reserved_inflight",
            credit_account="available_for_orders",
            amount=float(notional),
            note="margin reservation release",
        )
        log.debug(
            "release_reservation | order=%s notional=%.2f reserved_total=%.2f",
            order_id,
            notional,
            self._reserved_margin,
        )

    @property
    def buying_power(self) -> float:
        """available_cash'in max_position_pct kadarı tek işlemde kullanılabilir."""
        return self.available_cash * self._max_position_pct

    # ── BotEngine geriye dönük uyumluluk ─────────────────────────────────────

    @property
    def equity(self) -> float:
        """BotEngine.equity → nav"""
        return self.nav

    @property
    def free_capital(self) -> float:
        """BotEngine.free_capital → available_cash"""
        return self.available_cash

    # ── Pozisyon işlemleri ────────────────────────────────────────────────────

    def open_position(
        self,
        symbol: str,
        order_id: str,
        entry_price: float,
        qty: float,
        notional: float,
        fee: float = 0.0,
    ) -> bool:
        """
        Pozisyon açılışı.

        Ledger değişikliği:
            cash         -= notional + fee
            margin_used  += notional
            fees_paid    += fee

        Dönüş: True → başarılı | False → yetersiz nakit
        """
        total_cost = notional + fee
        # FIX-A: available_cash kontrol — _reserved_margin dahil, >= ile
        if total_cost >= self.available_cash and total_cost > 0:
            log.warning(
                "CapitalEngine.open_position | yetersiz nakit | "
                "gerekli=%.2f available=%.2f (cash=%.2f reserved=%.2f) | symbol=%s",
                total_cost,
                self.available_cash,
                self._cash,
                self._reserved_margin,
                symbol,
            )
            return False

        if symbol in self._positions:
            log.warning(
                "CapitalEngine.open_position | zaten açık pozisyon var | symbol=%s",
                symbol,
            )
            return False

        self._cash -= total_cost
        self._margin_used += notional
        self._fees_paid += fee

        pos = PositionLedger(
            symbol=symbol,
            order_id=order_id,
            entry_price=entry_price,
            qty=qty,
            notional=notional,
            peak_price=entry_price,
        )
        self._positions[symbol] = pos

        self._record(
            event="OPEN",
            symbol=symbol,
            order_id=order_id,
            debit_account="cash",
            credit_account="margin_used",
            amount=notional,
            note=f"entry={entry_price:.6f} qty={qty:.8f} fee={fee:.4f}",
        )
        if fee > 0:
            self._record(
                event="FEE",
                symbol=symbol,
                order_id=order_id,
                debit_account="cash",
                credit_account="fees_paid",
                amount=fee,
                note="açılış komisyonu",
            )

        self._check_invariant()
        log.info(
            "CAPITAL | OPEN | %s | notional=%.2f fee=%.4f | cash=%.2f margin=%.2f nav=%.2f",
            symbol,
            notional,
            fee,
            self._cash,
            self._margin_used,
            self.nav,
        )
        return True

    def close_position(
        self,
        symbol: str,
        order_id: str,
        exit_price: float,
        filled_qty: float,
        fee: float = 0.0,
    ) -> Optional[float]:
        """
        Pozisyon kapanışı — tam veya kısmi fill desteklenir.

        Kısmi fill (filled_qty < pos.qty):
            Sadece doldurulan miktar kapatılır.
            Pozisyon kalan qty ile güncellenir, silinmez.
            notional orantılı hesaplanır: fill_ratio × pos.notional

        Ledger değişikliği:
            margin_used    -= partial_notional
            cash           += partial_notional + realized_pnl - fee
            realized_pnl   += realized_pnl
            unrealized_pnl  yeniden hesaplanır (delta tabanlı değil)
            fees_paid      += fee

        Dönüş: realized PnL (float) | None → pozisyon bulunamadı
        """
        pos = self._positions.get(symbol)
        if pos is None:
            log.warning(
                "CapitalEngine.close_position | pozisyon bulunamadı | symbol=%s",
                symbol,
            )
            return None

        # FIX-3: Kısmi fill oranı — tüm notional değil, doldurulan kadar
        fill_ratio = min(1.0, filled_qty / pos.qty) if pos.qty > 0 else 1.0
        partial_notional = pos.notional * fill_ratio
        realized = (exit_price - pos.entry_price) * filled_qty
        cash_return = partial_notional + realized - fee

        self._margin_used = max(0.0, self._margin_used - partial_notional)  # FIX-E
        self._realized_pnl += realized
        self._cash += cash_return
        self._fees_paid += fee

        if fill_ratio >= 1.0:
            # Tam kapanış — pozisyonu kaldır
            self._positions.pop(symbol)
            self._unrealized_pnl -= pos.unrealized
        else:
            # Kısmi kapanış — pozisyonu güncelle
            pos.qty -= filled_qty
            pos.notional -= partial_notional
            old_unrealized = pos.unrealized
            pos.unrealized = (exit_price - pos.entry_price) * pos.qty
            self._unrealized_pnl += pos.unrealized - old_unrealized
            # Float epsilon: qty çok küçükse pozisyonu kapat
            if pos.qty < 1e-10 or pos.notional < 1e-8:
                self._positions.pop(symbol)
                self._unrealized_pnl -= pos.unrealized
                log.info(
                    "CAPITAL | PARTIAL_CLOSE→FULL | %s | qty=%.2e epsilon altında kapandı",
                    symbol,
                    pos.qty,
                )
            else:
                log.info(
                    "CAPITAL | PARTIAL_CLOSE | %s | fill_ratio=%.2f | "
                    "kalan_qty=%.6f kalan_notional=%.2f",
                    symbol,
                    fill_ratio,
                    pos.qty,
                    pos.notional,
                )

        # cash asla negatife düşmesin
        if self._cash < 0:
            log.error(
                "CapitalEngine | cash negatife düştü! cash=%.4f | düzeltiliyor → 0.0 | symbol=%s",
                self._cash,
                symbol,
            )
            self._cash = 0.0

        # FIX-4: unrealized'ı pozisyonlardan yeniden hesapla (float drift önlemi)
        self._unrealized_pnl = sum(p.unrealized for p in self._positions.values())

        self._record(
            event="CLOSE" if fill_ratio >= 1.0 else "PARTIAL_CLOSE",
            symbol=symbol,
            order_id=order_id,
            debit_account="margin_used",
            credit_account="cash",
            amount=partial_notional,
            note=(
                f"exit={exit_price:.6f} entry={pos.entry_price:.6f} "
                f"filled_qty={filled_qty:.8f} fill_ratio={fill_ratio:.4f} "
                f"pnl={realized:.4f} fee={fee:.4f}"
            ),
        )
        if fee > 0:
            self._record(
                event="FEE",
                symbol=symbol,
                order_id=order_id,
                debit_account="cash",
                credit_account="fees_paid",
                amount=fee,
                note="kapanış komisyonu",
            )

        self._check_invariant()
        log.info(
            "CAPITAL | CLOSE | %s | pnl=%.4f fee=%.4f fill_ratio=%.2f | "
            "cash=%.2f margin=%.2f realized=%.2f nav=%.2f",
            symbol,
            realized,
            fee,
            fill_ratio,
            self._cash,
            self._margin_used,
            self._realized_pnl,
            self.nav,
        )
        return realized

    def close_partial(
        self,
        symbol: str,
        order_id: str,
        exit_price: float,
        ratio: float,
        fee: float = 0.0,
    ) -> Optional[float]:
        """Açık pozisyonun ``ratio`` (0–1) kadarını kapatır — ``close_position`` sarmalayıcısı."""
        pos = self._positions.get(symbol)
        if pos is None:
            log.warning(
                "CapitalEngine.close_partial | pozisyon bulunamadı | symbol=%s",
                symbol,
            )
            return None
        r = max(0.0, min(1.0, float(ratio)))
        if r <= 0.0:
            return None
        filled_qty = pos.qty * r
        if filled_qty <= 0.0:
            return None
        return self.close_position(
            symbol=symbol,
            order_id=order_id,
            exit_price=exit_price,
            filled_qty=filled_qty,
            fee=fee,
        )

    def update_unrealized(self, prices: Dict[str, float]) -> None:
        """
        Tüm açık pozisyonlar için unrealized PnL güncelle.
        Her tick'te çağrılmalı.

        FIX-4: Delta birikimi yerine pozisyonlardan yeniden hesaplama.
        Delta += delta yaklaşımı binlerce tick sonra float sapması üretir.
        Her tick sonunda _unrealized_pnl = sum(pos.unrealized) ile sıfırlanır.
        """
        for symbol, pos in self._positions.items():
            price = prices.get(symbol)
            if price is None:
                continue
            delta = pos.update_unrealized(float(price))
            if abs(delta) > 0.001:
                log.debug(
                    "CAPITAL | UNREALIZED | %s | delta=%.4f unrealized=%.4f",
                    symbol,
                    delta,
                    pos.unrealized,
                )

        # FIX-4: Delta tabanlı birikim yerine pozisyonlardan doğrudan topla
        self._unrealized_pnl = sum(p.unrealized for p in self._positions.values())

    def record_fee(self, symbol: str, order_id: str, fee: float, note: str = "") -> None:
        """Komisyon veya swap gibi ek ücretleri kaydet."""
        if fee <= 0:
            return
        self._cash -= fee
        self._fees_paid += fee
        self._cash = max(0.0, self._cash)
        self._record(
            event="FEE",
            symbol=symbol,
            order_id=order_id,
            debit_account="cash",
            credit_account="fees_paid",
            amount=fee,
            note=note or "ek ücret",
        )
        self._check_invariant()  # FIX-B

    def deposit(self, amount: float, note: str = "") -> None:
        """Sermaye artışı (yatırımcı para eklemesi)."""
        self._cash += float(amount)
        self._net_deposits += float(amount)  # FIX-1: invariant için takip
        self._record(
            event="DEPOSIT",
            symbol="—",
            order_id="—",
            debit_account="external",
            credit_account="cash",
            amount=amount,
            note=note or "sermaye girişi",
        )
        self._check_invariant()
        log.info("CAPITAL | DEPOSIT | %.2f | cash=%.2f nav=%.2f", amount, self._cash, self.nav)

    def withdrawal(self, amount: float, note: str = "") -> bool:
        """Sermaye çıkışı. Yetersizse False döner."""
        if amount > self.available_cash:
            log.warning(
                "CAPITAL | WITHDRAWAL | yetersiz | talep=%.2f mevcut=%.2f",
                amount,
                self.available_cash,
            )
            return False
        self._cash -= float(amount)
        self._net_deposits -= float(amount)  # FIX-1: invariant için takip
        self._record(
            event="WITHDRAWAL",
            symbol="—",
            order_id="—",
            debit_account="cash",
            credit_account="external",
            amount=amount,
            note=note or "sermaye çıkışı",
        )
        self._check_invariant()
        log.info("CAPITAL | WITHDRAWAL | %.2f | cash=%.2f nav=%.2f", amount, self._cash, self.nav)
        return True

    # ── Snapshot & durum ─────────────────────────────────────────────────────

    def snapshot(self) -> Dict[str, Any]:
        """
        Anlık ledger durumu.
        BotEngine.status() içinde kullanılacak.
        """
        return {
            "nav": round(self.nav, 2),
            "cash": round(self._cash, 2),
            "margin_used": round(self._margin_used, 2),
            "reserved_margin": round(self._reserved_margin, 2),
            "unrealized_pnl": round(self._unrealized_pnl, 4),
            "realized_pnl": round(self._realized_pnl, 4),
            "fees_paid": round(self._fees_paid, 4),
            "net_deposits": round(self._net_deposits, 2),  # FIX-1
            "available_cash": round(self.available_cash, 2),
            "buying_power": round(self.buying_power, 2),
            "open_positions": len(self._positions),
            "total_return_pct": round(
                (self.nav - self.initial_capital) / self.initial_capital * 100, 4
            )
            if self.initial_capital > 0
            else 0.0,
            "journal_entries": len(self._journal),
        }

    def position_snapshot(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Tek pozisyonun detayı."""
        pos = self._positions.get(symbol)
        if pos is None:
            return None
        return {
            "symbol": pos.symbol,
            "order_id": pos.order_id,
            "entry_price": pos.entry_price,
            "qty": pos.qty,
            "notional": pos.notional,
            "peak_price": pos.peak_price,
            "unrealized": round(pos.unrealized, 4),
            "opened_at": pos.opened_at,
        }

    def all_positions(self) -> List[Dict[str, Any]]:
        return [self.position_snapshot(s) for s in self._positions]

    # ── Invariant kontrolü ────────────────────────────────────────────────────

    def _check_invariant(self) -> bool:
        """
        nav == initial_capital + _net_deposits + realized_pnl + unrealized_pnl - fees_paid

        _net_deposits: toplam deposit - toplam withdrawal
        Küçük yuvarlama farkı toleransı: _INVARIANT_TOLERANCE
        """
        expected = (
            self.initial_capital
            + self._net_deposits
            + self._realized_pnl
            + self._unrealized_pnl
            - self._fees_paid
        )
        diff = abs(self.nav - expected)
        if diff > _INVARIANT_TOLERANCE:
            log.error(
                "CAPITAL | INVARIANT IHLALI | nav=%.4f expected=%.4f diff=%.6f | "
                "cash=%.4f margin=%.4f unrealized=%.4f realized=%.4f fees=%.4f net_deposits=%.4f",
                self.nav,
                expected,
                diff,
                self._cash,
                self._margin_used,
                self._unrealized_pnl,
                self._realized_pnl,
                self._fees_paid,
                self._net_deposits,
            )
            return False
        return True

    # ── Journal ───────────────────────────────────────────────────────────────

    def _record(
        self,
        event: str,
        symbol: str,
        order_id: str,
        debit_account: str,
        credit_account: str,
        amount: float,
        note: str = "",
    ) -> None:
        entry = JournalEntry(
            ts=time.time(),
            event=event,
            symbol=symbol,
            debit_account=debit_account,
            credit_account=credit_account,
            amount=round(float(amount), 8),
            order_id=order_id,
            note=note,
            snap_cash=round(self._cash, 4),
            snap_margin_used=round(self._margin_used, 4),
            snap_unrealized_pnl=round(self._unrealized_pnl, 4),
            snap_realized_pnl=round(self._realized_pnl, 4),
            snap_fees_paid=round(self._fees_paid, 4),
            snap_nav=round(self.nav, 4),
        )
        self._journal.append(entry)
        if len(self._journal) > self._journal_max:
            self._journal = self._journal[-self._journal_max :]

        # Dosyaya da yaz — FIX-D: 50MB üstünde rotate
        try:
            if os.path.exists(self._journal_file):
                if os.path.getsize(self._journal_file) > _JOURNAL_MAX_BYTES:
                    bak = self._journal_file + ".bak"
                    os.replace(self._journal_file, bak)
                    log.warning("CapitalEngine journal rotate | %s → %s", self._journal_file, bak)
            with open(self._journal_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
        except Exception as exc:
            log.error("CapitalEngine journal yazma hatası: %s", exc)

        if self._journal_sink is not None:
            try:
                self._journal_sink(asdict(entry))
            except Exception as exc:
                log.error("CapitalEngine journal_sink hatası: %s", exc)

    def get_journal(self, last_n: int = 50) -> List[Dict[str, Any]]:
        """Son N journal entry'yi dict olarak döndür."""
        return [asdict(e) for e in self._journal[-last_n:]]

    # ── Serileştirme (state kaydet/yükle) ────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """BotEngine._save_state() içinde kullanılacak."""
        return {
            "initial_capital": self.initial_capital,
            "cash": self._cash,
            "margin_used": self._margin_used,
            "reserved_margin": self._reserved_margin,  # FIX-2
            "unrealized_pnl": self._unrealized_pnl,
            "realized_pnl": self._realized_pnl,
            "fees_paid": self._fees_paid,
            "net_deposits": self._net_deposits,  # FIX-1
            "reserve_pct": self._reserve_pct,  # config korunur
            "max_position_pct": self._max_position_pct,  # config korunur
            "positions": {
                sym: {
                    "order_id": p.order_id,
                    "entry_price": p.entry_price,
                    "qty": p.qty,
                    "notional": p.notional,
                    "peak_price": p.peak_price,
                    "unrealized": p.unrealized,
                    "opened_at": p.opened_at,
                }
                for sym, p in self._positions.items()
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], **kwargs) -> "CapitalEngine":
        """BotEngine._load_state() içinde kullanılacak."""
        # Config değerlerini kaydedilmiş state'ten al — kwargs override edebilir
        reserve_pct = data.get("reserve_pct", 0.05)
        max_position_pct = data.get("max_position_pct", 0.95)
        kwargs.setdefault("reserve_pct", reserve_pct)
        kwargs.setdefault("max_position_pct", max_position_pct)

        engine = cls(initial_capital=data["initial_capital"], **kwargs)
        engine._cash = float(data.get("cash", engine._cash))
        engine._margin_used = float(data.get("margin_used", 0.0))
        engine._reserved_margin = float(data.get("reserved_margin", 0.0))  # FIX-2
        engine._unrealized_pnl = float(data.get("unrealized_pnl", 0.0))
        engine._realized_pnl = float(data.get("realized_pnl", 0.0))
        engine._fees_paid = float(data.get("fees_paid", 0.0))
        engine._net_deposits = float(data.get("net_deposits", 0.0))  # FIX-1
        for sym, pd in data.get("positions", {}).items():
            pos = PositionLedger(
                symbol=sym,
                order_id=pd.get("order_id", ""),
                entry_price=float(pd["entry_price"]),
                qty=float(pd["qty"]),
                notional=float(pd["notional"]),
                peak_price=float(pd.get("peak_price", pd["entry_price"])),
                unrealized=float(pd.get("unrealized", 0.0)),
                opened_at=float(pd.get("opened_at", time.time())),
            )
            engine._positions[sym] = pos
        log.info(
            "CapitalEngine yüklendi | nav=%.2f | pozisyon=%d | reserved=%.2f",
            engine.nav,
            len(engine._positions),
            engine._reserved_margin,
        )
        return engine
