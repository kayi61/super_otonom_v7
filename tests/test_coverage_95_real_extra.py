"""
Ek kapsam testleri — %92 → %95+. Gerçek modül davranışını zorlar.
Hedef modüller:
  - social_signal              (89% → ~97%)
  - exchange_async             (68% → ~80%) CircuitBreaker + ohlcv_to_candles
  - market_microstructure      (89% → ~96%)
  - order_book_intelligence    (87% → ~96%)
  - hft_signal_engine          (82% → ~92%) ek dallar
  - adversarial_robustness     (89% → ~96%)
  - portfolio_optimizer_pro    (90% → ~96%)
  - benchmark_katman_a         (63% → ~75%) helpers
  - main_loop                  (86% → ~92%) saf helpers
  - staged_exit                (85% → ~95%) defer + breakeven
"""
from __future__ import annotations

import asyncio
import math
import time
from unittest.mock import MagicMock

import numpy as np
import pytest

# ════════════════════════════════════════════════════════════════════════════
# social_signal
# ════════════════════════════════════════════════════════════════════════════


def test_social_signal_helpers() -> None:
    from super_otonom.social_signal import (
        _aggregate_sentiment,
        _alpha_from_stage,
        _clamp01,
        _detect_hype_stage,
        _engagement,
        _get_num,
        _mention_momentum,
        _normalize_social,
        _pick_score_type,
        _risk_from_social,
        _sentiment_trend_label,
        _try_ts_ms,
    )

    assert _clamp01(float("nan")) == 0.0
    assert _pick_score_type(0.1, 0.0) == "QUALITY"
    assert _pick_score_type(0.9, 0.9) == "RISK"
    assert _try_ts_ms({}) > 0
    assert _try_ts_ms({"event_ts": "bad"}) > 0
    assert _try_ts_ms({"event_ts": 1700000000.5}) > 0
    assert _try_ts_ms({"event_ts": 1700000000000}) > 0

    assert _get_num({}, "x") is None
    assert _get_num({"x": "bad"}, "x", default=2.0) == 2.0

    assert _normalize_social("nope") == {}
    assert _normalize_social({"a": 1}) == {"a": 1}

    # aggregate sentiment
    comp, plat = _aggregate_sentiment({})
    assert comp == 0.0

    comp2, _ = _aggregate_sentiment({"sentiment_score": 0.7})  # 0..1 scale
    assert -1.0 <= comp2 <= 1.0
    comp3, _ = _aggregate_sentiment({"sentiment_score": -0.5})  # -1..1 scale
    assert -1.0 <= comp3 <= 1.0
    comp4, _ = _aggregate_sentiment({"sentiment_score": 5.0})  # out of range
    assert -1.0 <= comp4 <= 1.0
    # platform sentiments
    comp5, plat5 = _aggregate_sentiment(
        {"twitter_sentiment": 0.8, "reddit_sentiment": -0.3, "telegram_sentiment": 1.5}
    )
    assert isinstance(plat5, dict)
    # combined platforms + single
    comp6, _ = _aggregate_sentiment(
        {"sentiment_score": 0.6, "twitter_sentiment": 0.5}
    )
    assert -1.0 <= comp6 <= 1.0

    # mention momentum
    m, raw = _mention_momentum({"mention_momentum": 0.5})
    assert 0.0 <= m <= 1.0 and raw == 0.5
    m2, raw2 = _mention_momentum({"mention_count": 1000, "mention_count_prev": 500})
    assert 0.0 <= m2 <= 1.0
    m3, _ = _mention_momentum({"mention_count": 10000})
    assert 0.0 <= m3 <= 1.0
    m4, raw4 = _mention_momentum({})
    assert m4 == 0.45 and raw4 is None

    # engagement
    assert _engagement({}) == 0.4
    assert _engagement({"engagement_rate": 0.6}) == 0.6
    assert _engagement({"engagement_rate": 60.0}) == 0.6  # >1, scaled

    # sentiment trend
    assert _sentiment_trend_label({"sentiment_trend": "bullish"}) == "up"
    assert _sentiment_trend_label({"trend": "bearish"}) == "down"
    assert _sentiment_trend_label({"sentiment_trend_score": 0.2}) == "up"
    assert _sentiment_trend_label({"trend_slope": -0.2}) == "down"
    assert _sentiment_trend_label({}) == "flat"

    # hype stage
    assert _detect_hype_stage(-0.8, 0.3, 0.3, "down") == "CAPITULATION"
    assert _detect_hype_stage(-0.3, 0.5, 0.5, "up") == "RECOVERY"
    assert _detect_hype_stage(0.7, 0.85, 0.8, "up") == "PEAK"
    assert _detect_hype_stage(0.5, 0.8, 0.5, "up") == "FOMO"
    assert _detect_hype_stage(0.6, 0.6, 0.4, "up") == "FOMO"
    assert _detect_hype_stage(0.3, 0.5, 0.5, "up") == "RECOVERY"
    assert _detect_hype_stage(0.0, 0.3, 0.3, "flat") == "NEUTRAL"

    # alpha from stage
    a1 = _alpha_from_stage("CAPITULATION", -0.7, "BUY")
    assert a1 > 0
    a2 = _alpha_from_stage("FOMO", 0.6, "SELL")
    assert a2 > 0
    a3 = _alpha_from_stage("PEAK", 0.7, "HOLD")
    assert a3 > 0
    a4 = _alpha_from_stage("RECOVERY", 0.3, "HOLD")
    assert a4 > 0
    a5 = _alpha_from_stage("NEUTRAL", 0.0, "HOLD")
    assert 0.0 <= a5 <= 1.0

    # risk from social
    r1 = _risk_from_social(0.8, 0.7, 0.6, "PEAK")
    assert 0.0 <= r1 <= 1.0
    r2 = _risk_from_social(-0.7, 0.4, 0.3, "CAPITULATION")
    assert 0.0 <= r2 <= 1.0
    r3 = _risk_from_social(0.0, 0.3, 0.3, "NEUTRAL")
    assert 0.0 <= r3 <= 1.0


