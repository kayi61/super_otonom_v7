from __future__ import annotations

"""
MarketAnalyzer v5.1
─────────────────────────────────────────────────────────────────────────────
v5   → detect_market_regime() + Hurst regime filtreli sinyal motoru
v5.1 → analyze_v5_1(): Üst zaman dilimi (4H) trend uyum kontrolü
         1H BUY sinyali + 4H trend DOWN → sinyal HOLD'a düşürülür
         Çoklu zaman dilimi doğrulaması: false signal oranını azaltır
"""

import logging
import math
import os
from typing import Any, Dict, List, Tuple

import numpy as np

from super_otonom.signal_quality_scorer import compute_signal_quality

log = logging.getLogger("super_otonom.analyzer")

# ── Sinyal bantları — env ile override edilebilir ─────────────────────────────
_BUY_RSI_LO  = float(os.getenv("ANALYZER_BUY_RSI_MIN",  "42") or 42)
_BUY_RSI_HI  = float(os.getenv("ANALYZER_BUY_RSI_MAX",  "68") or 68)
_SELL_RSI_LO = float(os.getenv("ANALYZER_SELL_RSI_MIN", "32") or 32)
_SELL_RSI_HI = float(os.getenv("ANALYZER_SELL_RSI_MAX", "58") or 58)
_MIN_CLOSES  = max(3, int(os.getenv("ANALYZER_MIN_CLOSES", "30") or 30))

# ── Hurst parametreleri ───────────────────────────────────────────────────────
_HURST_TREND_FLOOR    = float(os.getenv("HURST_TREND_FLOOR",    "0.55") or 0.55)
_HURST_REVERTING_CEIL = float(os.getenv("HURST_REVERTING_CEIL", "0.45") or 0.45)


# ─────────────────────────────────────────────────────────────────────────────
#  Teknik gösterge hesapları
# ─────────────────────────────────────────────────────────────────────────────

