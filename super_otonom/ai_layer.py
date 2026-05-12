from __future__ import annotations

"""
AILayer v6.1
─────────────────────────────────────────────────────────────────────────────
YENİLİKLER (v5 → v6.1):
  • Sürüm numarası güncellendi (v5 → v6.1)
  • Gerekçe (reason) loglaması iyileştirildi
  • NOISY/MEAN_REVERTING rejim farkındalığı: analiz.regime bilgisi değerlendirmeye alınır
"""

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from super_otonom.config import AI, RISK

log = logging.getLogger("super_otonom.ai")

# ModelServer lazy import — yoksa fallback
try:
    from super_otonom.core.market_models import ModelServer

    _MODEL_SERVER_AVAILABLE = True
except ImportError:
    ModelServer = None  # type: ignore
    _MODEL_SERVER_AVAILABLE = False


def _entry_conf_floor() -> float:
    """
    Merkezi confidence floor — bot_engine.py ile aynı kaynaktan okur.
    config.py RISK['entry_min_confidence'] kullanılır; env ile override edilebilir.
    """
    try:
        v = float(
            os.getenv("ENTRY_MIN_CONFIDENCE", str(RISK.get("entry_min_confidence", 0.55))) or 0.55
        )
    except ValueError:
        v = 0.55
    return max(0.45, min(0.95, v))