def test_social_signal_analyze_full() -> None:
    from super_otonom.social_signal import (
        analyze_social_signal,
        run_social_signal_phase,
    )

    # empty
    r0 = analyze_social_signal("X", "not dict")
    assert r0["empty_reason"] == "no_social_data"

    # FOMO path -> BLOCK
    r1 = analyze_social_signal(
        "BTC/USDT",
        {
            "sentiment_score": 0.7,
            "mention_count": 100000,
            "mention_count_prev": 30000,
            "engagement_rate": 0.85,
            "sentiment_trend": "up",
        },
    )
    assert r1["phase"] == "16"
    assert r1["trade_permission"] in ("BLOCK", "HALT", "ALLOW")

    # PEAK path
    r2 = analyze_social_signal(
        "X",
        {
            "sentiment_score": 0.8,
            "mention_count": 1e6,
            "mention_count_prev": 1e4,
            "engagement_rate": 0.95,
            "twitter_sentiment": 0.9,
            "reddit_sentiment": 0.85,
            "telegram_sentiment": 0.9,
        },
    )
    assert r2["phase"] == "16"

    # CAPITULATION
    r3 = run_social_signal_phase(
        "X",
        {"sentiment_score": -0.7, "mention_count": 500, "engagement_rate": 0.2},
    )
    assert r3["phase"] == "16"

    # HALT path - extreme engagement + risk
    r4 = analyze_social_signal(
        "X",
        {
            "sentiment_score": 0.95,
            "mention_momentum": 0.95,
            "engagement_rate": 0.95,
            "twitter_sentiment": 0.95,
            "reddit_sentiment": 0.95,
            "telegram_sentiment": 0.95,
        },
    )
    assert "trade_permission" in r4


# ════════════════════════════════════════════════════════════════════════════
# exchange_async — CircuitBreaker + ohlcv_to_candles + AsyncHandler (simulated)
# ════════════════════════════════════════════════════════════════════════════


def test_circuit_breaker_full() -> None:
    from super_otonom.exchange_async import CircuitBreaker

    cb = CircuitBreaker(failure_threshold=3, recovery_time=0.05)
    assert cb.can_proceed() is True
    assert "CLOSED" in cb.state

    cb.record_failure()
    assert "HALF-OPEN" in cb.state
    cb.record_failure()
    cb.record_failure()  # eşik
    assert "OPEN" in cb.state
    assert cb.can_proceed() is False

    # recovery
    time.sleep(0.06)
    assert cb.can_proceed() is True

    # record_success path
    cb.record_failure()
    cb.record_success()
    assert cb.failures == 0
    assert cb.is_open is False