def _ema(values: List[float], period: int) -> float:
    if not values:
        return 0.0
    k = 2 / (period + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e


def _rsi(closes: List[float], period: int = 14) -> float:
    """Wilder smoothing RSI — daha gerçekçi."""
    if len(closes) < period + 1:
        return 50.0
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        ch = closes[i] - closes[i - 1]
        if ch >= 0:
            gains += ch
        else:
            losses += abs(ch)
    avg_gain = gains / period
    avg_loss = losses / period

    for i in range(period + 1, len(closes)):
        ch = closes[i] - closes[i - 1]
        gain = ch if ch > 0 else 0.0
        loss = abs(ch) if ch < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _bollinger(closes: List[float], period: int = 20, k: float = 2.0):
    """Bollinger Bands: (mid, upper, lower, pct_b)"""
    if len(closes) < period:
        mid = closes[-1] if closes else 0.0
        return mid, mid, mid, 0.5
    window = closes[-period:]
    mid = sum(window) / period
    std = math.sqrt(sum((x - mid) ** 2 for x in window) / period)
    upper = mid + k * std
    lower = mid - k * std
    price = closes[-1]
    band_width = upper - lower
    pct_b = (price - lower) / band_width if band_width > 0 else 0.5
    return mid, upper, lower, max(0.0, min(1.0, pct_b))


def _atr(candles: List[Dict], period: int = 14) -> float:
    """Average True Range — volatilite ölçütü."""
    if len(candles) < 2:
        return 0.01
    trs = []
    for i in range(1, len(candles)):
        h  = float(candles[i].get("high",  0) or 0)
        lo = float(candles[i].get("low",   0) or 0)
        pc = float(candles[i - 1].get("close", 0) or 0)
        tr = max(h - lo, abs(h - pc), abs(lo - pc))
        trs.append(tr)
    recent = trs[-period:]
    return sum(recent) / len(recent) if recent else 0.01


def _volume_ratio(candles: List[Dict], short: int = 5, long: int = 20) -> float:
    """Son 5 mum hacminin son 20 mum ortalamasına oranı."""
    if len(candles) < long:
        return 1.0
    vols = [float(c.get("volume") or 0.0) for c in candles]
    short_avg = sum(vols[-short:]) / short
    long_avg  = sum(vols[-long:])  / long
    return short_avg / long_avg if long_avg > 0 else 1.0


def _calculate_hurst(ts: List[float]) -> float:
    """
    Hurst Exponent — R/S analizi.
    0.5  → Rastgele (brownian)
    >0.5 → Trend kalıcı (momentum)
    <0.5 → Mean-reverting (yatay/geri dönüş)
    En az 30 veri noktası gerekir; yetersizse 0.5 döner.
    """
    if len(ts) < 30:
        return 0.5
    try:
        lags = range(2, 20)
        tau  = [
            np.sqrt(np.std(np.subtract(ts[lag:], ts[:-lag])))
            for lag in lags
        ]
        poly = np.polyfit(np.log(lags), np.log(tau), 1)
        h = float(poly[0] * 2.0)
        return max(0.0, min(1.0, h))
    except Exception:
        return 0.5


def _rising_last_two_closes(closes: List[float]) -> bool:
    return len(closes) >= 2 and closes[-1] > closes[-2]


def _falling_last_two_closes(closes: List[float]) -> bool:
    return len(closes) >= 2 and closes[-1] < closes[-2]


# ─────────────────────────────────────────────────────────────────────────────
#  v5: Piyasa Rejimi Tespiti
# ─────────────────────────────────────────────────────────────────────────────

def detect_market_regime(hurst_val: float) -> str:
    """
    Hurst değerine göre piyasa karakterini belirler.

    TRENDING       (H > 0.55) → Trend takip stratejileri geçerli (EMA, momentum)
    MEAN_REVERTING (H < 0.45) → Kanallara geri dönen stratejiler (RSI, BB)
    NOISY          (0.45-0.55)→ Belirsiz bölge — işlem açılmamalı
    """
    if hurst_val > _HURST_TREND_FLOOR:
        return "TRENDING"
    elif hurst_val < _HURST_REVERTING_CEIL:
        return "MEAN_REVERTING"
    return "NOISY"


# ─────────────────────────────────────────────────────────────────────────────
#  Ana analizör
# ─────────────────────────────────────────────────────────────────────────────

class MarketAnalyzer:
    """
    v5.1 — Hurst Regime Filtreli + Çoklu Zaman Dilimi Sinyal Motoru

    Sinyal hiyerarşisi:
      1. Hurst Regime Filtresi  (v5)  : NOISY/MEAN_REVERTING → HOLD
      2. 4H Trend Uyum Kontrolü (v5.1): 1H BUY + 4H DOWN      → HOLD
      3. 1H EMA + RSI + Momentum       : TRENDING piyasada karar ver

    Dış ML köprüsü: `blend_omega_confidence` (ai_confidence_bridge) — analiz dict’ine
    ml_score / omega_ml_score (0-1) verildiğinde güven birleşimi.

    Yeni metot:
      analyze_v5_1(symbol, candles_1h, candles_4h)
        → Çoklu TF analizi, 4H doğrulaması içeren sonuç döner

    Eski metot (geriye uyumlu):
      analyze(symbol, candles) → Tek zaman dilimi (v5 davranışı)
    """

    @staticmethod
    def apply_liquidity_context(
        analysis: Dict[str, Any],
        ob_safe: Any,
        target_notional: float,
    ) -> None:
        """
        Emir defteri tavanı (ob_safe) ile teknik tavan (target_notional) oranı — sadece zenginleştirme.
        Mum/RSI sinyaline dokunmaz; `analysis` dict'ini yerinde günceller.

        - liquidity_ratio ≈ min(1, ob_safe / target_notional) — hedef 0 iken: unknown
        - entry_scale: full | scaled | minimal | blocked | unknown
        Eşikler: LIQ_SCALE_FULL (0.8), LIQ_SCALE_SCALED (0.3) env.
        """
        t_full  = float(os.getenv("LIQ_SCALE_FULL", "0.8") or 0.8)
        t_scal  = float(os.getenv("LIQ_SCALE_SCALED", "0.3") or 0.3)
        t_full  = max(0.01, min(0.99, t_full))
        t_scal  = max(0.01, min(t_full - 0.01, t_scal))

        tn = max(0.0, float(target_notional or 0.0))

        if ob_safe is None:
            analysis["liquidity_ratio"] = None
            analysis["entry_scale"] = "unknown"
            return
        try:
            ob = float(ob_safe)
        except (TypeError, ValueError):
            analysis["liquidity_ratio"] = None
            analysis["entry_scale"] = "unknown"
            return

        if ob <= 0:
            analysis["liquidity_ratio"] = 0.0
            analysis["entry_scale"] = "blocked"
            return

        if tn <= 0:
            analysis["liquidity_ratio"] = None
            analysis["entry_scale"] = "unknown"
            return

        ratio = min(1.0, ob / tn)
        analysis["liquidity_ratio"] = round(ratio, 4)

        if ratio >= t_full:
            analysis["entry_scale"] = "full"
        elif ratio >= t_scal:
            analysis["entry_scale"] = "scaled"
        else:
            analysis["entry_scale"] = "minimal"

    # ── v5.1 YENİLİK: Çoklu Zaman Dilimi Analizi ─────────────────────────────

    def analyze_v5_1(
        self,
        symbol: str,
        candles_1h: List[Dict[str, float]],
        candles_4h: List[Dict[str, float]],
    ) -> Dict[str, Any]:
        """
        Üst zaman dilimi (4H) trend doğrulaması ile birleşik analiz.

        Adımlar:
          1. 4H mumlardan EMA(9) ve EMA(21) hesapla → yön belirle (UP/DOWN)
          2. 1H mumlardan standart analyze() çalıştır
          3. Trend uyumu kontrol et:
             1H=BUY  + 4H=DOWN → signal=HOLD (üst trend onaylamıyor)
             1H=SELL + 4H=UP   → signal=HOLD (üst trend onaylamıyor)
             Uyum varsa → sinyal olduğu gibi bırakılır

        Dönüş: analyze() çıktısı + high_tf_trend + mtf_filtered alanları
        """
        # 4H üst trend yönü
        if candles_4h and len(candles_4h) >= 22:
            closes_4h   = [float(c["close"]) for c in candles_4h if c.get("close")]
            ema_4h_fast = _ema(closes_4h, 9)
            ema_4h_slow = _ema(closes_4h, 21)
            high_tf_trend = "UP" if ema_4h_fast > ema_4h_slow else "DOWN"
        else:
            high_tf_trend = "UNKNOWN"
            # 4H veri yoksa uyumluluk kontrolü atlanır
            result = self.analyze(symbol, candles_1h)
            result["high_tf_trend"] = high_tf_trend
            result["mtf_filtered"]  = False
            result["mtf_reason"]    = "4H veri yetersiz — kontrol atlandı"
            return result

        # 1H analizi (v5 rejim filtresi dahil)
        result = self.analyze(symbol, candles_1h)

        # 4H trend uyum kontrolü
        original_signal = result["signal"]
        mtf_filtered    = False
        mtf_reason      = "4H trend uyumlu"

        if original_signal == "BUY" and high_tf_trend != "UP":
            result["signal"]      = "HOLD"
            result["futures_side"] = "FLAT"
            mtf_filtered          = True
            mtf_reason            = f"4H trend aykiri: 1H=BUY ama 4H={high_tf_trend}"
            result["reason"]      = mtf_reason
            result["regime_reason"] = (
                result.get("regime_reason", "") + f" | MTF: {mtf_reason}"
            )

        elif original_signal == "SELL" and high_tf_trend != "DOWN":
            result["signal"]       = "HOLD"
            result["futures_side"] = "FLAT"
            mtf_filtered           = True
            mtf_reason             = f"4H trend aykiri: 1H=SELL ama 4H={high_tf_trend}"
            result["reason"]       = mtf_reason
            result["regime_reason"] = (
                result.get("regime_reason", "") + f" | MTF: {mtf_reason}"
            )

        result["high_tf_trend"] = high_tf_trend
        result["mtf_filtered"]  = mtf_filtered
        result["mtf_reason"]    = mtf_reason

        if mtf_filtered:
            log.info(
                "MTF_FILTRE: symbol=%s | 1H=%s → HOLD | %s",
                symbol, original_signal, mtf_reason,
            )
        else:
            log.debug(
                "MTF OK: symbol=%s | sinyal=%s | 4H=%s",
                symbol, result["signal"], high_tf_trend,
            )

        return result

    # ── v5 tek zaman dilimi analizi (geriye uyumlu) ───────────────────────────

    def analyze(self, symbol: str, candles: List[Dict[str, float]]) -> Dict[str, Any]:
        if not candles:
            return _empty(symbol)

        closes = [float(c["close"]) for c in candles if c.get("close") is not None]
        if len(closes) < _MIN_CLOSES:
            return _empty(symbol)

        # ── Temel göstergeler ──────────────────────────────────────────────
        rsi      = _rsi(closes, 14)
        ema_fast = _ema(closes[-60:],  9)
        ema_slow = _ema(closes[-120:], 21)
        ema_diff = 0.0 if ema_slow == 0 else (ema_fast - ema_slow) / ema_slow

        _, _, _, bb_pct_b = _bollinger(closes, 20, 2.0)

        atr        = _atr(candles, 14)
        last_close = closes[-1] if closes else 1.0
        vol        = atr / (last_close + 1e-9)

        vol_ratio = _volume_ratio(candles, 5, 20)

        # ── Hurst Exponent ─────────────────────────────────────────────────
        hurst_val = _calculate_hurst(closes[-100:])

        # ── v5: Regime tespiti ─────────────────────────────────────────────
        regime = detect_market_regime(hurst_val)

        # Eski market_state mantığını koruyoruz (geriye dönük uyumluluk)
        if hurst_val > _HURST_TREND_FLOOR or abs(ema_diff) > 0.005 or vol > 0.025:
            market_state = "TREND"
        elif hurst_val < _HURST_REVERTING_CEIL:
            market_state = "MEAN_REVERTING"
        elif vol < 0.008 and 40.0 < rsi < 60.0 and abs(ema_diff) < 0.002:
            market_state = "SIDEWAYS"
        else:
            market_state = "NEUTRAL"

        # ── v5: Rejime bağlı sinyal mantığı ───────────────────────────────
        up      = ema_fast > ema_slow
        down    = ema_fast < ema_slow
        rising  = _rising_last_two_closes(closes)
        falling = _falling_last_two_closes(closes)

        buy_ok  = up   and (_BUY_RSI_LO  < rsi < _BUY_RSI_HI)  and rising
        sell_ok = down and (_SELL_RSI_LO < rsi < _SELL_RSI_HI) and falling

        if regime == "NOISY":
            signal        = "HOLD"
            futures_side  = "FLAT"
            regime_reason = f"NOISY piyasa (Hurst={hurst_val:.3f}, 0.45-0.55 band)"
        elif regime == "MEAN_REVERTING":
            signal        = "HOLD"
            futures_side  = "FLAT"
            regime_reason = f"MEAN_REVERTING piyasa (Hurst={hurst_val:.3f} < {_HURST_REVERTING_CEIL})"
        else:
            signal        = "BUY"  if buy_ok  else ("SELL" if sell_ok  else "HOLD")
            futures_side  = "LONG" if buy_ok  else ("SHORT" if sell_ok else "FLAT")
            regime_reason = f"TRENDING piyasa (Hurst={hurst_val:.3f} > {_HURST_TREND_FLOOR})"

        # ── Flash crash tespiti ────────────────────────────────────────────
        flash_crash = False
        if len(closes) >= 3:
            drop = (closes[-3] - closes[-1]) / (closes[-3] + 1e-9)
            flash_crash = drop > 0.03

        return {
            "symbol":        symbol,
            "signal":        signal,
            "futures_side":  futures_side,
            "ema_fast":      float(ema_fast),
            "ema_slow":      float(ema_slow),
            "rsi":           float(rsi),
            "ema_diff":      float(ema_diff),
            "volatility":    float(vol),
            "vol_ratio":     float(vol_ratio),
            "bb_pct_b":      float(bb_pct_b),
            "atr":           float(atr),
            "flash_crash":   flash_crash,
            "market_state":  market_state,
            "hurst":         round(hurst_val, 4),
            "regime":        regime,
            "regime_reason": regime_reason,
            "momentum":      bool(buy_ok),
            "sentiment_score": 0.0,
            # MTF alanları — analyze_v5_1 tarafından doldurulur, yoksa None
            "high_tf_trend": None,
            "mtf_filtered":  False,
            "mtf_reason":    "",
            "thresholds": {
                "min_closes":      _MIN_CLOSES,
                "spot_buy_rsi":    (_BUY_RSI_LO, _BUY_RSI_HI),
                "spot_sell_rsi":   (_SELL_RSI_LO, _SELL_RSI_HI),
                "hurst_trend":     _HURST_TREND_FLOOR,
                "hurst_reverting": _HURST_REVERTING_CEIL,
            },
        }

    @staticmethod
    def score_signal_quality(
        analysis: Dict[str, Any],
    ) -> Tuple[int, List[str], Dict[str, float], str]:
        """
        Sinyal kalitesi (0-100) — bkz. `signal_quality_scorer.compute_signal_quality`.
        Dönüş: (score, penalty_reasons, component_scores, quality_main_penalty)
        """
        return compute_signal_quality(analysis)

    def summary(self) -> str:
        return (
            "Analyzer v5.1: Hurst Regime filtreli + Çoklu Zaman Dilimi sinyal motoru. "
            "NOISY/MEAN_REVERTING → HOLD. TRENDING + 4H uyum → BUY/SELL. "
            "Wilder RSI, Bollinger, ATR, Hurst, MTF doğrulama aktif."
        )


def _empty(symbol: str) -> Dict[str, Any]:
    return {
        "symbol":        symbol,
        "signal":        "HOLD",
        "futures_side":  "FLAT",
        "ema_fast":      0.0,
        "ema_slow":      0.0,
        "rsi":           50.0,
        "ema_diff":      0.0,
        "volatility":    0.0,
        "vol_ratio":     1.0,
        "bb_pct_b":      0.5,
        "atr":           0.0,
        "flash_crash":   False,
        "market_state":  "NEUTRAL",
        "hurst":         0.5,
        "regime":        "NOISY",
        "regime_reason": "Yetersiz veri",
        "momentum":      False,
        "sentiment_score": 0.0,
        "high_tf_trend": None,
        "mtf_filtered":  False,
        "mtf_reason":    "",
    }
