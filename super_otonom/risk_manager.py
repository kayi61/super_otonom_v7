from __future__ import annotations

"""
RiskManager v5.3
─────────────────────────────────────────────────────────────────────────────
v5.3 → VR-19: VaR/CVaR breach kill-switch
         _check_var_breach() → var_99, cvar_975, stressed_var breach trigger
         Model dispersion uyarısı (>50%)
         check_risk() zincirine entegre (loss/drawdown sonrası, exposure öncesi)
v5.2 → check_risk() artık RiskOntology'den okur (tek NAV kaynağı)
         daily_loss/sod_nav · weekly_loss/sow_nav · drawdown/peak_nav
         Tutarlı denominators — inconsistent baz sorunu kapandı
         Geriye dönük uyumluluk korundu (onto=None → eski davranış)
"""

import logging
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

from super_otonom.config import RISK

if TYPE_CHECKING:
    from super_otonom.risk.risk_engine import RiskEngine
    from super_otonom.risk_ontology import RiskOntology

log = logging.getLogger("super_otonom.risk")

# VR-19 sentinel — var_topology tarafından tespit edilir
var_breach_kill_switch = True


class RiskManager:
    """
    v5.3 — VaR/CVaR Breach Kill-switch

    Kontrol zinciri (check_risk):
      1. emergency_stop kilidi
      2. Dinamik günlük kayıp limiti  ← v5.1
      3. Haftalık kayıp limiti (statik)
      4. Peak-to-trough drawdown
      5. VaR/CVaR breach kill-switch  ← v5.3 / VR-19 YENİLİK
      6. Exposure limiti
      7. Volatility spike
    """

    def __init__(self, initial_capital: float):
        self.initial_capital = float(initial_capital)
        self.emergency_stop = False
        self.emergency_reason: Optional[str] = None
        self._last_risk_deny: Optional[str] = None
        self.daily_loss = 0.0
        self.weekly_loss = 0.0
        self._peak_equity = float(initial_capital)
        self._day_start = time.time()
        self._week_start = time.time()
        self._pnl_history: List[float] = []
        self._vol_history: List[float] = []
        # v5.1: son hesaplanan dinamik limit — status_dict için
        self._last_dynamic_limit: float = RISK.get("max_daily_loss_pct", 0.05)
        # OMEGA: kapanan işlemlerden feedback — etkin SIGNAL_QUALITY_MIN sıkılaşması
        self._omega_qmin_tighten: int = 0
        # v5.2 — RiskOntology referansı (bot_engine tarafından set edilir)
        self._onto: Optional["RiskOntology"] = None
        self._onto_warned: bool = False  # log flood önlemi
        # v5.3 / VR-19 — VaR breach kill-switch
        self._risk_engine: Optional["RiskEngine"] = None
        self._returns_history: List[float] = []
        self._last_var_breach_reason: Optional[str] = None

    def record_omega_trade_outcome(self, pnl: float) -> None:
        """
        Son işlem sonuç: zararda kalite eşiğini artır, kârda hafif gevşet.
        """
        if pnl < 0:
            self._omega_qmin_tighten = min(25, self._omega_qmin_tighten + 2)
            log.info(
                "OMEGA-AI | feedback | kapanis_zarar | qmin_tighten=+%d (simdi +%d)",
                2,
                self._omega_qmin_tighten,
            )
        else:
            self._omega_qmin_tighten = max(0, self._omega_qmin_tighten - 1)

    def get_omega_effective_qmin(self, base_min: int) -> int:
        """Baz env eşiği + OMEGA sıkılaşması (üst sınır 90)."""
        b = int(max(0, min(95, base_min)))
        return int(max(0, min(90, b + self._omega_qmin_tighten)))

    def set_ontology(self, onto: "RiskOntology") -> None:
        """BotEngine __init__ sonrası çağrılır — tek NAV kaynağını bağlar."""
        self._onto = onto
        log.info("RiskManager: RiskOntology baglandi — tutarli denominatorlar aktif")

    def set_risk_engine(self, engine: "RiskEngine") -> None:
        """VR-19: RiskEngine referansını bağlar — VaR breach kontrolü için."""
        self._risk_engine = engine
        log.info("RiskManager: RiskEngine baglandi — VaR breach kill-switch aktif")

    def record_return(self, ret: float) -> None:
        """
        VR-19: Portföy return'ünü kaydet — _check_var_breach() için.
        BotEngine her tick'te çağırmalı.
        """
        self._returns_history.append(float(ret))
        if len(self._returns_history) > 500:
            self._returns_history = self._returns_history[-500:]

    def _check_var_breach(self) -> Optional[str]:
        """
        VR-19: VaR/CVaR breach kill-switch.

        Kontroller (sırasıyla):
          1. var_99 > max_var_99_pct → emergency_stop
          2. cvar_975 > max_cvar_975_pct → emergency_stop
          3. stressed_var > 2 × var_99 → emergency_stop
          4. model_dispersion > max_model_dispersion_pct → log.critical (uyarı, stop yok)

        Dönüş: breach kodu veya None (geçti).
        """
        if self._risk_engine is None:
            return None
        if len(self._returns_history) < 20:
            return None

        from super_otonom.risk.stressed_var import StressedVaR

        try:
            # Stressed VaR için fixture yükle (varsa)
            stress_returns: Optional[Dict[str, Sequence[float]]] = None
            try:
                svar = StressedVaR.from_fixture()
                stress_returns = svar._stress_periods
            except Exception:
                pass

            metrics = self._risk_engine.compute(
                self._returns_history,
                stress_returns=stress_returns,
            )
        except Exception as exc:
            log.warning("VR-19 | _check_var_breach compute hata: %s", exc)
            return None

        max_var_99 = float(RISK.get("max_var_99_pct", 0.06))
        max_cvar_975 = float(RISK.get("max_cvar_975_pct", 0.10))
        max_dispersion = float(RISK.get("max_model_dispersion_pct", 0.50))

        # Check 1: VaR 99% breach
        if metrics.var_99_1d > max_var_99:
            self.trigger_emergency("var_99_breach", silent=True)
            log.critical(
                "KILL_SWITCH | code=var_99_breach | var_99=%.4f > limit=%.4f",
                metrics.var_99_1d,
                max_var_99,
            )
            self._last_var_breach_reason = "var_99_breach"
            return "var_99_breach"

        # Check 2: CVaR 97.5% breach
        if metrics.cvar_975_1d > max_cvar_975:
            self.trigger_emergency("cvar_975_breach", silent=True)
            log.critical(
                "KILL_SWITCH | code=cvar_975_breach | cvar_975=%.4f > limit=%.4f",
                metrics.cvar_975_1d,
                max_cvar_975,
            )
            self._last_var_breach_reason = "cvar_975_breach"
            return "cvar_975_breach"

        # Check 3: Stressed VaR > 2 × VaR 99%
        if metrics.stressed_var > 0 and metrics.var_99_1d > 0:
            if metrics.stressed_var > 2 * metrics.var_99_1d:
                self.trigger_emergency("stressed_var_breach", silent=True)
                log.critical(
                    "KILL_SWITCH | code=stressed_var_breach | "
                    "stressed_var=%.4f > 2*var_99=%.4f",
                    metrics.stressed_var,
                    2 * metrics.var_99_1d,
                )
                self._last_var_breach_reason = "stressed_var_breach"
                return "stressed_var_breach"

        # Check 4: Model dispersion warning (log only, no kill)
        if metrics.model_dispersion_pct > max_dispersion:
            log.critical(
                "MODEL_RISK | dispersion=%.2f%% > limit=%.2f%% — manuel review gerekli",
                metrics.model_dispersion_pct * 100,
                max_dispersion * 100,
            )

        self._last_var_breach_reason = None
        return None

    def _warn_if_onto_missing(self) -> None:
        """
        FIX-6: onto bağlı değilse uyarı ver — sadece bir kez.
        Her tick'te tekrar etmez (log flood önlemi).
        """
        if self._onto is None and not self._onto_warned:
            self._onto_warned = True
            log.warning(
                "RiskManager | onto=None | eski inconsistent baz kullaniliyor "
                "(set_ontology() cagirilmadi mi?)"
            )

    def trigger_emergency(self, code: str, *, silent: bool = False) -> None:
        """
        Sert kilit: tekrar trading için reset_emergency gerekir (veya proses + env).
        İlk tetikleyen kod reason olarak saklanır — sonraki çağrılar reason'ı değiştirmez.
        """
        if not self.emergency_stop:
            # İlk tetikleme — reason kaydet
            self.emergency_stop = True
            self.emergency_reason = code
        # Zaten kilitli — reason korunur (latch)
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
        """
        PnL kaydı — hem RiskManager hem RiskOntology'ye iletilir.
        FIX-1: Çift state sorunu: daily_loss sadece burada birikiyordu,
        RiskOntology'deki daily_loss_pct ise nav farkından hesaplanıyordu.
        İkisi artık senkronize — onto varsa VaR geçmişi de onto'ya gider.
        """
        self._maybe_reset()
        self._pnl_history.append(float(pnl))
        if len(self._pnl_history) > 500:
            self._pnl_history = self._pnl_history[-500:]
        if pnl < 0:
            loss = abs(float(pnl))
            self.daily_loss += loss
            self.weekly_loss += loss
        # FIX-1: onto varsa VaR geçmişini onto'ya da ilet
        if self._onto is not None:
            self._onto._pnl_history.append(float(pnl))
            if len(self._onto._pnl_history) > 500:
                self._onto._pnl_history = self._onto._pnl_history[-500:]
            self._onto.var_1d = self._onto._calc_var()

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
                current_vol,
                avg_vol,
                spike_multiplier,
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

        dynamic_limit = max(0.02, min(0.05, market_volatility * 2))
        self._last_dynamic_limit = dynamic_limit

        # FIX-2: current_equity payda olarak kullan — initial_capital değil
        # Büyük kâr sonrası initial_capital bazlı oran riski küçümser
        base = current_equity if current_equity > 0 else self.initial_capital
        daily_pct = self.daily_loss / base

        if daily_pct >= dynamic_limit:
            self.trigger_emergency("dynamic_daily_loss", silent=True)
            log.critical(
                "EMERGENCY_STOP | code=dynamic_daily_loss | "
                "gunluk_kayip=%.2f%% >= dinamik_limit=%.2f%% | vol=%.6f | base=%.2f",
                daily_pct * 100,
                dynamic_limit * 100,
                market_volatility,
                base,
            )
            return False

        log.debug(
            "DynamicRisk OK | kayip=%.2f%% < limit=%.2f%% | vol=%.6f",
            daily_pct * 100,
            dynamic_limit * 100,
            market_volatility,
        )
        return True

    # ── Ana risk kontrolü (v5.1: dinamik limit entegre) ──────────────────────

    def _check_risk_with_onto(self) -> Optional[str]:
        """onto bağlıyken risk kontrolleri. Deny reason veya None döner."""
        if self._onto.is_daily_limit_breached():
            self.trigger_emergency("dynamic_daily_loss", silent=True)
            log.critical(
                "EMERGENCY_STOP | code=dynamic_daily_loss | "
                "gunluk_kayip=%.2f%% >= dinamik_limit=%.2f%% [onto]",
                self._onto.daily_loss_pct * 100,
                self._onto.dynamic_daily_limit * 100,
            )
            return "dynamic_daily_loss"

        if self._onto.is_weekly_limit_breached(RISK["max_weekly_loss_pct"]):
            self.trigger_emergency("weekly_loss", silent=True)
            log.critical(
                "EMERGENCY_STOP | code=weekly_loss | %.2f%% >= %.2f%% [onto]",
                self._onto.weekly_loss_pct * 100,
                RISK["max_weekly_loss_pct"] * 100,
            )
            return "weekly_loss"

        if self._onto.is_drawdown_breached(RISK["max_total_drawdown"]):
            self.trigger_emergency("max_drawdown", silent=True)
            log.critical(
                "EMERGENCY_STOP | code=max_drawdown | dd=%.2f%% [onto]",
                self._onto.intraday_dd_pct * 100,
            )
            return "max_drawdown"

        return None

    def _check_risk_without_onto(self, current_equity: float, current_vol: float) -> Optional[str]:
        """onto yoksa geriye dönük uyumluluk kontrolleri. Deny reason veya None döner."""
        if current_vol > 0:
            if not self.check_dynamic_risk(current_equity, current_vol):
                return "dynamic_daily_loss"
        else:
            daily_pct = self.daily_loss / self.initial_capital
            if daily_pct >= RISK["max_daily_loss_pct"]:
                self.trigger_emergency("static_daily_loss", silent=True)
                log.critical(
                    "EMERGENCY_STOP | code=static_daily_loss | %.2f%% >= %.2f%%",
                    daily_pct * 100,
                    RISK["max_daily_loss_pct"] * 100,
                )
                return "static_daily_loss"

        weekly_pct = self.weekly_loss / self.initial_capital
        if weekly_pct >= RISK["max_weekly_loss_pct"]:
            self.trigger_emergency("weekly_loss", silent=True)
            log.critical(
                "EMERGENCY_STOP | code=weekly_loss | %.2f%% >= %.2f%%",
                weekly_pct * 100,
                RISK["max_weekly_loss_pct"] * 100,
            )
            return "weekly_loss"

        self.update_peak(current_equity)
        if self._peak_equity > 0:
            real_dd = (self._peak_equity - current_equity) / self._peak_equity
            if real_dd >= RISK["max_total_drawdown"]:
                self.trigger_emergency("max_drawdown", silent=True)
                log.critical(
                    "EMERGENCY_STOP | code=max_drawdown | peak=%.2f current=%.2f dd=%.2f%%",
                    self._peak_equity,
                    current_equity,
                    real_dd * 100,
                )
                return "max_drawdown"

        return None

    def _check_exposure_and_vol(
        self, current_equity: float, open_exposure: float, current_vol: float
    ) -> Optional[str]:
        """Exposure ve volatility spike kontrolleri. Deny reason veya None döner."""
        equity_for_exposure = self._onto.nav if self._onto is not None else current_equity
        if equity_for_exposure > 0:
            exposure_pct = open_exposure / equity_for_exposure
            if exposure_pct > RISK["max_exposure_pct"]:
                if RISK.get("exposure_breach_emergency"):
                    self.trigger_emergency("max_exposure", silent=True)
                    log.critical(
                        "EMERGENCY_STOP | code=max_exposure | %.2f%% > %.2f%%",
                        exposure_pct * 100,
                        RISK["max_exposure_pct"] * 100,
                    )
                else:
                    log.warning(
                        "GIRIS | exposure_limit | %.2f%% > %.2f%%",
                        exposure_pct * 100,
                        RISK["max_exposure_pct"] * 100,
                    )
                return "max_exposure"

        if current_vol > 0:
            self.record_volatility(current_vol)
            if not self.check_volatility_spike(current_vol):
                log.warning("GIRIS | volatility_spike | vol=%.6f | islem engellendi", current_vol)
                return "volatility_spike"

        return None

    def check_risk(
        self,
        current_equity: float,
        open_exposure: float = 0.0,
        current_vol: float = 0.0,
    ) -> bool:
        """
        Tüm risk kontrollerini sırayla denetler.
        Herhangi biri başarısız olursa False döner.

        Kontroller (sırasıyla):
          1. emergency_stop kilidi
          2. Dinamik günlük kayıp limiti  [v5.1 - volatiliteye duyarlı]
          3. Haftalık kayıp limiti (statik)
          4. Peak-to-trough drawdown
          5. VaR/CVaR breach kill-switch  [v5.3 / VR-19]
          6. Exposure limiti
          7. Volatility spike
        """
        self._last_risk_deny = None
        self._warn_if_onto_missing()

        if self.emergency_stop:
            self._last_risk_deny = self.emergency_reason or "emergency_latched"
            return False

        self._maybe_reset()

        if self.initial_capital <= 0:
            self._last_risk_deny = "invalid_capital"
            return False

        # Loss/drawdown kontrolleri
        if self._onto is not None:
            deny = self._check_risk_with_onto()
        else:
            deny = self._check_risk_without_onto(current_equity, current_vol)

        if deny:
            self._last_risk_deny = deny
            return False

        # VR-19: VaR/CVaR breach kill-switch
        deny = self._check_var_breach()
        if deny:
            self._last_risk_deny = deny
            return False

        # Exposure ve volatility
        deny = self._check_exposure_and_vol(current_equity, open_exposure, current_vol)
        if deny:
            self._last_risk_deny = deny
            return False

        return True

    # ── VaR & Trailing Stop ───────────────────────────────────────────────────

    def calculate_var(self) -> float:
        """
        Value at Risk (95. percentile).
        onto aktifse tek kaynak: onto._calc_var() — duplikasyon yok.
        onto yoksa kendi _pnl_history'den hesapla (min 100 örnek).
        """
        if self._onto is not None:
            return self._onto._calc_var()
        from super_otonom.risk.risk_engine import RiskEngine

        conf = float(RISK["var_confidence"])
        return RiskEngine().compute_from_pnl_history(
            self._pnl_history,
            confidence=conf,
            min_obs=100,
        )

    def should_trailing_stop(self, entry: float, current: float, peak: float) -> bool:
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
        avg_vol_recent = sum(self._vol_history[-10:]) / 10 if len(self._vol_history) >= 10 else None
        d = {
            "daily_loss": round(self.daily_loss, 2),
            "weekly_loss": round(self.weekly_loss, 2),
            "var_95": self.calculate_var(),
            "emergency_stop": self.emergency_stop,
            "emergency_reason": self.emergency_reason,
            "last_risk_deny": self._last_risk_deny,
            "peak_equity": round(self._peak_equity, 2),
            "peak_drawdown_pct": round(peak_dd, 2),
            "avg_vol_recent": round(avg_vol_recent, 6) if avg_vol_recent else None,
            "dynamic_daily_limit_pct": round(self._last_dynamic_limit * 100, 2),
            "omega_qmin_tighten": self._omega_qmin_tighten,
            "onto_active": self._onto is not None,  # v5.2
            "var_breach_kill_switch_active": self._risk_engine is not None,  # v5.3
            "last_var_breach_reason": self._last_var_breach_reason,  # v5.3
            "returns_history_len": len(self._returns_history),  # v5.3
        }
        # v5.2 — onto varsa tutarlı metrikleri üzerine yaz
        if self._onto is not None:
            d.update(
                {
                    "nav": round(self._onto.nav, 2),
                    "sod_nav": round(self._onto.sod_nav, 2),
                    "peak_nav": round(self._onto.peak_nav, 2),
                    "daily_loss_pct": round(self._onto.daily_loss_pct * 100, 2),
                    "weekly_loss_pct": round(self._onto.weekly_loss_pct * 100, 2),
                    "intraday_dd_pct": round(self._onto.intraday_dd_pct * 100, 2),
                    "dynamic_limit_pct": round(self._onto.dynamic_daily_limit * 100, 2),
                    "gross_exp": round(self._onto.gross_exp, 2),
                    "net_exp": round(self._onto.net_exp, 2),
                    "exp_pct": round(self._onto.exp_pct * 100, 2),
                    "var_1d": self._onto.var_1d,
                }
            )
        return d