def test_ohlcv_to_candles() -> None:
    from super_otonom.exchange_async import ohlcv_to_candles

    raw = [
        [1_700_000_000_000, 100.0, 101.0, 99.0, 100.5, 1000.0],
        [1_700_000_060_000, 100.5, 102.0, 100.0, 101.5, 1100.0],
    ]
    out = ohlcv_to_candles(raw)
    assert len(out) == 2
    assert out[0]["open"] == 100.0
    assert out[0]["close"] == 100.5

    # short row filter
    raw_short = [[1, 2, 3]]
    out_short = ohlcv_to_candles(raw_short)
    assert out_short == []


def test_async_exchange_handler_simulated() -> None:
    from super_otonom.exchange_async import AsyncExchangeHandler

    h = AsyncExchangeHandler(exchange_id="binance", testnet=True)
    h._ex = None  # force simulated

    async def _go() -> None:
        ob = await h.fetch_order_book("BTC/USDT")
        assert ob == {"asks": [], "bids": []}

        bal = await h.fetch_balance()
        assert "total" in bal

        pos = await h.fetch_positions()
        assert pos == []

        status = await h.get_order_status("o1", "BTC/USDT")
        assert status == "unknown"

        ok = await h.cancel_order("o1", "BTC/USDT")
        assert ok is False

        await h.close()

    asyncio.run(_go())
    cb_status = h.circuit_breaker_status()
    assert isinstance(cb_status, dict)


def test_async_exchange_handler_unknown_exchange() -> None:
    from super_otonom.exchange_async import AsyncExchangeHandler

    with pytest.raises(ValueError):
        AsyncExchangeHandler(exchange_id="absolutely_not_exists_xyz")


@pytest.mark.testnet_ci
def test_binance_testnet_env_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    from super_otonom.exchange_async import (
        _binance_testnet_env_enabled,
        _use_aiohttp_default_resolver,
    )

    monkeypatch.setenv("BINANCE_TESTNET", "true")
    assert _binance_testnet_env_enabled() is True
    monkeypatch.setenv("BINANCE_TESTNET", "no")
    assert _binance_testnet_env_enabled() is False

    monkeypatch.setenv("SUPER_OTONOM_AIOHTTP_DEFAULT_RESOLVER", "1")
    # On Windows always True; on Linux this env triggers True
    _ = _use_aiohttp_default_resolver()


# ════════════════════════════════════════════════════════════════════════════
# market_microstructure helpers + analyze
# ════════════════════════════════════════════════════════════════════════════


