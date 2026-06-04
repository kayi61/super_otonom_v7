"""PROMPT-6.1 — Makroekonomik Event Tracker — regime/meta_regime feed.

Kripto piyasayı etkileyen makro olayları takip eder; `regime_detection_engine`
(Faz 26) ve `meta_regime_orchestrator` (A9) rejim çıkarımını makro ortamla
zenginleştirir.

1. **Ekonomik takvim**: FED faiz kararı/beklenti, CPI/PPI, işsizlik, FOMC tutanak.
2. **Makro indikatörler**: DXY (↑ = crypto↓), US 10Y yield, S&P/Nasdaq korelasyonu,
   VIX (>30 = risk-off).
3. **Likidite**: Fed balance sheet (QE/QT), M2, reverse repo, global net likidite
   (Fed + ECB + BOJ + PBOC).
4. **Geopolitik**: savaş/yaptırım keyword, CBDC, regülasyon (SEC, EU MiCA).

Sinyal mantığı:
- FED dovish + DXY düşüş + M2 artış → **BULLISH** ortam.
- FED hawkish + DXY yükseliş + VIX spike → **RISK_OFF**, risk azalt.
- CPI surprise (beklentiden yüksek) → volatilite spike beklentisi.

Kaynaklar: FRED (Federal Reserve, ücretsiz) / investing.com (enjekte edilebilir
``http_get``). Analiz fonksiyonları saftır (ağsız test edilir).
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

log = logging.getLogger("super_otonom.macro")

HttpGet = Callable[[str, float], Optional[str]]

# Makro ortam etiketleri
BULLISH = "BULLISH"
BEARISH = "BEARISH"
NEUTRAL = "NEUTRAL"
RISK_OFF = "RISK_OFF"

# Kanonik rejim ipuçları (omega / meta_regime ile aynı üçlü)
TRENDING = "TRENDING"
RANGING = "RANGING"
CRASH_RISK = "CRASH_RISK"
UNKNOWN = "UNKNOWN"

VIX_RISK_OFF = 30.0             # VIX > 30 → risk-off
VIX_ELEVATED = 22.0

_WAR_KW = re.compile(r"\b(war|invasion|invade|military|conflict|sanction|sanctions|missile|attack)\b", re.I)
_REG_KW = re.compile(r"\b(sec|lawsuit|ban|crackdown|mica|regulation|regulatory|enforcement|subpoena)\b", re.I)
_CBDC_KW = re.compile(r"\b(cbdc|digital euro|digital dollar|digital yuan)\b", re.I)


def _coerce_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else float(x)


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _truthy(v: Any) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y", "evet")
    return bool(v)


def _default_http_get(url: str, timeout: float) -> Optional[str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "super_otonom/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        log.debug("macro http_get hata (%s): %s", url[:60], exc)
        return None


def _stance_bias(stance: Any) -> float:
    """FED duruşu → bias (dovish=+1, hawkish=-1, neutral=0)."""
    s = str(stance or "").strip().lower()
    if s in ("dovish", "dove", "cut", "easing", "ease"):
        return 1.0
    if s in ("hawkish", "hawk", "hike", "tightening", "tighten"):
        return -1.0
    return 0.0


def _trend_dir(trend: Any, change: Optional[float] = None, *, eps: float = 0.0) -> int:
    """'up'/'down' string veya sayısal değişimden yön (+1/0/-1)."""
    s = str(trend or "").strip().lower()
    if s in ("up", "rising", "rise", "bullish", "expanding", "qe", "higher", "increase"):
        return 1
    if s in ("down", "falling", "fall", "bearish", "contracting", "qt", "lower", "decrease", "draining"):
        return -1
    c = _coerce_float(change)
    if c is not None:
        if c > eps:
            return 1
        if c < -eps:
            return -1
    return 0


# ── 1) Ekonomik takvim ───────────────────────────────────────────────────────


def analyze_economic_calendar(
    *,
    fed_stance: Any = None,
    cpi_actual: Optional[float] = None,
    cpi_expected: Optional[float] = None,
    ppi_actual: Optional[float] = None,
    ppi_expected: Optional[float] = None,
    fomc_sentiment: Optional[float] = None,
    days_until_major_event: Optional[float] = None,
) -> Tuple[float, float, Optional[float], List[str]]:
    """FED/CPI/PPI/FOMC → (bias [-1,1], vol_expectation [0,1], cpi_surprise, reasons)."""
    reasons: List[str] = []
    bias = 0.45 * _stance_bias(fed_stance)
    if _stance_bias(fed_stance) > 0:
        reasons.append("FED dovish")
    elif _stance_bias(fed_stance) < 0:
        reasons.append("FED hawkish")

    vol = 0.0
    cpi_surprise: Optional[float] = None
    ca, ce = _coerce_float(cpi_actual), _coerce_float(cpi_expected)
    if ca is not None and ce is not None:
        cpi_surprise = ca - ce
        # Beklentiden yüksek CPI → hawkish baskı (bearish) + volatilite
        bias -= _clamp(cpi_surprise / 0.5, -0.6, 0.6)
        vol = max(vol, _clamp01(abs(cpi_surprise) / 0.4))
        if cpi_surprise > 0.05:
            reasons.append(f"CPI beklentiden yüksek (+{cpi_surprise:.2f}) → volatilite/hawkish")
        elif cpi_surprise < -0.05:
            reasons.append(f"CPI beklentiden düşük ({cpi_surprise:.2f}) → dovish eğilim")

    pa, pe = _coerce_float(ppi_actual), _coerce_float(ppi_expected)
    if pa is not None and pe is not None:
        bias -= _clamp((pa - pe) / 0.8, -0.3, 0.3)

    fs = _coerce_float(fomc_sentiment)
    if fs is not None:
        bias += 0.2 * _clamp(fs, -1.0, 1.0)

    due = _coerce_float(days_until_major_event)
    if due is not None and 0 <= due <= 2:
        vol = max(vol, 0.5)
        reasons.append("Yaklaşan büyük makro olay (≤2 gün) → volatilite beklentisi")

    return _clamp(bias, -1.0, 1.0), _clamp01(vol), cpi_surprise, reasons


# ── 2) Makro indikatörler ────────────────────────────────────────────────────


def analyze_macro_indicators(
    *,
    dxy_trend: Any = None,
    dxy_change_pct: Optional[float] = None,
    yield_10y_change: Optional[float] = None,
    spx_trend: Any = None,
    vix: Optional[float] = None,
) -> Tuple[float, bool, float, List[str]]:
    """DXY/yield/SPX/VIX → (bias [-1,1], risk_off, risk [0,1], reasons)."""
    reasons: List[str] = []
    bias = 0.0
    risk = 0.0

    dxy = _trend_dir(dxy_trend, dxy_change_pct)
    if dxy > 0:
        bias -= 0.35  # DXY↑ → crypto↓
        reasons.append("DXY yükseliş → crypto baskı")
    elif dxy < 0:
        bias += 0.30
        reasons.append("DXY düşüş → crypto destek")

    y = _coerce_float(yield_10y_change)
    if y is not None and y > 0:
        bias -= _clamp(y / 0.5, 0.0, 0.25)

    spx = _trend_dir(spx_trend)
    if spx > 0:
        bias += 0.15
    elif spx < 0:
        bias -= 0.15
        risk = max(risk, 0.3)

    v = _coerce_float(vix)
    risk_off = False
    if v is not None:
        if v >= VIX_RISK_OFF:
            risk_off = True
            bias -= 0.45
            risk = max(risk, _clamp01(0.6 + (v - VIX_RISK_OFF) / 40.0))
            reasons.append(f"VIX {v:.0f} > 30 → risk-off")
        elif v >= VIX_ELEVATED:
            risk = max(risk, 0.4)
            reasons.append(f"VIX {v:.0f} yükseldi")

    return _clamp(bias, -1.0, 1.0), risk_off, _clamp01(risk), reasons


# ── 3) Likidite ──────────────────────────────────────────────────────────────


def analyze_liquidity(
    *,
    fed_balance_sheet_trend: Any = None,
    m2_trend: Any = None,
    m2_change_pct: Optional[float] = None,
    reverse_repo_trend: Any = None,
    global_liquidity_trend: Any = None,
) -> Tuple[float, List[str]]:
    """Fed BS / M2 / RRP / global likidite → (bias [-1,1], reasons)."""
    reasons: List[str] = []
    bias = 0.0

    bs = _trend_dir(fed_balance_sheet_trend)
    if bs > 0:
        bias += 0.25
        reasons.append("Fed bilanço genişliyor (QE) → likidite")
    elif bs < 0:
        bias -= 0.25
        reasons.append("Fed bilanço daralıyor (QT) → likidite çekiliyor")

    m2 = _trend_dir(m2_trend, m2_change_pct)
    if m2 > 0:
        bias += 0.25
        reasons.append("M2 artıyor → bullish likidite")
    elif m2 < 0:
        bias -= 0.20

    # Reverse repo düşüşü → piyasaya likidite (bullish)
    rrp = _trend_dir(reverse_repo_trend)
    if rrp < 0:
        bias += 0.15
        reasons.append("Reverse repo düşüyor → likidite serbest kalıyor")
    elif rrp > 0:
        bias -= 0.10

    gl = _trend_dir(global_liquidity_trend)
    if gl > 0:
        bias += 0.20
        reasons.append("Global net likidite artıyor")
    elif gl < 0:
        bias -= 0.20

    return _clamp(bias, -1.0, 1.0), reasons


# ── 4) Geopolitik ────────────────────────────────────────────────────────────


def analyze_geopolitical(
    *,
    text: Any = None,
    war_risk: bool = False,
    sanctions: bool = False,
    regulation_news: bool = False,
    regulatory_severity: Optional[float] = None,
    cbdc_news: bool = False,
) -> Tuple[float, float, List[str]]:
    """Savaş/yaptırım/regülasyon/CBDC → (risk [0,1], bias [-1,0], reasons)."""
    reasons: List[str] = []
    risk = 0.0
    s = text if isinstance(text, str) else ""

    if war_risk or sanctions or bool(_WAR_KW.search(s)):
        risk = max(risk, 0.6)
        reasons.append("Geopolitik risk (savaş/yaptırım) tespit edildi")

    reg = regulation_news or bool(_REG_KW.search(s))
    if reg:
        sev = _coerce_float(regulatory_severity)
        risk = max(risk, _clamp01(sev) if sev is not None else 0.5)
        reasons.append("Kripto regülasyon haberi (SEC/MiCA)")

    if cbdc_news or bool(_CBDC_KW.search(s)):
        reasons.append("CBDC gelişmesi (nötr/izlenmeli)")

    bias = -risk
    return _clamp01(risk), _clamp(bias, -1.0, 0.0), reasons


# ── Birleşik makro sinyali ───────────────────────────────────────────────────


@dataclass(frozen=True)
class MacroSignal:
    environment: str                # BULLISH | BEARISH | NEUTRAL | RISK_OFF
    bias: float                     # -1..1
    risk_score: float               # 0..1
    alpha_bias: float               # -1..1
    volatility_expectation: float   # 0..1
    regime_hint: str                # TRENDING | RANGING | CRASH_RISK | UNKNOWN
    trade_permission: str           # ALLOW | BLOCK | HALT
    risk_off: bool
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "environment": self.environment,
            "macro_bias": self.bias,
            "macro_risk_score": self.risk_score,
            "macro_alpha_bias": self.alpha_bias,
            "volatility_expectation": self.volatility_expectation,
            "regime_hint": self.regime_hint,
            "trade_permission": self.trade_permission,
            "risk_off": self.risk_off,
            "macro_reasons": list(self.reasons),
        }


def _environment_to_regime(environment: str) -> str:
    if environment == BULLISH:
        return TRENDING
    if environment == RISK_OFF:
        return CRASH_RISK
    if environment == BEARISH:
        return RANGING
    return UNKNOWN


def analyze_macro(
    *,
    fed_stance: Any = None,
    cpi_actual: Optional[float] = None,
    cpi_expected: Optional[float] = None,
    ppi_actual: Optional[float] = None,
    ppi_expected: Optional[float] = None,
    fomc_sentiment: Optional[float] = None,
    days_until_major_event: Optional[float] = None,
    dxy_trend: Any = None,
    dxy_change_pct: Optional[float] = None,
    yield_10y_change: Optional[float] = None,
    spx_trend: Any = None,
    vix: Optional[float] = None,
    fed_balance_sheet_trend: Any = None,
    m2_trend: Any = None,
    m2_change_pct: Optional[float] = None,
    reverse_repo_trend: Any = None,
    global_liquidity_trend: Any = None,
    text: Any = None,
    war_risk: bool = False,
    sanctions: bool = False,
    regulation_news: bool = False,
    regulatory_severity: Optional[float] = None,
    cbdc_news: bool = False,
) -> MacroSignal:
    """Tüm makro katmanlarını birleşik bir ortam/rejim sinyaline indirger."""
    cal_bias, cal_vol, cpi_surprise, cal_reasons = analyze_economic_calendar(
        fed_stance=fed_stance, cpi_actual=cpi_actual, cpi_expected=cpi_expected,
        ppi_actual=ppi_actual, ppi_expected=ppi_expected, fomc_sentiment=fomc_sentiment,
        days_until_major_event=days_until_major_event,
    )
    ind_bias, risk_off, ind_risk, ind_reasons = analyze_macro_indicators(
        dxy_trend=dxy_trend, dxy_change_pct=dxy_change_pct,
        yield_10y_change=yield_10y_change, spx_trend=spx_trend, vix=vix,
    )
    liq_bias, liq_reasons = analyze_liquidity(
        fed_balance_sheet_trend=fed_balance_sheet_trend, m2_trend=m2_trend,
        m2_change_pct=m2_change_pct, reverse_repo_trend=reverse_repo_trend,
        global_liquidity_trend=global_liquidity_trend,
    )
    geo_risk, geo_bias, geo_reasons = analyze_geopolitical(
        text=text, war_risk=war_risk, sanctions=sanctions,
        regulation_news=regulation_news, regulatory_severity=regulatory_severity,
        cbdc_news=cbdc_news,
    )

    bias = _clamp(0.34 * cal_bias + 0.30 * ind_bias + 0.26 * liq_bias + 0.10 * geo_bias, -1.0, 1.0)
    risk = _clamp01(max(ind_risk, geo_risk, 0.5 * max(0.0, -bias)))
    vol = _clamp01(max(cal_vol, 0.6 if risk_off else 0.0))
    reasons = cal_reasons + ind_reasons + liq_reasons + geo_reasons

    # Birleşik kurallar (prompt sinyal mantığı)
    dovish = _stance_bias(fed_stance) > 0
    hawkish = _stance_bias(fed_stance) < 0
    dxy_up = _trend_dir(dxy_trend, dxy_change_pct) > 0
    dxy_down = _trend_dir(dxy_trend, dxy_change_pct) < 0
    m2_up = _trend_dir(m2_trend, m2_change_pct) > 0
    vix_spike = (_coerce_float(vix) or 0.0) >= VIX_RISK_OFF

    if dovish and dxy_down and m2_up:
        bias = _clamp(max(bias, 0.45), -1.0, 1.0)
        reasons.append("FED dovish + DXY↓ + M2↑ → BULLISH ortam")
    if hawkish and dxy_up and vix_spike:
        risk_off = True
        risk = _clamp01(max(risk, 0.8))
        reasons.append("FED hawkish + DXY↑ + VIX spike → RISK_OFF")

    if risk_off or bias <= -0.5:
        environment = RISK_OFF
    elif bias >= 0.3:
        environment = BULLISH
    elif bias <= -0.2:
        environment = BEARISH
    else:
        environment = NEUTRAL

    perm = "BLOCK" if (environment == RISK_OFF and risk >= 0.75) else "ALLOW"
    alpha = _clamp(bias, -1.0, 1.0)

    return MacroSignal(
        environment=environment,
        bias=float(bias),
        risk_score=float(risk),
        alpha_bias=float(alpha),
        volatility_expectation=float(vol),
        regime_hint=_environment_to_regime(environment),
        trade_permission=perm,
        risk_off=bool(risk_off),
        reasons=reasons,
    )


# Köprü aktivasyonu için makro anahtarları
_MACRO_KEYS = (
    "fed_stance", "cpi_actual", "cpi_expected", "ppi_actual", "ppi_expected",
    "fomc_sentiment", "days_until_major_event", "dxy_trend", "dxy_change_pct",
    "yield_10y_change", "spx_trend", "vix", "fed_balance_sheet_trend", "m2_trend",
    "m2_change_pct", "reverse_repo_trend", "global_liquidity_trend", "war_risk",
    "sanctions", "regulation_news", "regulatory_severity", "cbdc_news", "macro_text",
)


def analyze_macro_data(source: Any) -> Optional[MacroSignal]:
    """``macro`` alt dict veya düz makro anahtarları → MacroSignal. Veri yoksa None."""
    if not isinstance(source, dict):
        return None
    block = source.get("macro") if isinstance(source.get("macro"), dict) else {}
    src: Dict[str, Any] = {**source, **block}
    if not (block or any(k in source for k in _MACRO_KEYS)):
        return None

    def g(*keys: str) -> Any:
        for k in keys:
            if k in src and src[k] is not None:
                return src[k]
        return None

    return analyze_macro(
        fed_stance=g("fed_stance"),
        cpi_actual=_coerce_float(g("cpi_actual")),
        cpi_expected=_coerce_float(g("cpi_expected")),
        ppi_actual=_coerce_float(g("ppi_actual")),
        ppi_expected=_coerce_float(g("ppi_expected")),
        fomc_sentiment=_coerce_float(g("fomc_sentiment")),
        days_until_major_event=_coerce_float(g("days_until_major_event")),
        dxy_trend=g("dxy_trend"),
        dxy_change_pct=_coerce_float(g("dxy_change_pct")),
        yield_10y_change=_coerce_float(g("yield_10y_change")),
        spx_trend=g("spx_trend"),
        vix=_coerce_float(g("vix")),
        fed_balance_sheet_trend=g("fed_balance_sheet_trend"),
        m2_trend=g("m2_trend"),
        m2_change_pct=_coerce_float(g("m2_change_pct")),
        reverse_repo_trend=g("reverse_repo_trend"),
        global_liquidity_trend=g("global_liquidity_trend"),
        text=g("macro_text", "text"),
        war_risk=_truthy(g("war_risk")),
        sanctions=_truthy(g("sanctions")),
        regulation_news=_truthy(g("regulation_news")),
        regulatory_severity=_coerce_float(g("regulatory_severity")),
        cbdc_news=_truthy(g("cbdc_news")),
    )


def macro_regime_hint(source: Any) -> str:
    """Makro ortamdan kanonik rejim ipucu. Veri yoksa ``UNKNOWN``."""
    sig = analyze_macro_data(source)
    return sig.regime_hint if sig is not None else UNKNOWN


# ── Parser + Collector ───────────────────────────────────────────────────────


def parse_fred_series(payload: Any) -> Optional[float]:
    """FRED ``/series/observations`` JSON → son geçerli gözlem değeri."""
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", errors="replace")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return None
    if not isinstance(payload, dict):
        return None
    obs = payload.get("observations")
    if not isinstance(obs, list):
        return None
    for row in reversed(obs):
        if isinstance(row, dict):
            v = _coerce_float(row.get("value"))
            if v is not None:
                return v
    return None


class MacroCollector:
    """FRED makro veri toplayıcı (ücretsiz API key; mock'lanabilir)."""

    def __init__(self, *, http_get: Optional[HttpGet] = None, timeout_sec: float = 6.0) -> None:
        self._http_get: HttpGet = http_get or _default_http_get
        self._timeout = float(timeout_sec)

    def fetch_fred_series(self, series_id: str) -> Optional[float]:
        api_key = os.getenv("FRED_API_KEY", "")
        if not api_key:
            return None
        base = os.getenv("FRED_API_URL", "https://api.stlouisfed.org/fred/series/observations")
        url = f"{base}?series_id={series_id}&api_key={api_key}&file_type=json&sort_order=desc&limit=1"
        body = self._http_get(url, self._timeout)
        return parse_fred_series(body) if body else None


__all__ = [
    "BEARISH",
    "BULLISH",
    "CRASH_RISK",
    "NEUTRAL",
    "RANGING",
    "RISK_OFF",
    "TRENDING",
    "UNKNOWN",
    "VIX_RISK_OFF",
    "MacroCollector",
    "MacroSignal",
    "analyze_economic_calendar",
    "analyze_geopolitical",
    "analyze_liquidity",
    "analyze_macro",
    "analyze_macro_data",
    "analyze_macro_indicators",
    "macro_regime_hint",
    "parse_fred_series",
]
