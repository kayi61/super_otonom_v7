"""CI %99 hedefi — adversarial, causal, liquidity, main_loop, portfolio_optimizer_pro, hft_signal_engine."""

from __future__ import annotations

import time
from typing import Any, Dict
from unittest.mock import MagicMock

import numpy as np
import pytest


def _returns_dict(n: int = 40, syms: tuple[str, ...] = ("AAA", "BBB")) -> Dict[str, Any]:
    rng = np.random.default_rng(42)
    return {
        s: (rng.normal(0, 0.01, size=n)).astype(float).tolist()
        for s in syms
    }


# ── adversarial_robustness / causal_alpha_engine / liquidity_games_detector ─


@pytest.mark.asyncio
async def test_adversarial_analyze_attaches_when_empty_dict() -> None:
    from super_otonom.adversarial_robustness import analyze_adversarial_robustness

    a: Dict[str, Any] = {}
    out = analyze_adversarial_robustness("X", {}, a, attach_to_analysis=True)
    assert out.get("empty_reason") == "no_market_data"
    assert "phase33" in a or "faz33" in a


@pytest.mark.asyncio
async def test_causal_analyze_attaches_empty_payload() -> None:
    from super_otonom.signals.causal_alpha_engine import analyze_causal_alpha

    a: Dict[str, Any] = {}
    out = analyze_causal_alpha("Y", {}, a, attach_to_analysis=True)
    assert out.get("empty_reason") == "no_causal_data"
    assert "phase31" in a or "faz31" in a


@pytest.mark.asyncio
async def test_liquidity_detect_stop_hunt_when_wide_spread_and_skewed_book() -> None:
    from super_otonom.liquidity_games_detector import detect_liquidity_games

    ob: Dict[str, Any] = {
        "bids": [[50.0, 10.0]],
        "asks": [[150.0, 1.0]],
    }
    r = detect_liquidity_games(symbol="Q", analysis={"volatility": 0.12}, order_book=ob)
    assert r.manipulation_risk_score >= 80
    assert r.game_type == "stop_hunt"
    assert r.do_not_trade_flag is True


# ── main_loop ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_apply_ob_safe_size_uses_candle_ts_when_redis_kline_has_no_updated_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import super_otonom.infra.redis_bridge as rb_mod
    from super_otonom.main_loop import _apply_ob_safe_size

    class _RB:
        def get_kline(self, _sym: str) -> Dict[str, Any]:
            return {"close": 100.0}

    monkeypatch.setattr(rb_mod, "RedisBridge", lambda *a, **k: _RB())

    engine = MagicMock()
    engine.equity = 10_000.0
    engine.trade_log = []
    engine.sizer = MagicMock()
    engine.sizer.validate_and_calculate.return_value = 2.5
    engine.sizer.set_trade_log = MagicMock()

    ts = int(time.time() * 1000)
    candles = [{"timestamp": float(ts), "close": 101.0}]
    analysis: Dict[str, Any] = {}
    ob = {"asks": [[102.0, 1.0]], "bids": [[100.0, 1.0]]}
    _apply_ob_safe_size(engine, "BTC/USDT", ob, candles, analysis, 0.02, 0.8)
    assert analysis["ob_safe_size"] == 2.5
    engine.sizer.validate_and_calculate.assert_called_once()
    cargs = engine.sizer.validate_and_calculate.call_args.kwargs
    assert float(cargs["last_candle_ts"]) == float(ts)