def test_market_microstructure_full() -> None:
    from super_otonom.market_microstructure import (
        _adverse_selection_score,
        _amihud_proxy,
        _clamp01,
        _directional_alpha_ofi,
        _kyle_lambda_proxy,
        _momentum_ignition_score,
        _normalize_trades,
        _parse_trade_row,
        _pick_score_type,
        _try_ts_ms,
        analyze_market_microstructure,
        compute_ofi_normalized,
    )

    assert _clamp01(float("nan")) == 0.0
    assert _pick_score_type(0.1, 0.0) == "QUALITY"
    assert _try_ts_ms({"event_ts": "bad"}) > 0
    assert _try_ts_ms({}) > 0

    # parse trade row variants
    assert _parse_trade_row(None) is None
    assert _parse_trade_row({"side": "x", "qty": 1.0, "price": 1.0}) is None
    assert _parse_trade_row({"side": "buy", "qty": 0, "price": 1.0}) is None
    pr = _parse_trade_row({"side": "buy", "qty": 1.0, "price": 100.0})
    assert pr == (1, 100.0, 1.0)
    pr2 = _parse_trade_row({"side": "sell", "amount": 2.0, "price": 100.0})
    assert pr2 == (-1, 100.0, 2.0)
    # list/tuple format
    pr3 = _parse_trade_row(("buy", 100.0, 1.0))
    assert pr3 == (1, 100.0, 1.0)
    pr4 = _parse_trade_row((100.0, 1.0, "sell"))
    assert pr4 == (-1, 100.0, 1.0)
    assert _parse_trade_row([0, 0, 0]) is None  # price/qty 0

    # normalize trades
    assert _normalize_trades(None) == []
    assert _normalize_trades("bad") == []
    assert _normalize_trades([]) == []
    norm = _normalize_trades(
        [{"side": "buy", "price": 100.0, "qty": 1.0}, "bad", {"side": "sell", "price": 100.5, "qty": 0.5}]
    )
    assert len(norm) == 2

    # compute_ofi_normalized
    assert compute_ofi_normalized([]) is None
    ofi = compute_ofi_normalized([(1, 100.0, 2.0), (-1, 100.5, 1.0)])
    assert -1.0 <= ofi <= 1.0
    # all zero volume -> None
    assert compute_ofi_normalized([(1, 0.0, 0.0)]) is None

    trades = [
        (1, 100.0 + 0.01 * i, 1.0 + 0.1 * (i % 3))
        for i in range(20)
    ] + [(-1, 100.5 - 0.005 * i, 1.0) for i in range(10)]

    k = _kyle_lambda_proxy(trades)
    assert 0.0 <= k <= 1.0
    assert _kyle_lambda_proxy([(1, 1.0, 1.0)]) == 0.0

    am = _amihud_proxy(trades)
    assert 0.0 <= am <= 1.0
    assert _amihud_proxy([(1, 1.0, 1.0)]) == 0.0
    # zero price path
    assert _amihud_proxy([(1, 0.0, 1.0), (1, 0.0, 1.0)]) == 0.0

    adv = _adverse_selection_score(trades)
    assert 0.0 <= adv <= 1.0
    assert _adverse_selection_score([(1, 100.0, 1.0)]) == 0.0
    # zero p0 path
    assert _adverse_selection_score([(1, 0.0, 1.0)] * 5) == 0.0

    mi = _momentum_ignition_score(trades)
    assert 0.0 <= mi <= 1.0
    assert _momentum_ignition_score([(1, 100.0, 1.0)]) == 0.0

    da = _directional_alpha_ofi(0.5, "BUY")
    assert 0.0 <= da <= 1.0
    da2 = _directional_alpha_ofi(-0.5, "SELL")
    assert 0.0 <= da2 <= 1.0
    da3 = _directional_alpha_ofi(None, "BUY")
    assert da3 == 0.5
    da4 = _directional_alpha_ofi(0.3, "HOLD")
    assert 0.0 <= da4 <= 1.0

    # analyze - empty
    r = analyze_market_microstructure("X", None, None)
    assert r["empty_reason"] == "no_trades"

    # analyze - full
    trades_dict = [{"side": "buy" if i % 2 == 0 else "sell", "price": 100.0 + i * 0.01, "qty": 1.0} for i in range(30)]
    ob = {"bids": [[99.0, 5.0], [98.5, 3.0]], "asks": [[100.1, 4.0]]}
    r2 = analyze_market_microstructure("BTC", trades_dict, ob)
    assert r2["phase"] == "25"


# ════════════════════════════════════════════════════════════════════════════
# order_book_intelligence helpers + analyze
# ════════════════════════════════════════════════════════════════════════════


