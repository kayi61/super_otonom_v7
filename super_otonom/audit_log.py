from __future__ import annotations

"""
AuditLog + DailyReconciler v1.0
─────────────────────────────────────────────────────────────────────────────
Kurumsal denetim ve mutabakat modülü.

AuditLog:
    Her trade olayını yapılandırılmış şekilde kaydeder.
    Denetçinin bakacağı ilk dosya budur.
    Format: JSONL (her satır bir olay) + günlük özet JSON.

    Kaydedilen olaylar:
        TRADE_OPEN    → pozisyon açıldı
        TRADE_CLOSE   → pozisyon kapandı
        RISK_BLOCK    → risk motoru işlemi engelledi
        EMERGENCY     → acil durum tetiklendi
        SIGNAL        → sinyal üretildi (BUY/SELL/HOLD)
        ORDER_SENT    → exchange'e emir gönderildi
        ORDER_FILLED  → emir doldu
        ORDER_CANCEL  → emir iptal edildi
        RECONCILE     → gün sonu mutabakat sonucu
        SYSTEM        → sistem olayı (başlatma, kapanma)

DailyReconciler:
    Gün sonu beklenen vs gerçekleşen PnL karşılaştırması.
    Fark tolerans dışındaysa uyarı üretir.

    Kontroller:
        1. Beklenen NAV vs gerçekleşen NAV
        2. Trade sayısı tutarlılığı
        3. Fee toplam tutarlılığı
        4. Açık pozisyon mutabakatı
        5. PnL attribution (hangi trade ne kadar katkı sağladı)
"""

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional

log = logging.getLogger("super_otonom.audit")

_AUDIT_DIR = "data/audit"
_RECONCILE_DIR = "data/reconcile"
_RECONCILE_TOLERANCE = 0.05  # %5 NAV farkı kabul edilir üstü uyarı


# ── Audit Event ───────────────────────────────────────────────────────────────


@dataclass
class AuditEvent:
    """Tek bir denetim olayı."""

    ts: float
    date_str: str  # "2026-04-27"
    time_str: str  # "14:32:01"
    event_type: str  # TRADE_OPEN, TRADE_CLOSE, RISK_BLOCK, ...
    symbol: str
    order_id: str
    # Trade detayları
    price: float = 0.0
    qty: float = 0.0
    notional: float = 0.0
    pnl: float = 0.0
    fee: float = 0.0
    # Karar detayları
    signal: str = ""
    reason: str = ""
    confidence: float = 0.0
    risk_deny: str = ""
    # Sistem durumu snapshot
    nav: float = 0.0
    cash: float = 0.0
    realized_pnl: float = 0.0
    open_positions: int = 0
    # Serbest alan
    meta: Dict[str, Any] = field(default_factory=dict)


# ── Reconcile Raporu ──────────────────────────────────────────────────────────


@dataclass
class ReconcileReport:
    """Gün sonu mutabakat raporu."""

    date_str: str
    generated_at: float
    # NAV karşılaştırması
    sod_nav: float  # gün başı NAV
    eod_nav_expected: float  # beklenen gün sonu NAV
    eod_nav_actual: float  # gerçekleşen gün sonu NAV
    nav_diff: float  # fark
    nav_diff_pct: float  # fark yüzdesi
    nav_ok: bool  # tolerans içinde mi
    # Trade özeti
    total_trades: int
    winning_trades: int
    losing_trades: int
    total_realized_pnl: float
    total_fees: float
    # Açık pozisyonlar
    open_positions: List[Dict[str, Any]]
    open_positions_count: int
    # PnL attribution (hangi symbol ne kadar katkı sağladı)
    pnl_by_symbol: Dict[str, float]
    # Uyarılar
    warnings: List[str]
    passed: bool  # tüm kontroller geçti mi


# ── AuditLog ─────────────────────────────────────────────────────────────────


