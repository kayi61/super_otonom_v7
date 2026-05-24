"""v8 — Pozisyon yönetimi: çıkış veya giriş (BotEngine._handle_*).

Cross-venue / emir yönlendirme ayrımı:
- Seçenek 1 — Faz 74 → Faz 80 girdisi: `decide_autonomously(..., phase74=...)`; çıktıda `route_preference`, `leader_venue`.
- Seçenek 2 — Ayrı execution katmanı: `out["execution_layer"]` (Faz 80 + Faz 47 birleşik yük).
- Seçenek 3 — Faz 47 smart_order_router: `phase_chain["faz47"]`, `out["faz47"]`.
"""

from __future__ import annotations

from typing import Any, Dict, List

from super_otonom.autonomous_decision_core import decide_autonomously
from super_otonom.confidence_calibration import calibrate_confidence_mvp
from super_otonom.cross_venue_leadlag_intelligence import infer_cross_venue_leadlag
from super_otonom.dealer_intent_inference_engine import infer_dealer_intent
from super_otonom.decision_context import DecisionStage
from super_otonom.liquidity_games_detector import detect_liquidity_games
from super_otonom.meta_regime_orchestrator import attach_meta_regime
from super_otonom.mm_whale_consensus_controller import compute_mm_whale_consensus
from super_otonom.multi_timeframe_consensus_engine import infer_mtf_consensus
from super_otonom.pipelines.override_phase_bridge import fill_governance_phases_if_missing
from super_otonom.regime_adaptive_execution_engine import infer_regime_adaptive_execution
from super_otonom.signals.alpha_decay_realtime_monitor import monitor_alpha_decay
from super_otonom.smart_order_router import compute_smart_order_route
from super_otonom.smart_stop_engine import compute_smart_stop
from super_otonom.whale_intent_microstructure_engine import infer_whale_intent


def _phase_dict_from_analysis(analysis: Dict[str, Any], *keys: str) -> Dict[str, Any]:
    for k in keys:
        v = analysis.get(k)
        if isinstance(v, dict):
            return dict(v)
    return {}


def _phase_override_from_analysis(analysis: Dict[str, Any], *keys: str) -> Any:
    """analysis['phase50'] / ['faz50'] veya analysis['override_phases'] içinden ilk bulunanı döndür."""
    for k in keys:
        v = analysis.get(k)
        if v is not None:
            return v
    nested = analysis.get("override_phases") or analysis.get("phase_overrides")
    if isinstance(nested, dict):
        for k in keys:
            v = nested.get(k)
            if v is not None:
                return v
    return None


