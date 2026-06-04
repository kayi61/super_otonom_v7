"""PROMPT-6.2 — Stablecoin Dominance & Flow (signals/) — macro/likidite feed.

Stablecoin piyasa dinamiklerini izler; `macro_event_intelligence` (Faz 6.1)
likidite/makro ortamını zenginleştirir (``stablecoin_mint`` → insider_fusion
STRONG_BUY kuralını besler).

1. **Market cap**: USDT/USDC/DAI/BUSD toplam mcap trendi. Artış → yeni para girişi
   (BULLISH); düşüş → para çıkışı (BEARISH).
2. **Dominance**: stablecoin dominance ↑ → piyasa cash'e dönüyor (BEARISH);
   ↓ → cash'ten crypto'ya geçiş (BULLISH).
3. **Mint/Burn**: USDT büyük mint (>$200M) → alım gücü artışı; USDT büyük burn →
   likidite çekilmesi; USDC mint → kurumsal para girişi.
4. **Depeg**: USDT/USDC peg sapması (>%0.5 = alarm), Curve 3pool dengesizliği,
   swap volume spike → panik göstergesi.

Kaynak: CoinGecko API + on-chain USDT/USDC transfer (enjekte edilebilir ``http_get``).
Analiz fonksiyonları saftır (ağsız test edilir).
"""

from __future__ import annotations

import json
import logging
import math
import os
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

log = logging.getLogger("super_otonom.stablecoin")

HttpGet = Callable[[str, float], Optional[str]]

# Ortam etiketleri
BULLISH = "BULLISH"
BEARISH = "BEARISH"
NEUTRAL = "NEUTRAL"
RISK_OFF = "RISK_OFF"

# Eşikler
USDT_BIG_MINT_USD = 200_000_000.0       # > $200M mint → alım gücü
USDT_BIG_BURN_USD = 200_000_000.0       # > $200M burn → likidite çekilmesi
DEPEG_ALARM_PCT = 0.005                 # |peg sapması| > %0.5 → alarm


def _coerce_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else float(x)


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else float(x)


def _truthy(v: Any) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y", "on")
    return bool(v)


def _default_http_get(url: str, timeout: float) -> Optional[str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "super_otonom/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        log.debug("stablecoin http_get hata (%s): %s", url[:60], exc)
        return None


def _change(cur: Optional[float], prev: Optional[float], pct: Optional[float]) -> Optional[float]:
    p = _coerce_float(pct)
    if p is not None:
        return p
    c, pr = _coerce_float(cur), _coerce_float(prev)
    if c is not None and pr is not None and pr > 0:
        return (c - pr) / pr
    return None


# ── 1) Market cap ────────────────────────────────────────────────────────────


def analyze_market_cap(
    *,
    total_mcap: Optional[float] = None,
    total_mcap_prev: Optional[float] = None,
    mcap_change_pct: Optional[float] = None,
) -> Tuple[float, List[str]]:
    """Toplam stablecoin mcap → (bias [-1,1], reasons). Artış = yeni para = BULLISH."""
    ch = _change(total_mcap, total_mcap_prev, mcap_change_pct)
    if ch is None:
        return 0.0, []
    bias = _clamp(ch * 8.0, -0.6, 0.6)   # %5 değişim ~ 0.4
    reasons: List[str] = []
    if ch >= 0.01:
        reasons.append(f"Stablecoin mcap +%{ch * 100:.1f} → yeni para girişi (bullish)")
    elif ch <= -0.01:
        reasons.append(f"Stablecoin mcap %{ch * 100:.1f} → para çıkışı (bearish)")
    return bias, reasons


# ── 2) Dominance ─────────────────────────────────────────────────────────────


def analyze_dominance(
    *,
    dominance: Optional[float] = None,
    dominance_prev: Optional[float] = None,
    dominance_change_pct: Optional[float] = None,
) -> Tuple[float, List[str]]:
    """Stablecoin dominance → (bias, reasons). Dominance ↑ = cash'e dönüş = BEARISH (ters)."""
    ch = _change(dominance, dominance_prev, dominance_change_pct)
    if ch is None:
        return 0.0, []
    bias = _clamp(-ch * 10.0, -0.6, 0.6)   # ters yön
    reasons: List[str] = []
    if ch >= 0.005:
        reasons.append("Stablecoin dominance ↑ → piyasa cash'e dönüyor (bearish)")
    elif ch <= -0.005:
        reasons.append("Stablecoin dominance ↓ → cash'ten crypto'ya geçiş (bullish)")
    return bias, reasons


# ── 3) Mint / Burn ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MintBurnAnalysis:
    usdt_mint_usd: Optional[float]
    usdt_burn_usd: Optional[float]
    usdc_mint_usd: Optional[float]
    big_mint: bool                  # USDT > $200M mint
    big_burn: bool                  # USDT > $200M burn
    institutional_inflow: bool      # USDC mint
    bias: float                     # -1..1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "usdt_mint_usd": self.usdt_mint_usd,
            "usdt_burn_usd": self.usdt_burn_usd,
            "usdc_mint_usd": self.usdc_mint_usd,
            "big_mint": self.big_mint,
            "big_burn": self.big_burn,
            "institutional_inflow": self.institutional_inflow,
            "bias": self.bias,
        }