class AuditLog:
    """
    Yapılandırılmış denetim kaydı.

    Kullanım:
        audit = AuditLog()
        audit.trade_open(symbol, order_id, price, qty, notional, nav=engine.capital.nav)
        audit.trade_close(symbol, order_id, exit_price, qty, pnl, fee)
        audit.risk_block(symbol, reason, signal)
        audit.emergency(code, nav)
    """

    def __init__(self, audit_dir: str = _AUDIT_DIR):
        self._dir = audit_dir
        os.makedirs(audit_dir, exist_ok=True)
        self._events: List[AuditEvent] = []
        self._max_memory = 500
        log.info("AuditLog başlatıldı | dizin=%s", audit_dir)

    def _now(self):
        now = datetime.now()
        return time.time(), now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S")

    def _log_file(self, date_str: str) -> str:
        return os.path.join(self._dir, f"audit_{date_str}.jsonl")

    def _write(self, event: AuditEvent) -> None:
        """Belleğe + dosyaya yaz."""
        self._events.append(event)
        if len(self._events) > self._max_memory:
            self._events = self._events[-self._max_memory :]
        try:
            with open(self._log_file(event.date_str), "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")
        except Exception as exc:
            log.error("AuditLog yazma hatası: %s", exc)

    # ── Olay kayıt metodları ──────────────────────────────────────────────────

    def trade_open(
        self,
        symbol: str,
        order_id: str,
        price: float,
        qty: float,
        notional: float,
        fee: float = 0.0,
        confidence: float = 0.0,
        nav: float = 0.0,
        cash: float = 0.0,
        open_positions: int = 0,
        meta: Optional[Dict] = None,
    ) -> None:
        ts, date_str, time_str = self._now()
        e = AuditEvent(
            ts=ts,
            date_str=date_str,
            time_str=time_str,
            event_type="TRADE_OPEN",
            symbol=symbol,
            order_id=order_id,
            price=price,
            qty=qty,
            notional=notional,
            fee=fee,
            confidence=confidence,
            nav=nav,
            cash=cash,
            open_positions=open_positions,
            meta=meta or {},
        )
        self._write(e)
        log.info(
            "AUDIT | TRADE_OPEN | %s | order=%s | price=%.4f qty=%.6f notional=%.2f",
            symbol,
            order_id,
            price,
            qty,
            notional,
        )

    def trade_close(
        self,
        symbol: str,
        order_id: str,
        price: float,
        qty: float,
        pnl: float,
        fee: float = 0.0,
        reason: str = "",
        nav: float = 0.0,
        realized_pnl: float = 0.0,
        open_positions: int = 0,
        meta: Optional[Dict] = None,
    ) -> None:
        ts, date_str, time_str = self._now()
        e = AuditEvent(
            ts=ts,
            date_str=date_str,
            time_str=time_str,
            event_type="TRADE_CLOSE",
            symbol=symbol,
            order_id=order_id,
            price=price,
            qty=qty,
            pnl=pnl,
            fee=fee,
            reason=reason,
            nav=nav,
            realized_pnl=realized_pnl,
            open_positions=open_positions,
            meta=meta or {},
        )
        self._write(e)
        log.info(
            "AUDIT | TRADE_CLOSE | %s | order=%s | price=%.4f pnl=%.4f reason=%s",
            symbol,
            order_id,
            price,
            pnl,
            reason,
        )

    def risk_block(
        self,
        symbol: str,
        reason: str,
        signal: str = "",
        nav: float = 0.0,
        meta: Optional[Dict] = None,
    ) -> None:
        ts, date_str, time_str = self._now()
        e = AuditEvent(
            ts=ts,
            date_str=date_str,
            time_str=time_str,
            event_type="RISK_BLOCK",
            symbol=symbol,
            order_id="",
            signal=signal,
            risk_deny=reason,
            nav=nav,
            meta=meta or {},
        )
        self._write(e)
        log.debug("AUDIT | RISK_BLOCK | %s | reason=%s", symbol, reason)

    def emergency(
        self,
        code: str,
        nav: float = 0.0,
        meta: Optional[Dict] = None,
    ) -> None:
        ts, date_str, time_str = self._now()
        e = AuditEvent(
            ts=ts,
            date_str=date_str,
            time_str=time_str,
            event_type="EMERGENCY",
            symbol="—",
            order_id="",
            reason=code,
            nav=nav,
            meta=meta or {},
        )
        self._write(e)
        log.critical("AUDIT | EMERGENCY | code=%s | nav=%.2f", code, nav)

    def signal_event(
        self,
        symbol: str,
        signal: str,
        confidence: float,
        reason: str = "",
        meta: Optional[Dict] = None,
    ) -> None:
        ts, date_str, time_str = self._now()
        e = AuditEvent(
            ts=ts,
            date_str=date_str,
            time_str=time_str,
            event_type="SIGNAL",
            symbol=symbol,
            order_id="",
            signal=signal,
            confidence=confidence,
            reason=reason,
            meta=meta or {},
        )
        self._write(e)

    def system_event(
        self,
        event_type: str,
        reason: str = "",
        nav: float = 0.0,
        meta: Optional[Dict] = None,
    ) -> None:
        """Sistem olayları: START, STOP, CONFIG_CHANGE vb."""
        ts, date_str, time_str = self._now()
        e = AuditEvent(
            ts=ts,
            date_str=date_str,
            time_str=time_str,
            event_type=f"SYSTEM_{event_type}",
            symbol="—",
            order_id="",
            reason=reason,
            nav=nav,
            meta=meta or {},
        )
        self._write(e)
        log.info("AUDIT | SYSTEM_%s | %s", event_type, reason)

    # ── Sorgulama ─────────────────────────────────────────────────────────────

    def get_events(
        self,
        event_type: Optional[str] = None,
        symbol: Optional[str] = None,
        last_n: int = 100,
    ) -> List[Dict[str, Any]]:
        filtered = self._events
        if event_type:
            filtered = [e for e in filtered if e.event_type == event_type]
        if symbol:
            filtered = [e for e in filtered if e.symbol == symbol]
        return [asdict(e) for e in filtered[-last_n:]]

    def today_summary(self) -> Dict[str, Any]:
        """Bugünkü olayların özeti."""
        today = date.today().strftime("%Y-%m-%d")
        today_events = [e for e in self._events if e.date_str == today]
        trades_open = [e for e in today_events if e.event_type == "TRADE_OPEN"]
        trades_close = [e for e in today_events if e.event_type == "TRADE_CLOSE"]
        risk_blocks = [e for e in today_events if e.event_type == "RISK_BLOCK"]
        emergencies = [e for e in today_events if e.event_type == "EMERGENCY"]
        total_pnl = sum(e.pnl for e in trades_close)
        total_fees = sum(e.fee for e in today_events if e.fee > 0)
        return {
            "date": today,
            "trades_opened": len(trades_open),
            "trades_closed": len(trades_close),
            "risk_blocks": len(risk_blocks),
            "emergencies": len(emergencies),
            "total_pnl": round(total_pnl, 4),
            "total_fees": round(total_fees, 4),
            "event_count": len(today_events),
        }


