"""PROMPT-10.1 — Insider Intelligence Fusion Controller (signals/) — son karar katmanı.

Tüm insider intelligence kaynaklarını tek `insider_conviction` skoruna indirger;
`signal_fusion_engine` (Faz 36) ve `mm_whale_consensus_controller` (Faz 75) ile
entegre. BotEngine'e `analysis["insider_conviction"]` (+ phase76) olarak iletilir.

Girdi (hepsi opsiyonel, dict/dataclass — decoupled; sinyallerin SONUÇLARI):
``whale_signal``, ``onchain_signal``, ``defi_signal``, ``derivatives_signal``,
``social_signal``, ``token_signal``, ``macro_signal``, ``etf_signal``,
``exploit_alert``, ``arb_signal``.

Fusion mantığı:
1. Her sinyale yön (-1..1) + conviction (0..1) + ağırlık.
2. Çelişki tespiti (whale bullish ama funding aşırı → WAIT).
3. Confluence: 3+ bağımsız kaynak aynı yöne → conviction artır.
4. Override: exploit_alert → HALT (her şeyi ezer); macro RISK_OFF + whale satış →
   STRONG_SELL; whale birikim + stablecoin mint + ETF inflow → STRONG_BUY.
5. Position sizing önerisi: conviction × kelly_fraction × risk_budget.

Saf (ağsız); testler deterministik.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger("super_otonom.insider_fusion")

# Karar etiketleri
STRONG_BUY = "STRONG_BUY"
BUY = "BUY"
WAIT = "WAIT"
NEUTRAL = "NEUTRAL"
SELL = "SELL"
STRONG_SELL = "STRONG_SELL"
HALT = "HALT"

CONFLUENCE_MIN = 3              # 3+ bağımsız kaynak aynı yöne → confluence
_DIR_EPS = 0.15                 # anlamlı yön eşiği

# Kategori ağırlıkları (varsayılan)
DEFAULT_WEIGHTS: Dict[str, float] = {
    "whale_signal": 1.0,
    "onchain_signal": 0.7,
    "defi_signal": 0.6,
    "derivatives_signal": 0.8,
    "social_signal": 0.5,
    "token_signal": 0.6,
    "macro_signal": 0.9,
    "etf_signal": 0.7,
    "arb_signal": 0.5,
}
_CATEGORIES = tuple(DEFAULT_WEIGHTS.keys())


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else float(x)


def _clamp01(x: float) -> float:
    return _clamp(x, 0.0, 1.0)


def _coerce_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _as_dict(sig: Any) -> Dict[str, Any]:
    if isinstance(sig, dict):
        return sig
    if hasattr(sig, "to_dict") and callable(sig.to_dict):
        try:
            d = sig.to_dict()
            if isinstance(d, dict):
                return d
        except Exception:
            pass
    if hasattr(sig, "__dict__"):
        return {k: v for k, v in vars(sig).items() if not k.startswith("_")}
    return {}


def _get(d: Dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _truthy(v: Any) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "active", "on")
    if isinstance(v, dict):
        return bool(_get(v, "active", "alert", "exploit_alert", "detected")) or bool(v)
    return bool(v)


def _signal_direction(d: Dict[str, Any]) -> Optional[float]:
    """Sinyal sözlüğünden yön (-1..1)."""
    for k in ("alpha_bias", "macro_alpha_bias", "defi_alpha_bias", "kol_alpha_bias",
              "direction", "bias", "net_direction", "weighted_sentiment", "composite_sentiment"):
        v = _coerce_float(d.get(k))
        if v is not None:
            return _clamp(v, -1.0, 1.0)
    # Aksiyon / sinyal etiketinden
    act = str(_get(d, "action", "signal", "decision", "trade_signal") or "").upper()
    if act in ("STRONG_BUY", "BUY", "LONG", "ACCUMULATE", "OPEN_SMALL", "SCALE_UP"):
        return 1.0 if "STRONG" in act else 0.6
    if act in ("STRONG_SELL", "SELL", "SHORT", "CLOSE", "REDUCE"):
        return -1.0 if "STRONG" in act else -0.6
    # Makro ortam etiketi
    env = str(_get(d, "environment", "regime_hint") or "").upper()
    if env in ("BULLISH", "TRENDING"):
        return 0.7
    if env == "RISK_OFF" or env == "CRASH_RISK":
        return -1.0
    if env in ("BEARISH", "RANGING"):
        return -0.5
    # ETF / akış net yönü
    nf = _coerce_float(_get(d, "net_flow_usd", "etf_net_flow_usd", "net_inflow_usd"))
    if nf is not None:
        return _clamp(nf / 1e8, -1.0, 1.0)
    return None


def _signal_conviction(d: Dict[str, Any], direction: float) -> float:
    """Sinyal conviction'ı (0..1)."""
    c = _coerce_float(_get(d, "conviction"))
    if c is not None:
        return _clamp01(c / 100.0 if c > 1.0 else c)
    conf = _coerce_float(_get(d, "confidence", "data_health"))
    if conf is not None:
        return _clamp01(0.4 + 0.6 * conf) * _clamp01(0.3 + abs(direction))
    return _clamp01(abs(direction))


