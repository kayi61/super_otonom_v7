"""
DecisionContext — karar izi (audit) ve ileride tek noktadan politika.

Mevcut BotEngine.tick sırası (özet)::

    [main_loop: OHLCV → analyzer → (order book ob_safe_size) → engine.tick]

    engine.tick (symbol, analysis, candles)::

        0) correlation_mgr.update_returns(symbol, price)
        1) risk.check_risk(equity, exposure, current_vol)  →  hayır: çık
        2) ai.update_buffer; base = analysis["signal"]
           TREND_FOLLOW? → (final, conf, reason) aksi halde
           ai.validate_signal(symbol, base, analysis)      →  final, conf, reason
        3) final BUY/SELL ise sentiment_layer.validate_with_sentiment
           → HOLD olabilir: erken dön (açık poz. varsa _handle_exit HOLD yolu)
        4) final BUY ve açık poz. yok → corr_multiplier = adjust_risk_exposure
        5) Açık poz. var? _handle_exit : _handle_entry
        6) metrics (status, record_analysis)

    ob_safe_size: main_loop (order book) → pre_trade_gate.merge_entry_notional
    ile sizer.calculate tek tavanda birleşir (min).
    apply_liquidity_context: liquidity_ratio, entry_scale (full|scaled|minimal|blocked|unknown)
    signal_quality (ham), adj_signal_quality (OMEGA rejim çarpanı sonrası), penalty_reasons,
    quality_main_penalty, effective_quality_min (env + RiskManager OMEGA sıkılaşması).
    omega_*: rejim, çarpan, notional faktörü, [OMEGA-AI] birleşik log.
    external_ai_*: dış ML servis (HTTP) gecikme + skor; [EXTERNAL-AI] log.

    entry_blocked: giriş yapılamadıysa kısa kod (log/metrik); low_quality = LOW_QUALITY_REJECT
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class DecisionStage(str, Enum):
    """Hangi aşamada kesildi / üretildi (log/metrik etiketleri)."""

    RISK = "risk"
    AI = "ai"
    SENTIMENT = "sentiment"
    CORRELATION = "correlation"
    EXIT = "exit"
    ENTRY = "entry"
    NONE = "none"


@dataclass
class DecisionContext:
    """
    Bir tick içinde toplanan karar durumu; JSON’a dökülebilir (observability).
    """

    symbol: str
    tick_id: int
    # Analyzer / MTF
    analysis_signal: str = "HOLD"
    regime: str = "NOISY"
    # Aşamalar
    risk_passed: bool = True
    after_ai_signal: str = "HOLD"
    after_sentiment_signal: str = "HOLD"
    sentiment_status: str = "UNKNOWN"
    corr_multiplier: float = 1.0
    # Son
    final_signal: str = "HOLD"
    decision_reason: str = ""
    ai_confidence: Optional[float] = None
    # Giriş boyutu (BUY) — tek kaynak birleşimi
    notional_technical: Optional[float] = None
    ob_safe_size_input: Optional[float] = None
    notional_pre_corr: Optional[float] = None
    notional_after_corr: Optional[float] = None
    sizing_source: str = ""
    entry_blocked: Optional[str] = None
    # EMERGENCY_STOP:... — global kill, hard limit veya risk.trigger_emergency
    emergency_code: Optional[str] = None
    # Likidite zenginleştirme (main_loop: apply_liquidity_context)
    liquidity_ratio: Optional[float] = None
    entry_scale: str = "unknown"  # full | scaled | minimal | blocked | unknown
    # Signal Quality Scorer (0-100) — elite BUY gating
    signal_quality: Optional[int] = None
    adj_signal_quality: Optional[int] = None
    penalty_reasons: List[str] = field(default_factory=list)
    quality_main_penalty: str = ""
    effective_quality_min: Optional[int] = None
    # OMEGA orkestrasyonu
    omega_regime: str = ""
    omega_quality_mult: float = 1.0
    omega_size_factor: float = 1.0
    omega_ai_log: str = ""
    # Dış ML servis (ml_client) — [EXTERNAL-AI] neural link
    external_ai_latency_ms: Optional[float] = None
    external_ai_confidence: Optional[float] = None
    external_ai_log: str = ""
    # İzlenebilir adımlar: (aşama, kısa not)
    trace: List[Tuple[str, str]] = field(default_factory=list)

    def add_trace(self, stage: str, note: str) -> None:
        self.trace.append((stage, note))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "tick_id": self.tick_id,
            "analysis_signal": self.analysis_signal,
            "regime": self.regime,
            "risk_passed": self.risk_passed,
            "after_ai_signal": self.after_ai_signal,
            "after_sentiment_signal": self.after_sentiment_signal,
            "sentiment_status": self.sentiment_status,
            "corr_multiplier": self.corr_multiplier,
            "final_signal": self.final_signal,
            "decision_reason": self.decision_reason,
            "ai_confidence": self.ai_confidence,
            "notional_technical": self.notional_technical,
            "ob_safe_size_input": self.ob_safe_size_input,
            "notional_pre_corr": self.notional_pre_corr,
            "notional_after_corr": self.notional_after_corr,
            "sizing_source": self.sizing_source,
            "entry_blocked": self.entry_blocked,
            "emergency_code": self.emergency_code,
            "liquidity_ratio": self.liquidity_ratio,
            "entry_scale": self.entry_scale,
            "signal_quality": self.signal_quality,
            "adj_signal_quality": self.adj_signal_quality,
            "penalty_reasons": list(self.penalty_reasons),
            "quality_main_penalty": self.quality_main_penalty,
            "effective_quality_min": self.effective_quality_min,
            "omega_regime": self.omega_regime,
            "omega_quality_mult": self.omega_quality_mult,
            "omega_size_factor": self.omega_size_factor,
            "omega_ai_log": self.omega_ai_log,
            "external_ai_latency_ms": self.external_ai_latency_ms,
            "external_ai_confidence": self.external_ai_confidence,
            "external_ai_log": self.external_ai_log,
            "trace": [{"stage": s, "note": n} for s, n in self.trace],
        }

    @staticmethod
    def start(symbol: str, tick_id: int, analysis: Dict[str, Any]) -> "DecisionContext":
        a = analysis or {}
        lr = a.get("liquidity_ratio")
        try:
            lr_f = float(lr) if lr is not None else None
        except (TypeError, ValueError):
            lr_f = None
        return DecisionContext(
            symbol=symbol,
            tick_id=tick_id,
            analysis_signal=str(a.get("signal", "HOLD")),
            regime=str(a.get("regime", "NOISY")).upper(),
            liquidity_ratio=lr_f,
            entry_scale=str(a.get("entry_scale", "unknown") or "unknown"),
        )