def analyze_mint_burn(
    *,
    usdt_mint_usd: Optional[float] = None,
    usdt_burn_usd: Optional[float] = None,
    usdc_mint_usd: Optional[float] = None,
) -> MintBurnAnalysis:
    """USDT mint/burn + USDC mint (kurumsal) → bias + bayraklar."""
    um = _coerce_float(usdt_mint_usd)
    ub = _coerce_float(usdt_burn_usd)
    uc = _coerce_float(usdc_mint_usd)

    big_mint = um is not None and um >= USDT_BIG_MINT_USD
    big_burn = ub is not None and ub >= USDT_BIG_BURN_USD
    inst = uc is not None and uc >= USDT_BIG_MINT_USD * 0.5

    bias = 0.0
    if big_mint:
        bias += _clamp(math.tanh(um / 1e9), 0.0, 0.5)
    if inst:
        bias += _clamp(math.tanh(uc / 1e9) * 0.6, 0.0, 0.4)
    if big_burn:
        bias -= _clamp(math.tanh(ub / 1e9), 0.0, 0.5)
    return MintBurnAnalysis(
        usdt_mint_usd=um, usdt_burn_usd=ub, usdc_mint_usd=uc,
        big_mint=bool(big_mint), big_burn=bool(big_burn),
        institutional_inflow=bool(inst), bias=float(_clamp(bias, -1.0, 1.0)),
    )


# ── 4) Depeg ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DepegAnalysis:
    max_depeg_pct: float            # en büyük peg sapması (mutlak)
    alarm: bool                     # > %0.5
    curve_imbalance: float          # 0..1 (3pool dengesizliği)
    swap_volume_spike: bool         # panik göstergesi
    risk: float                     # 0..1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_depeg_pct": self.max_depeg_pct,
            "alarm": self.alarm,
            "curve_imbalance": self.curve_imbalance,
            "swap_volume_spike": self.swap_volume_spike,
            "risk": self.risk,
        }


def analyze_depeg(
    *,
    usdt_price: Optional[float] = None,
    usdc_price: Optional[float] = None,
    depeg_pct: Optional[float] = None,
    curve_imbalance: Optional[float] = None,
    swap_volume_spike: bool = False,
) -> DepegAnalysis:
    """Peg sapması + Curve dengesizliği + swap spike → depeg riski."""
    deviations: List[float] = []
    dp = _coerce_float(depeg_pct)
    if dp is not None:
        deviations.append(abs(dp))
    for px in (usdt_price, usdc_price):
        p = _coerce_float(px)
        if p is not None:
            deviations.append(abs(p - 1.0))
    max_dev = max(deviations) if deviations else 0.0

    curve = _clamp01(_coerce_float(curve_imbalance) or 0.0)
    alarm = max_dev >= DEPEG_ALARM_PCT
    spike = _truthy(swap_volume_spike)

    risk = 0.0
    if alarm:
        risk = _clamp01(0.6 + max_dev * 20.0)
    risk = max(risk, 0.5 * curve)
    if spike:
        risk = max(risk, 0.5)
    return DepegAnalysis(
        max_depeg_pct=float(max_dev), alarm=bool(alarm),
        curve_imbalance=float(curve), swap_volume_spike=bool(spike),
        risk=float(_clamp01(risk)),
    )