@pytest.mark.asyncio
async def test_apply_ob_safe_size_redis_import_path_falls_back_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from super_otonom.main_loop import _apply_ob_safe_size

    def _bad_rb(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("redis bridge unavailable")

    monkeypatch.setattr("super_otonom.infra.redis_bridge.RedisBridge", _bad_rb)

    engine = MagicMock()
    engine.equity = 10_000.0
    engine.trade_log = []
    engine.sizer = MagicMock()
    engine.sizer.validate_and_calculate.return_value = 1.25
    engine.sizer.set_trade_log = MagicMock()

    ts = int(time.time() * 1000)
    candles = [{"timestamp": float(ts), "close": 99.0}]
    analysis: Dict[str, Any] = {}
    ob = {"asks": [[100.5, 1.0]], "bids": [[99.0, 1.0]]}
    _apply_ob_safe_size(engine, "ETH/USDT", ob, candles, analysis, 0.02, 0.8)
    assert analysis["ob_safe_size"] == 1.25


@pytest.mark.asyncio
async def test_log_elite_startup_when_emergency_stop_active() -> None:
    from super_otonom.main_loop import _log_elite_startup

    eng = MagicMock()
    eng.risk = MagicMock()
    eng.risk.emergency_stop = True
    _log_elite_startup(eng)


@pytest.mark.asyncio
async def test_prep_symbol_sentiment_exception_is_non_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    import super_otonom.main_loop as ml

    async def _ob(_sym: str, **_k: Any) -> Dict[str, Any]:
        return {"bids": [[100.0, 1.0]], "asks": [[100.1, 1.0]]}

    h = MagicMock()
    h.circuit_breaker_status.return_value = {"BTC/USDT": "CLOSED"}
    h.fetch_order_book = _ob

    now_ms = int(time.time() * 1000)
    raw_1h = {
        "BTC/USDT": [
            [now_ms - (120 - i) * 60_000, 100.0, 101.0, 99.0, 100.0 + 0.01 * i, 1000.0]
            for i in range(120)
        ]
    }
    eng = MagicMock()
    eng.equity = 5000.0
    eng.trade_log = []
    eng.risk = MagicMock()
    eng.sentiment_layer = MagicMock()
    eng.sentiment_layer.get_market_sentiment.side_effect = RuntimeError("sentiment down")
    eng.sizer = MagicMock()
    eng.sizer.calculate.return_value = 100.0
    eng.sizer.validate_and_calculate.return_value = 1.0
    eng.sizer.set_trade_log = MagicMock()

    monkeypatch.setattr(ml, "apply_storm_trip_to_risk", lambda _r: False)

    class _A:
        def analyze(self, *_a: Any, **_k: Any) -> Dict[str, Any]:
            return {
                "regime": "RANGING",
                "hurst": 0.5,
                "signal": "HOLD",
                "volatility": 0.02,
                "high_tf_trend": "N/A",
                "mtf_filtered": False,
            }

        def apply_liquidity_context(self, *_a: Any, **_k: Any) -> None:
            pass

    out = await ml.prep_symbol_for_tick(
        "BTC/USDT",
        h,
        _A(),
        eng,
        raw_1h,
        {},
        None,
    )
    assert out is not None
    sym, analysis, _c1h = out
    assert sym == "BTC/USDT"
    assert "sentiment_score" not in analysis


@pytest.mark.asyncio
async def test_process_tick_result_logs_slippage_on_buy_action() -> None:
    from super_otonom.main_loop import _process_tick_result

    eng = MagicMock()
    eng.status.return_value = {}
    eng.metrics = MagicMock()
    candles = [{"close": 100.0, "timestamp": time.time() * 1000}]
    res = {
        "final_signal": "BUY",
        "ai_confidence": 0.7,
        "decision_reason": "test",
        "sentiment_status": "BULL",
        "corr_multiplier": 0.9,
        "actions": [{"type": "BUY", "price": 100.5}],
    }
    _process_tick_result("BTC/USDT", res, candles, eng)
    eng.metrics.record_slippage.assert_called_once()


@pytest.mark.asyncio
async def test_check_heartbeat_triggers_when_silent_too_long(monkeypatch: pytest.MonkeyPatch) -> None:
    import super_otonom.main_loop as ml

    eng = MagicMock()
    eng.alerts = MagicMock()
    monkeypatch.setattr(ml, "_LAST_SUCCESSFUL_FETCH", time.time() - 500.0)
    monkeypatch.setattr(ml, "_HEARTBEAT_TIMEOUT_SEC", 10)
    ml._check_heartbeat(eng)
    eng.alerts.system.assert_called()


# ── portfolio_optimizer_pro ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_portfolio_optimizer_five_factor_dict_paths_and_list_weights() -> None:
    from super_otonom.portfolio_optimizer_pro import analyze_portfolio_optimizer

    d = _returns_dict(48, ("AAA", "BBB"))
    data: Dict[str, Any] = {
        "asset_returns": d,
        "weights": [["AAA", 0.7], ["BBB", 0.3]],
        "book_to_market": {"AAA": 1.2, "BBB": 0.8},
        "market_cap": {"AAA": 1e9, "BBB": 2e9},
    }
    out = analyze_portfolio_optimizer("P", data, {}, attach_to_analysis=False)
    assert out["phase"] == "29"
    assert len(out["portfolio_optimizer"]["symbols"]) == 2


@pytest.mark.asyncio
async def test_portfolio_optimizer_black_litterman_fallback_on_singular_views() -> None:
    from super_otonom.portfolio_optimizer_pro import analyze_portfolio_optimizer

    d = _returns_dict(48, ("X", "Y"))
    data: Dict[str, Any] = {
        "asset_returns": d,
        "bl_views": {
            "P": [[1.0, 0.0], [0.0, 1.0]],
            "Q": [0.01, 0.02, 0.03],
            "Omega": [1.0, 1.0],
        },
    }
    out = analyze_portfolio_optimizer("P2", data, {}, attach_to_analysis=False)
    assert out["source"] == "portfolio_optimizer_pro"
    assert 0.0 <= float(out["portfolio_optimizer"]["black_litterman_view_uncertainty"]) <= 1.0


# ── hft_signal_engine ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_hft_analyze_force_halt_permission() -> None:
    from super_otonom.signals.hft_signal_engine import analyze_hft_signal

    ticks = [{"price": 100.0 + 0.01 * i, "ts": float(i * 1000), "size": 1.0} for i in range(40)]
    out = analyze_hft_signal("H", {"ticks": ticks, "force_halt": True}, {}, attach_to_analysis=False)
    assert out["trade_permission"] == "HALT"


@pytest.mark.asyncio
async def test_hft_resolve_ohlcv_dict_rows_and_synthetic_ts_step() -> None:
    from super_otonom.signals.hft_signal_engine import _resolve_series, analyze_hft_signal

    ohlcv: list[Dict[str, Any]] = []
    for i in range(40):
        ohlcv.append({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0 + 0.02 * i, "volume": 10.0})
    p, v, t, src = _resolve_series({"ohlcv": ohlcv, "synthetic_ts_step_ms": 250.0})
    assert src == "ohlcv"
    assert p.size == 40

    out = analyze_hft_signal(
        "D",
        {"ohlcv": ohlcv, "synthetic_ts_step_ms": 250.0, "micro_N": 12},
        {},
        attach_to_analysis=False,
    )
    assert out["phase"] == "28"
    assert out["hft_signal"]["data_source"] == "ohlcv"


@pytest.mark.asyncio
async def test_hft_extract_prices_timestamps_mid_times_keys() -> None:
    from super_otonom.signals.hft_signal_engine import _extract_ticks_from_dict

    n = 30
    d = {
        "mid": [100.0 + 0.01 * i for i in range(n)],
        "times": [float(i) for i in range(n)],
    }
    ext = _extract_ticks_from_dict(d)
    assert ext is not None
    p, _v, t = ext
    assert p.size == n and float(np.max(t)) >= 1000.0
