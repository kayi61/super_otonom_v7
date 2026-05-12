"""
Override fazları (39 / 50 / 64 / 66–70 / 68) → analysis['phase39'] … için köprü.

Faz 66–70 modülleri burada çalışır; Faz 68 güvenlik + FORCE_ALL_CLOSE birleşimi en sonda.

Çağrı yeri: BotEngine.tick — risk + sinyal + filtrelerden sonra, execute_trade öncesi.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from super_otonom.backtest_leakage_guard import evaluate_backtest_leakage_guard
from super_otonom.data_quality_governance import evaluate_data_quality_governance
from super_otonom.exchange_connectivity_engine import evaluate_exchange_connectivity
from super_otonom.incident_response_engine import evaluate_incident_response
from super_otonom.pipelines import risk_pipeline
from super_otonom.safety_policy_engine import evaluate_safety_policy


def _snap(
    trade_permission: str,
    *,
    source: str,
    half_life_ms: int = 60_000,
    event_ts: Optional[int] = None,
) -> Dict[str, Any]:
    ts = int(event_ts) if event_ts is not None else int(time.time() * 1000)
    return {
        "trade_permission": trade_permission,
        "event_ts": ts,
        "half_life_ms": int(half_life_ms),
        "source": source,
    }


def attach_override_phases_to_analysis(
    analysis: Dict[str, Any],
    *,
    engine: Any,
    dctx: Any,
    out: Dict[str, Any],
    symbol: str = "",
) -> None:
    """
    analysis üzerine phase39, phase50, phase64, phase68 yazar (idempotent overwrite her tick).
    """
    _ = out

    # phase50 — portföy risk / acil durum (RiskManager)
    perm50 = "HALT" if bool(getattr(engine.risk, "emergency_stop", False)) else "ALLOW"
    analysis["phase50"] = _snap(perm50, source="risk_manager")

    # phase39 — likidite / ön kapı sonucu (main_loop apply_liquidity_context, pre_trade)
    perm39 = "ALLOW"
    if str(analysis.get("entry_scale", "") or "").lower() == "blocked":
        perm39 = "BLOCK"
    elif dctx is not None and getattr(dctx, "entry_blocked", None):
        perm39 = "BLOCK"
    analysis["phase39"] = _snap(perm39, source="liquidity_entry_gates")

    # phase64 — sinyal kalitesi tabanı (DecisionContext OMEGA / quality gating)
    perm64 = "ALLOW"
    if dctx is not None:
        adj = getattr(dctx, "adj_signal_quality", None)
        eqm = getattr(dctx, "effective_quality_min", None)
        try:
            if adj is not None and eqm is not None and int(adj) < int(eqm):
                perm64 = "BLOCK"
        except (TypeError, ValueError):
            pass
    analysis["phase64"] = _snap(perm64, source="signal_quality_gate")

    sym = (symbol or analysis.get("symbol") or "").strip() or "UNKNOWN"

    # phase66 — veri kalitesi yönetişimi
    r66 = evaluate_data_quality_governance(symbol=sym, analysis=analysis)
    d66 = r66.to_dict()
    d66["source"] = "data_quality_governance"
    analysis["phase66"] = d66

    # phase67 — borsa bağlantısı
    r67 = evaluate_exchange_connectivity(symbol=sym, analysis=analysis)
    d67 = r67.to_dict()
    d67["source"] = "exchange_connectivity_engine"
    analysis["phase67"] = d67

    # phase69 — backtest sızıntı koruması
    r69 = evaluate_backtest_leakage_guard(symbol=sym, analysis=analysis)
    d69 = r69.to_dict()
    d69["source"] = "backtest_leakage_guard"
    analysis["phase69"] = d69

    # phase70 — olay müdahalesi
    r70 = evaluate_incident_response(symbol=sym, analysis=analysis)
    d70 = r70.to_dict()
    d70["source"] = "incident_response_engine"
    analysis["phase70"] = d70

    # phase68 — Faz 68 safety policy + ortam kill (FORCE_ALL_CLOSE)
    r68 = evaluate_safety_policy(symbol=sym, analysis=analysis)
    d68 = r68.to_dict()
    d68["source"] = "safety_policy_engine"
    if risk_pipeline.force_all_close_requested():
        d68["trade_permission"] = "HALT"
        d68["source"] = "safety_policy_engine+force_all_close"
    analysis["phase68"] = d68


def fill_governance_phases_if_missing(analysis: Dict[str, Any], symbol: str) -> None:
    """
    execution_pipeline doğrudan çağrıldığında (bridge yok) Faz 66–70 sözlüklerini üretir.
    BotEngine.tick yolunda attach_override_phases_to_analysis zaten doldurur — çift hesap yok.
    """
    sym = (symbol or analysis.get("symbol") or "").strip() or "UNKNOWN"

    if analysis.get("phase66") is None and analysis.get("faz66") is None:
        r66 = evaluate_data_quality_governance(symbol=sym, analysis=analysis)
        analysis["phase66"] = {**r66.to_dict(), "source": "data_quality_governance"}
    if analysis.get("phase67") is None and analysis.get("faz67") is None:
        r67 = evaluate_exchange_connectivity(symbol=sym, analysis=analysis)
        analysis["phase67"] = {**r67.to_dict(), "source": "exchange_connectivity_engine"}
    if analysis.get("phase69") is None and analysis.get("faz69") is None:
        r69 = evaluate_backtest_leakage_guard(symbol=sym, analysis=analysis)
        analysis["phase69"] = {**r69.to_dict(), "source": "backtest_leakage_guard"}
    if analysis.get("phase70") is None and analysis.get("faz70") is None:
        r70 = evaluate_incident_response(symbol=sym, analysis=analysis)
        analysis["phase70"] = {**r70.to_dict(), "source": "incident_response_engine"}
    if analysis.get("phase68") is None and analysis.get("faz68") is None:
        r68 = evaluate_safety_policy(symbol=sym, analysis=analysis)
        d68 = {**r68.to_dict(), "source": "safety_policy_engine"}
        if risk_pipeline.force_all_close_requested():
            d68["trade_permission"] = "HALT"
            d68["source"] = "safety_policy_engine+force_all_close"
        analysis["phase68"] = d68