# ── Birleşik sinyal ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StablecoinSignal:
    environment: str                # BULLISH | BEARISH | NEUTRAL | RISK_OFF
    bias: float                     # -1..1
    risk_score: float               # 0..1
    stablecoin_mint: bool           # büyük mint (alım gücü) → STRONG_BUY beslemesi
    depeg_alarm: bool
    depeg_risk: float               # 0..1
    mint_burn: Optional[MintBurnAnalysis]
    depeg: Optional[DepegAnalysis]
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "environment": self.environment,
            "stablecoin_bias": self.bias,
            "stablecoin_risk_score": self.risk_score,
            "stablecoin_mint": self.stablecoin_mint,
            "depeg_alarm": self.depeg_alarm,
            "depeg_risk": self.depeg_risk,
            "stablecoin_reasons": list(self.reasons),
        }
        if self.mint_burn is not None:
            out["mint_burn"] = self.mint_burn.to_dict()
        if self.depeg is not None:
            out["depeg"] = self.depeg.to_dict()
        return out


def analyze_stablecoin(
    *,
    total_mcap: Optional[float] = None,
    total_mcap_prev: Optional[float] = None,
    mcap_change_pct: Optional[float] = None,
    dominance: Optional[float] = None,
    dominance_prev: Optional[float] = None,
    dominance_change_pct: Optional[float] = None,
    usdt_mint_usd: Optional[float] = None,
    usdt_burn_usd: Optional[float] = None,
    usdc_mint_usd: Optional[float] = None,
    usdt_price: Optional[float] = None,
    usdc_price: Optional[float] = None,
    depeg_pct: Optional[float] = None,
    curve_imbalance: Optional[float] = None,
    swap_volume_spike: bool = False,
) -> Optional[StablecoinSignal]:
    """Stablecoin dinamiklerini ortam/bias/risk'e indirger. Veri yoksa None."""
    mcap_bias, mcap_reasons = analyze_market_cap(
        total_mcap=total_mcap, total_mcap_prev=total_mcap_prev, mcap_change_pct=mcap_change_pct,
    )
    dom_bias, dom_reasons = analyze_dominance(
        dominance=dominance, dominance_prev=dominance_prev,
        dominance_change_pct=dominance_change_pct,
    )
    has_mb = any(v is not None for v in (usdt_mint_usd, usdt_burn_usd, usdc_mint_usd))
    mb = analyze_mint_burn(
        usdt_mint_usd=usdt_mint_usd, usdt_burn_usd=usdt_burn_usd, usdc_mint_usd=usdc_mint_usd,
    ) if has_mb else None
    has_dp = any(v is not None for v in (usdt_price, usdc_price, depeg_pct, curve_imbalance)) or swap_volume_spike
    dp = analyze_depeg(
        usdt_price=usdt_price, usdc_price=usdc_price, depeg_pct=depeg_pct,
        curve_imbalance=curve_imbalance, swap_volume_spike=swap_volume_spike,
    ) if has_dp else None

    has_mcap = mcap_change_pct is not None or (total_mcap is not None and total_mcap_prev is not None)
    has_dom = dominance_change_pct is not None or (dominance is not None and dominance_prev is not None)
    if not (has_mcap or has_dom or has_mb or has_dp):
        return None

    reasons = mcap_reasons + dom_reasons
    bias = _clamp(0.4 * mcap_bias + 0.35 * dom_bias + (0.5 * mb.bias if mb else 0.0), -1.0, 1.0)

    risk = 0.0
    depeg_alarm = False
    depeg_risk = 0.0
    if dp is not None:
        depeg_alarm = dp.alarm
        depeg_risk = dp.risk
        risk = max(risk, dp.risk)
        if dp.alarm:
            bias = _clamp(bias - 0.3, -1.0, 1.0)
            reasons.append(f"Stablecoin depeg alarmı (%{dp.max_depeg_pct * 100:.2f} sapma) → panik riski")
        if dp.swap_volume_spike:
            reasons.append("Stablecoin swap volume spike → panik göstergesi")

    stablecoin_mint = bool(mb and mb.big_mint)
    if mb is not None:
        if mb.big_mint:
            reasons.append(f"USDT büyük mint (${(mb.usdt_mint_usd or 0) / 1e6:.0f}M) → alım gücü artışı")
        if mb.big_burn:
            reasons.append("USDT büyük burn → likidite çekilmesi")
        if mb.institutional_inflow:
            reasons.append("USDC mint → kurumsal para girişi (Circle/Coinbase)")

    if depeg_alarm and depeg_risk >= 0.6:
        environment = RISK_OFF
    elif bias >= 0.15:
        environment = BULLISH
    elif bias <= -0.15:
        environment = BEARISH
    else:
        environment = NEUTRAL

    return StablecoinSignal(
        environment=environment,
        bias=float(bias),
        risk_score=float(_clamp01(risk)),
        stablecoin_mint=stablecoin_mint,
        depeg_alarm=bool(depeg_alarm),
        depeg_risk=float(depeg_risk),
        mint_burn=mb,
        depeg=dp,
        reasons=reasons,
    )