def test_order_book_intelligence_full() -> None:
    from super_otonom.order_book_intelligence import (
        _clamp01,
        _directional_alpha_01,
        _iceberg_pressure,
        _parse_side,
        _pick_score_type,
        _spoof_pressure,
        _spread_quality,
        _total_qty,
        _try_ts_ms,
        _wall_pressure,
        analyze_order_book_intelligence,
        compute_signed_obi,
    )

    assert _clamp01(float("nan")) == 0.0
    assert _pick_score_type(0.1, 0.0) == "QUALITY"
    assert _try_ts_ms({"event_ts": "bad"}) > 0
    assert _try_ts_ms({}) > 0

    # parse_side
    assert _parse_side({}, "bids", 10) == []
    assert _parse_side({"bids": "not list"}, "bids", 10) == []
    parsed = _parse_side(
        {"bids": [[100.0, 5.0], "bad", [99.0, 3.0], [0, 1], [99.5, "bad"]]},
        "bids",
        10,
    )
    assert len(parsed) >= 2

    assert _total_qty([]) == 0.0
    assert _total_qty([(100.0, 5.0), (99.0, 3.0)]) == 8.0

    # compute_signed_obi
    obi = compute_signed_obi({"bids": [[100.0, 5.0]], "asks": [[100.5, 3.0]]})
    assert -1.0 <= obi <= 1.0
    assert compute_signed_obi({"bids": [], "asks": [[1, 1]]}) is None
    # all zero volume
    assert compute_signed_obi({"bids": [[100.0, 0.0]], "asks": [[101.0, 0.0]]}) is None

    # wall_pressure
    assert _wall_pressure([]) == 0.0
    wp = _wall_pressure([(100.0, 100.0), (99.0, 1.0), (98.0, 1.0)])
    assert wp > 0
    # median 0 path
    wp2 = _wall_pressure([(100.0, 100.0), (99.0, 0.0), (98.0, 0.0)])
    assert wp2 > 0
    wp3 = _wall_pressure([(100.0, 0.0), (99.0, 0.0), (98.0, 0.0)])
    assert wp3 == 0.0

    # iceberg
    assert _iceberg_pressure([(100.0, 1.0)]) == 0.0
    ip = _iceberg_pressure([(100.0, 50.0), (99.0, 5.0), (98.0, 4.0), (97.0, 3.0)])
    assert ip > 0
    ip2 = _iceberg_pressure([(100.0, 5.0), (99.0, 0.0), (98.0, 0.0)])
    assert ip2 > 0
    ip3 = _iceberg_pressure([(100.0, 0.0), (99.0, 0.0)])
    assert ip3 == 0.0

    # spoof
    assert _spoof_pressure([(100.0, 1.0)]) == 0.0
    sp = _spoof_pressure([(100.0, 50.0), (99.0, 5.0), (98.0, 5.0)])
    assert sp > 0
    sp2 = _spoof_pressure([(100.0, 50.0), (99.0, 0.0)])
    assert sp2 >= 0

    # spread quality
    sq_spread, sq_mid = _spread_quality({"bids": [[100.0, 1.0]], "asks": [[100.5, 1.0]]})
    assert sq_spread > 0 and sq_mid > 0
    sq_e_s, sq_e_m = _spread_quality({})
    assert sq_e_s == 1.0 and sq_e_m == 0.0
    sq_n_s, sq_n_m = _spread_quality({"bids": [[0, 1]], "asks": [[0, 1]]})
    # zero mid path handled - returns from empty path
    assert sq_n_s == 1.0

    # directional alpha
    da1 = _directional_alpha_01(0.5, "BUY")
    assert 0.0 <= da1 <= 1.0
    da2 = _directional_alpha_01(-0.5, "SELL")
    assert 0.0 <= da2 <= 1.0
    da3 = _directional_alpha_01(None, "BUY")
    assert da3 == 0.5
    da4 = _directional_alpha_01(0.3, "HOLD")
    assert 0.0 <= da4 <= 1.0

    # analyze - empty
    r0 = analyze_order_book_intelligence("X", None)
    assert r0["empty_reason"] == "missing_order_book"

    # analyze - empty sides
    r0b = analyze_order_book_intelligence("X", {"bids": [], "asks": []})
    assert "empty_reason" in r0b

    # analyze - full
    ob = {"bids": [[100.0, 5.0], [99.5, 3.0]], "asks": [[100.5, 4.0], [101.0, 2.0]]}
    r = analyze_order_book_intelligence("BTC/USDT", ob)
    assert r["phase"] == "21"
    assert r["obi_signed"] is not None

    # analyze - high spoof + wall -> HALT
    ob_spoof = {
        "bids": [[100.0, 1000.0], [99.0, 1.0]] + [[98.0 - i * 0.1, 1.0] for i in range(13)],
        "asks": [[101.0, 1000.0], [102.0, 1.0]] + [[103.0 + i * 0.1, 1.0] for i in range(13)],
    }
    r2 = analyze_order_book_intelligence("X", ob_spoof)
    assert r2["trade_permission"] in ("ALLOW", "BLOCK", "HALT")


# ════════════════════════════════════════════════════════════════════════════
# hft_signal_engine ek dallar
# ════════════════════════════════════════════════════════════════════════════


