"""
DecisionContext — karar izi (audit) ve ileride tek noktadan politika.

PROMPT-A11: analyzer yalnızca ``main_loop`` öncesi; ``tick`` / ``_tick_impl`` tek tur;
donmuş çekirdek + reentrancy ``self_feedback_guard``.

Politika özeti (madde listesi) ``docs/GOVERNANCE_CHECKLIST_TR.md`` §0.1 ile hizalı tutulur; büyük sıra
değişikliğinde A1 güncelleme kuralı — aynı PR.

**Döngü dışı** — ``main_loop.prep_symbol_for_tick``::

    OHLCV → analyzer → (OB / ob_safe_size / likidite) → opsiyonel ``record_analyzer_snapshot``
    → ``await engine.tick(symbol, analysis, candles)``.

**``BotEngine._tick_impl`` sırası (v8 gerçek çağrı; ``bot_engine.py``)**::

    1) ``analysis`` zenginleştirme (avg_volume, candle_ts) + ``attach_tick_frozen_mark``
    2) ``DecisionContext.start`` + ``compute_trading_state``
    3) unrealized PnL, peak equity / ``risk.update_peak``
    4) funding / ``RiskOntology.update``
    5) ``correlation_mgr.update_returns``
    6) ``run_system_gate_phase`` (Faz 50) → ``kill`` / ``risk`` ise erken çıkış
    7) ``process_signal`` → ``run_signal_fusion_phase`` → ``signal_pipeline.process_signal_phase``
       (AI buffer, ML, ``validate_signal``, omega blend, explain → ``out`` / ``dctx``)
    8) ``apply_filters`` → ``apply_filters_phase`` (sentiment veto; ``run_unified_alpha_phase``)
    9) ``calculate_position`` (BUY için korelasyon × drawdown ölçeği)
    10) diğer semboller için trailing stop kontrolü
    11) ``attach_override_phases_to_analysis`` (köprü fazlar)
    12) ``execute_trade`` → ``execution_pipeline.execute_trade_phase``
        (açık pozisyon: ``_handle_exit``; yok: Faz 71→80 + 47 zinciri sonra ``_handle_entry``)
    13) ``signal_lineage``, ``metrics``

Grafik ve tablo: ``docs/HOT_TICK_PATH.md``.

**Giriş emri sırasında** (``_handle_entry`` içi, özet): ``ob_safe_size`` / ``merge_entry_notional``,
``apply_liquidity_context``, ``signal_quality`` / OMEGA cezaları, ``pre_trade_gate`` slotları.
``omega_*``, ``external_ai_*``: çoğunlukla ``signal_pipeline`` / üst akış logları.

``entry_blocked``: giriş yapılamadıysa kısa kod; ``low_quality`` = LOW_QUALITY_REJECT.
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
    # v8: durum makinesi + AI açıklanabilirlik
    trading_state: str = ""
    ai_explain: str = ""
    # Faz zinciri (71+ gibi) — pipeline içi observability
    phase_chain: Dict[str, Any] = field(default_factory=dict)
    # PROMPT-A7 — tick son kararı özeti (``signal_lineage.build_signal_lineage``)
    signal_lineage: Optional[Dict[str, Any]] = None
    # VR-18 — VaR-aware position sizing observability
    var_cap_original_size: Optional[float] = None
    var_cap_final_size: Optional[float] = None
    var_cap_binding: bool = False
    var_cap_marginal_var: Optional[float] = None
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
            "trading_state": self.trading_state,
            "ai_explain": self.ai_explain,
            "phase_chain": dict(self.phase_chain),
            "signal_lineage": self.signal_lineage,
            "var_cap_original_size": self.var_cap_original_size,
            "var_cap_final_size": self.var_cap_final_size,
            "var_cap_binding": self.var_cap_binding,
            "var_cap_marginal_var": self.var_cap_marginal_var,
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