_STABLE_KEYS = (
    "total_mcap", "total_mcap_prev", "mcap_change_pct", "dominance", "dominance_prev",
    "dominance_change_pct", "usdt_mint_usd", "usdt_burn_usd", "usdc_mint_usd",
    "usdt_price", "usdc_price", "depeg_pct", "curve_imbalance", "swap_volume_spike",
)


def analyze_stablecoin_data(source: Any) -> Optional[StablecoinSignal]:
    """``stablecoin`` alt dict veya düz anahtarlar → StablecoinSignal. Veri yoksa None."""
    if not isinstance(source, dict):
        return None
    block = source.get("stablecoin") if isinstance(source.get("stablecoin"), dict) else {}
    src: Dict[str, Any] = {**source, **block}
    if not (block or any(k in source for k in _STABLE_KEYS)):
        return None

    def g(*keys: str) -> Any:
        for k in keys:
            if k in src and src[k] is not None:
                return src[k]
        return None

    return analyze_stablecoin(
        total_mcap=_coerce_float(g("total_mcap")),
        total_mcap_prev=_coerce_float(g("total_mcap_prev")),
        mcap_change_pct=_coerce_float(g("mcap_change_pct")),
        dominance=_coerce_float(g("dominance")),
        dominance_prev=_coerce_float(g("dominance_prev")),
        dominance_change_pct=_coerce_float(g("dominance_change_pct")),
        usdt_mint_usd=_coerce_float(g("usdt_mint_usd")),
        usdt_burn_usd=_coerce_float(g("usdt_burn_usd")),
        usdc_mint_usd=_coerce_float(g("usdc_mint_usd")),
        usdt_price=_coerce_float(g("usdt_price")),
        usdc_price=_coerce_float(g("usdc_price")),
        depeg_pct=_coerce_float(g("depeg_pct")),
        curve_imbalance=_coerce_float(g("curve_imbalance")),
        swap_volume_spike=_truthy(g("swap_volume_spike")),
    )


# ── Parser + Collector ───────────────────────────────────────────────────────


def parse_coingecko_stablecoins(payload: Any) -> Dict[str, float]:
    """CoinGecko ``/coins/markets`` (stablecoin) JSON → {total_mcap, by_coin}."""
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", errors="replace")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return {}
    if not isinstance(payload, list):
        return {}
    total = 0.0
    found = False
    for row in payload:
        if isinstance(row, dict):
            mc = _coerce_float(row.get("market_cap"))
            if mc is not None:
                total += mc
                found = True
    return {"total_mcap": total} if found else {}


class StablecoinCollector:
    """CoinGecko stablecoin toplayıcı (ücretsiz; mock'lanabilir)."""

    def __init__(self, *, http_get: Optional[HttpGet] = None, timeout_sec: float = 6.0) -> None:
        self._http_get: HttpGet = http_get or _default_http_get
        self._timeout = float(timeout_sec)

    def fetch_total_mcap(self) -> Optional[float]:
        base = os.getenv("COINGECKO_API_URL", "https://api.coingecko.com/api/v3")
        url = f"{base}/coins/markets?vs_currency=usd&category=stablecoins&per_page=20"
        body = self._http_get(url, self._timeout)
        out = parse_coingecko_stablecoins(body) if body else {}
        return out.get("total_mcap")


__all__ = [
    "BEARISH",
    "BULLISH",
    "DEPEG_ALARM_PCT",
    "NEUTRAL",
    "RISK_OFF",
    "USDT_BIG_MINT_USD",
    "DepegAnalysis",
    "MintBurnAnalysis",
    "StablecoinCollector",
    "StablecoinSignal",
    "analyze_depeg",
    "analyze_dominance",
    "analyze_market_cap",
    "analyze_mint_burn",
    "analyze_stablecoin",
    "analyze_stablecoin_data",
    "parse_coingecko_stablecoins",
]
