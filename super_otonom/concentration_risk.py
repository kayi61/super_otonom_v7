from __future__ import annotations

"""
ConcentrationRiskManager v1.0
─────────────────────────────────────────────────────────────────────────────
Sprint 5 M4 — Sektör / coin konsantrasyon risk yönetimi

SORUN (önceki durum):
    Aynı sektördeki coinler (örn. BTC/USDT + ETH/USDT + SOL/USDT) hepsi
    aynı anda açılabiliyordu. Yüksek korelasyon → gerçek diversifikasyon yok.
    Bir sektör düşünce tüm portföy düşer.

ÇÖZÜM:
    Her açılışta:
    1. Sembol → sektör eşlemesi
    2. Sektör bazlı exposure limiti (varsayılan: tek sektör max %40 NAV)
    3. Korelasyon bazlı pozisyon indirimi

Kullanım:
    conc = ConcentrationRiskManager()
    ok, reason = conc.check_concentration(
        symbol="ETH/USDT",
        notional=2000,
        nav=10000,
        open_positions=engine.open_positions,
    )
    if not ok:
        log.warning("Konsantrasyon limiti: %s", reason)
"""

import logging
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("super_otonom.concentration")

# Kripto sektör eşlemesi — genişletilebilir
_SECTOR_MAP: Dict[str, str] = {
    # Layer 1
    "BTC/USDT": "L1", "ETH/USDT": "L1", "SOL/USDT": "L1",
    "ADA/USDT": "L1", "AVAX/USDT": "L1", "DOT/USDT": "L1",
    "ATOM/USDT": "L1", "NEAR/USDT": "L1", "APT/USDT": "L1",
    "SUI/USDT": "L1", "TON/USDT": "L1", "TRX/USDT": "L1",
    # Layer 2
    "MATIC/USDT": "L2", "ARB/USDT": "L2", "OP/USDT": "L2",
    "IMX/USDT": "L2", "STRK/USDT": "L2", "MANTA/USDT": "L2",
    # DeFi
    "UNI/USDT": "DEFI", "AAVE/USDT": "DEFI", "COMP/USDT": "DEFI",
    "CRV/USDT": "DEFI", "MKR/USDT": "DEFI", "SNX/USDT": "DEFI",
    "SUSHI/USDT": "DEFI", "1INCH/USDT": "DEFI",
    # AI / Data
    "FET/USDT": "AI", "OCEAN/USDT": "AI", "AGIX/USDT": "AI",
    "RNDR/USDT": "AI", "WLD/USDT": "AI",
    # GameFi / Metaverse
    "AXS/USDT": "GAMEFI", "SAND/USDT": "GAMEFI", "MANA/USDT": "GAMEFI",
    "GALA/USDT": "GAMEFI", "ILV/USDT": "GAMEFI",
    # Exchange tokens
    "BNB/USDT": "CEX", "OKB/USDT": "CEX", "CRO/USDT": "CEX",
    # Stablecoins (genelde işlem yapılmaz ama takip için)
    "USDT/USD": "STABLE", "USDC/USDT": "STABLE",
}

_DEFAULT_MAX_SECTOR_PCT   = 0.40   # tek sektör max %40 NAV
_DEFAULT_MAX_SINGLE_PCT   = 0.25   # tek coin max %25 NAV
_DEFAULT_MAX_TOTAL_PCT    = 0.80   # toplam exposure max %80 NAV