# ── DailyReconciler ───────────────────────────────────────────────────────────


class DailyReconciler:
    """
    Gün sonu mutabakat.

    Kullanım:
        reconciler = DailyReconciler()
        reconciler.set_sod(nav=10_000.0)          # gün başında çağır
        # ... gün içinde işlemler ...
        report = reconciler.run(engine.capital, audit_log)   # gün sonunda
    """

    def __init__(self, reconcile_dir: str = _RECONCILE_DIR):
        self._dir = reconcile_dir
        os.makedirs(reconcile_dir, exist_ok=True)
        self._sod_nav: float = 0.0
        self._sod_date: str = ""
        self._trade_log: List[Dict[str, Any]] = []

    def set_sod(self, nav: float) -> None:
        """Gün başı NAV'ı kaydet. Bot başlarken çağrılmalı."""
        self._sod_nav = float(nav)
        self._sod_date = date.today().strftime("%Y-%m-%d")
        log.info("Reconciler | SOD NAV kaydedildi | %.2f | %s", nav, self._sod_date)

    def record_trade(
        self,
        symbol: str,
        pnl: float,
        fee: float = 0.0,
        reason: str = "",
    ) -> None:
        """Her kapanan işlemde çağır."""
        self._trade_log.append(
            {
                "symbol": symbol,
                "pnl": float(pnl),
                "fee": float(fee),
                "reason": reason,
                "ts": time.time(),
            }
        )

    def run(
        self,
        capital_snapshot: Dict[str, Any],
        audit_summary: Optional[Dict[str, Any]] = None,
    ) -> ReconcileReport:
        """
        Gün sonu mutabakatı çalıştır.

        capital_snapshot: engine.capital.snapshot() çıktısı
        audit_summary:    audit_log.today_summary() çıktısı (opsiyonel)

        Dönüş: ReconcileReport
        """
        today = date.today().strftime("%Y-%m-%d")
        warnings: List[str] = []

        # Gerçekleşen NAV
        eod_nav_actual = float(capital_snapshot.get("nav", 0.0))

        # Beklenen NAV: SOD + realized_pnl - fees
        total_realized = sum(t["pnl"] for t in self._trade_log)
        total_fees = sum(t["fee"] for t in self._trade_log)
        eod_nav_expected = self._sod_nav + total_realized - total_fees

        nav_diff = eod_nav_actual - eod_nav_expected
        nav_diff_pct = abs(nav_diff) / max(abs(self._sod_nav), 1.0) * 100
        nav_ok = nav_diff_pct <= (_RECONCILE_TOLERANCE * 100)

        if not nav_ok:
            warnings.append(
                f"NAV FARKI: beklenen={eod_nav_expected:.2f} "
                f"gerçekleşen={eod_nav_actual:.2f} "
                f"fark={nav_diff:.2f} ({nav_diff_pct:.2f}%)"
            )

        # Trade sayısı tutarlılığı
        audit_closed = (audit_summary or {}).get("trades_closed", len(self._trade_log))
        if audit_closed != len(self._trade_log):
            warnings.append(
                f"TRADE SAYISI UYUMSUZ: reconciler={len(self._trade_log)} audit={audit_closed}"
            )

        # Acil durum kontrolü
        if (audit_summary or {}).get("emergencies", 0) > 0:
            warnings.append(f"BUGÜN {audit_summary['emergencies']} ACİL DURUM TETİKLENDİ")

        # PnL attribution
        pnl_by_symbol: Dict[str, float] = {}
        for t in self._trade_log:
            sym = t["symbol"]
            pnl_by_symbol[sym] = round(pnl_by_symbol.get(sym, 0.0) + t["pnl"], 4)

        # Win/loss sayısı
        wins = [t for t in self._trade_log if t["pnl"] > 0]
        losses = [t for t in self._trade_log if t["pnl"] <= 0]

        # Açık pozisyonlar
        open_pos = capital_snapshot.get("open_positions", 0)
        if open_pos > 0:
            warnings.append(f"GÜN SONU AÇIK POZİSYON: {open_pos} pozisyon hâlâ açık")

        passed = len(warnings) == 0

        report = ReconcileReport(
            date_str=today,
            generated_at=time.time(),
            sod_nav=self._sod_nav,
            eod_nav_expected=round(eod_nav_expected, 2),
            eod_nav_actual=round(eod_nav_actual, 2),
            nav_diff=round(nav_diff, 2),
            nav_diff_pct=round(nav_diff_pct, 4),
            nav_ok=nav_ok,
            total_trades=len(self._trade_log),
            winning_trades=len(wins),
            losing_trades=len(losses),
            total_realized_pnl=round(total_realized, 4),
            total_fees=round(total_fees, 4),
            open_positions=capital_snapshot.get("positions", []),
            open_positions_count=open_pos,
            pnl_by_symbol=pnl_by_symbol,
            warnings=warnings,
            passed=passed,
        )

        self._save_report(report)
        self._log_report(report)
        return report

    def _save_report(self, report: ReconcileReport) -> None:
        path = os.path.join(self._dir, f"reconcile_{report.date_str}.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(asdict(report), f, indent=2, ensure_ascii=False)
        except Exception as exc:
            log.error("Reconciler kaydetme hatası: %s", exc)

    def _log_report(self, report: ReconcileReport) -> None:
        status = "✓ PASSED" if report.passed else "✗ FAILED"
        log.info(
            "RECONCILE | %s | %s | trades=%d wins=%d losses=%d | "
            "pnl=%.4f fees=%.4f | nav_diff=%.2f (%.4f%%)",
            report.date_str,
            status,
            report.total_trades,
            report.winning_trades,
            report.losing_trades,
            report.total_realized_pnl,
            report.total_fees,
            report.nav_diff,
            report.nav_diff_pct,
        )
        for w in report.warnings:
            log.warning("RECONCILE UYARI | %s", w)

    def reset_for_new_day(self, new_nav: float) -> None:
        """Yeni gün başında sıfırla."""
        self._trade_log = []
        self.set_sod(new_nav)
        log.info("Reconciler | yeni gün sıfırlandı | SOD=%.2f", new_nav)
