"""
Faz 27 — Alternatif veri motoru (opsiyon akışı, geliştirici aktivitesi, adoption, tokenomics).

Girdi `alt_data` (esnek dict); örnek anahtarlar:
- options_flow / options: put_call_ratio, put_volume, call_volume, large_notional_usd, whale_flow_ratio
- developer / dev / github: commits_30d, pr_count, days_since_last_commit
- adoption: active_addresses, tx_count_24h, tvl_usd, active_users (normalize edilir)
- tokenomics: circulating_supply_ratio, inflation_apy, vesting_unlock_pct_90d, emission_rate

Saf NumPy (+ stdlib).

Çıktı standard_phase_output uyumlu; phase27 / faz27.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Literal, Optional, Tuple

import numpy as np

from super_otonom.standard_phase_output import attach_phase_alias

ScoreType = Literal["ALPHA", "RISK", "QUALITY"]
TradePermission = Literal["ALLOW", "BLOCK", "HALT"]

_EPS = 1e-12

# Tokenomics — BLOCK eşikleri (göreceli birimler; alt_data ile kalibre edilir)
_MAX_INFLATION_APY_BLOCK = 0.22
_MAX_VESTING_UNLOCK_BLOCK = 0.38
_MIN_CIRCULATING_FOR_SAFE = 0.12


def _now_ms() -> int:
    return int(time.time() * 1000)


def _clamp01(x: float) -> float:
    if x != x:
        return 0.0
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else float(x)


def _normalize(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return dict(raw)


def _try_ts_ms(analysis: Dict[str, Any]) -> int:
    v = analysis.get("event_ts") or analysis.get("candle_ts")
    try:
        if v is None:
            return _now_ms()
        fv = float(v)
        if fv < 1e11:
            return int(fv * 1000.0)
        return int(fv)
    except (TypeError, ValueError):
        return _now_ms()


def _pick_score_type(data_health: float, risk_01: float) -> ScoreType:
    if data_health < 0.42:
        return "QUALITY"
    if risk_01 >= 0.72:
        return "RISK"
    return "ALPHA"


def _get_float(d: Dict[str, Any], *keys: str, default: float = float("nan")) -> float:
    for k in keys:
        if k in d:
            try:
                v = float(d[k])
                if v == v:
                    return v
            except (TypeError, ValueError):
                continue
    return default


def _merge_sections(d: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """options_flow, developer, adoption, tokenomics alt dict'lerini düzleştir."""
    opt = _normalize(d.get("options_flow") or d.get("options") or {})
    if not opt and isinstance(d.get("put_call_ratio"), (int, float)):
        opt = {
            k: d[k]
            for k in ("put_call_ratio", "put_volume", "call_volume", "large_notional_usd")
            if k in d
        }
    dev = _normalize(d.get("developer") or d.get("dev") or d.get("github") or {})
    ado = _normalize(d.get("adoption") or {})
    tok = _normalize(d.get("tokenomics") or {})
    return {"options": opt, "developer": dev, "adoption": ado, "tokenomics": tok}


def _put_call_risk(sections: Dict[str, Dict[str, Any]]) -> Tuple[float, Dict[str, float]]:
    """Yüksek put/call → risk [0,1]. Oran: put hacmi / call hacmi veya doğrudan put_call_ratio."""
    o = sections["options"]
    pc = _get_float(o, "put_call_ratio", "put_to_call", default=float("nan"))
    pv = _get_float(o, "put_volume", "puts", default=float("nan"))
    cv = _get_float(o, "call_volume", "calls", default=float("nan"))
    if pc != pc and pv == pv and cv == cv and cv > _EPS:
        pc = pv / max(cv, _EPS)
    if pc != pc:
        pc = 1.0
    # 1.0 nötr; >1.2 bearish bölge
    skew = _clamp01(max(0.0, (pc - 0.92) / 0.55))
    whale = _get_float(o, "large_notional_usd", "whale_notional", default=0.0)
    whale_n = _clamp01(min(whale / 5e7, 1.0)) if whale > 0 else 0.0
    risk = _clamp01(0.62 * skew + 0.22 * whale_n + 0.16 * _clamp01(skew * whale_n * 2.0))
    detail = {
        "put_call_ratio": float(pc),
        "options_skew_risk": float(skew),
        "whale_flow_weight": float(whale_n),
    }
    return risk, detail