class AILayer:
    """
    Kritik hedef: AI yüzünden ana döngü asla donmasın.
    - Model dosyası varsa: ModelServer ayrı process
    - Model yoksa veya PyTorch kapalı: güvenli fallback (işlem bloke olmaz)

    v5 yenilik: validate_signal() artık üçlü döndürür:
        (signal: str, confidence: float, reason: str)
    """

    def __init__(self, model_path: str = "data/lstm_model.pt"):
        self.model_path = model_path
        self.seq_len = AI["lstm_seq_len"]
        model_exists = os.path.isfile(model_path)
        self.enabled = bool(AI["lstm_enabled"]) and model_exists and _MODEL_SERVER_AVAILABLE
        if AI["lstm_enabled"] and not model_exists:
            log.warning(
                "AILayer: lstm_enabled=True ama model bulunamadi (%s). "
                "Fallback moda gecildi — islemler bloke olmaz.",
                model_path,
            )
        self._buffer: Dict[str, List[List[float]]] = {}
        self._server: Optional[object] = None
        if self.enabled and ModelServer is not None:
            self._server = ModelServer(model_path=model_path)
            self._server.start()  # type: ignore

    def stop(self) -> None:
        if self._server:
            self._server.stop()  # type: ignore

    def _extract_features(self, candle: Dict, analysis: Dict) -> List[float]:
        c = float(candle.get("close") or 1.0)
        if abs(c) < 1e-9:
            c = 1.0
        rsi_norm = float(analysis.get("rsi", 50.0)) / 100.0
        ema_diff = float(analysis.get("ema_diff", 0.0))
        ema_diff_clipped = max(-0.1, min(0.1, ema_diff)) * 10.0
        vol_ratio = min(float(analysis.get("vol_ratio", 1.0)), 10.0) / 10.0
        return [
            (float(candle.get("open", c)) - c) / c,
            (float(candle.get("high", c)) - c) / c,
            (float(candle.get("low", c)) - c) / c,
            float(candle.get("close", c)) / (c + 1e-9) - 1.0,
            vol_ratio,
            rsi_norm,
            ema_diff_clipped,
            float(analysis.get("bb_pct_b", 0.5)),
        ]

    def update_buffer(self, symbol: str, candle: Dict, analysis: Dict) -> None:
        self._buffer.setdefault(symbol, []).append(self._extract_features(candle, analysis))
        if len(self._buffer[symbol]) > self.seq_len * 2:
            self._buffer[symbol] = self._buffer[symbol][-self.seq_len :]

    # ── v5 YENİLİK: Karar gerekçesi ──────────────────────────────────────────

    def get_decision_reason(self, ai_sig: str, conf: float, analysis: Dict) -> str:
        """
        AI kararının açıklamasını üretir.
        main_loop içinde loglayarak botun 'düşünce sürecini' izleyebilirsin.

        Dönüş örnekleri:
          "AI_CAUTION_HIGH_VOLATILITY"
          "STRONG_AI_CONVICTION"
          "REGIME_BLOCKED_NOISY"
          "REGIME_BLOCKED_MEAN_REVERTING"
          "TECHNICAL_INDICATOR_DOMINANCE"
          "AI_MODEL_FALLBACK"
        """
        regime = str(analysis.get("regime", "NOISY")).upper()

        # Rejim kaynaklı engeller — en öncelikli
        if regime == "NOISY":
            return "REGIME_BLOCKED_NOISY"
        if regime == "MEAN_REVERTING":
            return "REGIME_BLOCKED_MEAN_REVERTING"

        # AI kaution: yüksek oynaklık + HOLD
        hurst = float(analysis.get("hurst", 0.5))
        if ai_sig == "HOLD" and hurst > 0.50:
            return "AI_CAUTION_HIGH_VOLATILITY"

        # Güçlü AI inancı
        if conf > 0.85:
            return "STRONG_AI_CONVICTION"

        # Model yok / fallback
        if not self.enabled or not self._server:
            return "AI_MODEL_FALLBACK"

        # Varsayılan: teknik indikatör ağırlıklı karar
        return "TECHNICAL_INDICATOR_DOMINANCE"

    def explain(
        self,
        symbol: str,
        base_signal: str,
        analysis: Dict[str, Any],
        final_signal: str,
        confidence: float,
        reason: str,
    ) -> str:
        """
        Tek satırlık insan-okur AI özeti (log / decision_context).
        """
        regime = str(analysis.get("regime", "NOISY")).upper()
        hurst = float(analysis.get("hurst", 0.5) or 0.5)
        vol = float(analysis.get("volatility", 0.0) or 0.0)
        model_on = bool(self.enabled and self._server)
        return (
            f"symbol={symbol} path={base_signal!r}→{final_signal!r} "
            f"conf={float(confidence):.3f} reason={reason!r} regime={regime} "
            f"hurst={hurst:.3f} vol={vol:.4f} lstm={'on' if model_on else 'off'}"
        )

    # ── Sinyal doğrulama (v5: üçlü döndürür) ─────────────────────────────────

    def validate_signal(
        self, symbol: str, base_signal: str, analysis: Dict
    ) -> Tuple[str, float, str]:
        """
        (signal, confidence, reason) üçlüsü döndürür.

        v5 not: reason alanı loglama + Prometheus label için kullanılabilir.
        Geriye dönük uyumluluk: çağıran taraf sadece ilk iki değeri kullanabilir.
        """
        fl = _entry_conf_floor()

        # Rejim engeli — AI'dan önce kontrol
        regime = str(analysis.get("regime", "NOISY")).upper()
        if regime in ("NOISY", "MEAN_REVERTING"):
            reason = self.get_decision_reason("HOLD", fl, analysis)
            return "HOLD", 0.30, reason

        # Model disabled veya server yok: analizör sinyaline geç, floor confidence
        if not self.enabled or not self._server:
            reason = self.get_decision_reason(base_signal, fl, analysis)
            return base_signal, fl, reason

        buf = self._buffer.get(symbol, [])
        if len(buf) < self.seq_len:
            reason = "AI_BUFFER_INSUFFICIENT"
            return base_signal, fl, reason

        r = self._server.predict(symbol, buf)  # type: ignore
        src = str(r.get("source", "") or "")

        # Model fallback durumları
        if src in ("no_model", "fallback", "timeout") or (
            src.startswith("error") and "model" in src.lower()
        ):
            conf = float(r.get("confidence", fl))
            clipped = max(fl, min(0.95, conf))
            reason = self.get_decision_reason(base_signal, clipped, analysis)
            return base_signal, clipped, reason

        ai_sig = r.get("signal", "HOLD")
        conf = float(r.get("confidence", 0.5))

        # AI ve analizör aynı yön: confidence boost
        if ai_sig == base_signal:
            boosted = min(0.95, conf * 1.1)
            final_conf = max(round(boosted, 3), fl)
            reason = self.get_decision_reason(ai_sig, final_conf, analysis)
            return base_signal, final_conf, reason

        # AI HOLD → analizör BUY/SELL sinyalini veto et
        if ai_sig == "HOLD" and base_signal in ("BUY", "SELL"):
            reason = self.get_decision_reason("HOLD", 0.30, analysis)
            return "HOLD", 0.30, reason

        # AI zıt yön → veto
        if base_signal in ("BUY", "SELL") and ai_sig != base_signal:
            reason = "AI_DIRECTION_VETO"
            return "HOLD", 0.30, reason

        final_conf = max(fl, min(0.95, conf))
        reason = self.get_decision_reason(base_signal, final_conf, analysis)
        return base_signal, final_conf, reason
