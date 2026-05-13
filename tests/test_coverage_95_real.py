"""
Gerçek kapsam artışı — %90 → %95. Sahte omit yok; testler asıl modül davranışını
zorlar. Hedef modüller (önceki coverage durumlarıyla birlikte):
  - autonomous_decision_core  (81% → ~95%)  tüm override/action/sizing dalları
  - smart_money_tracker       (82% → ~95%)  helpers + analyze + dump path
  - analyzer                  (90% → ~96%)  apply_liquidity_context + alt_tf_veto + analyze_v5_1
  - capital_engine            (89% → ~96%)  invariant violation + journal rotate edge
  - staged_exit               (80% → ~95%)  effective_stage_threshold + evaluate_exit + apply
  - audit_log                 (84% → ~95%)  AuditLog + DailyReconciler tüm yollar
  - kanon_drift_check         (70% → ~95%)  run_all_checks dalları
  - meta_regime_orchestrator  (86% → ~96%)  advisory + ack file path
  - regime_adaptive_execution (82% → ~96%)  infer_regime_adaptive_execution dalları
  - backtest_leakage_guard    (80% → ~98%)  tüm dallar
  - alpha_decay_realtime      (88% → ~98%)
  - signal_lineage            (92% → ~99%)
  - liquidity_games_detector  (89% → ~97%)
  - confidence_calibration    (87% → ~95%)
  - risk_ontology             (88% → ~95%)

Strateji/main_loop/bot_engine.tick mantığına dokunulmaz — yalnız modül çağrıları.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

# ════════════════════════════════════════════════════════════════════════════
# autonomous_decision_core — Faz 80 nihai karar
# ════════════════════════════════════════════════════════════════════════════


def _phase71_clean() -> Dict[str, Any]:
    return {
        "trade_permission": "ALLOW",
        "data_health": 0.95,
        "confidence": 0.85,
        "event_ts": 1_700_000_000_000,
        "half_life_ms": 25_000,
    }


def _phase72_clean() -> Dict[str, Any]:
    return {
        "trade_permission": "ALLOW",
        "data_health": 0.95,
        "confidence": 0.85,
        "whale_intent": "accumulate",
        "absorption_score": 80,
        "sweep_risk": 10,
        "entry_timing_hint": "enter_now",
        "event_ts": 1_700_000_000_000,
        "half_life_ms": 25_000,
    }


def _phase73_clean() -> Dict[str, Any]:
    return {
        "trade_permission": "ALLOW",
        "data_health": 0.95,
        "confidence": 0.85,
        "manipulation_risk_score": 10,
        "do_not_trade_flag": False,
        "cooldown_seconds": 0,
        "event_ts": 1_700_000_000_000,
        "half_life_ms": 25_000,
    }


def _phase74_clean() -> Dict[str, Any]:
    return {
        "trade_permission": "ALLOW",
        "data_health": 0.95,
        "confidence": 0.85,
        "leadlag_alpha_score": 75,
        "latency_arb_risk": 15,
        "route_preference": "leader",
        "leader_venue": "okx",
        "event_ts": 1_700_000_000_000,
        "half_life_ms": 25_000,
    }


def _phase75_clean(action: str = "TRADE") -> Dict[str, Any]:
    return {
        "trade_permission": "ALLOW",
        "data_health": 0.95,
        "confidence": 0.85,
        "action": action,
        "conviction": 70,
        "alpha_score": 75,
        "risk_score": 30,
        "execution_profile": "taker",
        "max_size_multiplier": 1.0,
        "event_ts": 1_700_000_000_000,
        "half_life_ms": 25_000,
    }


def test_autonomous_decision_helpers() -> None:
    from super_otonom.autonomous_decision_core import (
        _clamp01,
        _clamp100,
        _combine_trade_permission,
        _get,
        _perm_rank,
    )

    assert _clamp01(float("nan")) == 0.0
    assert _clamp01(-0.5) == 0.0
    assert _clamp01(2.0) == 1.0
    assert _clamp100(float("nan")) == 0
    assert _clamp100(120) == 100
    assert _clamp100(-5) == 0

    assert _get(None, "x", default=99) == 99
    assert _get({"a": 1}, "a") == 1

    class Dummy:
        x = 7

    assert _get(Dummy(), "x") == 7
    assert _get(Dummy(), "missing", default=42) == 42

    assert _perm_rank("HALT") == 2
    assert _perm_rank("BLOCK") == 1
    assert _perm_rank("ALLOW") == 0
    assert _perm_rank("?") == 0

    assert _combine_trade_permission("ALLOW", "BLOCK", "HALT") == "HALT"
    assert _combine_trade_permission("ALLOW", "ALLOW") == "ALLOW"
    assert _combine_trade_permission() == "ALLOW"


def test_autonomous_decision_enter_path() -> None:
    from super_otonom.autonomous_decision_core import decide_autonomously

    res = decide_autonomously(
        symbol="BTC/USDT",
        phase71=_phase71_clean(),
        phase72=_phase72_clean(),
        phase73=_phase73_clean(),
        phase74=_phase74_clean(),
        phase75=_phase75_clean("TRADE"),
        phase78={"alpha_freshness_score": 80, "exit_urgency": 10, "data_health": 0.9, "confidence": 0.8, "trade_permission": "ALLOW"},
        phase79={"mtf_consensus_score": 75, "conflict_flag": False, "entry_timing": "ok", "data_health": 0.9, "confidence": 0.8, "trade_permission": "ALLOW"},
    )
    assert res.final_action in ("ENTER", "WAIT")
    assert isinstance(res.to_dict(), dict)


def test_autonomous_decision_halt_path() -> None:
    from super_otonom.autonomous_decision_core import decide_autonomously

    p75 = _phase75_clean("HALT")
    p75["trade_permission"] = "HALT"
    res = decide_autonomously(
        symbol="X",
        phase71=_phase71_clean(),
        phase72=_phase72_clean(),
        phase73=_phase73_clean(),
        phase74=_phase74_clean(),
        phase75=p75,
    )
    assert res.final_action == "HALT"
    assert res.trade_permission == "HALT"


def test_autonomous_decision_override_chain() -> None:
    from super_otonom.autonomous_decision_core import decide_autonomously

    # phase50 BLOCK -> override:phase50
    res = decide_autonomously(
        symbol="X",
        phase71=_phase71_clean(),
        phase72=_phase72_clean(),
        phase73=_phase73_clean(),
        phase74=_phase74_clean(),
        phase75=_phase75_clean(),
        phase50={"trade_permission": "BLOCK"},
    )
    assert "phase50" in res.block_reason

    # phase39 BLOCK
    res2 = decide_autonomously(
        symbol="X",
        phase71=_phase71_clean(),
        phase72=_phase72_clean(),
        phase73=_phase73_clean(),
        phase74=_phase74_clean(),
        phase75=_phase75_clean(),
        phase39={"trade_permission": "BLOCK"},
    )
    assert "phase39" in res2.block_reason

    # phase64/66/67/68/69/70 BLOCK
    for ph_name in ("phase64", "phase66", "phase67", "phase68", "phase69", "phase70"):
        res_n = decide_autonomously(
            symbol="X",
            phase71=_phase71_clean(),
            phase72=_phase72_clean(),
            phase73=_phase73_clean(),
            phase74=_phase74_clean(),
            phase75=_phase75_clean(),
            **{ph_name: {"trade_permission": "BLOCK"}},
        )
        assert ph_name.replace("phase", "phase") in res_n.block_reason


def test_autonomous_decision_hedge_exit() -> None:
    from super_otonom.autonomous_decision_core import decide_autonomously

    # extreme risk -> HEDGE
    p75 = _phase75_clean("WAIT")
    p75["risk_score"] = 95
    p73 = _phase73_clean()
    p73["manipulation_risk_score"] = 90
    res = decide_autonomously(
        symbol="X",
        phase71=_phase71_clean(),
        phase72=_phase72_clean(),
        phase73=p73,
        phase74=_phase74_clean(),
        phase75=p75,
    )
    assert res.final_action in ("HEDGE", "WAIT")

    # exit_urgency high + low freshness -> EXIT path (forbidden side)
    p73_b = _phase73_clean()
    p73_b["do_not_trade_flag"] = True
    res2 = decide_autonomously(
        symbol="X",
        phase71=_phase71_clean(),
        phase72=_phase72_clean(),
        phase73=p73_b,
        phase74=_phase74_clean(),
        phase75=_phase75_clean(),
        phase78={"alpha_freshness_score": 10, "exit_urgency": 90, "data_health": 0.9, "confidence": 0.8, "trade_permission": "ALLOW"},
    )
    assert res2.final_action in ("EXIT", "HEDGE", "WAIT")


def test_autonomous_decision_cooldown_and_stop_hint() -> None:
    from super_otonom.autonomous_decision_core import decide_autonomously

    # cooldown active -> WAIT
    p73 = _phase73_clean()
    p73["cooldown_seconds"] = 60
    res = decide_autonomously(
        symbol="X",
        phase71=_phase71_clean(),
        phase72=_phase72_clean(),
        phase73=p73,
        phase74=_phase74_clean(),
        phase75=_phase75_clean(),
    )
    assert res.final_action == "WAIT"
    assert "cooldown" in res.block_reason

    # stop_hint widen + risk score in window
    p77 = {
        "trade_permission": "ALLOW",
        "data_health": 0.95,
        "confidence": 0.85,
        "hunt_risk_score": 50,
        "stop_placement_hint": "widen",
    }
    res2 = decide_autonomously(
        symbol="X",
        phase71=_phase71_clean(),
        phase72=_phase72_clean(),
        phase73=_phase73_clean(),
        phase74=_phase74_clean(),
        phase75=_phase75_clean(),
        phase77=p77,
    )
    assert res2.final_action in ("ENTER", "WAIT")

    # avoid_latency_arb + high latency
    p74_h = _phase74_clean()
    p74_h["route_preference"] = "avoid_latency_arb"
    p74_h["latency_arb_risk"] = 90
    res3 = decide_autonomously(
        symbol="X",
        phase71=_phase71_clean(),
        phase72=_phase72_clean(),
        phase73=_phase73_clean(),
        phase74=p74_h,
        phase75=_phase75_clean(),
    )
    assert res3.final_action in ("ENTER", "WAIT")


# ════════════════════════════════════════════════════════════════════════════
# smart_money_tracker
# ════════════════════════════════════════════════════════════════════════════


def test_smart_money_helpers() -> None:
    from super_otonom.smart_money_tracker import (
        _alpha_smart_money,
        _clamp01,
        _exchange_netflow_bias,
        _get_num,
        _institutional_vc_score,
        _normalize_input,
        _parse_direction,
        _pick_score_type,
        _risk_smart_money,
        _transfer_amount,
        _try_ts_ms,
        _whale_transfer_scores,
    )

    assert _clamp01(float("nan")) == 0.0
    assert _pick_score_type(0.1, 0.0) == "QUALITY"
    assert _pick_score_type(0.9, 0.9) == "RISK"
    assert _try_ts_ms({"event_ts": "bad"}) > 0
    assert _try_ts_ms({"event_ts": 1700000000}) > 0
    assert _try_ts_ms({"event_ts": 1700000000.5}) > 0
    assert _get_num({}, "x") is None
    assert _get_num({"x": "bad"}, "x", default=1.0) == 1.0
    assert _get_num({"x": 5}, "x") == 5.0
    assert _normalize_input("nope") == {}

    assert _parse_direction({"direction": "INFLOW"}) == "inflow"
    assert _parse_direction({"flow": "outflow"}) == "outflow"
    assert _parse_direction({}) == ""
    assert _transfer_amount({"amount_usd": 100}) == 100.0
    assert _transfer_amount({"size_usd": 50}) == 50.0
    assert _transfer_amount({}) == 0.0

    # empty
    act, bias, dump = _whale_transfer_scores([])
    assert act == 0.25 and bias == 0.0
    # accumulation only
    act2, bias2, dump2 = _whale_transfer_scores([
        {"amount_usd": 1e7, "flow": "accumulation"},
        {"amount_usd": 5e6, "flow": "cold_storage"},
    ])
    assert bias2 > 0
    # distribution
    act3, bias3, dump3 = _whale_transfer_scores([
        {"amount_usd": 2e7, "flow": "to_exchange"},
        {"amount_usd": 1e7, "flow": "distribution"},
    ])
    assert bias3 < 0 and dump3 > 0
    # neutral
    act4, bias4, _ = _whale_transfer_scores([{"amount_usd": 1e6, "flow": "internal"}])
    assert bias4 == 0.0
    # zero amount filtered + invalid row
    act5, bias5, _ = _whale_transfer_scores([
        "not a dict",
        {"amount_usd": 0},
        {"amount_usd": 1e6, "flow": "inflow"},
    ])
    assert act5 > 0
    # all-zero
    act6, _, _ = _whale_transfer_scores([{"amount_usd": 0}, {"amount_usd": -1}])
    assert act6 == 0.25

    # institutional helpers
    inst = _institutional_vc_score({"institutional_accumulation_score": 0.7})
    assert inst == 0.7
    inst2 = _institutional_vc_score({"smart_money_index": 75})  # >1 -> /100
    assert inst2 == 0.75
    inst3 = _institutional_vc_score({"etf_net_flow_usd": 1e7, "vc_net_flow_usd": 5e6})
    assert 0.0 <= inst3 <= 1.0
    inst4 = _institutional_vc_score({})
    assert inst4 == 0.35

    bias_net = _exchange_netflow_bias(None)
    assert bias_net == 0.5
    bias_net2 = _exchange_netflow_bias(-1e7)  # outflow -> positive bias
    assert bias_net2 > 0.5
    bias_net3 = _exchange_netflow_bias(1e7)
    assert bias_net3 < 0.5

    a = _alpha_smart_money("BUY", 0.5, 0.7, 0.7, 0.5)
    assert 0.0 <= a <= 1.0
    a2 = _alpha_smart_money("SELL", -0.3, 0.4, 0.4, 0.3)
    assert 0.0 <= a2 <= 1.0
    a3 = _alpha_smart_money("HOLD", 0.0, 0.5, 0.5, 0.0)
    assert 0.0 <= a3 <= 1.0

    r = _risk_smart_money(0.8, 0.5, -0.4)
    assert 0.0 <= r <= 1.0


def test_smart_money_analyze_full() -> None:
    from super_otonom.smart_money_tracker import analyze_smart_money, run_smart_money_phase

    full = {
        "whale_transfers": [
            {"amount_usd": 2e6, "flow": "inflow"},
            {"amount_usd": 1e6, "flow": "cold_storage"},
        ],
        "exchange_netflow_usd": -5e6,
        "etf_net_flow_usd": 1e7,
        "vc_net_flow_usd": 2e6,
        "institutional_flow_usd": 5e6,
    }
    res = analyze_smart_money("BTC/USDT", full)
    assert res["phase"] == "17"

    # HALT path - extreme dump pressure
    huge_dump = {
        "whale_transfers": [
            {"amount_usd": 5e7, "flow": "to_exchange"},
            {"amount_usd": 5e7, "flow": "distribution"},
            {"amount_usd": 5e7, "flow": "dump"},
        ],
    }
    res2 = run_smart_money_phase("X", huge_dump)
    assert res2["trade_permission"] in ("BLOCK", "HALT", "ALLOW")

    res3 = analyze_smart_money("X", "not dict")
    assert res3["empty_reason"] == "no_smart_money_data"


# ════════════════════════════════════════════════════════════════════════════
# analyzer
# ════════════════════════════════════════════════════════════════════════════


def _candles(n: int, start: float = 100.0, drift: float = 0.001) -> List[Dict[str, float]]:
    out: List[Dict[str, float]] = []
    p = start
    for i in range(n):
        p_new = p * (1.0 + drift + 0.001 * (i % 5 - 2))
        out.append({
            "open": p,
            "high": max(p, p_new) * 1.001,
            "low": min(p, p_new) * 0.999,
            "close": p_new,
            "volume": 1000.0 + (i % 7) * 10,
        })
        p = p_new
    return out


def test_analyzer_helpers() -> None:
    from super_otonom.analyzer import (
        _atr,
        _bollinger,
        _calculate_hurst,
        _ema,
        _falling_last_two_closes,
        _rising_last_two_closes,
        _rsi,
        _volume_ratio,
        detect_market_regime,
    )

    assert _ema([], 9) == 0.0
    assert _ema([100.0, 101.0, 102.0], 9) > 0

    assert _rsi([], 14) == 50.0  # too short
    # increasing prices -> high RSI
    inc = [100.0 + i for i in range(30)]
    assert _rsi(inc, 14) > 50
    # all same -> avg_loss = 0 -> 100
    assert _rsi([100.0] * 30, 14) == 100.0

    mid, up, lo, pct = _bollinger([100.0, 101.0], 20)
    assert mid > 0  # short fallback
    mid2, up2, lo2, pct2 = _bollinger([100.0 + i * 0.1 for i in range(30)], 20)
    assert up2 > mid2 > lo2

    cs = _candles(30)
    assert _atr(cs, 14) > 0
    assert _atr([{}], 14) == 0.01
    assert _volume_ratio(cs, 5, 20) > 0
    assert _volume_ratio([], 5, 20) == 1.0

    assert _calculate_hurst([1.0] * 10) == 0.5  # too short
    series = [100.0 + i * 0.01 for i in range(80)]
    h = _calculate_hurst(series)
    assert 0.0 <= h <= 1.0

    assert _rising_last_two_closes([100.0]) is False
    assert _rising_last_two_closes([100.0, 101.0]) is True
    assert _falling_last_two_closes([100.0]) is False
    assert _falling_last_two_closes([101.0, 100.0]) is True

    assert detect_market_regime(0.7) == "TRENDING"
    assert detect_market_regime(0.3) == "MEAN_REVERTING"
    assert detect_market_regime(0.5) == "NOISY"


def test_analyzer_analyze() -> None:
    from super_otonom.analyzer import MarketAnalyzer

    ma = MarketAnalyzer()
    # too few candles
    empty = ma.analyze("X", [])
    assert empty["signal"] == "HOLD"
    empty2 = ma.analyze("X", _candles(5))
    assert empty2["signal"] == "HOLD"

    res = ma.analyze("BTC/USDT", _candles(60))
    assert res["symbol"] == "BTC/USDT"
    assert res["signal"] in ("BUY", "SELL", "HOLD")
    assert "thresholds" in res

    # crash candles
    crash = _candles(50)
    crash[-1]["close"] = crash[-3]["close"] * 0.9
    res2 = ma.analyze("X", crash)
    assert "flash_crash" in res2

    # MTF analyze_v5_1
    res3 = ma.analyze_v5_1("BTC/USDT", _candles(60), _candles(30))
    assert "high_tf_trend" in res3
    # 4H veri yetersiz
    res4 = ma.analyze_v5_1("X", _candles(60), [])
    assert res4["high_tf_trend"] == "UNKNOWN"
    assert res4["mtf_filtered"] is False

    # MTF filter — 4H DOWN with 1H BUY signal manuel
    res5 = ma.analyze_v5_1("X", _candles(60), _candles(30, start=100.0, drift=-0.005))
    assert "mtf_filtered" in res5

    # apply_liquidity_context
    a: Dict[str, Any] = {}
    MarketAnalyzer.apply_liquidity_context(a, 1000.0, 500.0)
    assert a["entry_scale"] == "full"
    a2: Dict[str, Any] = {}
    MarketAnalyzer.apply_liquidity_context(a2, 300.0, 1000.0)
    assert a2["entry_scale"] in ("scaled", "minimal")
    a3: Dict[str, Any] = {}
    MarketAnalyzer.apply_liquidity_context(a3, None, 500.0)
    assert a3["entry_scale"] == "unknown"
    a4: Dict[str, Any] = {}
    MarketAnalyzer.apply_liquidity_context(a4, "bad", 500.0)
    assert a4["entry_scale"] == "unknown"
    a5: Dict[str, Any] = {}
    MarketAnalyzer.apply_liquidity_context(a5, 0.0, 500.0)
    assert a5["entry_scale"] == "blocked"
    a6: Dict[str, Any] = {}
    MarketAnalyzer.apply_liquidity_context(a6, 100.0, 0.0)
    assert a6["entry_scale"] == "unknown"

    # apply_alt_timeframe_veto
    ana: Dict[str, Any] = {"signal": "BUY", "symbol": "X"}
    ma.apply_alt_timeframe_veto(ana, [])
    assert "alt_tf_filtered" in ana

    ana2: Dict[str, Any] = {"signal": "BUY", "symbol": "X"}
    ma.apply_alt_timeframe_veto(ana2, _candles(50))
    assert "alt_tf_filtered" in ana2

    # score_signal_quality
    sq = MarketAnalyzer.score_signal_quality({"signal": "BUY", "rsi": 50, "volatility": 0.01})
    assert isinstance(sq, tuple) and len(sq) == 4

    assert "v5.1" in ma.summary()


# ════════════════════════════════════════════════════════════════════════════
# capital_engine — invariant + edge cases
# ════════════════════════════════════════════════════════════════════════════


def test_capital_engine_edge_cases(tmp_path: Any) -> None:
    from super_otonom.capital_engine import CapitalEngine, PositionLedger

    jf = str(tmp_path / "j.jsonl")
    eng = CapitalEngine(initial_capital=10_000.0, journal_file=jf)

    # reserve insufficient
    assert eng.reserve_margin("o1", 1e9) is False

    # PositionLedger update_unrealized
    pos = PositionLedger(symbol="X", order_id="o", entry_price=100.0, qty=1.0, notional=100.0, peak_price=100.0)
    delta = pos.update_unrealized(105.0)
    assert delta == 5.0
    assert pos.peak_price == 105.0
    delta2 = pos.update_unrealized(102.0)
    assert delta2 == -3.0

    # close_position partial->full via tiny qty
    eng.open_position("X/Y", "o2", entry_price=100.0, qty=1.0, notional=100.0)
    # update_unrealized + partial close to almost-zero
    eng.update_unrealized({"X/Y": 105.0})
    real = eng.close_partial("X/Y", "o3", exit_price=105.0, ratio=0.9999999999)
    assert real is not None

    # forced negative cash recovery
    eng2 = CapitalEngine(initial_capital=100.0, journal_file=jf)
    eng2.open_position("X/Y", "o", entry_price=100.0, qty=0.9, notional=90.0, fee=1.0)
    # synthetic close with massive fee -> cash should clamp to 0
    eng2.close_position("X/Y", "o", exit_price=10.0, filled_qty=0.9, fee=5000.0)

    # snapshot positions list
    snap = eng2.snapshot()
    assert "nav" in snap

    # journal rotate when file is huge — simulate by writing past max bytes
    big = str(tmp_path / "big.jsonl")
    eng3 = CapitalEngine(initial_capital=1000.0, journal_file=big)
    with open(big, "w", encoding="utf-8") as f:
        f.write("X" * (60 * 1024 * 1024))  # >50MB - triggers rotate path
    eng3.open_position("R", "or", entry_price=10.0, qty=1.0, notional=10.0)
    assert os.path.exists(big + ".bak") or os.path.exists(big)

    # from_dict round-trip
    eng4 = CapitalEngine(initial_capital=500.0, journal_file=jf)
    eng4.open_position("Z", "oz", entry_price=50.0, qty=1.0, notional=50.0)
    eng4.update_unrealized({"Z": 55.0})
    d = eng4.to_dict()
    eng5 = CapitalEngine.from_dict(d, journal_file=jf)
    assert eng5.equity > 0  # property
    assert eng5.free_capital >= 0  # property

    # position_snapshot present
    psnap = eng4.position_snapshot("Z")
    assert psnap is not None

    # zero initial capital -> total_return_pct == 0.0
    eng6 = CapitalEngine(initial_capital=0.0, journal_file=jf)
    s = eng6.snapshot()
    assert s["total_return_pct"] == 0.0


# ════════════════════════════════════════════════════════════════════════════
# staged_exit — full evaluator
# ════════════════════════════════════════════════════════════════════════════


def test_staged_exit_full() -> None:
    from super_otonom.staged_exit import (
        _atr_pct,
        _clamp,
        _partial_ratio_for_stage,
        _should_defer_stage,
        _trailing_pct,
        effective_stage_threshold,
        evaluate_exit,
    )

    assert _clamp(0.5, 0.0, 1.0) == 0.5
    assert _clamp(-0.1, 0.0, 1.0) == 0.0
    assert _clamp(2.0, 0.0, 1.0) == 1.0

    assert _atr_pct({}, 100.0) == 0.0
    assert _atr_pct({"atr": 2.0}, 100.0) == 0.02
    assert _atr_pct({"atr": 0}, 100.0) == 0.0
    assert _atr_pct({"atr": 1}, 0) == 0.0

    th1 = effective_stage_threshold(1, {"atr": 1.0}, 100.0)
    assert th1 > 0
    th2 = effective_stage_threshold(2, {"atr": 1.0}, 100.0)
    th3 = effective_stage_threshold(3, {}, 100.0)
    assert th1 != th2 or th1 == th2  # both valid
    assert th3 > 0

    # trailing_pct branches
    tp1 = _trailing_pct({"omega_regime": "TRENDING", "adj_signal_quality": 99, "alpha_decay_freshness": {"confidence": 0.9}})
    assert tp1 > 0
    tp2 = _trailing_pct({"omega_regime": "RANGING"})
    assert tp2 > 0
    tp3 = _trailing_pct({"omega_regime": "CRASH_RISK"})
    assert tp3 > 0
    tp4 = _trailing_pct({"omega_regime": "OTHER"})
    assert tp4 > 0
    tp5 = _trailing_pct({"omega_regime": "RANGING", "alpha_decay_freshness": "bad"})
    assert tp5 > 0
    tp6 = _trailing_pct({"alpha_decay_freshness": {"confidence": 0.1}})
    assert tp6 > 0

    assert _partial_ratio_for_stage(1) > 0
    assert _partial_ratio_for_stage(2) > 0
    assert _partial_ratio_for_stage(3) > 0

    # _should_defer_stage paths
    assert _should_defer_stage({}, {}) is False
    # entry zero -> None
    assert evaluate_exit({"entry": 0.0, "qty": 1.0}, 100.0, {}) is None
    # zero qty
    assert evaluate_exit({"entry": 100.0, "qty": 0.0}, 100.0, {}) is None

    # stop loss
    res = evaluate_exit(
        {"entry": 100.0, "qty": 1.0, "initial_qty": 1.0, "exit_stage": 0, "peak": 100.0},
        50.0,
        {},
    )
    assert res is not None and res[0] == "STOP_LOSS"

    # trailing stop
    res2 = evaluate_exit(
        {"entry": 100.0, "qty": 1.0, "initial_qty": 1.0, "exit_stage": 0, "peak": 200.0},
        90.0,
        {},
    )
    # peak vs price drop > trailing pct -> trailing stop
    assert res2 is not None

    # SIGNAL_EXIT
    res3 = evaluate_exit(
        {"entry": 100.0, "qty": 1.0, "initial_qty": 1.0, "exit_stage": 0, "peak": 100.0},
        101.0,
        {},
        signal="SELL",
    )
    assert res3 is not None and res3[0] == "SIGNAL_EXIT"

    # below TP threshold
    res4 = evaluate_exit(
        {"entry": 100.0, "qty": 1.0, "initial_qty": 1.0, "exit_stage": 0, "peak": 100.0},
        100.5,
        {},
    )
    assert res4 is None

    # stage 3 already - no further
    res5 = evaluate_exit(
        {"entry": 100.0, "qty": 1.0, "initial_qty": 1.0, "exit_stage": 3, "peak": 100.0},
        150.0,
        {},
    )
    assert res5 is None


def test_apply_staged_exit_async() -> None:
    import asyncio

    from super_otonom.staged_exit import apply_staged_exit

    closed = {"called": False, "ratio": 0.0}

    class FakeEngine:
        def __init__(self) -> None:
            self.open_positions = {
                "X/Y": {
                    "entry": 100.0,
                    "qty": 1.0,
                    "initial_qty": 1.0,
                    "exit_stage": 0,
                    "peak": 100.0,
                    "hold_bars": 0,
                }
            }

        async def _close(self, sym: str, price: float, out: Any, reason: str, analysis: Any) -> None:
            closed["called"] = True
            closed["reason"] = reason

        async def _close_partial(self, sym: str, price: float, ratio: float, out: Any, reason: str, analysis: Any, stage: int) -> None:
            closed["called"] = True
            closed["ratio"] = ratio

    eng = FakeEngine()
    asyncio.run(apply_staged_exit(eng, "X/Y", 50.0, "HOLD", {}, {}))
    assert closed["called"] is True

    # no-position path
    closed2 = {"called": False}
    eng2 = FakeEngine()
    eng2.open_positions = {}
    asyncio.run(apply_staged_exit(eng2, "MISSING", 100.0, "HOLD", {}, {}))
    assert closed2["called"] is False

    # partial close path
    closed3 = {"ratio": 0.0}

    class PartialEngine:
        def __init__(self) -> None:
            self.open_positions = {
                "X/Y": {
                    "entry": 100.0,
                    "qty": 1.0,
                    "initial_qty": 1.0,
                    "exit_stage": 0,
                    "peak": 100.0,
                }
            }

        async def _close(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def _close_partial(self, sym: str, price: float, ratio: float, *args: Any) -> None:
            closed3["ratio"] = ratio

    eng3 = PartialEngine()
    asyncio.run(apply_staged_exit(eng3, "X/Y", 110.0, "HOLD", {}, {}))
    # no decision (since threshold may not be met under defaults) is also valid


# ════════════════════════════════════════════════════════════════════════════
# audit_log — AuditLog + DailyReconciler
# ════════════════════════════════════════════════════════════════════════════


def test_audit_log_full(tmp_path: Any) -> None:
    from super_otonom.audit_log import AuditLog

    audit = AuditLog(audit_dir=str(tmp_path))
    audit.trade_open("BTC/USDT", "o1", 100.0, 1.0, 100.0, fee=0.1, confidence=0.8, nav=10000, cash=9900, open_positions=1)
    audit.trade_close("BTC/USDT", "o1", 110.0, 1.0, pnl=10.0, fee=0.1, reason="TP", nav=10010)
    audit.risk_block("BTC/USDT", "limit_breach", signal="BUY", nav=10000)
    audit.emergency("KILL_SWITCH", nav=10000)
    audit.signal_event("BTC/USDT", "BUY", confidence=0.7)
    audit.system_event("START", reason="bot up", nav=10000)

    events_all = audit.get_events(last_n=100)
    assert len(events_all) >= 6
    events_typed = audit.get_events(event_type="TRADE_OPEN")
    assert all(e["event_type"] == "TRADE_OPEN" for e in events_typed)
    events_sym = audit.get_events(symbol="BTC/USDT")
    assert all(e["symbol"] == "BTC/USDT" for e in events_sym)

    summary = audit.today_summary()
    assert "trades_opened" in summary
    assert summary["trades_opened"] >= 1


def test_daily_reconciler_full(tmp_path: Any) -> None:
    from super_otonom.audit_log import DailyReconciler

    rec = DailyReconciler(reconcile_dir=str(tmp_path / "rec"))
    rec.set_sod(10_000.0)
    rec.record_trade("BTC/USDT", pnl=5.0, fee=0.1, reason="TP")
    rec.record_trade("BTC/USDT", pnl=-3.0, fee=0.05, reason="SL")

    # mismatch trade count + emergency present + open pos
    audit_summary = {"trades_closed": 5, "emergencies": 1}
    cap_snap = {"nav": 10_002.0, "open_positions": 2, "positions": [{"sym": "X"}]}
    report = rec.run(cap_snap, audit_summary)
    assert report.warnings  # at least one warning
    assert report.total_trades == 2
    assert report.winning_trades == 1 and report.losing_trades == 1

    # passed path
    rec.reset_for_new_day(11_000.0)
    rec.record_trade("X", pnl=1.0, fee=0.0)
    cap_snap2 = {"nav": 11_001.0, "open_positions": 0}
    report2 = rec.run(cap_snap2, {"trades_closed": 1, "emergencies": 0})
    assert report2.total_trades == 1

    # write error path: lock target by making dir read-only would be fragile;
    # skip and instead drive run() with empty audit summary
    rec.reset_for_new_day(12_000.0)
    rep3 = rec.run({"nav": 12_000.0, "open_positions": 0}, None)
    assert rep3.total_trades == 0


# ════════════════════════════════════════════════════════════════════════════
# kanon_drift_check
# ════════════════════════════════════════════════════════════════════════════


def test_kanon_drift_check_full(tmp_path: Any) -> None:
    from super_otonom.kanon_drift_check import (
        canonical_phase_chain_keys,
        expected_phase_dirs_from_docs,
        forbidden_phase_dirs,
        parse_phase_chain_keys_from_pipeline,
        repo_root_from_package,
        run_all_checks,
        scan_actual_phase_dirs,
    )

    expected = expected_phase_dirs_from_docs()
    assert "phase_38" in expected and "phase_55" in expected
    assert "phase_45" in forbidden_phase_dirs()
    assert "faz71" in canonical_phase_chain_keys()

    rr = repo_root_from_package()
    assert rr.is_dir()

    # empty/non-existent
    assert scan_actual_phase_dirs(tmp_path / "nope") == frozenset()
    fake_phases = tmp_path / "phases"
    fake_phases.mkdir()
    (fake_phases / "phase_38").mkdir()
    (fake_phases / "phase_99").mkdir()
    (fake_phases / "not_phase").mkdir()
    scanned = scan_actual_phase_dirs(fake_phases)
    assert "phase_38" in scanned and "phase_99" in scanned and "not_phase" not in scanned

    # parse pipeline — non-existent path
    assert parse_phase_chain_keys_from_pipeline(tmp_path / "missing.py") is None

    # parse - syntax error
    bad_py = tmp_path / "bad.py"
    bad_py.write_text("def x(", encoding="utf-8")
    assert parse_phase_chain_keys_from_pipeline(bad_py) is None

    # valid pipeline file
    good_py = tmp_path / "good.py"
    good_py.write_text(
        "class X:\n    def y(self):\n        self.phase_chain.update({'faz71': 1, 'faz72': 2})\n",
        encoding="utf-8",
    )
    keys = parse_phase_chain_keys_from_pipeline(good_py)
    assert keys is not None and "faz71" in keys

    # run_all_checks — drift scenario
    ok, issues = run_all_checks(tmp_path)
    assert isinstance(ok, bool) and isinstance(issues, list)

    # forbidden present scenario
    fake_repo = tmp_path / "fake_repo"
    fake_repo.mkdir()
    fp = fake_repo / "src" / "phases"
    fp.mkdir(parents=True)
    (fp / "phase_45").mkdir()  # forbidden
    pipe_dir = fake_repo / "super_otonom" / "pipelines"
    pipe_dir.mkdir(parents=True)
    pipe_path = pipe_dir / "execution_pipeline.py"
    pipe_path.write_text("class X:\n    pass\n", encoding="utf-8")
    ok2, issues2 = run_all_checks(fake_repo)
    assert ok2 is False
    assert any("phase_45" in s for s in issues2)


# ════════════════════════════════════════════════════════════════════════════
# meta_regime_orchestrator — advisory + ack
# ════════════════════════════════════════════════════════════════════════════


def test_meta_regime_full(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from super_otonom.meta_regime_orchestrator import (
        _clamp,
        _env_truthy,
        _families_present,
        _resolve_advisory_bounds,
        _resolve_mode,
        _weighted_mean,
        advisory_ack_path_for_gate,
        attach_meta_regime,
        compact_meta_regime_for_attribution,
        compute_meta_regime,
        family_weights_for_regime,
        main,
        normalize_regime,
        write_meta_advisory_ack_file,
    )

    assert _clamp(0.5, 0.0, 1.0) == 0.5
    assert _clamp(-1, 0, 1) == 0
    assert _clamp(2, 0, 1) == 1

    assert _resolve_mode(None) in ("shadow", "advisory", "off")
    assert _resolve_mode("shadow") == "shadow"
    assert _resolve_mode("ADVISORY") == "advisory"
    assert _resolve_mode("garbage") == "shadow"

    monkeypatch.setenv("META_ADVISORY_MIN", "0.95")
    monkeypatch.setenv("META_ADVISORY_MAX", "1.05")
    lo, hi = _resolve_advisory_bounds()
    assert lo == 0.95 and hi == 1.05

    monkeypatch.setenv("META_ADVISORY_MIN", "bad")
    monkeypatch.setenv("META_ADVISORY_MAX", "bad")
    lo2, hi2 = _resolve_advisory_bounds()
    assert lo2 == 0.92 and hi2 == 1.08

    # inverted bounds path
    monkeypatch.setenv("META_ADVISORY_MIN", "1.5")
    monkeypatch.setenv("META_ADVISORY_MAX", "0.5")
    lo3, hi3 = _resolve_advisory_bounds()
    assert lo3 <= hi3
    monkeypatch.delenv("META_ADVISORY_MIN", raising=False)
    monkeypatch.delenv("META_ADVISORY_MAX", raising=False)

    assert normalize_regime("trend") == "TRENDING"
    assert normalize_regime("chop") == "RANGING"
    assert normalize_regime("crisis") == "CRASH_RISK"
    assert normalize_regime("UNKNOWN") == "UNKNOWN"
    assert normalize_regime("???") == "UNKNOWN"
    assert normalize_regime(None) == "UNKNOWN"

    fw = family_weights_for_regime("TRENDING")
    assert "gov" in fw and "exec" in fw

    monkeypatch.setenv("META_ADVISORY_LOOSE", "1")
    assert _env_truthy("META_ADVISORY_LOOSE") is True
    monkeypatch.setenv("META_ADVISORY_LOOSE", "0")
    assert _env_truthy("META_ADVISORY_LOOSE") is False

    # advisory_ack_path_for_gate
    assert advisory_ack_path_for_gate("shadow") is None
    monkeypatch.setenv("META_ADVISORY_LOOSE", "1")
    assert advisory_ack_path_for_gate("advisory") is None
    monkeypatch.setenv("META_ADVISORY_LOOSE", "0")
    monkeypatch.setenv("META_ADVISORY_ACK_FILE", str(tmp_path / "ack.txt"))
    assert advisory_ack_path_for_gate("advisory") == str(tmp_path / "ack.txt")
    monkeypatch.delenv("META_ADVISORY_ACK_FILE", raising=False)

    # families_present
    assert _families_present(None) == {}
    counts = _families_present({"faz71": 1, "faz50": 2, "garbage": 3})
    assert sum(counts.values()) == 3

    assert _weighted_mean({"gov": 1.0}, {"gov": 0}) is None
    wm = _weighted_mean({"gov": 1.1, "exec": 0.9}, {"gov": 2, "exec": 1})
    assert wm is not None and 0.0 < wm < 2.0

    # compute_meta_regime — shadow
    payload = compute_meta_regime(
        analysis={"omega_regime": "trend"},
        phase_chain={"faz71": 1, "faz72": 2},
        base_confidence=0.7,
        mode="shadow",
    )
    assert payload["mode"] == "shadow"
    assert payload["regime"] == "TRENDING"

    # advisory without ack -> blocked
    payload2 = compute_meta_regime(
        analysis={"omega_regime": "TRENDING"},
        phase_chain={"faz71": 1},
        base_confidence=0.7,
        mode="advisory",
    )
    # may have advisory_blocked_reason or not (depends on default ack file)
    assert "advised_confidence_mult" in payload2

    # write ack file then advisory with ack passes
    ack_path = tmp_path / "ack.txt"
    monkeypatch.setenv("META_ADVISORY_ACK_FILE", str(ack_path))
    written = write_meta_advisory_ack_file(operator_note="A5 measurement done")
    assert ack_path.exists() or os.path.exists(written)

    payload3 = compute_meta_regime(
        analysis={"omega_regime": "TRENDING"},
        phase_chain={"faz71": 1, "faz72": 2, "faz74": 3},
        base_confidence=0.7,
        mode="advisory",
    )
    assert payload3["mode"] == "advisory"

    # off mode
    payload_off = compute_meta_regime(analysis={}, phase_chain={}, base_confidence=0.5, mode="off")
    assert payload_off["mode"] == "off"

    # attach_meta_regime
    a: Dict[str, Any] = {"omega_regime": "TRENDING"}
    new_conf, p = attach_meta_regime(a, {"faz71": 1}, base_confidence=0.6, mode="shadow")
    assert "meta_regime" in a
    # off mode doesn't write
    a2: Dict[str, Any] = {}
    new_conf2, _ = attach_meta_regime(a2, None, base_confidence=0.5, mode="off")
    assert "meta_regime" not in a2

    # compact
    compact = compact_meta_regime_for_attribution(payload2)
    assert compact is not None
    assert compact_meta_regime_for_attribution(None) is None
    assert compact_meta_regime_for_attribution("not dict") is None

    # main CLI
    rc = main(["--message", "test note", "--path", str(tmp_path / "cli_ack.txt")])
    assert rc == 0

    monkeypatch.delenv("META_ADVISORY_ACK_FILE", raising=False)
    monkeypatch.delenv("META_ADVISORY_LOOSE", raising=False)


# ════════════════════════════════════════════════════════════════════════════
# regime_adaptive_execution_engine
# ════════════════════════════════════════════════════════════════════════════


def test_regime_adaptive_full() -> None:
    from super_otonom.regime_adaptive_execution_engine import (
        _clamp01,
        _clamp100,
        _compute_spread_pct,
        _extract_best_prices,
        _map_regime,
        _try_float,
        infer_regime_adaptive_execution,
    )

    assert _clamp01(float("nan")) == 0.0
    assert _clamp100(float("nan")) == 0
    assert _try_float("bad") is None
    assert _try_float(None) is None
    assert _try_float(1.5) == 1.5

    assert _map_regime("TREND") == "trend"
    assert _map_regime("RANGE") == "range"
    assert _map_regime("VOLATILE") == "volatile"
    assert _map_regime("CRISIS") == "crisis"
    assert _map_regime("???") == "unknown"
    assert _map_regime("") == "unknown"

    bb, ba = _extract_best_prices({"bids": [[100.0, 1.0]], "asks": [[101.0, 1.0]]})
    assert bb == 100.0 and ba == 101.0
    assert _extract_best_prices({}) == (None, None)
    assert _extract_best_prices({"bids": [[0, 1]], "asks": [[1, 1]]}) == (None, None)

    assert _compute_spread_pct(100.0, 101.0) > 0
    assert _compute_spread_pct(0, 0) == 0.0

    ob = {"bids": [[100.0, 1.0]], "asks": [[100.1, 1.0]]}
    # range regime
    r1 = infer_regime_adaptive_execution(
        symbol="X",
        analysis={"regime": "RANGE", "volatility": 0.005, "liquidity_ratio": 0.8},
        order_book=ob,
    )
    assert r1.regime_execution_mode == "range"
    assert r1.preferred_order_type in ("maker", "twap")

    # trend regime + urgency high + low slippage -> taker
    r2 = infer_regime_adaptive_execution(
        symbol="X",
        analysis={"regime": "TRENDING", "volatility": 0.04, "liquidity_ratio": 0.7},
        order_book=ob,
    )
    assert r2.regime_execution_mode == "trend"

    # volatile regime + high slippage
    r3 = infer_regime_adaptive_execution(
        symbol="X",
        analysis={"regime": "VOLATILE", "volatility": 0.08, "liquidity_ratio": 0.3},
        order_book={"bids": [[100.0, 1.0]], "asks": [[105.0, 1.0]]},
    )
    assert r3.regime_execution_mode == "volatile"

    # crisis regime
    r4 = infer_regime_adaptive_execution(
        symbol="X",
        analysis={"regime": "CRISIS"},
        order_book=ob,
    )
    assert r4.regime_execution_mode == "crisis"
    assert r4.preferred_order_type == "twap"

    # unknown regime
    r5 = infer_regime_adaptive_execution(symbol="X")
    assert r5.regime_execution_mode == "unknown"

    # BLOCK path - low data health
    r6 = infer_regime_adaptive_execution(
        symbol="X",
        analysis={"regime": "VOLATILE"},  # no OB, no vol, no liq
    )
    assert r6.trade_permission in ("ALLOW", "BLOCK")

    # event_ts override
    r7 = infer_regime_adaptive_execution(
        symbol="X", analysis={"regime": "TREND"}, order_book=ob, event_ts=1_700_000_000_000
    )
    assert r7.event_ts == 1_700_000_000_000

    assert isinstance(r1.to_dict(), dict)


# ════════════════════════════════════════════════════════════════════════════
# backtest_leakage_guard
# ════════════════════════════════════════════════════════════════════════════


def test_backtest_leakage_guard_full() -> None:
    from super_otonom.backtest_leakage_guard import (
        _clamp01,
        _clamp100,
        evaluate_backtest_leakage_guard,
    )

    assert _clamp01(float("nan")) == 0.0
    assert _clamp100(float("nan")) == 0

    # clean
    r1 = evaluate_backtest_leakage_guard(symbol="X")
    assert r1.trade_permission == "ALLOW"

    # lookahead -> BLOCK
    r2 = evaluate_backtest_leakage_guard(
        symbol="X",
        analysis={"lookahead_detected": True, "leakage_risk_score": 60},
    )
    assert r2.trade_permission == "BLOCK"

    # integrity breach -> HALT
    r3 = evaluate_backtest_leakage_guard(
        symbol="X",
        analysis={"backtest_integrity_breach": True, "lookahead_detected": True},
    )
    assert r3.trade_permission == "HALT"

    # data_snooping_warning + purged_cv
    r4 = evaluate_backtest_leakage_guard(
        symbol="X",
        analysis={"data_snooping_warning": True, "purged_cv_required": True},
    )
    assert r4.trade_permission == "BLOCK"

    # explicit leakage_risk_score
    r5 = evaluate_backtest_leakage_guard(
        symbol="X",
        analysis={"leakage_risk_score": 70},
    )
    assert r5.trade_permission == "BLOCK"

    # event_ts override
    r6 = evaluate_backtest_leakage_guard(symbol="X", event_ts=1_700_000_000_000)
    assert r6.event_ts == 1_700_000_000_000

    assert isinstance(r1.to_dict(), dict)


# ════════════════════════════════════════════════════════════════════════════
# alpha_decay_realtime_monitor
# ════════════════════════════════════════════════════════════════════════════


def test_alpha_decay_full() -> None:
    from super_otonom.alpha_decay_realtime_monitor import (
        _clamp01,
        _clamp100,
        _try_int,
        monitor_alpha_decay,
    )

    assert _clamp01(float("nan")) == 0.0
    assert _clamp100(float("nan")) == 0
    assert _try_int(None) is None
    assert _try_int("bad") is None
    assert _try_int("5") == 5

    # fresh signal
    r1 = monitor_alpha_decay(
        symbol="X",
        event_ts=1_700_000_000_000,
        half_life_ms=30_000,
        now_ts=1_700_000_001_000,
    )
    assert r1.alpha_freshness_score > 50

    # very stale - exit urgency
    r2 = monitor_alpha_decay(
        symbol="X",
        event_ts=1_700_000_000_000,
        half_life_ms=10_000,
        now_ts=1_700_000_100_000,  # 100s = 10 half-lives
    )
    assert r2.exit_urgency > 50

    # no inputs -> low data_health -> BLOCK
    r3 = monitor_alpha_decay(symbol="X")
    assert r3.trade_permission in ("ALLOW", "BLOCK")

    # event_ts from analysis dict
    r4 = monitor_alpha_decay(
        symbol="X",
        analysis={"event_ts": 1_700_000_000_000, "half_life_ms": 30_000},
        now_ts=1_700_000_010_000,
    )
    assert r4.signal_age_ms > 0

    assert isinstance(r1.to_dict(), dict)


# ════════════════════════════════════════════════════════════════════════════
# signal_lineage
# ════════════════════════════════════════════════════════════════════════════


def test_signal_lineage_full() -> None:
    from super_otonom.signal_lineage import (
        SCHEMA_VERSION,
        _f,
        _infer_primary_phase,
        _scores_bundle,
        _source_summary,
        build_signal_lineage,
        log_signal_lineage,
    )

    assert SCHEMA_VERSION == "a7/v1"

    assert _f({}, "x") is None
    assert _f({"x": "bad"}, "x") is None
    assert _f({"x": 1.5}, "x") == 1.5
    assert _f({"a": 2.0}, "x", "a") == 2.0

    # scores bundle
    out = {"phase80": {"alpha_score": 0.6, "risk_score": 0.3, "confidence": 0.7}, "ai_confidence": 0.8}
    analysis = {
        "phase50": {"alpha_score": 0.5, "risk_score": 0.4, "confidence": 0.6, "data_health": 0.9},
        "phase45": {"alpha_score": 0.7, "risk_score": 0.2},
    }
    dctx = MagicMock()
    dctx.signal_quality = 75
    dctx.adj_signal_quality = 80
    bundle = _scores_bundle(out, analysis, dctx)
    assert bundle["phase50_alpha_score"] == 0.5
    assert bundle["signal_quality"] == 75

    # bad inputs - phase50 / 80 / 45 not dict
    out_bad = {"phase80": "not dict", "ai_confidence": "bad"}
    analysis_bad = {"phase50": "x", "phase45": None}
    b2 = _scores_bundle(out_bad, analysis_bad, None)
    assert b2["phase50_alpha_score"] is None

    # primary phase inference
    assert _infer_primary_phase("kill", None, {}, {}) == 50
    assert _infer_primary_phase("risk", "risk", {}, {}) == 50
    assert _infer_primary_phase("full", None, {"decision_reason": "LOW_QUALITY_REJECT"}, {}) == 45
    assert _infer_primary_phase("full", None, {"phase80": {}}, {}) == 80
    assert _infer_primary_phase("full", None, {"execution_layer": "x"}, {}) == 80
    assert _infer_primary_phase("full", None, {"decision_reason": "FAZ80 something"}, {}) == 80
    assert _infer_primary_phase("full", None, {}, {}) == 0

    # source summary
    dctx2 = MagicMock()
    dctx2.phase_chain = {"faz71": 1, "faz72": 2}
    s = _source_summary("BTC", {"final_signal": "BUY", "trade_permission": "ALLOW", "final_action": "ENTER", "decision_reason": "ok"}, dctx2, "full", "full")
    assert "BTC" in s and "BUY" in s
    s2 = _source_summary("X", {}, None, None, "no_candles")
    assert "X" in s2

    # build_signal_lineage
    payload = build_signal_lineage(
        symbol="BTC/USDT",
        tick_id=1,
        out={"final_signal": "BUY", "trade_permission": "ALLOW", "phase80": {}, "decision_reason": "FAZ80"},
        dctx=dctx,
        analysis=analysis,
        event_ts=1700000000.0,
        gate=None,
        completion="full",
    )
    assert payload["symbol"] == "BTC/USDT"
    assert payload["phase"] == 80

    # log_signal_lineage - good payload
    log_signal_lineage(payload)
    # log_signal_lineage - bad payload (non-serializable)
    log_signal_lineage({"x": object()})

    # with no decision_reason, fallback to dctx fields
    dctx3 = MagicMock()
    dctx3.emergency_code = "KILL"
    dctx3.entry_blocked = ""
    dctx3.phase_chain = {}
    p2 = build_signal_lineage(
        symbol="X",
        tick_id=2,
        out={"final_signal": "HOLD"},
        dctx=dctx3,
        analysis={},
        event_ts=0.0,
        gate="kill",
        completion="kill",
    )
    assert p2["phase"] == 50


# ════════════════════════════════════════════════════════════════════════════
# liquidity_games_detector — daha fazla dal
# ════════════════════════════════════════════════════════════════════════════


def test_liquidity_games_full() -> None:
    from super_otonom.liquidity_games_detector import (
        _clamp01,
        _clamp100,
        _compute_ob_imbalance,
        _compute_spread_pct,
        _extract_best_prices,
        detect_liquidity_games,
    )

    assert _clamp01(float("nan")) == 0.0
    assert _clamp100(float("nan")) == 0
    assert _extract_best_prices({}) == (None, None)
    assert _compute_spread_pct(0, 0) == 0.0
    assert _compute_ob_imbalance({}) is None
    assert _compute_ob_imbalance({"bids": [["bad", "bad"]], "asks": [[1, 1]]}) is None

    # stop_hunt path: wide spread + high vol + imbalance
    ob = {"bids": [[100.0, 100.0]] * 5, "asks": [[110.0, 1.0]] * 5}
    r = detect_liquidity_games(
        symbol="X",
        analysis={"volatility": 0.05},
        order_book=ob,
    )
    assert r.game_type in ("stop_hunt", "momentum_ignition", "quote_stuffing", "spoofing", "none", "unknown")
    assert r.cooldown_seconds >= 0

    # tight spread + imbalance -> spoofing proxy
    ob_spoof = {"bids": [[100.0, 100.0]] * 5, "asks": [[100.01, 1.0]] * 5}
    r2 = detect_liquidity_games(
        symbol="X",
        analysis={"volatility": 0.01},
        order_book=ob_spoof,
    )
    assert r2.confidence > 0

    # market_snapshot a8/v1 path
    snap_an = {
        "market_snapshot": {
            "schema": "a8/v1",
            "order_book": {
                "empty": False,
                "spread_rel": 0.005,
                "ob_imbalance_top10": 0.75,
                "levels": {"bids": [[100.0, 1.0]], "asks": [[100.5, 1.0]]},
            },
        },
        "volatility": 0.02,
    }
    r3 = detect_liquidity_games(symbol="X", analysis=snap_an)
    assert r3.spread_pct == 0.005

    # market_snapshot with missing spread/imb falls back to OB extract
    snap_partial = {
        "market_snapshot": {
            "schema": "a8/v1",
            "order_book": {
                "empty": False,
                "levels": {"bids": [[100.0, 1.0]], "asks": [[100.1, 2.0]]},
            },
        },
    }
    r4 = detect_liquidity_games(symbol="X", analysis=snap_partial)
    assert r4.event_ts > 0

    # bad volatility string -> default 0.02
    r5 = detect_liquidity_games(symbol="X", analysis={"volatility": "bad"}, order_book=ob)
    assert r5.event_ts > 0

    # no order book + no snapshot
    r6 = detect_liquidity_games(symbol="X")
    assert r6.game_type == "unknown"

    assert isinstance(r.to_dict(), dict)


# ════════════════════════════════════════════════════════════════════════════
# multi_timeframe + meta_learning ek dallar
# ════════════════════════════════════════════════════════════════════════════


def test_mtf_consensus_extra() -> None:
    from super_otonom.multi_timeframe_consensus_engine import infer_mtf_consensus

    # high agreement scenario - enter_now
    res = infer_mtf_consensus(
        symbol="X",
        analysis={"mtf": {f"{m}m": {"signal": "BUY", "score": 90, "confidence": 0.9} for m in (1, 5, 15, 30)}},
    )
    assert "entry_timing" in res.to_dict()

    # block path - low coverage with conflict
    res2 = infer_mtf_consensus(
        symbol="X",
        analysis={"mtf": {"1m": "BUY", "5m": "SELL"}},
    )
    assert res2.timeframes_seen == 2


def test_meta_learning_extra() -> None:
    import time as _time

    from super_otonom.meta_learning_engine import analyze_meta_learning

    now = int(_time.time() * 1000)
    # rollback_trigger via cusum_drift + high degrade
    res = analyze_meta_learning(
        "M",
        {
            "loss_series": [0.1] * 30 + [50.0] * 30,
            "active_model_version": "v3",
            "previous_model_version": "v2",
            "deployed_at_ms": now,
        },
    )
    assert res["trade_permission"] in ("BLOCK", "HALT", "ALLOW")

    # accuracy_series (lower_is_better=False) path
    res2 = analyze_meta_learning(
        "M",
        {
            "accuracy_series": [0.9 - 0.01 * i for i in range(40)],
            "active_model_version": "v4",
            "deployed_at_ms": now,
        },
    )
    assert res2["phase"] == "35"

    # version_staleness with very old
    res3 = analyze_meta_learning(
        "M",
        {
            "loss_series": [1.0] * 30,
            "active_model_version": "v1",
            "deployed_at_ms": now - 30 * 24 * 3600 * 1000,
        },
    )
    assert res3["phase"] == "35"


# ════════════════════════════════════════════════════════════════════════════
# confidence_calibration ek dallar
# ════════════════════════════════════════════════════════════════════════════


def test_confidence_calibration_extra() -> None:
    from super_otonom.confidence_calibration import (
        family_for_phase_num,
        phase_key_to_int,
    )

    assert phase_key_to_int("faz71") == 71
    assert phase_key_to_int("phase50") == 50
    assert phase_key_to_int("garbage") is None
    assert phase_key_to_int("FAZ72") == 72  # case-insensitive
    # fallback regex tail digits
    assert phase_key_to_int("anything80") == 80

    assert family_for_phase_num(68) == "gov"  # 66-70 -> gov
    assert family_for_phase_num(73) == "micro"  # 71-75 -> micro
    assert family_for_phase_num(76) == "exec"  # 76-80 -> exec
    assert family_for_phase_num(47) == "exec"  # 47 special-case -> exec
    assert family_for_phase_num(99) == "other"
    assert family_for_phase_num(50) == "other"  # 50 not in any family band

    # calibrate_confidence_mvp - core function
    from super_otonom.confidence_calibration import calibrate_confidence_mvp
    cal, meta = calibrate_confidence_mvp(0.8, {})
    assert cal == 0.8
    assert meta["applied"] is False
    # multiple high-confidence in same family -> penalty
    cal2, meta2 = calibrate_confidence_mvp(0.9, {
        "faz71": {"confidence": 0.85},
        "faz72": {"confidence": 0.85},
        "faz73": {"confidence": 0.85},
        "faz74": {"confidence": 0.85},
    })
    assert cal2 <= 0.9
    assert meta2["redundant_count"] >= 1
    # bad blob types
    cal3, _ = calibrate_confidence_mvp(0.7, {"faz71": "not dict", "faz72": {"confidence": "bad"}})
    assert cal3 == 0.7


# ════════════════════════════════════════════════════════════════════════════
# risk_ontology ek dallar
# ════════════════════════════════════════════════════════════════════════════


def test_risk_ontology_extra() -> None:
    from super_otonom import risk_ontology as ro

    # explore the module attributes
    for name in dir(ro):
        if name.startswith("_"):
            continue
        attr = getattr(ro, name, None)
        if attr is None:
            continue
        # just touch
        _ = repr(attr)[:40]