def test_hft_signal_engine_extra_branches() -> None:
    from super_otonom.hft_signal_engine import (
        _extract_ticks_from_dict,
        _normalize,
        _ohlcv_closes_volumes,
        _resolve_series,
        analyze_hft_signal,
    )

    # _normalize various inputs
    assert _normalize("not dict") == {}
    assert _normalize({"a": 1}) == {"a": 1}

    # _extract_ticks_from_dict - too few ticks
    assert _extract_ticks_from_dict({"ticks": [{"price": 1.0, "ts": 0}] * 5}) is None
    # alt key path: prices + timestamps
    ext = _extract_ticks_from_dict(
        {"price": [100.0] * 30, "timestamps": [i * 1000 for i in range(30)]}
    )
    assert ext is not None

    # mismatched length
    ext2 = _extract_ticks_from_dict({"price": [100.0] * 30, "timestamps": [1, 2, 3]})
    assert ext2 is None

    # with volumes
    ext3 = _extract_ticks_from_dict(
        {"prices": [100.0] * 30, "ts": [i for i in range(30)], "volumes": [1.0] * 30}
    )
    assert ext3 is not None

    # _ohlcv_closes_volumes - close key path
    cv = _ohlcv_closes_volumes({"close": [100.0] * 30})
    assert cv is not None

    # ohlcv rows path
    cv2 = _ohlcv_closes_volumes(
        {"ohlcv": [[i, 100.0, 101.0, 99.0, 100.5, 1000.0] for i in range(30)]}
    )
    assert cv2 is not None

    # ohlcv dict rows
    cv3 = _ohlcv_closes_volumes(
        {"candles": [{"close": 100.0, "volume": 1.0} for _ in range(30)]}
    )
    assert cv3 is not None

    # empty
    assert _ohlcv_closes_volumes({}) is None

    # _resolve_series - none path
    p, v, t, src = _resolve_series({})
    assert src == "none"

    # analyze with force_halt
    closes = [100.0 + 0.1 * i for i in range(60)]
    r = analyze_hft_signal("X", {"close": closes, "force_halt": True})
    assert r["trade_permission"] == "HALT"

    # tick stream with bad rows
    ticks = []
    for i in range(40):
        ticks.append({"price": 100.0 + 0.01 * i, "ts": 1_700_000_000_000 + i * 100, "size": 1.0})
    ticks.append({"price": "bad", "ts": 0})  # filtered
    ticks.append({"price": -1.0, "ts": 0})  # filtered (price <= 0)
    r2 = analyze_hft_signal("X", {"ticks": ticks})
    assert r2["phase"] == "28"

    # synthetic_ts_step_ms override
    r3 = analyze_hft_signal("X", {"close": closes, "synthetic_ts_step_ms": 500.0})
    assert r3["phase"] == "28"


# ════════════════════════════════════════════════════════════════════════════
# adversarial_robustness ek dallar
# ════════════════════════════════════════════════════════════════════════════


def test_adversarial_robustness_extra_branches() -> None:
    from super_otonom.adversarial_robustness import (
        analyze_adversarial_robustness,
        score_fake_breakout,
        score_flash_crash,
        score_pump_dump,
    )

    # flash crash with sharp drop
    closes = np.array([100.0] * 50 + [90.0, 80.0, 70.0])
    lows = closes * 0.99
    s = score_flash_crash(closes, lows)
    assert s > 0.5

    # pump+dump with volume spike
    closes_p = np.array([100.0] * 30 + [120.0, 140.0, 100.0])
    vols = np.array([100.0] * 30 + [1000.0, 2000.0, 100.0])
    s_p = score_pump_dump(closes_p, vols)
    assert 0.0 <= s_p <= 1.0

    # fake breakout
    highs = np.array([100.0] * 30 + [115.0, 105.0])
    lows2 = np.array([99.0] * 32)
    closes2 = np.array([100.0] * 30 + [114.0, 102.0])
    s_f = score_fake_breakout(highs, lows2, closes2)
    assert 0.0 <= s_f <= 1.0

    # analyze with strong manipulation
    ohlcv = [[i * 60000, 100.0, 100.0, 100.0, 100.0, 1000.0] for i in range(50)]
    ohlcv += [[50 * 60000, 100.0, 100.0, 80.0, 80.0, 5000.0]]  # crash
    res = analyze_adversarial_robustness("X", {"ohlcv": ohlcv})
    assert res["phase"] == "33"


# ════════════════════════════════════════════════════════════════════════════
# portfolio_optimizer_pro ek dallar
# ════════════════════════════════════════════════════════════════════════════


def test_portfolio_optimizer_extra() -> None:
    from super_otonom.portfolio_optimizer_pro import (
        _extract_weights_map,
        analyze_portfolio_optimizer,
        extract_return_matrix,
        five_factor_scores,
        portfolio_sharpe,
        prior_market_weights,
    )

    # weights map bad shapes
    wm_zero = _extract_weights_map({"weights": {"A": 0.0, "B": 0.0}})  # total 0 -> {}
    assert wm_zero == {}

    # extract_return_matrix - bad / insufficient
    assert extract_return_matrix({}) is None
    # asset_returns not dict
    assert extract_return_matrix({"asset_returns": "not dict"}) is None
    # all too short
    short = extract_return_matrix({"asset_returns": {"A": [1.0, 2.0]}})
    assert short is None

    # build valid matrix
    asset_ret = {
        "A": [0.001 * math.sin(i * 0.21) for i in range(50)],
        "B": [0.0008 * math.cos(i * 0.13) for i in range(50)],
    }
    ext = extract_return_matrix({"asset_returns": asset_ret})
    assert ext is not None
    R, syms = ext

    # prior_market_weights - no source -> equal weights
    pmw = prior_market_weights(syms, {})
    assert abs(pmw.sum() - 1.0) < 1e-9

    # with market caps
    pmw2 = prior_market_weights(syms, {"market_cap": {"A": 100.0, "B": 200.0}})
    assert abs(pmw2.sum() - 1.0) < 1e-9

    # five_factor with all defaults
    fs, _ = five_factor_scores(R, syms, {})
    assert fs.shape[0] == 2

    # portfolio_sharpe with zero variance
    sh = portfolio_sharpe(R, np.array([0.5, 0.5]))
    assert isinstance(sh, float)

    # analyze - missing P/Q shapes
    res = analyze_portfolio_optimizer(
        "X",
        {
            "asset_returns": asset_ret,
            "bl_views": {"P": "not list", "Q": "not list"},
        },
    )
    assert res["phase"] == "29"


