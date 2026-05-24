"""Gerçek kapsam artışı — küçük, doğrudan import / main() yolları (omit yok)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest


def _strip_event_ts_keys(obj: Any) -> Any:
    """Dict/list/tuple içinde tüm seviyelerde `event_ts` anahtarını çıkar (flake önleme)."""
    if isinstance(obj, dict):
        return {k: _strip_event_ts_keys(v) for k, v in obj.items() if k != "event_ts"}
    if isinstance(obj, list):
        return [_strip_event_ts_keys(x) for x in obj]
    if isinstance(obj, tuple):
        return tuple(_strip_event_ts_keys(x) for x in obj)
    return obj


def _assert_dicts_equal_ignore_event_ts(a: dict, b: dict) -> None:
    assert _strip_event_ts_keys(a) == _strip_event_ts_keys(b)


def test_hard_safety_contract_namespace() -> None:
    import super_otonom.hard_safety_contract as h

    assert h.HARD_SAFETY_CONFIG_NAMESPACE == "RISK"
    assert "MAX_LEVERAGE" in h.HARD_SAFETY_ENV_KEYS


def test_release_gate_main_invokes_pytest(monkeypatch: pytest.MonkeyPatch) -> None:
    from super_otonom import release_gate as rg

    calls: list[list[str]] = []

    def fake_call(cmd: list[str]) -> int:
        calls.append(cmd)
        return 0

    monkeypatch.setattr(rg.subprocess, "call", fake_call)
    rc = rg.main([])
    assert rc == 0
    assert calls
    assert "pytest" in calls[0]
    assert "-m" in calls[0]
    assert "release_gate" in calls[0]


def test_deploy_env_check_main_paper_shadow_skip_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    import super_otonom.config as cfg
    from super_otonom import deploy_env_check as dec

    monkeypatch.setenv("META_REGIME_MODE", "shadow")
    monkeypatch.setenv("DEPLOY_ENV_SKIP_RISK_SUMMARY", "1")
    monkeypatch.setitem(cfg.GENERAL, "paper_mode", True)
    monkeypatch.setitem(cfg.GENERAL, "live_confirm", "")
    monkeypatch.setitem(cfg.GENERAL, "default_exchange", "binance")

    stamp = tmp_path / "deploy_env_check_last_ok.json"

    def _fake_stamp() -> object:
        stamp.write_text("{}", encoding="utf-8")
        return stamp

    monkeypatch.setattr("super_otonom.deploy_env_stamp.write_last_ok", _fake_stamp)

    assert dec.main() == 0


def test_confidence_calibration_phase_key_edges() -> None:
    from super_otonom.confidence_calibration import phase_key_to_int

    assert phase_key_to_int("PHASE71") == 71
    assert phase_key_to_int("foo_80") == 80
    assert phase_key_to_int("nope") is None


def test_tick_timing_span_records_ms(monkeypatch: pytest.MonkeyPatch) -> None:
    from super_otonom import tick_timing as tt

    monkeypatch.setenv("SUPER_OTONOM_TICK_TIMING", "1")
    tt.reset_tick_timing_cache_for_tests()
    assert tt.is_tick_timing_enabled() is True

    analysis: dict = {}
    with tt.span(analysis, "unit"):
        pass
    assert "_tick_phase_ms" in analysis
    assert "unit" in analysis["_tick_phase_ms"]
    assert analysis["_tick_phase_ms"]["unit"] >= 0.0

    tt.reset_tick_timing_cache_for_tests()


def test_benchmark_katman_a_make_candles() -> None:
    from super_otonom.benchmark_katman_a import _make_candles

    c = _make_candles(5, base=50.0)
    assert len(c) == 5
    assert "close" in c[0]


def test_market_impact_model_estimate() -> None:
    from super_otonom.market_impact import MarketImpactModel

    m = MarketImpactModel()
    e = m.estimate(1000.0, 1_000_000.0, 0.02, symbol="BTC/USDT")
    assert e.total_pct > 0
    assert e.adjusted_price("buy", 100.0) > 100.0
    assert e.cost_usdt(1.0, 100.0) >= 0


def test_fake_order_book_scenario_smoke() -> None:
    from super_otonom.fake_order_book_scenarios import make_scenario

    ob, _analysis = make_scenario(scenario="normal")
    assert "bids" in ob and "asks" in ob


def test_concentration_risk_check_ok() -> None:
    from super_otonom.concentration_risk import ConcentrationRiskManager

    m = ConcentrationRiskManager(max_total_pct=0.99, max_single_pct=0.99, max_sector_pct=0.99)
    ok, reason = m.check_concentration("BTC/USDT", 100.0, 10_000.0, {})
    assert ok is True
    assert reason == ""
    assert m.sector_breakdown({}, 10_000.0) == {}


def test_deploy_env_stamp_write_read(tmp_path) -> None:
    from super_otonom import deploy_env_stamp as des

    path = des.write_last_ok(tmp_path)
    assert path.is_file()
    data = des.read_stamp(tmp_path)
    assert data is not None
    assert data.get("schema_version") == des.SCHEMA_VERSION


def test_self_feedback_guard_audit_intratick_paths() -> None:
    from super_otonom.self_feedback_guard import (
        A11_SCHEMA,
        FROZEN_CORE_KEYS,
        attach_tick_frozen_mark,
        audit_intratick_frozen_core,
    )

    assert audit_intratick_frozen_core(None) is None
    assert audit_intratick_frozen_core("not-a-dict") is None

    bare = {"signal": 1}
    assert audit_intratick_frozen_core(bare) is None

    wrong_meta = {"_a11": "bad", "signal": 1}
    assert audit_intratick_frozen_core(wrong_meta) is None

    wrong_schema = {"_a11": {"schema": "other", "core_snapshot": {}}, "signal": 1}
    assert audit_intratick_frozen_core(wrong_schema) is None

    bad_snap = {"_a11": {"schema": A11_SCHEMA, "core_snapshot": "nope"}, "signal": 1}
    assert audit_intratick_frozen_core(bad_snap) is None

    ok_core = {k: f"v-{k}" for k in FROZEN_CORE_KEYS}
    attach_tick_frozen_mark(ok_core, tick_id=7, symbol="BTC/USDT")
    assert audit_intratick_frozen_core(ok_core) is None

    mutated = dict(ok_core)
    attach_tick_frozen_mark(mutated, tick_id=8, symbol="BTC/USDT")
    mutated["signal"] = "changed"
    msg = audit_intratick_frozen_core(mutated)
    assert msg is not None
    assert "frozen core mutated" in msg


def test_tick_timing_phase_count_and_span_skips_non_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    from collections import UserDict

    from super_otonom import tick_timing as tt

    monkeypatch.setenv("SUPER_OTONOM_TICK_TIMING", "1")
    tt.reset_tick_timing_cache_for_tests()

    ud: UserDict[str, object] = UserDict()
    with tt.span(ud, "ph"):
        pass
    assert "_tick_phase_ms" not in ud

    class _Chain:
        phase_chain = {"a": 1, "b": 2}

    class _BadChain:
        phase_chain = "nope"

    assert tt.phase_count_from_chain(_Chain()) == 2
    assert tt.phase_count_from_chain(_BadChain()) == 0
    assert tt.phase_count_from_chain(object()) == 0

    tt.reset_tick_timing_cache_for_tests()


def test_smart_order_router_paths() -> None:
    import super_otonom.smart_order_router as sor
    from super_otonom.smart_order_router import SmartOrderRouteResult, compute_smart_order_route

    assert sor._get(None, "x", 1) == 1
    assert sor._get({"a": 2}, "a") == 2

    class _Attr:
        b = 3

    assert sor._get(_Attr(), "b") == 3
    assert sor._get(_Attr(), "missing", 0) == 0

    assert sor._lowest_latency_venue({}) == ("", "no_latency")
    assert sor._lowest_latency_venue({"v1": "notdict"}) == ("", "no_latency")
    assert sor._lowest_latency_venue({"v1": {"latency_ms": "bad"}}) == ("", "no_latency")
    assert sor._lowest_latency_venue({"v1": {"latency_ms": 0}}) == ("", "no_latency")
    k, rsn = sor._lowest_latency_venue({"slow": {"latency_ms": 50}, "fast": {"latency_ms": 10}})
    assert k == "fast"
    assert rsn == "crisis_lowest_latency"

    p74 = type("P74", (), {"leader_venue": "binance", "route_preference": "latency"})()
    p80_ok = type("P80", (), {"final_action": "ENTER", "trade_permission": "ALLOW"})()

    r_bad_venues = compute_smart_order_route(
        symbol="BTC/USDT",
        analysis={"venues": "bad"},
        phase74=p74,
        phase80=p80_ok,
    )
    assert r_bad_venues.venues_available == 0
    assert "no_venues" in r_bad_venues.reason

    r_block = compute_smart_order_route(
        symbol="X",
        analysis={"venues": {"a": {}}},
        phase74=p74,
        phase80=type("P80", (), {"final_action": "WAIT", "trade_permission": "BLOCK"})(),
    )
    assert r_block.preferred_venue == ""

    r_halt_action = compute_smart_order_route(
        symbol="X",
        analysis={"venues": {"a": {}}},
        phase74=p74,
        phase80=type("P80", (), {"final_action": "HALT", "trade_permission": "ALLOW"})(),
    )
    assert r_halt_action.preferred_venue == ""

    p76_crisis = type("P76", (), {"regime_execution_mode": "crisis"})()
    r_crisis = compute_smart_order_route(
        symbol="X",
        analysis={"venues": {"a": {"latency_ms": 5}, "b": {"latency_ms": 20}}},
        phase74=p74,
        phase80=p80_ok,
        phase76=p76_crisis,
    )
    assert r_crisis.preferred_venue == "a"

    r_crisis_no_lat = compute_smart_order_route(
        symbol="X",
        analysis={"venues": {"only": {"latency_ms": 0}}},
        phase74=p74,
        phase80=p80_ok,
        phase76=p76_crisis,
    )
    assert r_crisis_no_lat.preferred_venue == "only"

    r_leader = compute_smart_order_route(
        symbol="X",
        analysis={"venues": {"binance": {}, "other": {}}},
        phase74=p74,
        phase80=p80_ok,
    )
    assert r_leader.preferred_venue == "binance"

    r_fb = compute_smart_order_route(
        symbol="X",
        analysis={"venues": {"z_first": {}}},
        phase74=type("P74b", (), {"leader_venue": "missing", "route_preference": "x"})(),
        phase80=p80_ok,
    )
    assert r_fb.preferred_venue == "z_first"

    res = SmartOrderRouteResult(
        preferred_venue="v",
        route_preference="r",
        leader_venue="l",
        execution_mode="e",
        reason="why",
        venues_available=1,
        event_ts=123,
        half_life_ms=5000,
    )
    assert res.to_dict()["preferred_venue"] == "v"

    r_ts = compute_smart_order_route(
        symbol="X",
        analysis={"venues": {"x": {}}},
        phase74=type("P74c", (), {"leader_venue": "", "route_preference": "x"})(),
        phase80=p80_ok,
        event_ts=99,
    )
    assert r_ts.event_ts == 99

    r_hl = compute_smart_order_route(
        symbol="X",
        analysis={"venues": {"x": {}}},
        phase74=type("P74d", (), {"leader_venue": "", "route_preference": "x"})(),
        phase80=p80_ok,
        half_life_ms=50,
    )
    assert r_hl.half_life_ms == 2000

    r_hl_cap = compute_smart_order_route(
        symbol="X",
        analysis={"venues": {"x": {}}},
        phase74=type("P74e", (), {"leader_venue": "", "route_preference": "x"})(),
        phase80=p80_ok,
        half_life_ms=500_000,
    )
    assert r_hl_cap.half_life_ms == 300_000


def test_signal_fusion_engine_helpers_and_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    import super_otonom.signals.signal_fusion_engine as sfe

    snap = sfe.record_analyzer_snapshot("BTC/USDT", {"signal": "BUY", "confidence": 0.9})
    assert snap["prep_signal"] == "BUY"
    assert snap["symbol"] == "BTC/USDT"

    assert sfe._dir_from_signal("buy") == 1.0
    assert sfe._dir_from_signal("SELL") == -1.0
    assert sfe._dir_from_signal("") == 0.0

    assert sfe._dir_from_mtf("up") == 1.0
    assert sfe._dir_from_mtf("DOWN") == -1.0
    assert sfe._dir_from_mtf(None) == 0.0

    assert sfe._dir_from_ml({}) == 0.0
    assert sfe._dir_from_ml({"ml_score": "nope"}) == 0.0
    assert sfe._dir_from_ml({"omega_ml_score": 0.75}) > 0

    monkeypatch.setattr(sfe, "_W_TECH", 0.0)
    monkeypatch.setattr(sfe, "_W_ML", 0.0)
    monkeypatch.setattr(sfe, "_W_SENT", 0.0)
    monkeypatch.setattr(sfe, "_W_MTF", 0.0)
    z, parts = sfe._fusion_vector({"signal": "BUY"})
    assert z == 0.0
    assert parts["tech"] == 1.0

    monkeypatch.setattr(sfe, "_W_TECH", 0.4)
    monkeypatch.setattr(sfe, "_W_ML", 0.3)
    monkeypatch.setattr(sfe, "_W_SENT", 0.15)
    monkeypatch.setattr(sfe, "_W_MTF", 0.15)

    veto_out = {"final_signal": "BUY", "ai_confidence": 0.5}
    sfe._apply_fusion_to_out({"signal": "BUY", "sentiment_score": -0.9}, veto_out)
    assert veto_out["final_signal"] == "HOLD"
    assert veto_out.get("decision_reason") == "FUSION_SENTIMENT_VETO"

    conflict_out = {"final_signal": "BUY", "ai_confidence": 0.5}
    sfe._apply_fusion_to_out(
        {
            "signal": "BUY",
            "sentiment_score": 0.0,
            "ml_score": 0.02,
            "high_tf_trend": "DOWN",
        },
        conflict_out,
    )
    assert conflict_out["final_signal"] == "HOLD"
    assert conflict_out.get("decision_reason") == "FUSION_CONFLICT"

    boost_out = {"final_signal": "BUY", "ai_confidence": 0.6}
    sfe._apply_fusion_to_out(
        {
            "signal": "BUY",
            "sentiment_score": 0.7,
            "ml_score": 0.92,
            "high_tf_trend": "UP",
        },
        boost_out,
    )
    assert boost_out.get("ai_confidence", 0) >= 0.6


def test_standard_phase_output_phase_source_and_alias() -> None:
    from super_otonom.standard_phase_output import attach_phase_alias, make_standard_phase_output

    base = make_standard_phase_output(trade_permission="allow")
    assert "phase" not in base and "source" not in base

    full = make_standard_phase_output(phase="12", source="unit")
    assert full["phase"] == "12"
    assert full["source"] == "unit"

    analysis: dict = {}
    attach_phase_alias(analysis, "12", {"x": 1})
    _assert_dicts_equal_ignore_event_ts(analysis["phase12"], analysis["faz12"])
    assert analysis["phase12"]["x"] == 1


def test_run_signal_fusion_phase_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    import super_otonom.signals.signal_fusion_engine as sfe

    analysis: dict = {}
    out: dict = {}

    async def fake_hold(engine, symbol, analysis_in, candles, dctx, out_in):
        out_in["final_signal"] = "HOLD"
        out_in["ai_confidence"] = 0.0

    monkeypatch.setattr(sfe.signal_pipeline, "process_signal_phase", fake_hold)
    snap = asyncio.run(sfe.run_signal_fusion_phase(None, "BTC", analysis, [], None, out))
    assert snap.get("trade_permission") == "BLOCK"
    assert analysis.get("phase36") is snap
    assert snap.get("data_health") == 0.7

    out2: dict = {}

    async def fake_buy(engine, symbol, analysis_in, candles, dctx, out_in):
        out_in["final_signal"] = "BUY"
        out_in["ai_confidence"] = 0.72

    monkeypatch.setattr(sfe.signal_pipeline, "process_signal_phase", fake_buy)
    analysis2: dict = {
        "signal": "BUY",
        "sentiment_score": 0.7,
        "ml_score": 0.92,
        "high_tf_trend": "UP",
    }
    snap2 = asyncio.run(sfe.run_signal_fusion_phase(None, "ETH", analysis2, [], None, out2))
    assert snap2.get("trade_permission") == "ALLOW"
    assert snap2.get("data_health") == 1.0


def test_smart_stop_engine_paths() -> None:
    import super_otonom.smart_stop_engine as sse
    from super_otonom.smart_stop_engine import SmartStopResult, compute_smart_stop

    assert sse._clamp01(float("nan")) == 0.0
    assert sse._clamp01(-0.1) == 0.0
    assert sse._clamp01(9.0) == 1.0
    assert sse._clamp01(0.4) == 0.4

    assert sse._clamp100(float("nan")) == 0
    assert sse._try_float(None) is None
    assert sse._try_float("nope") is None
    assert sse._try_float("2.5") == 2.5

    r_crisis = compute_smart_stop(
        symbol="BTC/USDT",
        side="LONG",
        last_price=-1.0,
        analysis={"atr": 10.0, "volatility": 0.04, "regime": "CRISIS", "half_life_ms": 50_000},
        hunt_risk_score=88,
        event_ts=1_700_000_000_000,
    )
    assert r_crisis.stop_placement_hint == "widen"
    assert r_crisis.dynamic_stop_level > 0
    assert r_crisis.event_ts == 1_700_000_000_000

    r_short = compute_smart_stop(
        symbol="X",
        side="SHORT",
        last_price=100.0,
        analysis={"volatility": 0.05, "regime": "TREND_UP"},
        hunt_risk_score=20,
    )
    assert r_short.dynamic_stop_level > 100.0
    assert r_short.stop_placement_hint == "tighten"
    assert r_short.trail_mode == "chandelier"

    r_range = compute_smart_stop(
        symbol="X",
        side="LONG",
        last_price=50.0,
        analysis={"volatility": 0.01, "regime": "MEAN_REVERT_RANGE"},
        hunt_risk_score=50,
    )
    assert r_range.trail_mode == "off"

    r_atr_trail = compute_smart_stop(
        symbol="X",
        side="LONG",
        last_price=50.0,
        analysis={"atr": 2.0, "volatility": 0.1, "regime": "HIGH_VOLATILITY"},
        hunt_risk_score=40,
    )
    assert r_atr_trail.trail_mode == "atr"

    r_unknown = compute_smart_stop(
        symbol="X",
        side="LONG",
        last_price=50.0,
        analysis={"atr": 1.0, "volatility": 0.02, "regime": "QUIET"},
        hunt_risk_score=45,
    )
    assert r_unknown.trail_mode == "unknown"

    r_ts = compute_smart_stop(
        symbol="Z",
        side="LONG",
        last_price=10.0,
        analysis={"event_ts": 123456789, "atr": 0.5, "volatility": 0.02},
    )
    assert r_ts.event_ts == 123456789

    res = SmartStopResult(
        dynamic_stop_level=1.0,
        hunt_risk_score=1,
        stop_placement_hint="keep",
        trail_mode="unknown",
        trade_permission="ALLOW",
        alpha_score=1,
        risk_score=1,
        confidence=0.5,
        data_health=0.8,
        event_ts=1,
        half_life_ms=5000,
    )
    assert res.to_dict()["side"] == "UNKNOWN"

    r_hl = compute_smart_stop(
        symbol="Z",
        side="LONG",
        last_price=10.0,
        analysis={"atr": 0.5, "volatility": 0.02, "half_life_ms": 500},
    )
    assert r_hl.half_life_ms == 2000

    r_noisy = compute_smart_stop(
        symbol="Z",
        side="LONG",
        last_price=10.0,
        analysis={"atr": 1.0, "volatility": 0.06, "regime": "NOISY_CHOP"},
    )
    assert r_noisy.hunt_risk_score >= 0

    r_ext = compute_smart_stop(
        symbol="Z",
        side="LONG",
        last_price=10.0,
        analysis={"atr": 1.0, "volatility": 0.02},
        hunt_risk_score=9999,
    )
    assert r_ext.hunt_risk_score == 100

    r_hl_cap = compute_smart_stop(
        symbol="Z",
        side="LONG",
        last_price=10.0,
        analysis={"atr": 0.5, "volatility": 0.02, "half_life_ms": 400_000},
    )
    assert r_hl_cap.half_life_ms == 300_000

    r_atr_zero = compute_smart_stop(
        symbol="Z",
        side="LONG",
        last_price=100.0,
        analysis={"atr": 0.0, "volatility": 0.02},
    )
    assert r_atr_zero.dynamic_stop_level > 0

    r_vol_only = compute_smart_stop(
        symbol="Z",
        side="LONG",
        last_price=20.0,
        analysis={"atr": 2.0, "regime": "CALM"},
    )
    assert r_vol_only.data_health <= 0.75

    r_flash = compute_smart_stop(
        symbol="Z",
        side="LONG",
        last_price=10.0,
        analysis={"atr": 1.0, "volatility": 0.05, "regime": "FLASH_CRASH"},
    )
    assert r_flash.hunt_risk_score >= 50

    r_volat_hunt = compute_smart_stop(
        symbol="Z",
        side="LONG",
        last_price=10.0,
        analysis={"atr": 1.0, "volatility": 0.03, "regime": "HIGH_VOLATILITY_ONLY"},
    )
    assert r_volat_hunt.hunt_risk_score >= 30


def test_concentration_risk_limits_and_snapshot() -> None:
    from super_otonom.concentration_risk import ConcentrationRiskManager

    m = ConcentrationRiskManager(max_total_pct=0.95, max_single_pct=0.6, max_sector_pct=0.35)
    assert m.get_sector("UNKNOWN/PAIR") == "OTHER"

    ok_nav, _ = m.check_concentration("BTC/USDT", 100.0, -1.0, {})
    assert ok_nav is True

    bad_total, r1 = m.check_concentration("BTC/USDT", 8000.0, 10_000.0, {"ETH/USDT": {"size": 2000}})
    assert bad_total is False
    assert "total_exposure" in r1

    bad_single, r2 = m.check_concentration("BTC/USDT", 7000.0, 10_000.0, {"BTC/USDT": {"size": 0}})
    assert bad_single is False
    assert "single_coin" in r2

    bad_sector, r3 = m.check_concentration(
        "SOL/USDT",
        4000.0,
        10_000.0,
        {"BTC/USDT": {"size": 2000}},
    )
    assert bad_sector is False
    assert "sector_limit" in r3

    br = m.sector_breakdown({"BTC/USDT": {"size": 1000}, "UNI/USDT": {"notional": 500}}, 10_000.0)
    assert br.get("L1") == pytest.approx(10.0)
    assert br.get("DEFI") == pytest.approx(5.0)

    assert m.concentration_score({}, 10_000) == 0.0
    assert m.concentration_score({"BTC/USDT": {"size": 5000}}, 10_000) > 0

    snap = m.snapshot({"BTC/USDT": {"size": 1000}}, 10_000)
    assert snap["concentration_score"] >= 0
    assert snap["max_sector_pct"] == 35.0

    m2 = ConcentrationRiskManager()
    raw = m2.sector_breakdown({"BTC/USDT": {"size": 100}}, 0.0)
    assert raw.get("L1") == 100.0


def test_deploy_env_stamp_verify_enforce(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import json
    import time

    import super_otonom.config as cfg
    from super_otonom import deploy_env_stamp as des

    ok, msg = des.verify_stamp_for_live_start(tmp_path)
    assert ok is False
    assert "yok" in msg

    path = des.stamp_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{broken", encoding="utf-8")
    assert des.read_stamp(tmp_path) is None

    path.write_text("{}", encoding="utf-8")
    assert des.verify_stamp_for_live_start(tmp_path)[0] is False

    path.write_text(json.dumps({"schema_version": des.SCHEMA_VERSION}), encoding="utf-8")
    assert des.verify_stamp_for_live_start(tmp_path)[0] is False

    path.write_text(json.dumps({"passed_at_unix": "nope"}), encoding="utf-8")
    assert des.verify_stamp_for_live_start(tmp_path)[0] is False

    old_ts = time.time() - 999_999_999
    path.write_text(
        json.dumps({"passed_at_unix": old_ts, "passed_at_iso": "2000-01-01T00:00:00Z"}),
        encoding="utf-8",
    )
    stale, msg_stale = des.verify_stamp_for_live_start(tmp_path, max_age_hours=1.0)
    assert stale is False
    assert "eski" in msg_stale

    des.write_last_ok(tmp_path)
    fresh, msg_fresh = des.verify_stamp_for_live_start(tmp_path, max_age_hours=8760.0)
    assert fresh is True
    assert "OK" in msg_fresh

    monkeypatch.setenv("DEPLOY_ENV_LOCK_MAX_AGE_HOURS", "not_a_float")
    des.write_last_ok(tmp_path)
    ok_env, _ = des.verify_stamp_for_live_start(tmp_path, max_age_hours=None)
    assert ok_env is True

    monkeypatch.setenv("DEPLOY_ENV_LOCK_MAX_AGE_HOURS", "168")

    monkeypatch.setitem(cfg.GENERAL, "paper_mode", True)
    des.enforce_live_deploy_env_lock(tmp_path)

    monkeypatch.setitem(cfg.GENERAL, "paper_mode", False)
    monkeypatch.setenv("DEPLOY_ENV_LOCK_AT_START", "0")
    des.enforce_live_deploy_env_lock(tmp_path)

    monkeypatch.setenv("DEPLOY_ENV_LOCK_AT_START", "1")
    monkeypatch.setenv("DEPLOY_ENV_LOCK_BYPASS", "YES")
    path.unlink(missing_ok=True)
    des.enforce_live_deploy_env_lock(tmp_path)

    des.write_last_ok(tmp_path)
    monkeypatch.setenv("DEPLOY_ENV_LOCK_BYPASS", "")
    des.enforce_live_deploy_env_lock(tmp_path)


# --- coverage ~97%: benchmark live-OB (mocked exchange), coordination drift assert ---


def test_coordination_assert_invariants_raises_on_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    from super_otonom import coordination_resilience as cr

    def _fake_checks(repo_root=None):
        return False, ["synthetic drift for coverage"]

    monkeypatch.setattr(cr, "run_all_checks", _fake_checks)
    with pytest.raises(AssertionError, match="synthetic drift"):
        cr.assert_coordination_invariants()


def _silence_benchmark_output(monkeypatch: pytest.MonkeyPatch, bka: object) -> None:
    import builtins

    monkeypatch.setattr(bka, "_summarize", lambda *a, **k: None)
    monkeypatch.setattr(bka, "_print_omega_micro", lambda: None)
    monkeypatch.setattr(builtins, "print", lambda *a, **k: None)


def test_benchmark_live_ob_mocked_exchange(monkeypatch: pytest.MonkeyPatch) -> None:
    import super_otonom.benchmark_katman_a as bka

    class _FakeH:
        async def fetch_order_book(self, symbol: str, limit: int = 20) -> dict:
            _ = symbol, limit
            return {"bids": [[100.0, 1.0]], "asks": [[100.1, 1.0]]}

        def circuit_breaker_status(self) -> dict:
            return {}

    class _FakeAsyncEx:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> _FakeH:
            return _FakeH()

        async def __aexit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(bka, "AsyncExchangeHandler", _FakeAsyncEx)
    _silence_benchmark_output(monkeypatch, bka)
    asyncio.run(
        bka._run_live_ob_benchmark(
            iterations=1,
            warmup=1,
            scenario="normal",
            symbol="BTC/USDT",
            exchange_id="binance",
        )
    )


def test_benchmark_run_benchmark_live_ob_true(monkeypatch: pytest.MonkeyPatch) -> None:
    import super_otonom.benchmark_katman_a as bka

    class _FakeH:
        async def fetch_order_book(self, symbol: str, limit: int = 20) -> dict:
            _ = symbol, limit
            return {"bids": [[100.0, 1.0]], "asks": [[100.1, 1.0]]}

        def circuit_breaker_status(self) -> dict:
            return {}

    class _FakeAsyncEx:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> _FakeH:
            return _FakeH()

        async def __aexit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(bka, "AsyncExchangeHandler", _FakeAsyncEx)
    _silence_benchmark_output(monkeypatch, bka)
    asyncio.run(
        bka._run_benchmark(
            iterations=1,
            warmup=1,
            scenario="normal",
            symbol="BTC/USDT",
            live_ob=True,
            exchange_id="binance",
        )
    )


def test_benchmark_live_ob_empty_order_book_warn(monkeypatch: pytest.MonkeyPatch) -> None:
    import super_otonom.benchmark_katman_a as bka

    n = {"i": 0}

    class _FakeH:
        async def fetch_order_book(self, symbol: str, limit: int = 20) -> dict:
            _ = symbol, limit
            n["i"] += 1
            if n["i"] <= 2:
                return {"bids": [], "asks": []}
            return {"bids": [[100.0, 1.0]], "asks": [[100.1, 1.0]]}

        def circuit_breaker_status(self) -> dict:
            return {}

    class _FakeAsyncEx:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> _FakeH:
            return _FakeH()

        async def __aexit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(bka, "AsyncExchangeHandler", _FakeAsyncEx)
    _silence_benchmark_output(monkeypatch, bka)
    asyncio.run(
        bka._run_live_ob_benchmark(
            iterations=2,
            warmup=1,
            scenario="normal",
            symbol="BTC/USDT",
            exchange_id="binance",
        )
    )


def test_benchmark_kucoin_passphrase_in_extra_config(monkeypatch: pytest.MonkeyPatch) -> None:
    import super_otonom.benchmark_katman_a as bka

    seen: dict = {}

    class _FakeH:
        async def fetch_order_book(self, symbol: str, limit: int = 20) -> dict:
            _ = symbol, limit
            return {"bids": [[100.0, 1.0]], "asks": [[100.1, 1.0]]}

        def circuit_breaker_status(self) -> dict:
            return {}

    class _FakeAsyncEx:
        def __init__(self, *args: object, **kwargs: object) -> None:
            seen["extra"] = kwargs.get("extra_config")

        async def __aenter__(self) -> _FakeH:
            return _FakeH()

        async def __aexit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(bka, "AsyncExchangeHandler", _FakeAsyncEx)
    _silence_benchmark_output(monkeypatch, bka)
    orig = dict(bka.EXCHANGES)
    try:
        bka.EXCHANGES["kucoin"] = {
            "api_key": "k",
            "api_secret": "s",
            "api_passphrase": "ph",
            "testnet": True,
        }
        asyncio.run(
            bka._run_live_ob_benchmark(
                iterations=1,
                warmup=1,
                scenario="normal",
                symbol="BTC/USDT",
                exchange_id="kucoin",
            )
        )
        assert seen.get("extra") == {"password": "ph"}
    finally:
        bka.EXCHANGES.clear()
        bka.EXCHANGES.update(orig)


def test_benchmark_okx_password_in_extra_config(monkeypatch: pytest.MonkeyPatch) -> None:
    import super_otonom.benchmark_katman_a as bka

    seen: dict = {}

    class _FakeH:
        async def fetch_order_book(self, symbol: str, limit: int = 20) -> dict:
            _ = symbol, limit
            return {"bids": [[100.0, 1.0]], "asks": [[100.1, 1.0]]}

        def circuit_breaker_status(self) -> dict:
            return {}

    class _FakeAsyncEx:
        def __init__(self, *args: object, **kwargs: object) -> None:
            seen["extra"] = kwargs.get("extra_config")

        async def __aenter__(self) -> _FakeH:
            return _FakeH()

        async def __aexit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(bka, "AsyncExchangeHandler", _FakeAsyncEx)
    _silence_benchmark_output(monkeypatch, bka)
    orig = dict(bka.EXCHANGES)
    try:
        bka.EXCHANGES["okx"] = {
            "api_key": "k",
            "api_secret": "s",
            "api_password": "pwsecret",
            "testnet": True,
        }
        asyncio.run(
            bka._run_live_ob_benchmark(
                iterations=1,
                warmup=1,
                scenario="normal",
                symbol="BTC/USDT",
                exchange_id="okx",
            )
        )
        assert seen.get("extra") == {"password": "pwsecret"}
    finally:
        bka.EXCHANGES.clear()
        bka.EXCHANGES.update(orig)
