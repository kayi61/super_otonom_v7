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

from super_otonom.signals.signal_quality_scorer import compute_signal_quality

log = logging.getLogger("super_otonom.analyzer")

# ── Sinyal bantları — env ile override edilebilir (dar bant = az BUY) ───────────
_BUY_RSI_LO = float(os.getenv("ANALYZER_BUY_RSI_MIN", "38") or 38)
_BUY_RSI_HI = float(os.getenv("ANALYZER_BUY_RSI_MAX", "72") or 72)
_SELL_RSI_LO = float(os.getenv("ANALYZER_SELL_RSI_MIN", "28") or 28)
_SELL_RSI_HI = float(os.getenv("ANALYZER_SELL_RSI_MAX", "62") or 62)
_MIN_CLOSES = max(3, int(os.getenv("ANALYZER_MIN_CLOSES", "30") or 30))
_VOL_RATIO_CONFIRM = float(os.getenv("ANALYZER_VOL_RATIO_CONFIRM", "1.3") or 1.3)
_BB_BUY_MAX = float(os.getenv("ANALYZER_BB_BUY_MAX", "0.35") or 0.35)
_BB_SELL_MIN = float(os.getenv("ANALYZER_BB_SELL_MIN", "0.65") or 0.65)
_HURST_MIN_LEN = max(10, int(os.getenv("ANALYZER_HURST_MIN_LEN", "50") or 50))
_STRICT_VOL_BB = os.getenv("ANALYZER_STRICT_VOL_BB", "0").lower() in ("1", "true", "yes", "on")

# ── Hurst parametreleri ───────────────────────────────────────────────────────
_HURST_TREND_FLOOR = float(os.getenv("HURST_TREND_FLOOR", "0.55") or 0.55)
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
        h = float(candles[i].get("high", 0) or 0)
        lo = float(candles[i].get("low", 0) or 0)
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
    long_avg = sum(vols[-long:]) / long
    return short_avg / long_avg if long_avg > 0 else 1.0