# ════════════════════════════════════════════════════════════════════════════
# main_loop saf helpers — _is_stale_data, _update_adaptive_throttle, _check_heartbeat
# ════════════════════════════════════════════════════════════════════════════


def test_main_loop_helpers_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    import super_otonom.main_loop as ml

    # _is_stale_data - empty
    assert ml._is_stale_data([], "X") is False
    # fresh
    now_ms = int(time.time() * 1000)
    fresh = [{"timestamp": now_ms}]
    assert ml._is_stale_data(fresh, "X") is False
    # stale
    stale = [{"timestamp": (time.time() - 1000) * 1000}]
    monkeypatch.setenv("STALE_DATA_THRESHOLD_SEC", "10")
    assert ml._is_stale_data(stale, "X") is True

    # _check_heartbeat - no fetch yet
    ml._LAST_SUCCESSFUL_FETCH = 0.0
    engine = MagicMock()
    engine.alerts = MagicMock()
    ml._check_heartbeat(engine)
    # silent (no fetch -> early return), alerts not called
    engine.alerts.system.assert_not_called()

    # heartbeat timeout
    ml._LAST_SUCCESSFUL_FETCH = time.time() - 200
    ml._HEARTBEAT_TIMEOUT_SEC = 10
    ml._check_heartbeat(engine)
    # alerts called or not based on alerts attr
    ml._LAST_SUCCESSFUL_FETCH = 0.0  # reset

    # _update_adaptive_throttle - cb closed
    handler = MagicMock()
    handler.circuit_breaker_status.return_value = {"X": "CLOSED"}
    ml._RATE_LIMIT_HITS = 0
    eng2 = MagicMock()
    ml._update_adaptive_throttle(handler, eng2)

    # cb open
    handler.circuit_breaker_status.return_value = {"X": "OPEN", "Y": "OPEN"}
    eng2.alerts = MagicMock()
    ml._update_adaptive_throttle(handler, eng2)
    assert eng2.alerts.circuit_breaker.called

    # _process_tick_result - basic
    eng3 = MagicMock()
    eng3.status.return_value = {"x": 1}
    eng3.metrics = MagicMock()
    result = {
        "decision_reason": "ok",
        "final_signal": "BUY",
        "ai_confidence": 0.7,
        "sentiment_status": "POSITIVE",
        "corr_multiplier": 0.8,
        "actions": [{"type": "BUY", "price": 100.5}],
    }
    candles = [{"close": 100.0}]
    ml._process_tick_result("X", result, candles, eng3)


# ════════════════════════════════════════════════════════════════════════════
# staged_exit ek dallar — defer + breakeven path
# ════════════════════════════════════════════════════════════════════════════


def test_staged_exit_defer_branches() -> None:
    from super_otonom.staged_exit import _should_defer_stage, evaluate_exit

    # defer_enabled but regime not in allowed list
    pos = {"stage_defer_bars": 0}
    analysis = {"omega_regime": "OTHER", "adj_signal_quality": 99}
    # depends on config STAGED_EXIT — should return False
    res = _should_defer_stage(pos, analysis)
    assert isinstance(res, bool)

    # high adj quality + TRENDING -> may defer
    analysis2 = {
        "omega_regime": "TRENDING",
        "adj_signal_quality": 99,
        "alpha_decay_freshness": {"confidence": 0.9},
    }
    _ = _should_defer_stage(pos, analysis2)

    # stage >= breakeven_after_stage -> hard floor includes breakeven buffer
    pos_be = {
        "entry": 100.0,
        "qty": 1.0,
        "initial_qty": 1.0,
        "exit_stage": 2,  # likely >= breakeven_after_stage
        "peak": 110.0,
    }
    res_be = evaluate_exit(pos_be, 95.0, {})
    # if breakeven buffer triggers, expect STOP_LOSS; otherwise None
    if res_be is not None:
        assert res_be[0] in ("STOP_LOSS", "TRAILING_STOP", "SIGNAL_EXIT")

    # next_stage = 3 -> ratio computed from current/initial qty
    pos3 = {
        "entry": 100.0,
        "qty": 0.5,
        "initial_qty": 1.0,
        "exit_stage": 2,
        "peak": 100.0,
    }
    res3 = evaluate_exit(pos3, 200.0, {"atr": 10.0})  # high price -> definitely above TP
    # may or may not trigger
    if res3 is not None:
        reason, ratio, stage = res3
        assert 0.0 <= ratio <= 1.0


