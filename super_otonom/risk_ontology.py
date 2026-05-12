from __future__ import annotations

"""
RiskOntology v1.0
─────────────────────────────────────────────────────────────────────────────
Faz 2 — Unified Risk Ontology

SORUN (önceki durum):
    daily_loss   / initial_capital   → farklı baz
    drawdown     / peak_equity       → farklı baz
    sizing       / free_capital      → farklı baz
    weekly_loss  / initial_capital   → statik baz, NAV değişse de sabit kalır
    NAV kaynağı  → equity, free_capital, capital.nav — 3 ayrı değer

ÇÖZÜM:
    RiskOntology tek bir dataclass olarak tüm risk metriklerini tutar.
    Tek NAV kaynağı: CapitalEngine.nav
    Tüm yüzdeler aynı baz üzerinden hesaplanır: sod_nav (gün başı NAV)
    RiskManager.check_risk() bu ontoloji üzerinden çalışır.

Yapı:
    nav           → anlık Net Asset Value (CapitalEngine'den)
    sod_nav       → gün başı NAV (günlük kayıp bazı)
    sow_nav       → hafta başı NAV (haftalık kayıp bazı)
    peak_nav      → tarihsel zirve NAV (drawdown bazı)
    intraday_dd_pct  → (peak_nav - nav) / peak_nav
    daily_loss_pct   → (sod_nav - nav) / sod_nav
    weekly_loss_pct  → (sow_nav - nav) / sow_nav
    gross_exp     → tüm açık pozisyonların notional toplamı
    net_exp       → long - short (şimdilik long only)
    var_1d        → 1 günlük VaR (95. percentil)
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

log = logging.getLogger("super_otonom.risk_ontology")

_SOD_RESET_SECONDS = 86400  # 24 saat
_SOW_RESET_SECONDS = 604800  # 7 gün


@dataclass
class RiskOntology:
    """
    Tek NAV kaynağı — tüm risk hesapları buradan beslenir.

    Kullanım:
        onto = RiskOntology(initial_nav=10_000.0)
        onto.update(nav=capital.nav, positions=engine.open_positions)
        if onto.daily_loss_pct >= onto.dynamic_daily_limit:
            trigger_emergency(...)
    """

    # ── Başlangıç ──────────────────────────────────────────────────────────────
    initial_nav: float = 10_000.0

    # ── NAV serileri ───────────────────────────────────────────────────────────
    nav: float = field(default=0.0)
    sod_nav: float = field(default=0.0)  # start-of-day
    sow_nav: float = field(default=0.0)  # start-of-week
    peak_nav: float = field(default=0.0)

    # ── Türetilmiş metrikler ───────────────────────────────────────────────────
    intraday_dd_pct: float = 0.0  # (peak_nav - nav) / peak_nav
    daily_loss_pct: float = 0.0  # (sod_nav - nav) / sod_nav
    weekly_loss_pct: float = 0.0  # (sow_nav - nav) / sow_nav

    # ── Exposure ───────────────────────────────────────────────────────────────
    gross_exp: float = 0.0  # long + short notional
    net_exp: float = 0.0  # long - short (long only → gross == net)
    exp_pct: float = 0.0  # gross_exp / nav

    # ── VaR ────────────────────────────────────────────────────────────────────
    var_1d: float = 0.0

    # ── Dinamik limit ──────────────────────────────────────────────────────────
    dynamic_daily_limit: float = 0.03  # volatiliteye göre güncellenir

    # ── İç durum ───────────────────────────────────────────────────────────────
    _day_start: float = field(default_factory=time.time)
    _week_start: float = field(default_factory=time.time)
    _pnl_history: List[float] = field(default_factory=list)
    _vol_history: List[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        if abs(self.nav) < 1e-9:
            self.nav = self.initial_nav
        if abs(self.sod_nav) < 1e-9:
            self.sod_nav = self.initial_nav
        if abs(self.sow_nav) < 1e-9:
            self.sow_nav = self.initial_nav
        if abs(self.peak_nav) < 1e-9:
            self.peak_nav = self.initial_nav

    # ── Ana güncelleme ─────────────────────────────────────────────────────────

    def update(
        self,
        nav: float,
        positions: Optional[Dict[str, Any]] = None,
        current_vol: float = 0.0,
        realized_pnl_delta: float = 0.0,
    ) -> None:
        """
        Her tick'te çağrılır.

        Parametreler:
            nav             → CapitalEngine.nav (tek kaynak)
            positions       → engine.open_positions (exposure hesabı için)
            current_vol     → analyzer.volatility (dinamik limit için)
            realized_pnl_delta → kapanan işlemden gelen PnL (VaR geçmişi için)
        """
        # FIX-5: nav ÖNCE güncellenir, sonra gün/hafta sıfırlaması
        # Eski sırada sod_nav bir tick önceki nav'ı alıyordu
        self.nav = float(nav)

        self._maybe_reset_day()
        self._maybe_reset_week()

        # Peak güncelle
        if self.nav > self.peak_nav:
            self.peak_nav = self.nav

        # Türetilmiş yüzdeler — hepsi aynı baz mantığıyla
        if self.peak_nav > 0:
            self.intraday_dd_pct = (self.peak_nav - self.nav) / self.peak_nav
        if self.sod_nav > 0:
            self.daily_loss_pct = max(0.0, (self.sod_nav - self.nav) / self.sod_nav)
        if self.sow_nav > 0:
            self.weekly_loss_pct = max(0.0, (self.sow_nav - self.nav) / self.sow_nav)

        # Exposure
        if positions:
            self._update_exposure(positions)

        # Volatilite geçmişi + dinamik limit
        if current_vol > 0:
            self._vol_history.append(float(current_vol))
            if len(self._vol_history) > 200:
                self._vol_history = self._vol_history[-200:]
            self.dynamic_daily_limit = max(0.02, min(0.05, current_vol * 2))

        # PnL geçmişi (VaR için)
        if abs(realized_pnl_delta) > 1e-9:
            self._pnl_history.append(float(realized_pnl_delta))
            if len(self._pnl_history) > 500:
                self._pnl_history = self._pnl_history[-500:]
            self.var_1d = self._calc_var()

        log.debug(
            "RiskOntology | nav=%.2f | dd=%.2f%% | daily_loss=%.2f%% | "
            "weekly_loss=%.2f%% | exp=%.1f%% | dyn_limit=%.2f%%",
            self.nav,
            self.intraday_dd_pct * 100,
            self.daily_loss_pct * 100,
            self.weekly_loss_pct * 100,
            self.exp_pct * 100,
            self.dynamic_daily_limit * 100,
        )

    # ── Yardımcılar ───────────────────────────────────────────────────────────

    def _update_exposure(self, positions: Dict[str, Any]) -> None:
        """Long only sistem — gross == net."""
        total = 0.0
        for pos in positions.values():
            qty = float(pos.get("qty", 0))
            entry = float(pos.get("entry", 0))
            total += qty * entry
        self.gross_exp = total
        self.net_exp = total  # long only
        self.exp_pct = (total / self.nav) if self.nav > 0 else 0.0

    def _maybe_reset_day(self) -> None:
        now = time.time()
        if now - self._day_start >= _SOD_RESET_SECONDS:
            self.sod_nav = self.nav
            self._day_start = now
            log.info("RiskOntology: gün sıfırlandı | sod_nav=%.2f", self.sod_nav)

    def _maybe_reset_week(self) -> None:
        now = time.time()
        if now - self._week_start >= _SOW_RESET_SECONDS:
            self.sow_nav = self.nav
            self._week_start = now
            log.info("RiskOntology: hafta sıfırlandı | sow_nav=%.2f", self.sow_nav)

    def _calc_var(self, confidence: float = 0.95) -> float:
        # FIX-4: 20 örnek istatistiksel olarak anlamsız — minimum 100
        if len(self._pnl_history) < 100:
            return 0.0
        return round(float(np.percentile(self._pnl_history, (1 - confidence) * 100)), 2)

    # ── Risk kontrol sorguları ─────────────────────────────────────────────────

    def is_daily_limit_breached(self) -> bool:
        return self.daily_loss_pct >= self.dynamic_daily_limit

    def is_weekly_limit_breached(self, max_weekly_pct: float = 0.10) -> bool:
        return self.weekly_loss_pct >= max_weekly_pct

    def is_drawdown_breached(self, max_dd: float = 0.15) -> bool:
        return self.intraday_dd_pct >= max_dd

    def is_exposure_breached(self, max_exp_pct: float = 0.95) -> bool:
        return self.exp_pct > max_exp_pct

    # ── Snapshot ──────────────────────────────────────────────────────────────

    def snapshot(self) -> Dict[str, Any]:
        """status() içinde kullanılacak — tek kaynak."""
        return {
            "nav": round(self.nav, 2),
            "sod_nav": round(self.sod_nav, 2),
            "sow_nav": round(self.sow_nav, 2),
            "peak_nav": round(self.peak_nav, 2),
            "intraday_dd_pct": round(self.intraday_dd_pct * 100, 2),
            "daily_loss_pct": round(self.daily_loss_pct * 100, 2),
            "weekly_loss_pct": round(self.weekly_loss_pct * 100, 2),
            "dynamic_daily_limit": round(self.dynamic_daily_limit * 100, 2),
            "gross_exp": round(self.gross_exp, 2),
            "net_exp": round(self.net_exp, 2),
            "exp_pct": round(self.exp_pct * 100, 2),
            "var_1d": self.var_1d,
        }

    def to_dict(self) -> Dict[str, Any]:
        """_save_state() için."""
        return {
            "initial_nav": self.initial_nav,
            "nav": self.nav,
            "sod_nav": self.sod_nav,
            "sow_nav": self.sow_nav,
            "peak_nav": self.peak_nav,
            "dynamic_daily_limit": self.dynamic_daily_limit,
            "day_start": self._day_start,
            "week_start": self._week_start,
            "pnl_history": self._pnl_history[-500:],
            "vol_history": self._vol_history[-200:],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RiskOntology":
        """_load_state() için."""
        onto = cls(initial_nav=float(data.get("initial_nav", 10_000.0)))
        onto.nav = float(data.get("nav", onto.initial_nav))
        onto.sod_nav = float(data.get("sod_nav", onto.initial_nav))
        onto.sow_nav = float(data.get("sow_nav", onto.initial_nav))
        onto.peak_nav = float(data.get("peak_nav", onto.initial_nav))
        onto.dynamic_daily_limit = float(data.get("dynamic_daily_limit", 0.03))
        onto._day_start = float(data.get("day_start", time.time()))
        onto._week_start = float(data.get("week_start", time.time()))
        onto._pnl_history = [float(x) for x in data.get("pnl_history", [])]
        onto._vol_history = [float(x) for x in data.get("vol_history", [])]
        log.info(
            "RiskOntology yüklendi | nav=%.2f | sod=%.2f | peak=%.2f",
            onto.nav,
            onto.sod_nav,
            onto.peak_nav,
        )
        return onto