def _calculate_hurst(ts: List[float]) -> float:
    """
    Hurst Exponent — log-log varyans / lag (kısa seride gürültülü; min uzunluk env).
    0.5  → Rastgele (brownian)
    >0.5 → Trend kalıcı (momentum)
    <0.5 → Mean-reverting (yatay/geri dönüş)
    """
    if len(ts) < _HURST_MIN_LEN:
        return 0.5
    try:
        n = len(ts)
        max_lag = max(3, min(20, n // 4))
        lags = range(2, max_lag + 1)
        tau = [np.sqrt(np.std(np.subtract(ts[lag:], ts[:-lag]))) for lag in lags]
        poly = np.polyfit(np.log(list(lags)), np.log(tau), 1)
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
        t_full = float(os.getenv("LIQ_SCALE_FULL", "0.8") or 0.8)
        t_scal = float(os.getenv("LIQ_SCALE_SCALED", "0.3") or 0.3)
        t_full = max(0.01, min(0.99, t_full))
        t_scal = max(0.01, min(t_full - 0.01, t_scal))

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

    def apply_alt_timeframe_veto(
        self,
        analysis: Dict[str, Any],
        candles_alt: List[Dict[str, float]],
    ) -> None:
        """5m alt TF: BUY değilse 1h sinyalini veto eder (yalnızca zenginleştirme)."""
        from super_otonom.config import ALT_TF

        if not ALT_TF.get("enabled") or not ALT_TF.get("veto"):
            analysis["alt_tf_filtered"] = False
            return
        if not candles_alt or len(candles_alt) < 22:
            analysis["alt_tf_filtered"] = False
            analysis["alt_tf_reason"] = "5m veri yetersiz"
            return
        alt = self.analyze(str(analysis.get("symbol", "ALT")), candles_alt)
        alt_sig = str(alt.get("signal", "HOLD") or "HOLD")
        analysis["alt_tf_signal"] = alt_sig
        if analysis.get("signal") == "BUY" and alt_sig != "BUY":
            analysis["signal"] = "HOLD"
            analysis["futures_side"] = "FLAT"
            analysis["alt_tf_filtered"] = True
            analysis["alt_tf_reason"] = f"5m veto: alt={alt_sig}"
            analysis["reason"] = analysis.get("alt_tf_reason", "")
        else:
            analysis["alt_tf_filtered"] = False
            analysis["alt_tf_reason"] = "5m uyumlu"

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
            closes_4h = [float(c["close"]) for c in candles_4h if c.get("close")]
            ema_4h_fast = _ema(closes_4h, 9)
            ema_4h_slow = _ema(closes_4h, 21)
            high_tf_trend = "UP" if ema_4h_fast > ema_4h_slow else "DOWN"
        else:
            high_tf_trend = "UNKNOWN"
            # 4H veri yoksa uyumluluk kontrolü atlanır
            result = self.analyze(symbol, candles_1h)
            result["high_tf_trend"] = high_tf_trend
            result["mtf_filtered"] = False
            result["mtf_reason"] = "4H veri yetersiz — kontrol atlandı"
            return result

        # 1H analizi (v5 rejim filtresi dahil)
        result = self.analyze(symbol, candles_1h)

        # 4H trend uyum kontrolü
        original_signal = result["signal"]
        mtf_filtered = False
        mtf_reason = "4H trend uyumlu"

        if original_signal == "BUY" and high_tf_trend != "UP":
            result["signal"] = "HOLD"
            result["futures_side"] = "FLAT"
            mtf_filtered = True
            mtf_reason = f"4H trend aykiri: 1H=BUY ama 4H={high_tf_trend}"
            result["reason"] = mtf_reason
            result["regime_reason"] = result.get("regime_reason", "") + f" | MTF: {mtf_reason}"

        elif original_signal == "SELL" and high_tf_trend != "DOWN":
            result["signal"] = "HOLD"
            result["futures_side"] = "FLAT"
            mtf_filtered = True
            mtf_reason = f"4H trend aykiri: 1H=SELL ama 4H={high_tf_trend}"
            result["reason"] = mtf_reason
            result["regime_reason"] = result.get("regime_reason", "") + f" | MTF: {mtf_reason}"

        result["high_tf_trend"] = high_tf_trend
        result["mtf_filtered"] = mtf_filtered
        result["mtf_reason"] = mtf_reason

        if mtf_filtered:
            log.info(
                "MTF_FILTRE: symbol=%s | 1H=%s → HOLD | %s",
                symbol,
                original_signal,
                mtf_reason,
            )
        else:
            log.debug(
                "MTF OK: symbol=%s | sinyal=%s | 4H=%s",
                symbol,
                result["signal"],
                high_tf_trend,
            )

        return result

    # ── v5 tek zaman dilimi analizi (geriye uyumlu) ───────────────────────────

    def _calc_indicators(self, closes: List[float], candles: List[Dict[str, float]]) -> dict:
        """Temel göstergeleri hesaplar."""
        rsi = _rsi(closes, 14)
        ema_fast = _ema(closes[-60:], 9)
        ema_slow = _ema(closes[-120:], 21)
        ema_diff = 0.0 if ema_slow == 0 else (ema_fast - ema_slow) / ema_slow
        _, _, _, bb_pct_b = _bollinger(closes, 20, 2.0)
        atr = _atr(candles, 14)
        last_close = closes[-1] if closes else 1.0
        vol = atr / (last_close + 1e-9)
        vol_ratio = _volume_ratio(candles, 5, 20)
        hurst_val = _calculate_hurst(closes[-100:])
        return {
            "rsi": rsi,
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "ema_diff": ema_diff,
            "bb_pct_b": bb_pct_b,
            "atr": atr,
            "vol": vol,
            "vol_ratio": vol_ratio,
            "hurst_val": hurst_val,
        }

    def _calc_market_state(self, hurst_val: float, ema_diff: float, vol: float, rsi: float) -> str:
        """Market state hesaplar."""
        if hurst_val > _HURST_TREND_FLOOR or abs(ema_diff) > 0.005 or vol > 0.025:
            return "TREND"
        if hurst_val < _HURST_REVERTING_CEIL:
            return "MEAN_REVERTING"
        if vol < 0.008 and 40.0 < rsi < 60.0 and abs(ema_diff) < 0.002:
            return "SIDEWAYS"
        return "NEUTRAL"

    def _calc_signal(self, regime: str, hurst_val: float, buy_ok: bool, sell_ok: bool) -> tuple:
        """Regime'e göre sinyal ve futures_side döner."""
        if regime == "NOISY":
            return "HOLD", "FLAT", f"NOISY piyasa (Hurst={hurst_val:.3f}, 0.45-0.55 band)"
        if regime == "MEAN_REVERTING":
            return (
                "HOLD",
                "FLAT",
                f"MEAN_REVERTING piyasa (Hurst={hurst_val:.3f} < {_HURST_REVERTING_CEIL})",
            )
        if buy_ok:
            sig, fs = "BUY", "LONG"
        elif sell_ok:
            sig, fs = "SELL", "SHORT"
        else:
            sig, fs = "HOLD", "FLAT"
        return sig, fs, f"TRENDING piyasa (Hurst={hurst_val:.3f} > {_HURST_TREND_FLOOR})"

    def analyze(self, symbol: str, candles: List[Dict[str, float]]) -> Dict[str, Any]:
        if not candles:
            return _empty(symbol)

        closes = [float(c["close"]) for c in candles if c.get("close") is not None]
        if len(closes) < _MIN_CLOSES:
            return _empty(symbol)

        ind = self._calc_indicators(closes, candles)
        rsi = ind["rsi"]
        ema_fast = ind["ema_fast"]
        ema_slow = ind["ema_slow"]
        ema_diff = ind["ema_diff"]
        bb_pct_b = ind["bb_pct_b"]
        atr = ind["atr"]
        vol = ind["vol"]
        vol_ratio = ind["vol_ratio"]
        hurst_val = ind["hurst_val"]

        regime = detect_market_regime(hurst_val)
        market_state = self._calc_market_state(hurst_val, ema_diff, vol, rsi)

        up = ema_fast > ema_slow
        down = ema_fast < ema_slow
        rising = _rising_last_two_closes(closes)
        falling = _falling_last_two_closes(closes)
        if _STRICT_VOL_BB:
            vol_ok_buy = vol_ok_sell = vol_ratio > _VOL_RATIO_CONFIRM
            bb_buy_ok = bb_pct_b < _BB_BUY_MAX
            bb_sell_ok = bb_pct_b > _BB_SELL_MIN
        else:
            vol_ok_buy = vol_ok_sell = bb_buy_ok = bb_sell_ok = True
        buy_ok = up and (_BUY_RSI_LO < rsi < _BUY_RSI_HI) and rising and vol_ok_buy and bb_buy_ok
        sell_ok = (
            down and (_SELL_RSI_LO < rsi < _SELL_RSI_HI) and falling and vol_ok_sell and bb_sell_ok
        )

        flash_crash = False
        if len(closes) >= 3:
            drop = (closes[-3] - closes[-1]) / (closes[-3] + 1e-9)
            flash_crash = drop > 0.03
        if flash_crash:
            buy_ok = False

        if market_state == "SIDEWAYS":
            buy_ok = sell_ok = False

        signal, futures_side, regime_reason = self._calc_signal(regime, hurst_val, buy_ok, sell_ok)

        return {
            "symbol": symbol,
            "signal": signal,
            "futures_side": futures_side,
            "ema_fast": float(ema_fast),
            "ema_slow": float(ema_slow),
            "rsi": float(rsi),
            "ema_diff": float(ema_diff),
            "volatility": float(vol),
            "vol_ratio": float(vol_ratio),
            "bb_pct_b": float(bb_pct_b),
            "atr": float(atr),
            "flash_crash": flash_crash,
            "market_state": market_state,
            "hurst": round(hurst_val, 4),
            "regime": regime,
            "regime_reason": regime_reason,
            "momentum": bool(buy_ok),
            "sentiment_score": 0.0,
            "high_tf_trend": None,
            "mtf_filtered": False,
            "mtf_reason": "",
            "thresholds": {
                "min_closes": _MIN_CLOSES,
                "spot_buy_rsi": (_BUY_RSI_LO, _BUY_RSI_HI),
                "spot_sell_rsi": (_SELL_RSI_LO, _SELL_RSI_HI),
                "hurst_trend": _HURST_TREND_FLOOR,
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
        "symbol": symbol,
        "signal": "HOLD",
        "futures_side": "FLAT",
        "ema_fast": 0.0,
        "ema_slow": 0.0,
        "rsi": 50.0,
        "ema_diff": 0.0,
        "volatility": 0.0,
        "vol_ratio": 1.0,
        "bb_pct_b": 0.5,
        "atr": 0.0,
        "flash_crash": False,
        "market_state": "NEUTRAL",
        "hurst": 0.5,
        "regime": "NOISY",
        "regime_reason": "Yetersiz veri",
        "momentum": False,
        "sentiment_score": 0.0,
        "high_tf_trend": None,
        "mtf_filtered": False,
        "mtf_reason": "",
    }