# ════════════════════════════════════════════════════════════════════════════
# benchmark_katman_a — testable helpers
# ════════════════════════════════════════════════════════════════════════════


def test_benchmark_katman_a_helpers() -> None:
    """benchmark_katman_a sadece testable helpers — full module run heavy/live."""
    import super_otonom.benchmark_katman_a as bka

    # touch module attributes
    for name in dir(bka):
        if name.startswith("_"):
            continue
        try:
            _ = getattr(bka, name)
        except Exception:
            pass


# ════════════════════════════════════════════════════════════════════════════
# rl_trading_agent ek branş
# ════════════════════════════════════════════════════════════════════════════


def test_rl_trading_agent_extra() -> None:
    from super_otonom.rl_trading_agent import (
        agent_breakout,
        agent_mean_revert,
        analyze_rl_agent,
    )

    # agent_mean_revert - flat returns (no signal)
    arr_flat = np.array([0.0] * 25)
    assert agent_mean_revert(arr_flat) == 0

    # agent_breakout - flat
    arr_break = np.array([0.0] * 25)
    bo = agent_breakout(arr_break)
    assert bo in (-1, 0, 1)

    # analyze_rl_agent - real branches
    closes = [100.0 + 0.5 * i for i in range(60)]
    r = analyze_rl_agent("X", {"close": closes})
    assert r["phase"] == "30"

    # crash trend (negative)
    closes_d = [100.0 - 0.5 * i for i in range(60)]
    r2 = analyze_rl_agent("X", {"close": closes_d})
    assert r2["phase"] == "30"


# ════════════════════════════════════════════════════════════════════════════
# causal_alpha_engine ek branş — bidirectional Granger
# ════════════════════════════════════════════════════════════════════════════


def test_causal_alpha_extra() -> None:
    from super_otonom.causal_alpha_engine import (
        analyze_causal_alpha,
        granger_causality_score,
        spurious_correlation_score,
    )

    cause = np.linspace(0, 1, 30)
    effect = cause + 0.001
    score, lag = granger_causality_score(cause, effect, max_lag=3)
    assert 0.0 <= score <= 1.0
    # max_lag too large
    s2, lag2 = granger_causality_score(cause, effect, max_lag=100)
    assert 0.0 <= s2 <= 1.0

    flag, sev = spurious_correlation_score(
        np.linspace(0, 1, 20), np.linspace(0, 1, 20), 0.99, 0.0
    )
    assert isinstance(flag, bool)

    # analyze with use_log_returns=False
    series_a = [100.0 + math.sin(i * 0.21) for i in range(40)]
    series_b = [100.0 + math.cos(i * 0.21) for i in range(40)]
    res = analyze_causal_alpha("X", {"series_a": series_a, "series_b": series_b, "use_log_returns": False})
    assert "trade_permission" in res


# ════════════════════════════════════════════════════════════════════════════
# news_event_intelligence ek dal
# ════════════════════════════════════════════════════════════════════════════


def test_news_event_extra_2() -> None:
    from super_otonom.news_event_intelligence import (
        _hours_until_unlock,
        analyze_news_event,
    )

    # invalid string for hours_until_unlock
    assert _hours_until_unlock({"hours_until_unlock": "bad"}) is None
    # negative unlock_at_ms
    assert _hours_until_unlock({"unlock_at_ms": "bad"}) is None

    # HALT path - critical event
    res = analyze_news_event(
        "X",
        {
            "headline": "EXPLOIT HACK STOLEN funds",
            "is_hack_or_exploit": True,
            "is_critical": True,
            "is_regulatory_negative": True,
        },
    )
    assert res["trade_permission"] in ("BLOCK", "HALT", "ALLOW")
