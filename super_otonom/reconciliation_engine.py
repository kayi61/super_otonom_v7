from __future__ import annotations

"""
ReconciliationEngine v1.0
─────────────────────────────────────────────────────────────────────────────
Faz 4b — Execution Safety: Borsa ↔ Yerel Ledger Mutabakatı (4a = OrderEngine)

SORUN:
    CapitalEngine yerel gerçeği tutar (niyet).
    Exchange gerçek gerçeği tutar (bakiye).
    İkisi arasında fark oluşabilir: ağ hatası, çökme, kısmi fill.

ÇÖZÜM:
    ReconciliationEngine bot başlangıcında (startup handshake) borsa ile yerel NAV
    karşılaştırır; raporu ``data/recon/recon_*_startup.json`` olarak kaydeder.
    ``nav_diff_pct`` toleransın üstündeyse uyarı + gerektiğinde ayarlama; **STARTUP**
    sırasında fark ``hard_block_pct`` (varsayılan %10) üzerindeyse ``hard_blocked`` —
    ``main_loop`` **hemen çıkar** (tick başlamaz). Küçük farklarda journal uyarısı; operatör
    müdahalesi RUNBOOK Senaryo 3.

"Source of Truth" hiyerarşisi:
    1. Exchange → mutlak gerçek (para orada)
    2. CapitalEngine → niyet gerçeği (neden açıldı, audit trail)
    3. RAM → geçici (en değersiz)

Startup handshake akışı:
    main_loop.py başladığında:
        recon = ReconciliationEngine(capital, order_engine, exchange_handler)
        result = await recon.startup_handshake()
        if result.hard_blocked:
            sys.exit("Mutabakat farkı çok büyük — manuel müdahale gerekli")
"""

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("super_otonom.recon")

_RECON_DIR = "data/recon"
_RECON_TOLERANCE = 0.02  # %2 NAV farkı kabul edilir — üstü HARD uyarı
_HARD_BLOCK_PCT = 0.10  # %10 fark → botu durdur