def _developer_scores(sections: Dict[str, Dict[str, Any]]) -> Tuple[float, float, Dict[str, float]]:
    """Aktivite skoru [0,1] ve güven cezası [0,1] (düşük aktivite → confidence çarpanı düşer)."""
    g = sections["developer"]
    commits = _get_float(g, "commits_30d", "commit_count_30d", default=float("nan"))
    prs = _get_float(g, "pr_count", "pull_requests", "merged_prs_30d", default=float("nan"))
    days = _get_float(g, "days_since_last_commit", "staleness_days", default=float("nan"))

    if commits != commits:
        commits = 0.0
    if prs != prs:
        prs = 0.0
    if days != days:
        days = 14.0

    act_raw = 0.55 * _clamp01(commits / 120.0) + 0.45 * _clamp01(prs / 40.0)
    stale_pen = _clamp01(min(days / 45.0, 1.0))
    activity = _clamp01(act_raw * (1.0 - 0.35 * stale_pen))
    conf_penalty = (
        _clamp01(0.25 + 0.75 * stale_pen)
        if commits < 3 and prs < 2
        else _clamp01(0.15 + 0.35 * stale_pen)
    )
    detail = {
        "commits_30d": float(commits),
        "pr_count": float(prs),
        "days_since_last_commit": float(days),
        "activity_score": float(activity),
        "low_activity_confidence_penalty": float(conf_penalty),
    }
    return activity, conf_penalty, detail


def _adoption_scores(sections: Dict[str, Dict[str, Any]]) -> Tuple[float, Dict[str, float]]:
    a = sections["adoption"]
    aa = _get_float(a, "active_addresses", "daily_active_addresses", default=float("nan"))
    tx = _get_float(a, "tx_count_24h", "transactions_24h", "txns", default=float("nan"))
    tvl = _get_float(a, "tvl_usd", "tvl", default=float("nan"))
    users = _get_float(a, "active_users", "wallets_active", default=float("nan"))

    if aa != aa:
        aa = 0.0
    if tx != tx:
        tx = 0.0
    if tvl != tvl:
        tvl = 0.0
    if users != users:
        users = 0.0

    s1 = _clamp01(np.tanh(aa / 8e5))
    s2 = _clamp01(np.tanh(tx / 2e6))
    s3 = _clamp01(np.tanh(tvl / 2e9))
    s4 = _clamp01(np.tanh(users / 5e5))
    adoption = _clamp01(0.30 * s1 + 0.28 * s2 + 0.28 * s3 + 0.14 * s4)
    detail = {
        "active_addresses": float(aa),
        "tx_count_24h": float(tx),
        "tvl_usd": float(tvl),
        "adoption_score": float(adoption),
    }
    return adoption, detail


