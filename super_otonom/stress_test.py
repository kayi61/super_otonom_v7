from __future__ import annotations

"""
StressTestRunner v1.0
─────────────────────────────────────────────────────────────────────────────
Sprint 5 M5 — Kriz senaryosu stress testi

Tarihsel kriz senaryolarında sistemin nasıl davranacağını simüle eder.

Senaryolar:
    2020_MART    → COVID crash: BTC -%50 tek günde
    2022_LUNA    → LUNA/UST çöküşü: -%99 birkaç günde
    2022_FTX     → FTX iflası: BTC -%25, kripto piyasası -%30
    2021_MAYIS   → Çin yasağı: BTC -%30 tek haftada
    FLASH_CRASH  → Ani %20 düşüş, hemen toparlanma
    SIDEWAYS     → 30 gün yatay, düşük volatilite

Kullanım:
    runner = StressTestRunner(capital=10_000)
    results = runner.run_all()
    runner.print_report(results)
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger("super_otonom.stress")


@dataclass
class ScenarioDay:
    """Tek gün senaryosu."""
    day: int
    return_pct: float    # günlük getiri (negatif = kayıp)
    volatility: float
    volume_factor: float = 1.0   # normal hacme göre çarpan


@dataclass
class StressResult:
    """Tek senaryo sonucu."""
    scenario_name:     str
    initial_capital:   float
    final_nav:         float
    max_drawdown_pct:  float
    total_return_pct:  float
    days_in_drawdown:  int
    emergency_triggered: bool
    emergency_day:     Optional[int]
    daily_losses:      List[float] = field(default_factory=list)
    nav_series:        List[float] = field(default_factory=list)

    @property
    def survived(self) -> bool:
        return not self.emergency_triggered and self.final_nav > 0

    @property
    def loss_pct(self) -> float:
        return (self.initial_capital - self.final_nav) / self.initial_capital * 100


# ── Kriz Senaryoları ─────────────────────────────────────────────────────────

SCENARIOS: Dict[str, List[ScenarioDay]] = {

    "2020_MART_COVID": [
        # BTC Mart 2020: 12 Mart'ta -%50 tek günde
        ScenarioDay(1,  -0.05, 0.03, 1.5),
        ScenarioDay(2,  -0.08, 0.05, 2.0),
        ScenarioDay(3,  -0.50, 0.15, 5.0),   # ← kara gün
        ScenarioDay(4,  -0.10, 0.08, 3.0),
        ScenarioDay(5,   0.15, 0.06, 2.5),
        ScenarioDay(6,   0.08, 0.04, 2.0),
        ScenarioDay(7,  -0.05, 0.03, 1.5),
        ScenarioDay(8,   0.03, 0.02, 1.2),
        ScenarioDay(9,   0.05, 0.02, 1.1),
        ScenarioDay(10,  0.10, 0.03, 1.5),
    ],

    "2022_LUNA_COLLAPSE": [
        # LUNA/UST Mayıs 2022: birkaç günde -%99
        ScenarioDay(1,  -0.10, 0.05, 2.0),
        ScenarioDay(2,  -0.30, 0.10, 4.0),
        ScenarioDay(3,  -0.60, 0.20, 8.0),   # ← UST depeg
        ScenarioDay(4,  -0.85, 0.30, 10.0),  # ← spiral
        ScenarioDay(5,  -0.50, 0.25, 6.0),
        ScenarioDay(6,  -0.20, 0.15, 3.0),
        ScenarioDay(7,  -0.10, 0.08, 2.0),
        ScenarioDay(8,   0.05, 0.05, 1.5),
        ScenarioDay(9,  -0.05, 0.04, 1.2),
        ScenarioDay(10,  0.02, 0.03, 1.1),
    ],

    "2022_FTX_COLLAPSE": [
        # FTX iflası Kasım 2022
        ScenarioDay(1,  -0.05, 0.03, 2.0),
        ScenarioDay(2,  -0.10, 0.05, 3.0),
        ScenarioDay(3,  -0.15, 0.08, 4.0),
        ScenarioDay(4,  -0.25, 0.12, 5.0),   # ← iflas duyurusu
        ScenarioDay(5,  -0.10, 0.08, 3.0),
        ScenarioDay(6,  -0.05, 0.05, 2.0),
        ScenarioDay(7,   0.03, 0.03, 1.5),
        ScenarioDay(8,  -0.03, 0.03, 1.2),
        ScenarioDay(9,   0.05, 0.02, 1.1),
        ScenarioDay(10,  0.08, 0.03, 1.2),
    ],

    "2021_MAYIS_CHINA_BAN": [
        # Çin madencilik yasağı Mayıs 2021
        ScenarioDay(1,  -0.05, 0.03, 1.5),
        ScenarioDay(2,  -0.12, 0.06, 2.5),
        ScenarioDay(3,  -0.15, 0.07, 3.0),
        ScenarioDay(4,  -0.08, 0.05, 2.0),
        ScenarioDay(5,  -0.05, 0.04, 1.8),
        ScenarioDay(6,   0.03, 0.03, 1.5),
        ScenarioDay(7,  -0.02, 0.02, 1.2),
    ],

    "FLASH_CRASH_RECOVERY": [
        # Ani düşüş + hızlı toparlanma
        ScenarioDay(1,  -0.20, 0.10, 5.0),   # ← flash crash
        ScenarioDay(2,   0.15, 0.07, 3.0),
        ScenarioDay(3,   0.08, 0.04, 2.0),
        ScenarioDay(4,   0.03, 0.02, 1.5),
        ScenarioDay(5,   0.02, 0.01, 1.2),
    ],

    "SIDEWAYS_LOW_VOL": [
        # 10 gün yatay — düşük volatilite
        ScenarioDay(i, (-1)**i * 0.005, 0.005, 0.8)
        for i in range(1, 11)
    ],
}


class StressTestRunner:
    """
    Kriz senaryosu stress test motoru.

    Gerçek risk limitlerini kullanarak her senaryoda:
    - Emergency stop tetiklendi mi?
    - Max drawdown ne kadar?
    - Sistem hayatta kaldı mı?
    """

    def __init__(
        self,
        capital: float = 10_000.0,
        max_daily_loss_pct: float = 0.05,
        max_drawdown_pct: float   = 0.15,
        stop_loss_pct: float      = 0.02,
    ):
        self.capital            = float(capital)
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_drawdown_pct   = max_drawdown_pct
        self.stop_loss_pct      = stop_loss_pct

    def _check_emergency(
        self, name: str, day: ScenarioDay, daily_loss: float, dd: float
    ) -> bool:
        """Günlük kayıp veya drawdown limiti aşıldıysa True döner."""
        daily_loss_pct = daily_loss / self.capital
        if daily_loss_pct >= self.max_daily_loss_pct:
            log.info(
                "STRESS | %s | gün %d | daily_loss=%.1f%% → EMERGENCY",
                name, day.day, daily_loss_pct * 100,
            )
            return True
        if dd >= self.max_drawdown_pct:
            log.info(
                "STRESS | %s | gün %d | drawdown=%.1f%% → EMERGENCY",
                name, day.day, dd * 100,
            )
            return True
        return False

    def _calc_max_drawdown(self, nav_series: List[float]) -> float:
        """Nav serisi üzerinden max drawdown hesaplar."""
        max_dd = 0.0
        _peak  = self.capital
        for n in nav_series:
            if n > _peak:
                _peak = n
            dd = (_peak - n) / _peak if _peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
        return max_dd

    def run_scenario(
        self,
        name: str,
        days: List[ScenarioDay],
        position_pct: float = 0.50,
    ) -> StressResult:
        """Tek senaryoyu simüle et."""
        nav        = self.capital
        peak_nav   = self.capital
        nav_series = [nav]
        daily_losses: List[float] = []
        days_in_dd  = 0
        emg_day: Optional[int] = None
        emg_triggered = False

        for day in days:
            if emg_triggered:
                break

            position_value = nav * position_pct
            pnl = position_value * day.return_pct
            daily_loss = abs(pnl) if pnl < 0 else 0.0
            daily_losses.append(daily_loss)

            nav += pnl
            nav  = max(0.0, nav)
            nav_series.append(nav)

            if nav > peak_nav:
                peak_nav = nav

            dd = (peak_nav - nav) / peak_nav if peak_nav > 0 else 0.0
            if dd > 0:
                days_in_dd += 1

            if self._check_emergency(name, day, daily_loss, dd):
                emg_triggered = True
                emg_day = day.day

        final_nav = nav
        max_dd    = self._calc_max_drawdown(nav_series)

        return StressResult(
            scenario_name=name,
            initial_capital=self.capital,
            final_nav=round(final_nav, 2),
            max_drawdown_pct=round(max_dd * 100, 2),
            total_return_pct=round((final_nav - self.capital) / self.capital * 100, 2),
            days_in_drawdown=days_in_dd,
            emergency_triggered=emg_triggered,
            emergency_day=emg_day,
            daily_losses=daily_losses,
            nav_series=nav_series,
        )

    def run_all(self) -> Dict[str, StressResult]:
        """Tüm senaryoları çalıştır."""
        results = {}
        for name, days in SCENARIOS.items():
            result = self.run_scenario(name, days)
            results[name] = result
            log.info(
                "STRESS | %s | survived=%s | max_dd=%.1f%% | return=%.1f%% | emg=%s",
                name, result.survived,
                result.max_drawdown_pct,
                result.total_return_pct,
                f"gün {result.emergency_day}" if result.emergency_triggered else "hayır",
            )
        return results

    def print_report(self, results: Dict[str, StressResult]) -> str:
        """Okunabilir rapor."""
        lines = [
            "=" * 70,
            "STRESS TEST RAPORU — super_otonom",
            f"Başlangıç sermayesi: {self.capital:,.0f} USDT",
            f"Max günlük kayıp limiti: {self.max_daily_loss_pct*100:.1f}%",
            f"Max drawdown limiti: {self.max_drawdown_pct*100:.1f}%",
            "=" * 70,
        ]
        for name, r in results.items():
            status = "✓ HAYATTA" if r.survived else "✗ EMERGENCY"
            lines.append(
                f"\n{name}\n"
                f"  Durum:       {status}"
                + (f" (gün {r.emergency_day})" if r.emergency_day else "")
                + f"\n  Son NAV:     {r.final_nav:,.2f} USDT"
                f"\n  Max Drawdown: {r.max_drawdown_pct:.1f}%"
                f"\n  Toplam Getiri: {r.total_return_pct:+.1f}%"
                f"\n  DD'de geçen gün: {r.days_in_drawdown}"
            )
        lines.append("\n" + "=" * 70)
        survived = sum(1 for r in results.values() if r.survived)
        lines.append(
            f"ÖZET: {survived}/{len(results)} senaryoda hayatta kalındı"
        )
        report = "\n".join(lines)
        print(report)
        return report


if __name__ == "__main__":
    runner = StressTestRunner(capital=10_000)
    results = runner.run_all()
    runner.print_report(results)