def _truthy_env(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _dry_paper_skip_signed_exchange_fetch() -> bool:
    """Faz 5 — sim/paper'da imzalı fetch'i atla (apiKey gürültüsü). Varsayılan kapalı; aç: RECON_SIM_SKIP_SIGNED_FETCH=1."""
    if _truthy_env("RECON_FETCH_BALANCE_IN_SIM", "false"):
        return False
    if not _truthy_env("DRY_RUN", "true"):
        return False
    if not _truthy_env("PAPER_MODE", "true"):
        return False
    return _truthy_env("RECON_SIM_SKIP_SIGNED_FETCH", "false")


# ── Reconcile Result ──────────────────────────────────────────────────────────


@dataclass
class ReconResult:
    """Tek mutabakat koşusunun sonucu."""

    ts: float
    trigger: str  # STARTUP, PERIODIC, MANUAL
    # NAV karşılaştırması
    local_nav: float
    exchange_nav: float
    nav_diff: float
    nav_diff_pct: float
    nav_ok: bool
    hard_blocked: bool  # True → bot durdurulmalı
    # Pozisyon karşılaştırması
    local_positions: List[str]  # local'de açık semboller
    exchange_positions: List[str]  # exchange'de açık semboller
    position_mismatch: List[str]  # fark olanlar
    # PENDING emirler
    pending_recovered: int
    # Ayarlamalar
    adjustments: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    passed: bool = True


# ── ReconciliationEngine ─────────────────────────────────────────────────────


class ReconciliationEngine:
    """
    Borsa ↔ Yerel Ledger Mutabakatı.

    Kullanım (main_loop.py başlangıcında):
        recon = ReconciliationEngine(
            capital=engine.capital,
            order_engine=engine.order_engine,
        )
        result = await recon.startup_handshake(exchange_handler)
        if result.hard_blocked:
            log.critical("Manuel müdahale gerekli — bot durduruluyor")
            sys.exit(1)
    """

    def __init__(
        self,
        capital: Any,  # CapitalEngine instance
        order_engine: Any,  # OrderEngine instance
        recon_dir: str = _RECON_DIR,
        tolerance_pct: float = _RECON_TOLERANCE,
        hard_block_pct: float = _HARD_BLOCK_PCT,
        quote_currency: str = "USDT",
        market: str = "spot",
    ):
        self._capital = capital
        self._order_engine = order_engine
        self._dir = recon_dir
        self._tolerance = tolerance_pct
        self._hard_block = hard_block_pct
        self._quote = quote_currency
        self._market = self._normalize_market(market)
        self._last_run: Optional[ReconResult] = None

        os.makedirs(recon_dir, exist_ok=True)
        log.info(
            "ReconciliationEngine başlatıldı | market=%s | tolerance=%.1f%% | hard_block=%.1f%%",
            self._market,
            tolerance_pct * 100,
            hard_block_pct * 100,
        )

    @staticmethod
    def _normalize_market(raw: str) -> str:
        m = (raw or "spot").strip().lower()
        if m in ("future", "futures", "swap"):
            return "future"
        return "spot"

    # ── Ana giriş noktaları ───────────────────────────────────────────────────

    async def startup_handshake(self, exchange_handler: Any) -> ReconResult:
        """
        Bot başlangıcında zorunlu mutabakat.
        PENDING emirleri recovery'e gönderir, ardından bakiye karşılaştırır.
        """
        log.info("RECON | Startup handshake başlıyor...")

        # 1. PENDING emirleri önce recover et
        recovered = await self._order_engine.recover(exchange_handler)

        # 2. Exchange bakiyesini çek
        ex_nav, ex_positions, balance_total = await self._fetch_exchange_state(exchange_handler)

        # 3. Karşılaştır
        result = self._compare(
            trigger="STARTUP",
            ex_nav=ex_nav,
            ex_positions=ex_positions,
            balance_total=balance_total,
            pending_recovered=len(recovered),
        )

        # 4. Fark varsa CapitalEngine'i senkronize et
        if not result.nav_ok and not result.hard_blocked:
            self._apply_adjustment(ex_nav, ex_positions, result)

        self._save(result)
        self._log_result(result)
        self._last_run = result
        return result

    async def periodic_check(self, exchange_handler: Any) -> ReconResult:
        """
        Periyodik mutabakat (örn. her 60 döngüde bir).
        Hard block üretmez — sadece uyarı verir.
        """
        ex_nav, ex_positions, balance_total = await self._fetch_exchange_state(exchange_handler)
        result = self._compare(
            trigger="PERIODIC",
            ex_nav=ex_nav,
            ex_positions=ex_positions,
            balance_total=balance_total,
            pending_recovered=0,
        )
        if not result.nav_ok:
            self._apply_adjustment(ex_nav, ex_positions, result)
        self._save(result)
        self._log_result(result)
        self._last_run = result
        return result

    # ── Exchange veri çekme ───────────────────────────────────────────────────

    async def _fetch_exchange_state(
        self, handler: Any
    ) -> Tuple[float, Dict[str, float], Dict[str, float]]:
        """
        Exchange'den bakiye + (varsa) futures pozisyonları çeker.

        Dönüş:
            total_nav_usdt — USDT toplamı (+ futures notional ekleri)
            ex_positions — futures: {ccxt_symbol: notional}; spot mutabakatında anahtar seti
            balance_total — ``fetch_balance`` ``total`` sözlüğü (spot miktar karşılaştırması)
        """
        ex_nav = 0.0
        ex_positions: Dict[str, float] = {}
        balance_total: Dict[str, float] = {}

        if _dry_paper_skip_signed_exchange_fetch():
            ln = float(self._capital.nav)
            log.info(
                "RECON | sim/paper — exchange bakiye/pozisyon cekilmedi; yerel NAV=%.2f "
                "(imzali okuma: RECON_FETCH_BALANCE_IN_SIM=1 + BINANCE_SIGN_REQUESTS_IN_DRY_RUN "
                "+ Vault read-only anahtar; bu kisa yol: RECON_SIM_SKIP_SIGNED_FETCH=1, RUNBOOK Faz 5)",
                ln,
            )
            return ln, ex_positions, balance_total

        try:
            bal: Optional[Dict[str, Any]] = None
            # Bakiye
            if hasattr(handler, "fetch_balance"):
                bal = await handler.fetch_balance()
            elif hasattr(handler, "exchange"):
                bal = await handler.exchange.fetch_balance()

            if bal:
                raw_tot = bal.get("total", {}) or {}
                balance_total = {str(k): float(v or 0.0) for k, v in raw_tot.items()}
                ex_nav = float(balance_total.get(self._quote, 0.0))

            # Açık pozisyonlar (futures / margin unified)
            if hasattr(handler, "fetch_positions"):
                positions = await handler.fetch_positions()
                for pos in positions or []:
                    sym = pos.get("symbol", "")
                    notional = abs(float(pos.get("notional", 0.0)))
                    if sym and notional > 0:
                        ex_positions[sym] = notional
                        ex_nav += notional

        except Exception as exc:
            log.error("RECON | Exchange veri çekme hatası: %s", exc)
            # Hata durumunda local NAV ile devam et — hard block üretme
            ex_nav = self._capital.nav

        return ex_nav, ex_positions, balance_total

    # ── Karşılaştırma ─────────────────────────────────────────────────────────

    def _compare(
        self,
        trigger: str,
        ex_nav: float,
        ex_positions: Dict[str, float],
        pending_recovered: int,
        balance_total: Optional[Dict[str, float]] = None,
    ) -> ReconResult:
        local_nav = self._capital.nav
        nav_diff = ex_nav - local_nav
        nav_diff_pct = abs(nav_diff) / max(abs(local_nav), 1.0)

        nav_ok = nav_diff_pct <= self._tolerance
        hard_blocked = nav_diff_pct > self._hard_block and trigger == "STARTUP"

        # Pozisyon karşılaştırması — spot: bakiye bazlı miktar; future: sembol kümesi
        local_pos = list(self._capital._positions.keys())
        if self._market == "future":
            ex_pos_syms = list(ex_positions.keys())
            mismatch = list(set(local_pos).symmetric_difference(set(ex_pos_syms)))
        else:
            ex_pos_syms = self._spot_exchange_symbols(balance_total or {})
            mismatch = self._spot_qty_mismatch(balance_total or {})

        warnings: List[str] = []
        if not nav_ok:
            warnings.append(
                f"NAV FARKI: local={local_nav:.2f} exchange={ex_nav:.2f} "
                f"fark={nav_diff:+.2f} ({nav_diff_pct * 100:.2f}%)"
            )
        if mismatch:
            warnings.append(f"POZİSYON UYUMSUZLUĞU: {mismatch}")
        if hard_blocked:
            warnings.append(
                f"HARD BLOCK: fark %{nav_diff_pct * 100:.1f} > eşik %{self._hard_block * 100:.0f}"
            )

        return ReconResult(
            ts=time.time(),
            trigger=trigger,
            local_nav=round(local_nav, 2),
            exchange_nav=round(ex_nav, 2),
            nav_diff=round(nav_diff, 2),
            nav_diff_pct=round(nav_diff_pct * 100, 4),
            nav_ok=nav_ok,
            hard_blocked=hard_blocked,
            local_positions=local_pos,
            exchange_positions=ex_pos_syms,
            position_mismatch=mismatch,
            pending_recovered=pending_recovered,
            warnings=warnings,
            passed=nav_ok and not mismatch and not hard_blocked,
        )

    def _spot_exchange_symbols(self, balance_total: Dict[str, float]) -> List[str]:
        """Spot: borsada anlamlı base bakiyesi olan BTC/USDT vb. semboller (rapor)."""
        dust = float(os.getenv("RECON_SPOT_DUST_BASE", "1e-8"))
        out: List[str] = []
        for sym in self._capital._positions.keys():
            parts = sym.split("/")
            if len(parts) != 2:
                continue
            base, quote = parts[0], parts[1]
            if quote != self._quote:
                continue
            q = abs(float(balance_total.get(base, 0.0)))
            if q > dust:
                out.append(sym)
        return out

    def _spot_qty_mismatch(self, balance_total: Dict[str, float]) -> List[str]:
        """
        Spot LIVE mutabakatı: yerel ledger qty ile borsa ``total[base]`` karşılaştırılır.
        ``fetch_positions`` boş olduğu için sembol kümesi farkı kullanılmaz.
        """
        tol_pct = float(os.getenv("RECON_SPOT_QTY_TOLERANCE_PCT", "1.0")) / 100.0
        tol_pct = max(0.0, min(tol_pct, 0.5))
        dust = float(os.getenv("RECON_SPOT_DUST_BASE", "1e-8"))
        bad: List[str] = []
        for sym, pos in self._capital._positions.items():
            parts = sym.split("/")
            if len(parts) != 2:
                continue
            base, quote = parts[0], parts[1]
            if quote != self._quote:
                continue
            local_q = abs(float(getattr(pos, "qty", 0.0)))
            ex_q = abs(float(balance_total.get(base, 0.0)))
            if local_q <= dust and ex_q <= dust:
                continue
            if local_q <= dust or ex_q <= dust:
                bad.append(sym)
                continue
            denom = max(local_q, ex_q, 1e-12)
            if abs(local_q - ex_q) / denom > tol_pct:
                bad.append(sym)
        return bad

    # ── Ayarlama (CapitalEngine sync) ─────────────────────────────────────────

    def _apply_adjustment(
        self,
        ex_nav: float,
        ex_positions: Dict[str, float],  # NOSONAR — gelecekte pozisyon sync için tutuldu
        result: ReconResult,
    ) -> None:
        """
        CapitalEngine'i exchange gerçeğiyle hizala.
        Fark RECON_ADJUSTMENT olarak journal'a yazılır.
        """
        old_nav = self._capital.nav
        diff = ex_nav - old_nav

        # Cash'i düzelt — margin_used sabit tutulur
        margin = self._capital._margin_used
        new_cash = max(0.0, ex_nav - margin - self._capital._unrealized_pnl)
        old_cash = self._capital._cash
        self._capital._cash = new_cash

        adjustment = {
            "ts": time.time(),
            "old_nav": round(old_nav, 4),
            "new_nav": round(self._capital.nav, 4),
            "diff": round(diff, 4),
            "old_cash": round(old_cash, 4),
            "new_cash": round(new_cash, 4),
            "trigger": result.trigger,
        }
        result.adjustments.append(adjustment)

        # Journal'a yaz
        try:
            self._capital._record(
                event="RECON_ADJUSTMENT",
                symbol="—",
                order_id="recon",
                debit_account="exchange_sync",
                credit_account="cash" if diff > 0 else "loss",
                amount=abs(diff),
                note=f"exchange_nav={ex_nav:.2f} local_nav_before={old_nav:.2f}",
            )
        except Exception as exc:
            log.error("RECON | journal yazma hatası: %s", exc)

        log.warning(
            "RECON | ADJUSTMENT | nav: %.2f → %.2f (diff=%+.2f) | cash: %.2f → %.2f",
            old_nav,
            self._capital.nav,
            diff,
            old_cash,
            new_cash,
        )

    # ── Kaydetme ve loglama ───────────────────────────────────────────────────

    def _save(self, result: ReconResult) -> None:
        ts_str = time.strftime("%Y%m%d_%H%M%S", time.localtime(result.ts))
        path = os.path.join(self._dir, f"recon_{ts_str}_{result.trigger.lower()}.json")
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(asdict(result), f, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception as exc:
            log.error("RECON | kaydetme hatası: %s", exc)

    def _log_result(self, result: ReconResult) -> None:
        status = "✓ PASSED" if result.passed else "✗ FAILED"
        quiet = _dry_paper_skip_signed_exchange_fetch()
        if result.hard_blocked:
            summary_level = logging.CRITICAL
        elif quiet:
            summary_level = logging.INFO
        else:
            summary_level = logging.INFO if result.passed else logging.WARNING
        log.log(
            summary_level,
            "RECON | %s | %s | local=%.2f exchange=%.2f diff=%+.2f (%.2f%%) | "
            "positions: local=%d exchange=%d mismatch=%d | recovered=%d",
            result.trigger,
            status,
            result.local_nav,
            result.exchange_nav,
            result.nav_diff,
            result.nav_diff_pct,
            len(result.local_positions),
            len(result.exchange_positions),
            len(result.position_mismatch),
            result.pending_recovered,
        )
        warn_level = (
            logging.DEBUG
            if (quiet and not result.hard_blocked)
            else logging.WARNING
        )
        for w in result.warnings:
            log.log(warn_level, "RECON UYARI | %s", w)
        if result.hard_blocked:
            log.critical(
                "RECON | HARD BLOCK | Manuel müdahale gerekli | NAV farkı toleransı aştı: %.2f%%",
                result.nav_diff_pct,
            )

    def snapshot(self) -> Dict[str, Any]:
        if self._last_run is None:
            return {"status": "never_run"}
        r = self._last_run
        return {
            "last_run_ts": r.ts,
            "trigger": r.trigger,
            "nav_diff": r.nav_diff,
            "nav_diff_pct": r.nav_diff_pct,
            "passed": r.passed,
            "hard_blocked": r.hard_blocked,
            "position_mismatch": r.position_mismatch,
            "warnings": r.warnings,
        }