def _tokenomics_eval(
    sections: Dict[str, Dict[str, Any]],
) -> Tuple[bool, float, str, Dict[str, float]]:
    """
    Kötü tokenomics → BLOCK bayrağı.
    Returns: (should_block, risk_component [0,1], reason, detail)
    """
    t = sections["tokenomics"]
    circ = _get_float(
        t, "circulating_supply_ratio", "circulating_pct", "float_ratio", default=float("nan")
    )
    infl = _get_float(t, "inflation_apy", "annual_inflation", "emission_apy", default=float("nan"))
    vest = _get_float(
        t, "vesting_unlock_pct_90d", "unlock_pct_quarter", "cliff_pct", default=float("nan")
    )
    emis = _get_float(t, "emission_rate", "net_emission_pct", default=float("nan"))

    if circ != circ:
        circ = 0.35
    if infl != infl:
        infl = 0.08
    if vest != vest:
        vest = 0.12
    if emis != emis:
        emis = infl

    reasons: list[str] = []
    block = False
    if infl >= _MAX_INFLATION_APY_BLOCK:
        block = True
        reasons.append("high_inflation")
    if vest >= _MAX_VESTING_UNLOCK_BLOCK:
        block = True
        reasons.append("heavy_vesting")
    if circ < _MIN_CIRCULATING_FOR_SAFE and vest >= 0.22:
        block = True
        reasons.append("low_float_high_unlock")

    tok_risk = _clamp01(
        0.34 * _clamp01(infl / 0.35)
        + 0.33 * _clamp01(vest / 0.45)
        + 0.22 * _clamp01(max(0.0, 0.55 - circ))
        + 0.11 * _clamp01(emis / 0.30)
    )
    reason = ",".join(sorted(set(reasons))) if reasons else ""
    detail = {
        "circulating_supply_ratio": float(circ),
        "inflation_apy": float(infl),
        "vesting_unlock_pct_90d": float(vest),
        "emission_rate": float(emis),
        "tokenomics_risk_score": float(tok_risk),
        "tokenomics_block": bool(block),
    }
    return block, tok_risk, reason, detail