@dataclass(frozen=True)
class SourceContribution:
    category: str
    direction: float        # -1..1
    conviction: float       # 0..1
    weight: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "direction": round(self.direction, 4),
            "conviction": round(self.conviction, 4),
            "weight": self.weight,
        }


@dataclass(frozen=True)
class InsiderFusionResult:
    insider_conviction: int             # 0-100 (final skor)
    direction: float                    # -1..1 (net yön)
    decision: str                       # STRONG_BUY..HALT
    confluence_count: int               # aynı yöndeki bağımsız kaynak sayısı
    conflict: bool
    override_reason: str
    position_size_suggestion: float     # 0..1 (conviction × kelly × risk_budget)
    trade_permission: str               # ALLOW | BLOCK | HALT
    sources: List[SourceContribution] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "insider_conviction": self.insider_conviction,
            "direction": round(self.direction, 4),
            "decision": self.decision,
            "confluence_count": self.confluence_count,
            "conflict": self.conflict,
            "override_reason": self.override_reason,
            "position_size_suggestion": round(self.position_size_suggestion, 4),
            "trade_permission": self.trade_permission,
            "sources": [s.to_dict() for s in self.sources],
            "reasons": list(self.reasons),
        }


def _funding_extreme(deriv: Dict[str, Any]) -> bool:
    if _truthy(_get(deriv, "funding_extreme", "funding_spike")):
        return True
    f = _coerce_float(_get(deriv, "funding_rate", "funding_rate_8h", "funding"))
    return f is not None and abs(f) >= 0.001  # ~0.1%/8h → aşırı


def analyze_insider_fusion(
    signals: Dict[str, Any],
    *,
    kelly_fraction: float = 0.5,
    risk_budget: float = 1.0,
    weights: Optional[Dict[str, float]] = None,
) -> Optional[InsiderFusionResult]:
    """Tüm insider sinyallerini tek conviction/karar/pozisyon önerisine indirger."""
    if not isinstance(signals, dict) or not signals:
        return None
    w_table = {**DEFAULT_WEIGHTS, **(weights or {})}

    contribs: List[SourceContribution] = []
    for cat in _CATEGORIES:
        raw = signals.get(cat)
        if raw is None:
            continue
        d = _as_dict(raw)
        if not d:
            continue
        direction = _signal_direction(d)
        if direction is None:
            continue
        conv = _signal_conviction(d, direction)
        contribs.append(SourceContribution(cat, direction, conv, w_table.get(cat, 0.5)))

    if not contribs:
        return None

    reasons: List[str] = []

    # 1) Ağırlıklı net yön + conviction
    num = sum(c.weight * c.conviction * c.direction for c in contribs)
    den = sum(c.weight * c.conviction for c in contribs)
    net_dir = _clamp(num / den, -1.0, 1.0) if den > 1e-9 else 0.0

    # 2/3) Confluence + çelişki
    aligned = [c for c in contribs if c.direction * net_dir > 0 and abs(c.direction) > _DIR_EPS]
    opposed = [c for c in contribs if c.direction * net_dir < 0 and abs(c.direction) > _DIR_EPS]
    confluence = len(aligned)
    conflict = False

    base_conv = _clamp01(abs(net_dir) * (sum(c.conviction for c in contribs) / len(contribs)))
    conviction01 = base_conv
    if confluence >= CONFLUENCE_MIN:
        conviction01 = _clamp01(conviction01 + 0.08 * (confluence - CONFLUENCE_MIN + 1))
        reasons.append(f"Confluence: {confluence} bağımsız kaynak aynı yönde → conviction↑")

    # whale bullish ama funding aşırı → çelişki / WAIT
    whale = _as_dict(signals.get("whale_signal"))
    deriv = _as_dict(signals.get("derivatives_signal"))
    whale_dir = _signal_direction(whale) if whale else None
    if whale_dir is not None and whale_dir > 0.3 and deriv and _funding_extreme(deriv):
        conflict = True
        conviction01 = _clamp01(conviction01 * 0.5)
        net_dir = net_dir * 0.4  # çelişki → net yön söndürülür (WAIT eğilimi)
        reasons.append("Whale bullish ama funding aşırı → çelişki (WAIT)")
    elif len(opposed) >= 2 and len(aligned) <= len(opposed):
        conflict = True
        conviction01 = _clamp01(conviction01 * 0.6)
        reasons.append("Kaynaklar arası belirgin çelişki → conviction↓")

    # 4) Override kuralları
    override_reason = ""
    decision = NEUTRAL
    perm = "ALLOW"

    macro = _as_dict(signals.get("macro_signal"))
    etf = _as_dict(signals.get("etf_signal"))
    macro_risk_off = (
        str(_get(macro, "environment") or "").upper() == "RISK_OFF"
        or _truthy(_get(macro, "risk_off"))
    )
    stablecoin_mint = _truthy(_get(macro, "stablecoin_mint")) or _truthy(signals.get("stablecoin_signal"))
    etf_inflow = (_signal_direction(etf) or 0.0) > 0.2 if etf else False
    whale_accum = whale_dir is not None and whale_dir > 0.3
    whale_sell = whale_dir is not None and whale_dir < -0.3

    if _truthy(signals.get("exploit_alert")):
        decision, perm, override_reason = HALT, "HALT", "exploit_alert"
        conviction01 = 1.0
        conflict = False
        reasons.append("exploit_alert AKTİF → HER ŞEYİ override, HALT")
    elif macro_risk_off and whale_sell:
        decision, override_reason = STRONG_SELL, "macro_risk_off + whale_sell"
        conviction01 = _clamp01(max(conviction01, 0.8))
        net_dir = min(net_dir, -0.6)
        reasons.append("Macro RISK_OFF + whale satış → STRONG SELL")
    elif whale_accum and stablecoin_mint and etf_inflow:
        decision, override_reason = STRONG_BUY, "whale_accum + stablecoin_mint + etf_inflow"
        conviction01 = _clamp01(max(conviction01, 0.85))
        net_dir = max(net_dir, 0.6)
        reasons.append("Whale birikim + stablecoin mint + ETF inflow → STRONG BUY")

    # 5) Karar (override yoksa eşiklerden)
    if override_reason == "":
        if conflict and abs(net_dir) < 0.5:
            decision = WAIT
        elif net_dir >= 0.55 and conviction01 >= 0.6:
            decision = STRONG_BUY
        elif net_dir >= 0.2:
            decision = BUY
        elif net_dir <= -0.55 and conviction01 >= 0.6:
            decision = STRONG_SELL
        elif net_dir <= -0.2:
            decision = SELL
        else:
            decision = NEUTRAL

    conviction100 = int(round(conviction01 * 100))
    pos_size = _clamp01(conviction01 * _clamp01(kelly_fraction) * _clamp(risk_budget, 0.0, 2.0))
    if decision in (HALT, WAIT, NEUTRAL):
        pos_size = 0.0

    return InsiderFusionResult(
        insider_conviction=conviction100,
        direction=float(net_dir),
        decision=decision,
        confluence_count=confluence,
        conflict=bool(conflict),
        override_reason=override_reason,
        position_size_suggestion=float(pos_size),
        trade_permission=perm,
        sources=contribs,
        reasons=reasons,
    )


