from __future__ import annotations

"""
RiskManager v5.1
─────────────────────────────────────────────────────────────────────────────
v5   → Volatility Spike + Günlük/Haftalık kayıp limiti + VaR + Trailing Stop
v5.1 → check_dynamic_risk(): statik %3 günlük limit yerine oynaklığa duyarlı limit
         Formül: dynamic_limit = clamp(market_volatility × 2, 0.02, 0.05)
         Düşük vol → %2 (sıkı), yüksek vol → %5 (gevşek)
       check_risk() artık dinamik limiti çağırıyor
       status_dict()'e dynamic_daily_limit_pct eklendi (monitoring)
"""

import logging
import time
from typing import Any, Dict, List, Optional

import numpy as np

from super_otonom.config import RISK

log = logging.getLogger("super_otonom.risk")


class RiskManager:
    """
    v5.1 — Dinamik Oynaklık Bazlı Günlük Kayıp Limiti

    Kontrol zinciri (check_risk):
      1. emergency_stop kilidi
      2. Dinamik günlük kayıp limiti  ← v5.1 YENİLİK
      3. Haftalık kayıp limiti (statik)
      4. Peak-to-trough drawdown
      5. Exposure limiti
      6. Volatility spike
    """

    def __init__(self, initial_capital: float):
        self.initial_capital      = float(initial_capital)
        self.emergency_stop       = False
        self.emergency_reason: Optional[str] = None
        self._last_risk_deny: Optional[str] = None
        self.daily_loss           = 0.0
        self.weekly_loss          = 0.0
        self._peak_equity         = float(initial_capital)
        self._day_start           = time.time()
        self._week_start          = time.time()
        self._pnl_history: List[float] = []
        self._vol_history: List[float] = []
        # v5.1: son hesaplanan dinamik limit — status_dict için
        self._last_dynamic_limit: float = RISK.get("max_daily_loss_pct", 0.05)
        # OMEGA: kapanan işlemlerden feedback — etkin SIGNAL_QUALITY_MIN sıkılaşması
        self._omega_qmin_tighten: int = 0

    def record_omega_trade_outcome(self, pnl: float) -> None:
        """
        Son işlem sonuç: zararda kalite eşiğini artır, kârda hafif gevşet.
        """
        if pnl < 0:
            self._omega_qmin_tighten = min(25, self._omega_qmin_tighten + 2)
            log.info(
                "OMEGA-AI | feedback | kapanis_zarar | qmin_tighten=+%d (simdi +%d)",
                2, self._omega_qmin_tighten,
            )
        else:
            self._omega_qmin_tighten = max(0, self._omega_qmin_tighten - 1)

    def get_omega_effective_qmin(self, base_min: int) -> int:
        """Baz env eşiği + OMEGA sıkılaşması (üst sınır 90)."""
        b = int(max(0, min(95, base_min)))
        return int(max(0, min(90, b + self._omega_qmin_tighten)))

    def trigger_emergency(self, code: str, *, silent: bool = False) -> None:
        """
        Sert kilit: tekrar trading için reset_emergency gerekir (veya proses + env).
        """
        self.emergency_stop = True
        self.emergency_reason = code
        if not silent:
            log.critical("EMERGENCY_STOP | code=%s", code)

    def get_last_deny(self) -> str:
        return self._last_risk_deny or ""

    # ── Zamanlayıcı sıfırlama ─────────────────────────────────────────────────

    def _maybe_reset(self) -> None:
        now = time.time()
        if now - self._day_start >= 86400:
            self.daily_loss = 0.0
            self._day_start = now
            log.info("RiskManager: gunluk kayip sifirland.")
        if now - self._week_start >= 604800:
            self.weekly_loss = 0.0
            self._week_start = now
            log.info("RiskManager: haftalik kayip sifirland.")

    # ── PnL kayıt ─────────────────────────────────────────────────────────────

    def record_pnl(self, pnl: float) -> None:
        self._maybe_reset()
        self._pnl_history.append(float(pnl))
        if len(self._pnl_history) > 500:
            self._pnl_history = self._pnl_history[-500:]
        if pnl < 0:
            loss = abs(float(pnl))
            self.daily_loss  += loss
            self.weekly_loss += loss

    def update_peak(self, current_equity: float) -> None:
        """BotEngine her tick'te çağırmalı — gerçek drawdown için."""
        if current_equity > self._peak_equity:
            self._peak_equity = current_equity

    # ── Volatility Spike dedektörü ────────────────────────────────────────────

    def record_volatility(self, vol: float) -> None:
        """
        Her tick'te analyzer.volatility değerini buraya ilet.
        check_volatility_spike() için tarihsel baz oluşturur.
        """
        self._vol_history.append(float(vol))
        if len(self._vol_history) > 200:
            self._vol_history = self._vol_history[-200:]

    def check_volatility_spike(
        self,
        current_vol: float,
        history_vols=None,
        spike_multiplier: float = 2.0,
        min_history: int = 10,
    ) -> bool:
        """
        Oynaklık aniden spike_multiplier kattan fazla artarsa False döner
        (işlem yapma uyarısı).

        Dönüş: True → normal | False → spike, işlem riskli
        """
        vols = history_vols if history_vols is not None else self._vol_history
        if len(vols) < min_history:
            return True

        avg_vol = sum(vols) / len(vols)
        if avg_vol <= 0:
            return True

        if current_vol > avg_vol * spike_multiplier:
            log.critical(
                "VOLATILITY_SPIKE | current=%.6f avg=%.6f multiplier=%.1fx | "
                "islem riskli, pas gecildi.",
                current_vol, avg_vol, spike_multiplier,
            )
            return False
        return True

    # ── v5.1 YENİLİK: Dinamik Günlük Kayıp Limiti ────────────────────────────

    def check_dynamic_risk(
        self,
        current_equity: float,
        market_volatility: float,
    ) -> bool:
        """
        Statik günlük kayıp limiti yerine oynaklığa göre dinamik limit.

        Formül:
            dynamic_limit = clamp(market_volatility × 2, 0.02, 0.05)

        Örnekler:
            vol=0.005 → limit=%1.0 → clamp → %2.0  (sakin piyasa: sıkı)
            vol=0.015 → limit=%3.0                  (normal piyasa)
            vol=0.030 → limit=%6.0 → clamp → %5.0  (fırtına: gevşet ama kapat)

        Dönüş: True → limit içinde | False → limit aşıldı, emergency_stop açık
        """
        if self.initial_capital <= 0:
            return False

        # Dinamik limit hesabı — oynaklık düşükse %2, çok yüksekse max %5
        dynamic_limit = max(0.02, min(0.05, market_volatility * 2))
        self._last_dynamic_limit = dynamic_limit

        daily_pct = self.daily_loss / self.initial_capital

        if daily_pct >= dynamic_limit:
            self.trigger_emergency("dynamic_daily_loss", silent=True)
            log.critical(
                "EMERGENCY_STOP | code=dynamic_daily_loss | "
                "gunluk_kayip=%.2f%% >= dinamik_limit=%.2f%% | vol=%.6f",
                daily_pct * 100,
                dynamic_limit * 100,
                market_volatility,
            )
            return False

        log.debug(
            "DynamicRisk OK | kayip=%.2f%% < limit=%.2f%% | vol=%.6f",
            daily_pct * 100, dynamic_limit * 100, market_volatility,
        )
        return True

    # ── Ana risk kontrolü (v5.1: dinamik limit entegre) ──────────────────────

    def check_risk(
        self,
        current_equity: float,
        open_exposure: float = 0.0,
        current_vol: float   = 0.0,
    ) -> bool:
        """
        Tüm risk kontrollerini sırayla denetler.
        Herhangi biri başarısız olursa False döner.

        Kontroller (sırasıyla):
          1. emergency_stop kilidi
          2. Dinamik günlük kayıp limiti  [v5.1 - volatiliteye duyarlı]
          3. Haftalık kayıp limiti (statik)
          4. Peak-to-trough drawdown
          5. Exposure limiti
          6. Volatility spike
        """
        self._last_risk_deny = None

        if self.emergency_stop:
            self._last_risk_deny = self.emergency_reason or "emergency_latched"
            return False

        self._maybe_reset()

        if self.initial_capital <= 0:
            self._last_risk_deny = "invalid_capital"
            return False

        # 1. Dinamik günlük kayıp limiti (v5.1)
        if current_vol > 0:
            if not self.check_dynamic_risk(current_equity, current_vol):
                self._last_risk_deny = "dynamic_daily_loss"
                return False
        else:
            # Volatilite bilgisi yoksa statik limite dön (güvenlik)
            daily_pct = self.daily_loss / self.initial_capital
            if daily_pct >= RISK["max_daily_loss_pct"]:
                self._last_risk_deny = "static_daily_loss"
                self.trigger_emergency("static_daily_loss", silent=True)
                log.critical(
                    "EMERGENCY_STOP | code=static_daily_loss | "
                    "gunluk_kayip=%.2f%% >= %.2f%%",
                    daily_pct * 100,
                    RISK["max_daily_loss_pct"] * 100,
                )
                return False

        # 2. Haftalık kayıp limiti (statik)
        weekly_pct = self.weekly_loss / self.initial_capital
        if weekly_pct >= RISK["max_weekly_loss_pct"]:
            self._last_risk_deny = "weekly_loss"
            self.trigger_emergency("weekly_loss", silent=True)
            log.critical(
                "EMERGENCY_STOP | code=weekly_loss | %.2f%% >= %.2f%%",
                weekly_pct * 100,
                RISK["max_weekly_loss_pct"] * 100,
            )
            return False

        # 3. Peak-to-trough drawdown
        self.update_peak(current_equity)
        if self._peak_equity > 0:
            real_dd = (self._peak_equity - current_equity) / self._peak_equity
            if real_dd >= RISK["max_total_drawdown"]:
                self._last_risk_deny = "max_drawdown"
                self.trigger_emergency("max_drawdown", silent=True)
                log.critical(
                    "EMERGENCY_STOP | code=max_drawdown | peak=%.2f current=%.2f dd=%.2f%%",
                    self._peak_equity, current_equity, real_dd * 100,
                )
                return False

        # 4. Exposure limiti
        if current_equity > 0:
            exposure_pct = open_exposure / current_equity
            if exposure_pct > RISK["max_exposure_pct"]:
                if RISK.get("exposure_breach_emergency"):
                    self.trigger_emergency("max_exposure", silent=True)
                    self._last_risk_deny = "max_exposure"
                    log.critical(
                        "EMERGENCY_STOP | code=max_exposure | %.2f%% > %.2f%%",
                        exposure_pct * 100,
                        RISK["max_exposure_pct"] * 100,
                    )
                else:
                    self._last_risk_deny = "max_exposure"
                    log.warning(
                        "GIRIS | exposure_limit | %.2f%% > %.2f%%",
                        exposure_pct * 100,
                        RISK["max_exposure_pct"] * 100,
                    )
                return False

        # 5. Volatility spike
        if current_vol > 0:
            self.record_volatility(current_vol)
            if not self.check_volatility_spike(current_vol):
                self._last_risk_deny = "volatility_spike"
                log.warning(
                    "GIRIS | volatility_spike | vol=%.6f | islem engellendi", current_vol
                )
                return False

        return True

    # ── VaR & Trailing Stop ───────────────────────────────────────────────────

    def calculate_var(self) -> float:
        """Value at Risk (95. percentile)."""
        if len(self._pnl_history) < 20:
            return 0.0
        conf = RISK["var_confidence"]
        return round(float(np.percentile(self._pnl_history, (1 - conf) * 100)), 2)

    def should_trailing_stop(
        self, entry: float, current: float, peak: float
    ) -> bool:
        if peak <= entry:
            return False
        drawdown = (peak - current) / peak
        return drawdown >= RISK["trailing_stop_pct"]

    # ── Araçlar ───────────────────────────────────────────────────────────────

    def reset_emergency(self) -> None:
        """Manuel reset — sadece operasyon amaçlı."""
        log.warning("RiskManager: emergency_stop manuel sifirland.")
        self.emergency_stop = False
        self.emergency_reason = None

    def status_dict(self) -> Dict[str, Any]:
        peak_dd = (
            (self._peak_equity - self.initial_capital) / self._peak_equity * 100.0
            if self._peak_equity > 0
            else 0.0
        )
        avg_vol_recent = (
            sum(self._vol_history[-10:]) / 10
            if len(self._vol_history) >= 10
            else None
        )
        return {
            "daily_loss":              round(self.daily_loss, 2),
            "weekly_loss":             round(self.weekly_loss, 2),
            "var_95":                  self.calculate_var(),
            "emergency_stop":          self.emergency_stop,
            "emergency_reason":        self.emergency_reason,
            "last_risk_deny":          self._last_risk_deny,
            "peak_equity":             round(self._peak_equity, 2),
            "peak_drawdown_pct":       round(peak_dd, 2),
            "avg_vol_recent":          round(avg_vol_recent, 6) if avg_vol_recent else None,
            "dynamic_daily_limit_pct": round(self._last_dynamic_limit * 100, 2),  # v5.1
            "omega_qmin_tighten":      self._omega_qmin_tighten,
        }