def analyze_alternative_data(
    symbol: str,
    alt_data: Any,
    analysis: Optional[Dict[str, Any]] = None,
    *,
    attach_to_analysis: bool = True,
    half_life_ms: int = 86_400_000,
    event_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Alternatif veri özeti; `analysis['phase27']` / `['faz27']` yazar.
    """
    _ = symbol
    a = analysis if analysis is not None else {}
    ts = int(event_ts) if event_ts is not None else _try_ts_ms(a)
    d = _normalize(alt_data)

    if not d:
        payload = _empty_phase27(ts, half_life_ms, "no_alt_data")
        if attach_to_analysis:
            attach_phase_alias(a, "27", payload)
        return payload

    sections = _merge_sections(d)
    opt_risk, opt_detail = _put_call_risk(sections)
    options_an = _deep_options_analysis(d, sections)  # PROMPT-3.3
    dev_act, dev_conf_pen, dev_detail = _developer_scores(sections)
    dev_deep = _deep_developer_analysis(sections["developer"])  # PROMPT-5.3
    if dev_deep is not None:
        # Genişletilmiş GitHub aktivite skoru, temel developer skoruyla harmanlanır.
        dev_act = _clamp01(0.5 * dev_act + 0.5 * dev_deep.activity_score)
    adop, adop_detail = _adoption_scores(sections)
    onchain_an = _deep_onchain_analysis(d)  # PROMPT-2.1
    if onchain_an is not None:
        # On-chain adoption skoru mevcut adoption skoruyla harmanlanır.
        adop = _clamp01(0.55 * adop + 0.45 * onchain_an.adoption_score)
    tok_block, tok_risk, tok_reason, tok_detail = _tokenomics_eval(sections)

    coverage = sum(
        1
        for s in sections.values()
        if isinstance(s, dict) and len([k for k in s if s.get(k) not in (None, "", [])]) > 0
    )
    cov01 = _clamp01(coverage / 4.0)

    blend = _clamp01(
        0.28 * (1.0 - opt_risk) + 0.24 * dev_act + 0.30 * adop + 0.18 * (1.0 - tok_risk)
    )

    risk_01 = _clamp01(
        0.32 * opt_risk
        + 0.28 * tok_risk
        + 0.18 * _clamp01(max(0.0, opt_risk - 0.35))
        + 0.14 * (1.0 - cov01)
        + 0.08 * float(tok_block)
    )
    if opt_risk > 0.72:
        risk_01 = _clamp01(max(risk_01, 0.68))

    alpha_01 = _clamp01(
        0.38 * adop
        + 0.26 * dev_act
        + 0.18 * blend
        + 0.12 * (1.0 - opt_risk)
        + 0.06 * (1.0 - tok_risk)
    )
    if adop > 0.62:
        alpha_01 = _clamp01(min(1.0, alpha_01 * 1.08 + 0.03))

    # PROMPT-3.3: derinlemesine options flow (PCR/whale/max pain/IV)
    if options_an is not None:
        risk_01 = _clamp01(max(risk_01, options_an.risk_score))
        alpha_01 = _clamp01(alpha_01 + 0.10 * options_an.alpha_bias)

    # PROMPT-2.1: on-chain metrics (network/holder/miner/MVRV)
    if onchain_an is not None:
        risk_01 = _clamp01(max(risk_01, onchain_an.risk_score))
        alpha_01 = _clamp01(alpha_01 + 0.12 * onchain_an.alpha_bias)

    # PROMPT-5.1: token unlock & vesting (satış baskısı → risk, alpha negatif)
    unlock_an = _deep_unlock_analysis(d)
    if unlock_an is not None:
        risk_01 = _clamp01(max(risk_01, unlock_an.risk_score))
        alpha_01 = _clamp01(alpha_01 + 0.10 * unlock_an.alpha_bias)

    # PROMPT-5.3: developer activity (red flag → risk, pozitif sinyal → alpha)
    if dev_deep is not None:
        risk_01 = _clamp01(max(risk_01, dev_deep.risk_score))
        alpha_01 = _clamp01(alpha_01 + 0.10 * dev_deep.alpha_bias)

    conf_base = _clamp01(0.22 + 0.42 * cov01 + 0.24 * dev_act + 0.12 * (1.0 - opt_risk))
    conf = _clamp01(conf_base * (1.0 - 0.55 * dev_conf_pen))

    dh = _clamp01(0.18 + 0.30 * cov01 + 0.26 * dev_act + 0.16 * adop + 0.10 * (1.0 - tok_risk))

    perm: TradePermission = "ALLOW"
    if d.get("force_halt") is True:
        perm = "HALT"
    elif unlock_an is not None and unlock_an.trade_permission == "HALT":
        perm = "HALT"
    elif unlock_an is not None and unlock_an.trade_permission == "BLOCK":
        perm = "BLOCK"
    elif tok_block:
        perm = "BLOCK"
    elif risk_01 >= 0.88:
        perm = "BLOCK"
    elif risk_01 >= 0.72:
        perm = "BLOCK"

    st = _pick_score_type(dh, risk_01)

    payload: Dict[str, Any] = {
        "trade_permission": perm,
        "alpha_score": float(alpha_01),
        "risk_score": float(risk_01),
        "confidence": float(conf),
        "data_health": float(dh),
        "event_ts": float(ts),
        "half_life_ms": int(half_life_ms),
        "score_type": st,
        "phase": "27",
        "source": "alternative_data_engine",
        "alternative_data": {
            "options_flow": opt_detail,
            "developer": dev_detail,
            "adoption": adop_detail,
            "tokenomics": tok_detail,
            "blend_score": float(blend),
            "coverage_score": float(cov01),
            "tokenomics_block_reason": tok_reason or None,
        },
    }

    if options_an is not None:
        payload["alternative_data"]["options_flow_deep"] = options_an.to_dict()
    if onchain_an is not None:
        payload["alternative_data"]["onchain"] = onchain_an.to_dict()
    if unlock_an is not None:
        payload["alternative_data"]["unlock"] = unlock_an.to_dict()
    if dev_deep is not None:
        payload["alternative_data"]["developer_deep"] = dev_deep.to_dict()

    if attach_to_analysis:
        attach_phase_alias(a, "27", payload)

    return payload


def _deep_unlock_analysis(d: Dict[str, Any]) -> Any:
    """PROMPT-5.1 — token unlock & vesting takvimi. İlgili veri yoksa None.

    Girdi: ``token_unlock`` alt dict veya düz ``unlock_schedule`` listesi.
    """
    try:
        from super_otonom.signals.token_unlock_tracker import analyze_unlock_data

        return analyze_unlock_data(d)
    except Exception:  # unlock analizi asla Faz 27'yi bozmamalı
        return None


def _deep_developer_analysis(developer: Dict[str, Any]) -> Any:
    """PROMPT-5.3 — GitHub developer activity. Genişletilmiş veri yoksa None."""
    try:
        from super_otonom.signals.developer_activity_tracker import analyze_developer_data

        return analyze_developer_data(developer)
    except Exception:  # developer analizi asla Faz 27'yi bozmamalı
        return None


def _deep_onchain_analysis(d: Dict[str, Any]) -> Any:
    """PROMPT-2.1 — on-chain metrics (network/holder/miner/MVRV). Veri yoksa None.

    Girdi: ``onchain`` alt dict (veya düz alt_data) içinde ``active_addresses``,
    ``tx_count``, ``tx_volume_usd``, ``new_address_rate``, ``avg_tx_fee_usd``,
    ``top10_pct``/``top100_pct``/``top1000_pct``, ``holder_count_change_pct``,
    ``lth_ratio``, ``accumulation_trend_30d``, ``miner_outflow_usd``,
    ``staking_ratio_change``, ``hash_rate_change_pct``, ``mvrv``,
    ``market_price``, ``realized_price``.
    """
    oc = d.get("onchain") if isinstance(d.get("onchain"), dict) else {}
    src = {**d, **oc}

    def _g(*keys: str) -> Optional[float]:
        v = _get_float(src, *keys, default=float("nan"))
        return v if v == v else None

    has_net = any(
        _g(k) is not None
        for k in ("active_addresses", "tx_count", "tx_volume_usd", "new_address_rate", "avg_tx_fee_usd")
    )
    has_hold = any(
        _g(k) is not None
        for k in ("top10_pct", "holder_count_change_pct", "lth_ratio", "accumulation_trend_30d")
    )
    has_miner = any(
        _g(k) is not None for k in ("miner_outflow_usd", "staking_ratio_change", "hash_rate_change_pct")
    )
    has_mvrv = _g("mvrv") is not None or (
        _g("market_price") is not None and _g("realized_price") is not None
    )
    if not (has_net or has_hold or has_miner or has_mvrv):
        return None

    from super_otonom.signals.onchain_intelligence import (
        analyze_holders,
        analyze_miner_metrics,
        analyze_mvrv,
        analyze_network_activity,
        analyze_onchain,
    )

    try:
        net = analyze_network_activity(
            active_addresses=_g("active_addresses"), tx_count=_g("tx_count"),
            tx_volume_usd=_g("tx_volume_usd"), new_address_rate=_g("new_address_rate"),
            avg_tx_fee_usd=_g("avg_tx_fee_usd"),
        ) if has_net else None
        hold = analyze_holders(
            top10_pct=_g("top10_pct"), top100_pct=_g("top100_pct"), top1000_pct=_g("top1000_pct"),
            holder_count_change_pct=_g("holder_count_change_pct"), lth_ratio=_g("lth_ratio"),
            accumulation_trend_30d=_g("accumulation_trend_30d"),
        ) if has_hold else None
        miner = analyze_miner_metrics(
            miner_outflow_usd=_g("miner_outflow_usd"),
            staking_ratio_change=_g("staking_ratio_change"),
            hash_rate_change_pct=_g("hash_rate_change_pct"),
        ) if has_miner else None
        mvrv = analyze_mvrv(
            mvrv=_g("mvrv"), market_price=_g("market_price"), realized_price=_g("realized_price"),
        ) if has_mvrv else None
        return analyze_onchain(network=net, holders=hold, miner=miner, mvrv=mvrv)
    except Exception:  # on-chain analizi asla Faz 27'yi bozmamalı
        return None


def _deep_options_analysis(d: Dict[str, Any], sections: Dict[str, Dict[str, Any]]) -> Any:
    """PROMPT-3.3 — derinlemesine options flow. İlgili veri yoksa None.

    Girdi (opsiyonel): ``options_flow``/``options`` altında ``pcr_history``,
    ``whale_trades``, ``option_chain`` ([{strike,call_oi,put_oi}]), ``spot``,
    ``hours_to_expiry``, ``put_iv``/``call_iv``/``short_iv``/``long_iv``,
    ``realized_vol``, ``current_volume``/``avg_volume``.
    """
    o = sections.get("options", {})
    pcr_hist = o.get("pcr_history") or d.get("pcr_history")
    whale_trades = o.get("whale_trades") or d.get("whale_trades")
    chain = o.get("option_chain") or d.get("option_chain")
    put_iv = _get_float(o, "put_iv", default=float("nan"))
    call_iv = _get_float(o, "call_iv", default=float("nan"))
    short_iv = _get_float(o, "short_iv", "iv_short", default=float("nan"))
    long_iv = _get_float(o, "long_iv", "iv_long", default=float("nan"))

    pv = _get_float(o, "put_volume", "puts", default=float("nan"))
    cv = _get_float(o, "call_volume", "calls", default=float("nan"))
    pcr_val = _get_float(o, "put_call_ratio", "put_to_call", default=float("nan"))

    has_pcr = pcr_val == pcr_val or (pv == pv and cv == cv) or bool(pcr_hist)
    has_whale = isinstance(whale_trades, (list, tuple)) and len(whale_trades) > 0
    has_chain = isinstance(chain, (list, tuple)) and len(chain) > 0
    has_iv = any(x == x for x in (put_iv, call_iv, short_iv, long_iv))
    if not (has_pcr or has_whale or has_chain or has_iv):
        return None

    from super_otonom.signals.options_flow_intelligence import (
        analyze_iv,
        analyze_max_pain,
        analyze_options_flow,
        analyze_pcr,
        detect_whale_options,
    )

    def _opt(x: float) -> Optional[float]:
        return x if x == x else None

    try:
        pcr_sig = analyze_pcr(
            put_volume=_opt(pv), call_volume=_opt(cv), pcr=_opt(pcr_val),
            pcr_history=pcr_hist if isinstance(pcr_hist, (list, tuple)) else None,
        ) if has_pcr else None
        whale_sig = detect_whale_options(
            whale_trades,
            current_volume=_get_float(o, "current_volume", default=float("nan")) or None,
            avg_volume=_get_float(o, "avg_volume", default=float("nan")) or None,
        ) if has_whale else None
        mp_sig = analyze_max_pain(
            chain,
            spot=_get_float(o, "spot", "underlying_price", default=float("nan")) or None,
            hours_to_expiry=_get_float(o, "hours_to_expiry", default=float("nan")) or None,
        ) if has_chain else None
        iv_sig = analyze_iv(
            put_iv=_opt(put_iv), call_iv=_opt(call_iv),
            short_iv=_opt(short_iv), long_iv=_opt(long_iv),
            realized_vol=_get_float(o, "realized_vol", default=float("nan")) or None,
            hours_to_expiry=_get_float(o, "hours_to_expiry", default=float("nan")) or None,
        ) if has_iv else None
        return analyze_options_flow(pcr=pcr_sig, whale=whale_sig, max_pain=mp_sig, iv=iv_sig)
    except Exception:  # options analizi asla Faz 27'yi bozmamalı
        return None


def run_alternative_data_phase(
    symbol: str,
    alt_data: Any,
    analysis: Optional[Dict[str, Any]] = None,
    *,
    attach_to_analysis: bool = True,
    half_life_ms: int = 86_400_000,
    event_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """Pipeline girişi — `analyze_alternative_data` ile aynı."""
    return analyze_alternative_data(
        symbol,
        alt_data,
        analysis,
        attach_to_analysis=attach_to_analysis,
        half_life_ms=half_life_ms,
        event_ts=event_ts,
    )


def _empty_phase27(ts: int, half_life_ms: int, reason: str) -> Dict[str, Any]:
    return {
        "trade_permission": "BLOCK",
        "alpha_score": 0.0,
        "risk_score": 1.0,
        "confidence": 0.0,
        "data_health": 0.0,
        "event_ts": float(ts),
        "half_life_ms": int(half_life_ms),
        "score_type": "QUALITY",
        "phase": "27",
        "source": "alternative_data_engine",
        "empty_reason": reason,
        "alternative_data": {},
    }