def _collect_signals_from_analysis(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """analysis içinden insider sinyal anahtarlarını toplar."""
    out: Dict[str, Any] = {}
    for cat in (*_CATEGORIES, "exploit_alert", "stablecoin_signal"):
        if cat in analysis and analysis[cat] is not None:
            out[cat] = analysis[cat]
    return out


def run_insider_fusion_phase(
    analysis: Dict[str, Any],
    signals: Optional[Dict[str, Any]] = None,
    *,
    kelly_fraction: float = 0.5,
    risk_budget: float = 1.0,
    attach: bool = True,
) -> Optional[Dict[str, Any]]:
    """BotEngine girişi: insider fusion → ``analysis['insider_conviction']`` + phase76.

    ``signals`` verilmezse ``analysis`` içindeki insider anahtarlarından toplanır.
    İlgili sinyal yoksa None (geriye uyumlu: analysis değişmez).
    """
    src = signals if signals is not None else _collect_signals_from_analysis(analysis)
    res = analyze_insider_fusion(src, kelly_fraction=kelly_fraction, risk_budget=risk_budget)
    if res is None:
        return None

    payload = res.to_dict()
    if attach and isinstance(analysis, dict):
        analysis["insider_conviction"] = res.insider_conviction
        analysis["insider_direction"] = res.direction
        analysis["insider_fusion"] = payload
        try:
            from super_otonom.standard_phase_output import attach_phase_alias

            attach_phase_alias(analysis, "76", {**payload, "phase": "76", "source": "insider_fusion_controller"})
        except Exception:  # phase alias yoksa bile insider_conviction yazıldı
            log.debug("attach_phase_alias yok", exc_info=True)
    return payload


__all__ = [
    "BUY",
    "CONFLUENCE_MIN",
    "DEFAULT_WEIGHTS",
    "HALT",
    "NEUTRAL",
    "SELL",
    "STRONG_BUY",
    "STRONG_SELL",
    "WAIT",
    "InsiderFusionResult",
    "SourceContribution",
    "analyze_insider_fusion",
    "run_insider_fusion_phase",
]