class ConcentrationRiskManager:
    """
    Sektör bazlı konsantrasyon risk kontrolü.

    Kontroller:
    1. Tek coin limiti (max_single_pct)
    2. Sektör limiti (max_sector_pct)
    3. Toplam exposure limiti (max_total_pct)
    """

    def __init__(
        self,
        sector_map: Optional[Dict[str, str]] = None,
        max_sector_pct: float  = _DEFAULT_MAX_SECTOR_PCT,
        max_single_pct: float  = _DEFAULT_MAX_SINGLE_PCT,
        max_total_pct: float   = _DEFAULT_MAX_TOTAL_PCT,
    ):
        self._sectors       = sector_map or _SECTOR_MAP
        self._max_sector    = max_sector_pct
        self._max_single    = max_single_pct
        self._max_total     = max_total_pct

    def get_sector(self, symbol: str) -> str:
        """Sembol → sektör. Bilinmiyorsa 'OTHER'."""
        return self._sectors.get(symbol, "OTHER")

    def check_concentration(
        self,
        symbol: str,
        notional: float,
        nav: float,
        open_positions: Dict,
    ) -> Tuple[bool, str]:
        """
        Yeni pozisyon açmadan önce konsantrasyon kontrolü.

        Dönüş: (True, "") → geçebilir | (False, sebep) → engellendi
        """
        if nav <= 0:
            return True, ""

        new_sector = self.get_sector(symbol)

        # Mevcut pozisyon notional'larını hesapla
        current_notionals: Dict[str, float] = {}
        for sym, pos in open_positions.items():
            n = float(pos.get("size", 0) or pos.get("notional", 0))
            current_notionals[sym] = n

        total_exposure = sum(current_notionals.values()) + notional

        # 1. Toplam exposure limiti
        if total_exposure / nav > self._max_total:
            reason = (
                f"total_exposure_limit: {total_exposure/nav*100:.1f}% "
                f"> {self._max_total*100:.0f}%"
            )
            log.warning("CONCENTRATION | %s | %s", symbol, reason)
            return False, reason

        # 2. Tek coin limiti
        coin_total = current_notionals.get(symbol, 0) + notional
        if coin_total / nav > self._max_single:
            reason = (
                f"single_coin_limit: {symbol} {coin_total/nav*100:.1f}% "
                f"> {self._max_single*100:.0f}%"
            )
            log.warning("CONCENTRATION | %s | %s", symbol, reason)
            return False, reason

        # 3. Sektör limiti
        sector_exposure = notional
        for sym, n in current_notionals.items():
            if self.get_sector(sym) == new_sector:
                sector_exposure += n

        if sector_exposure / nav > self._max_sector:
            reason = (
                f"sector_limit: {new_sector} {sector_exposure/nav*100:.1f}% "
                f"> {self._max_sector*100:.0f}%"
            )
            log.warning("CONCENTRATION | %s | sektor=%s | %s", symbol, new_sector, reason)
            return False, reason

        log.debug(
            "CONCENTRATION OK | %s | sektor=%s | sector_exp=%.1f%% | coin=%.1f%%",
            symbol, new_sector,
            sector_exposure / nav * 100,
            coin_total / nav * 100,
        )
        return True, ""

    def sector_breakdown(
        self,
        open_positions: Dict,
        nav: float,
    ) -> Dict[str, float]:
        """Mevcut sektör dağılımı — monitoring için."""
        breakdown: Dict[str, float] = {}
        for sym, pos in open_positions.items():
            sector = self.get_sector(sym)
            n = float(pos.get("size", 0) or pos.get("notional", 0))
            breakdown[sector] = breakdown.get(sector, 0) + n

        if nav > 0:
            return {k: round(v / nav * 100, 2) for k, v in breakdown.items()}
        return breakdown

    def concentration_score(
        self,
        open_positions: Dict,
        nav: float,
    ) -> float:
        """
        Herfindahl-Hirschman Index (HHI) bazlı konsantrasyon skoru.
        0 → tam diversifiye | 1 → tek pozisyon
        """
        if not open_positions or nav <= 0:
            return 0.0
        weights = []
        for pos in open_positions.values():
            n = float(pos.get("size", 0) or pos.get("notional", 0))
            weights.append(n / nav)
        return round(sum(w ** 2 for w in weights), 4)

    def snapshot(self, open_positions: Dict, nav: float) -> Dict:
        return {
            "sector_breakdown":      self.sector_breakdown(open_positions, nav),
            "concentration_score":   self.concentration_score(open_positions, nav),
            "max_sector_pct":        self._max_sector * 100,
            "max_single_pct":        self._max_single * 100,
            "max_total_pct":         self._max_total * 100,
        }