async def execute_trade_phase(
    engine: Any,
    symbol: str,
    price: float,
    analysis: Dict[str, Any],
    out: Dict[str, Any],
    corr_multiplier: float,
    dctx: Any,
    candles: List[Dict[str, Any]],
) -> None:
    """Açık pozisyonda çıkış, değilse giriş."""
    final = out["final_signal"]
    conf = float(out.get("ai_confidence") or 0.0)

    if symbol in engine.open_positions:
        dctx.add_trace(DecisionStage.EXIT.value, "open_position")
        await engine._handle_exit(symbol, price, final, out, analysis)
    else:
        # ── KARAR AKIŞI (giriş, açık pozisyon yok) ─────────────────────────────
        # 1. fill_governance_phases_if_missing → analysis içi faz 66–70 sözlükleri
        # 2. infer_dealer_intent (71) … infer_mtf_consensus (79) → analysis + OB
        # 3. decide_autonomously(71–79, …) → p80 (final_action, trade_permission, …)
        # 4. compute_smart_order_route (47) + phase_chain güncellemesi
        # 5. BotEngine._handle_entry / _handle_exit — upstream out["final_signal"] (AI+füzyon)
        #    execution katmanı ağırlıklı olarak p80 ve risk gate ile boyut/rotayı şekillendirir.
        _sig_upstream = str(out.get("final_signal", ""))
        _dr_upstream = out.get("decision_reason")

        # Faz 66–70 + 68: BotEngine köprüsü yoksa eksik phase sözlüklerini doldurur
        fill_governance_phases_if_missing(analysis, symbol)

        # ── Faz 71→72→73→74→75→80 zinciri ───────────────────────────────────
        # Not: order_book ana döngüde fetch ediliyor; burada varsa analysis["order_book"] üzerinden alınır.
        order_book = analysis.get("order_book")
        if not isinstance(order_book, dict):
            order_book = None

        p71 = infer_dealer_intent(symbol=symbol, analysis=analysis, order_book=order_book)
        p72 = infer_whale_intent(symbol=symbol, analysis=analysis, order_book=order_book)
        p73 = detect_liquidity_games(symbol=symbol, analysis=analysis, order_book=order_book)
        p74 = infer_cross_venue_leadlag(symbol=symbol, analysis=analysis)
        # PROMPT-A11 — konsensus tek tur (çıktı aynı tick’te tekrar girdi olarak kullanılmaz)
        p75 = compute_mm_whale_consensus(
            symbol=symbol, phase71=p71, phase72=p72, phase73=p73, phase74=p74
        )

        p76 = infer_regime_adaptive_execution(
            symbol=symbol, analysis=analysis, order_book=order_book
        )
        p77 = compute_smart_stop(
            symbol=symbol,
            side="LONG",
            last_price=float(price),
            analysis=analysis,
            hunt_risk_score=int(getattr(p73, "manipulation_risk_score", 0) or 0),
        )
        p78 = monitor_alpha_decay(symbol=symbol, analysis=analysis)
        p79 = infer_mtf_consensus(symbol=symbol, analysis=analysis)

        p80 = decide_autonomously(
            symbol=symbol,
            phase71=p71,
            phase72=p72,
            phase73=p73,
            phase74=p74,
            phase75=p75,
            phase76=p76,
            phase77=p77,
            phase78=p78,
            phase79=p79,
            phase39=_phase_override_from_analysis(analysis, "phase39", "faz39"),
            phase50=_phase_override_from_analysis(analysis, "phase50", "faz50"),
            phase64=_phase_override_from_analysis(analysis, "phase64", "faz64"),
            phase66=_phase_override_from_analysis(analysis, "phase66", "faz66"),
            phase67=_phase_override_from_analysis(analysis, "phase67", "faz67"),
            phase68=_phase_override_from_analysis(analysis, "phase68", "faz68"),
            phase69=_phase_override_from_analysis(analysis, "phase69", "faz69"),
            phase70=_phase_override_from_analysis(analysis, "phase70", "faz70"),
        )

        p47 = compute_smart_order_route(
            symbol=symbol,
            analysis=analysis,
            phase74=p74,
            phase80=p80.to_dict(),
            phase76=p76,
        )

        # DecisionContext’e yazdır (observability)
        dctx.phase_chain.update(
            {
                "faz66": _phase_dict_from_analysis(analysis, "phase66", "faz66"),
                "faz67": _phase_dict_from_analysis(analysis, "phase67", "faz67"),
                "faz68": _phase_dict_from_analysis(analysis, "phase68", "faz68"),
                "faz69": _phase_dict_from_analysis(analysis, "phase69", "faz69"),
                "faz70": _phase_dict_from_analysis(analysis, "phase70", "faz70"),
                "faz71": p71.to_dict(),
                "faz72": p72.to_dict(),
                "faz73": p73.to_dict(),
                "faz74": p74.to_dict(),
                "faz75": p75.to_dict(),
                "faz76": p76.to_dict(),
                "faz77": p77.to_dict(),
                "faz78": p78.to_dict(),
                "faz79": p79.to_dict(),
                "faz47": p47.to_dict(),
                "faz80": p80.to_dict(),
            }
        )

        # PROMPT-A6 — aynı tick / faz ailesi yüksek güven tekrarına minimal ceza
        conf, _cal_meta = calibrate_confidence_mvp(conf, dctx.phase_chain)
        out["ai_confidence"] = conf
        dctx.ai_confidence = float(conf)
        analysis["confidence_calibration"] = _cal_meta
        if _cal_meta.get("applied"):
            dctx.add_trace("confidence_calibration", str(_cal_meta.get("summary", "")))

        # PROMPT-A9 — meta-orchestrator (varsayılan: shadow; ölçüm olmadan
        # ağırlık değiştirme yok). advisory modda dahi ±%8 ile sınırlandırılmış
        # güven çarpanı uygular; shadow modda yalnızca analysis'e yazar.
        conf, _meta_payload = attach_meta_regime(
            analysis,
            dctx.phase_chain,
            base_confidence=conf,
        )
        out["ai_confidence"] = conf
        dctx.ai_confidence = float(conf)
        if _meta_payload.get("applied"):
            dctx.add_trace("meta_regime", str(_meta_payload.get("summary", "")))

        out["final_action"] = p80.final_action
        out["trade_permission"] = p80.trade_permission
        out["phase80"] = p80.to_dict()
        out["faz47"] = p47.to_dict()
        out["dynamic_stop"] = float(p77.dynamic_stop_level)
        out["faz77_stop"] = p77.to_dict()
        out["execution_layer"] = {
            "final_action": p80.final_action,
            "execution_profile": p80.execution_profile,
            "position_size_multiplier": p80.position_size_multiplier,
            "risk_gate": p80.risk_gate,
            "route_preference": p80.route_preference,
            "leader_venue": p80.leader_venue,
            "preferred_venue": p47.preferred_venue,
            "execution_mode": p47.execution_mode,
            "faz47_reason": p47.reason,
        }

        # Faz 80 final_action → mevcut bot giriş sinyali (BUY/HOLD) köprüsü
        if p80.final_action == "ENTER":
            out["final_signal"] = "BUY"
            out["decision_reason"] = out.get("decision_reason") or "FAZ80_ENTER"
            dctx.add_trace(DecisionStage.ENTRY.value, "faz80:ENTER")
        elif p80.final_action == "HALT":
            out["final_signal"] = "HOLD"
            if "FORCE_ALL_CLOSE" not in (out.get("decision_reason") or ""):
                out["decision_reason"] = "FAZ80_HALT"
            dctx.add_trace(DecisionStage.ENTRY.value, "faz80:HALT")
        elif p80.final_action in ("HEDGE", "EXIT"):
            out["final_signal"] = "HOLD"
            out["decision_reason"] = f"FAZ80_{p80.final_action}"
            dctx.add_trace(DecisionStage.ENTRY.value, f"faz80:{p80.final_action}")
        else:
            out["final_signal"] = "HOLD"
            out["decision_reason"] = out.get("decision_reason") or "FAZ80_WAIT"
            dctx.add_trace(DecisionStage.ENTRY.value, "faz80:WAIT")

        # Faz 80 WAIT iken üst akış zaten BUY ise sinyali koru — giriş kapısı (OB merge, hard limit)
        # decide_autonomously sıkı WAIT üretebilir; legacy tick akışı BUY üzerinden risk kontrolü bekler.
        # TREND_FOLLOW_OVERRIDE: validate_signal atlanır; kalibrasyon/meta güveni düşürse de üst BUY korunur.
        _trend_follow_upstream = analysis.get("execution_mode") == "TREND_FOLLOW" or str(
            _dr_upstream or ""
        ).startswith("TREND_FOLLOW")
        if (
            p80.final_action == "WAIT"
            and _sig_upstream == "BUY"
            and (float(conf) >= 0.55 or _trend_follow_upstream)
        ):
            out["final_signal"] = "BUY"
            if _dr_upstream is not None and str(_dr_upstream).strip():
                out["decision_reason"] = str(_dr_upstream)
            dctx.add_trace(DecisionStage.ENTRY.value, "faz80:WAIT_upstream_buy")

        analysis["dynamic_stop"] = out["dynamic_stop"]
        analysis["faz77"] = out["faz77_stop"]

        await engine._handle_entry(
            symbol,
            price,
            analysis,
            out["final_signal"],
            conf,
            out,
            corr_multiplier=corr_multiplier,
            dctx=dctx,
            candles=candles,
        )
