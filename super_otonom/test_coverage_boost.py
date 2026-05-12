# -*- coding: utf-8 -*-
"""
test_coverage_boost.py
Coverage artırma testleri — tüm %0 modüller için
Çalıştırma: python test_coverage_boost.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import asyncio
import time
from unittest.mock import MagicMock, patch

PASS = 0
FAIL = 0


def ok(label):
    global PASS
    PASS += 1
    print(f"  ✓ {label}")


def fail(label, err):
    global FAIL
    FAIL += 1
    print(f"  ✗ {label} → {err}")


def section(title):
    print(f"\n── {title} ──")


# ══════════════════════════════════════════════════════════════════
# YARDIMCI: sahte mum verisi
# ══════════════════════════════════════════════════════════════════


def make_candles(n=60, base_price=100.0):
    candles = []
    p = base_price
    ts = time.time() * 1000 - n * 300_000
    for i in range(n):
        o = p
        h = p * 1.01
        lo = p * 0.99
        c = p * (1 + (0.001 if i % 2 == 0 else -0.001))
        candles.append(
            {"timestamp": ts, "open": o, "high": h, "low": lo, "close": c, "volume": 100.0 + i}
        )
        p = c
        ts += 300_000
    return candles


# ══════════════════════════════════════════════════════════════════
# 1. KILL SWITCH
# ══════════════════════════════════════════════════════════════════

section("TEST 1: KillSwitch / HardLimitTracker")

try:
    from super_otonom.kill_switch import (
        HardLimitTracker,
        RateLimitStormTracker,
        apply_storm_trip_to_risk,
        is_ratelimit_error,
    )

    # T1.1 - HardLimitTracker oluşturma
    try:
        ht = HardLimitTracker(max_orders=3, window_sec=1.0, max_price_jump_pct=0.05)
        assert ht._max_orders == 3
        ok("T1.1 HardLimitTracker oluşturuldu")
    except Exception as e:
        fail("T1.1", e)

    # T1.2 - from_config
    try:
        ht2 = HardLimitTracker.from_config()
        ok("T1.2 from_config çalışıyor")
    except Exception as e:
        fail("T1.2", e)

    # T1.3 - can_submit_order (boş → None)
    try:
        res = ht.can_submit_order()
        assert res is None
        ok("T1.3 can_submit_order boşken None döndü")
    except Exception as e:
        fail("T1.3", e)

    # T1.4 - record_order + rate exceeded
    try:
        for _ in range(3):
            ht.record_order()
        res = ht.can_submit_order()
        assert res == "order_rate_exceeded"
        ok("T1.4 order_rate_exceeded tetiklendi")
    except Exception as e:
        fail("T1.4", e)

    # T1.5 - check_price_tick normal
    try:
        ht3 = HardLimitTracker(max_orders=10, window_sec=60.0, max_price_jump_pct=0.05)
        res = ht3.check_price_tick("BTC/USDT", 100.0)
        assert res is None
        res2 = ht3.check_price_tick("BTC/USDT", 101.0)
        assert res2 is None
        ok("T1.5 check_price_tick normal fiyat → None")
    except Exception as e:
        fail("T1.5", e)

    # T1.6 - check_price_tick spike
    try:
        ht4 = HardLimitTracker(max_orders=10, window_sec=60.0, max_price_jump_pct=0.05)
        ht4.check_price_tick("BTC/USDT", 100.0)
        res = ht4.check_price_tick("BTC/USDT", 200.0)
        assert res == "price_spike"
        ok("T1.6 price_spike tespit edildi")
    except Exception as e:
        fail("T1.6", e)

    # T1.7 - status_line
    try:
        s = ht3.status_line()
        assert "orders_in_window" in s
        ok("T1.7 status_line çalışıyor")
    except Exception as e:
        fail("T1.7", e)

    # T1.8 - is_ratelimit_error
    try:

        class FakeExc(Exception):
            code = 429

        assert is_ratelimit_error(FakeExc()) is True
        assert is_ratelimit_error(ValueError("too many requests error")) is True
        assert is_ratelimit_error(ValueError("normal error")) is False
        ok("T1.8 is_ratelimit_error doğru tanımlıyor")
    except Exception as e:
        fail("T1.8", e)

    # T1.9 - RateLimitStormTracker
    try:
        rlt = RateLimitStormTracker(max_consecutive=3)
        assert rlt.poll_trip() is None
        rlt.on_ratelimit()
        rlt.on_ratelimit()
        rlt.on_ratelimit()
        assert rlt.poll_trip() == "rate_limit_storm"
        rlt.on_success()
        assert rlt.poll_trip() is None
        ok("T1.9 RateLimitStormTracker doğru çalışıyor")
    except Exception as e:
        fail("T1.9", e)

    # T1.10 - apply_storm_trip_to_risk
    try:
        mock_risk = MagicMock()
        mock_risk.emergency_stop = False
        result = apply_storm_trip_to_risk(mock_risk)
        ok("T1.10 apply_storm_trip_to_risk çalışıyor")
    except Exception as e:
        fail("T1.10", e)

except ImportError as e:
    fail("T1.x kill_switch import", e)

# ══════════════════════════════════════════════════════════════════
# 2. SIGNAL QUALITY SCORER
# ══════════════════════════════════════════════════════════════════

section("TEST 2: SignalQualityScorer")

try:
    from super_otonom.signal_quality_scorer import compute_signal_quality

    # T2.1 - trending iyi senaryo
    try:
        analysis = {
            "signal": "BUY",
            "hurst": 0.65,
            "regime": "TRENDING",
            "volatility": 0.02,
            "liquidity_ratio": 0.8,
            "high_tf_trend": "UP",
        }
        score, penalties, comps, main = compute_signal_quality(analysis)
        assert 0 <= score <= 100
        ok(f"T2.1 trending BUY kalite skoru={score}")
    except Exception as e:
        fail("T2.1", e)

    # T2.2 - noisy rejim düşük skor
    try:
        analysis2 = {
            "signal": "BUY",
            "hurst": 0.5,
            "regime": "NOISY",
            "volatility": 0.1,
            "liquidity_ratio": 0.1,
        }
        score2, penalties2, _, _ = compute_signal_quality(analysis2)
        assert "hurst:noisy_regime" in penalties2
        ok(f"T2.2 noisy rejim ceza uygulandı score={score2}")
    except Exception as e:
        fail("T2.2", e)

    # T2.3 - flash_crash kesme
    try:
        analysis3 = {
            "signal": "BUY",
            "hurst": 0.7,
            "regime": "TRENDING",
            "volatility": 0.02,
            "flash_crash": True,
        }
        score3, penalties3, _, _ = compute_signal_quality(analysis3)
        assert "flash_crash:cut" in penalties3
        ok(f"T2.3 flash_crash kesildi score={score3}")
    except Exception as e:
        fail("T2.3", e)

    # T2.4 - MTF mismatch
    try:
        analysis4 = {
            "signal": "BUY",
            "hurst": 0.6,
            "regime": "TRENDING",
            "volatility": 0.02,
            "high_tf_trend": "DOWN",
        }
        score4, penalties4, _, _ = compute_signal_quality(analysis4)
        assert "mtf:tf_mismatch" in penalties4
        ok("T2.4 mtf:tf_mismatch cezası uygulandı")
    except Exception as e:
        fail("T2.4", e)

    # T2.5 - likidite bilinmiyor
    try:
        analysis5 = {"signal": "HOLD", "regime": "TRENDING", "hurst": 0.6}
        score5, pen5, _, _ = compute_signal_quality(analysis5)
        assert "liquidity:unknown" in pen5
        ok("T2.5 liquidity:unknown cezası uygulandı")
    except Exception as e:
        fail("T2.5", e)

except ImportError as e:
    fail("T2.x signal_quality_scorer import", e)

# ══════════════════════════════════════════════════════════════════
# 3. SENTIMENT LAYER
# ══════════════════════════════════════════════════════════════════

section("TEST 3: SentimentLayer")

try:
    from super_otonom.sentiment_layer import SentimentLayer

    # T3.1 - mock bearish
    try:
        sl = SentimentLayer(mock_score=0.1)
        result = sl.get_market_sentiment()
        assert result["status"] == "BEARISH_PANIC"
        assert result["source"] == "mock"
        ok("T3.1 mock bearish doğru")
    except Exception as e:
        fail("T3.1", e)

    # T3.2 - mock bullish
    try:
        sl2 = SentimentLayer(mock_score=0.9)
        result2 = sl2.get_market_sentiment()
        assert result2["status"] == "BULLISH_EUPHORIA"
        ok("T3.2 mock bullish doğru")
    except Exception as e:
        fail("T3.2", e)

    # T3.3 - mock neutral
    try:
        sl3 = SentimentLayer(mock_score=0.5)
        result3 = sl3.get_market_sentiment()
        assert result3["status"] == "NEUTRAL"
        ok("T3.3 mock neutral doğru")
    except Exception as e:
        fail("T3.3", e)

    # T3.4 - BUY veto bearish panik
    try:
        sl4 = SentimentLayer(mock_score=0.1)
        sig, reason = sl4.validate_with_sentiment("BUY")
        assert sig == "HOLD"
        assert "NEWS_VETO" in reason
        ok("T3.4 BUY veto bearish panik")
    except Exception as e:
        fail("T3.4", e)

    # T3.5 - SELL veto bullish euphoria
    try:
        sl5 = SentimentLayer(mock_score=0.9)
        sig5, reason5 = sl5.validate_with_sentiment("SELL")
        assert sig5 == "HOLD"
        ok("T3.5 SELL veto bullish euphoria")
    except Exception as e:
        fail("T3.5", e)

    # T3.6 - BUY neutral geçer
    try:
        sl6 = SentimentLayer(mock_score=0.5)
        sig6, reason6 = sl6.validate_with_sentiment("BUY")
        assert sig6 == "BUY"
        assert "SENTIMENT_OK" in reason6
        ok("T3.6 BUY neutral geçiyor")
    except Exception as e:
        fail("T3.6", e)

    # T3.7 - set_mock_score
    try:
        sl7 = SentimentLayer(mock_score=0.5)
        sl7.set_mock_score(0.2)
        result7 = sl7.get_market_sentiment()
        assert result7["status"] == "BEARISH_PANIC"
        ok("T3.7 set_mock_score çalışıyor")
    except Exception as e:
        fail("T3.7", e)

    # T3.8 - dynamic fallback (no mock, no api)
    try:
        sl8 = SentimentLayer()
        result8 = sl8.get_market_sentiment()
        assert 0 <= result8["score"] <= 1
        assert result8["source"] in ("fallback_dynamic", "api")
        ok("T3.8 dynamic fallback çalışıyor")
    except Exception as e:
        fail("T3.8", e)

except ImportError as e:
    fail("T3.x sentiment_layer import", e)

# ══════════════════════════════════════════════════════════════════
# 4. OMEGA REGIME
# ══════════════════════════════════════════════════════════════════

section("TEST 4: OmegaRegime")

try:
    from super_otonom.omega_regime import compute_omega_regime

    # T4.1 - trending rejim
    try:
        analysis = {"regime": "TRENDING", "hurst": 0.65, "volatility": 0.02, "flash_crash": False}
        oreg, qm, sf, adj, log_line = compute_omega_regime(analysis, base_quality=70)
        assert oreg == "TRENDING"
        assert "[OMEGA-AI]" in log_line
        ok(f"T4.1 TRENDING rejim qm={qm:.2f} sf={sf:.2f}")
    except Exception as e:
        fail("T4.1", e)

    # T4.2 - crash risk
    try:
        analysis2 = {"regime": "TRENDING", "hurst": 0.6, "volatility": 0.1, "flash_crash": True}
        oreg2, qm2, sf2, adj2, _ = compute_omega_regime(analysis2, base_quality=80)
        assert oreg2 == "CRASH_RISK"
        assert qm2 < 1.0
        ok(f"T4.2 CRASH_RISK flash_crash tespit edildi qm={qm2}")
    except Exception as e:
        fail("T4.2", e)

    # T4.3 - ranging rejim
    try:
        analysis3 = {"regime": "NOISY", "hurst": 0.5, "volatility": 0.03, "flash_crash": False}
        oreg3, qm3, sf3, adj3, _ = compute_omega_regime(analysis3, base_quality=50)
        assert oreg3 == "RANGING"
        ok(f"T4.3 RANGING rejim sf={sf3}")
    except Exception as e:
        fail("T4.3", e)

    # T4.4 - yüksek kalite trending bonus
    try:
        analysis4 = {"regime": "TRENDING", "hurst": 0.7, "volatility": 0.02, "flash_crash": False}
        oreg4, qm4, sf4, adj4, _ = compute_omega_regime(analysis4, base_quality=95)
        assert sf4 >= 1.0
        ok(f"T4.4 yüksek kalite trending bonus sf={sf4}")
    except Exception as e:
        fail("T4.4", e)

except ImportError as e:
    fail("T4.x omega_regime import", e)

# ══════════════════════════════════════════════════════════════════
# 5. DECISION CONTEXT
# ══════════════════════════════════════════════════════════════════

section("TEST 5: DecisionContext")

try:
    from super_otonom.decision_context import DecisionContext, DecisionStage

    # T5.1 - start oluşturma
    try:
        analysis = {"signal": "BUY", "regime": "TRENDING", "liquidity_ratio": 0.8}
        dctx = DecisionContext.start("BTC/USDT", tick_id=1, analysis=analysis)
        assert dctx.symbol == "BTC/USDT"
        assert dctx.analysis_signal == "BUY"
        assert dctx.regime == "TRENDING"
        ok("T5.1 DecisionContext.start çalışıyor")
    except Exception as e:
        fail("T5.1", e)

    # T5.2 - add_trace
    try:
        dctx.add_trace("risk", "risk passed")
        dctx.add_trace("ai", "signal confirmed")
        assert len(dctx.trace) == 2
        ok("T5.2 add_trace çalışıyor")
    except Exception as e:
        fail("T5.2", e)

    # T5.3 - to_dict
    try:
        d = dctx.to_dict()
        assert d["symbol"] == "BTC/USDT"
        assert "trace" in d
        assert isinstance(d["trace"], list)
        ok("T5.3 to_dict çalışıyor")
    except Exception as e:
        fail("T5.3", e)

    # T5.4 - DecisionStage enum
    try:
        assert DecisionStage.RISK == "risk"
        assert DecisionStage.AI == "ai"
        assert DecisionStage.ENTRY == "entry"
        ok("T5.4 DecisionStage enum değerleri doğru")
    except Exception as e:
        fail("T5.4", e)

    # T5.5 - liquidity_ratio None güvenli
    try:
        dctx2 = DecisionContext.start("ETH/USDT", tick_id=2, analysis={"signal": "HOLD"})
        assert dctx2.liquidity_ratio is None
        ok("T5.5 liquidity_ratio None güvenli")
    except Exception as e:
        fail("T5.5", e)

except ImportError as e:
    fail("T5.x decision_context import", e)

# ══════════════════════════════════════════════════════════════════
# 6. STATE MACHINE
# ══════════════════════════════════════════════════════════════════

section("TEST 6: StateMachine")

try:
    from super_otonom.state_machine import TradingState, compute_trading_state

    def make_engine(emergency=False, omega_tighten=0):
        eng = MagicMock()
        eng.risk.emergency_stop = emergency
        eng.risk._omega_qmin_tighten = omega_tighten
        return eng

    # T6.1 - emergency → EMERGENCY
    try:
        eng = make_engine(emergency=True)
        state = compute_trading_state(eng, {})
        assert state == TradingState.EMERGENCY
        ok("T6.1 emergency → EMERGENCY")
    except Exception as e:
        fail("T6.1", e)

    # T6.2 - normal → AGGRESSIVE
    try:
        eng2 = make_engine()
        state2 = compute_trading_state(eng2, {"volatility": 0.01})
        assert state2 == TradingState.AGGRESSIVE
        ok("T6.2 normal → AGGRESSIVE")
    except Exception as e:
        fail("T6.2", e)

    # T6.3 - yüksek volatilite → DEFENSIVE
    try:
        eng3 = make_engine()
        state3 = compute_trading_state(eng3, {"volatility": 0.10})
        assert state3 == TradingState.DEFENSIVE
        ok("T6.3 yüksek volatilite → DEFENSIVE")
    except Exception as e:
        fail("T6.3", e)

    # T6.4 - omega tighten → DEFENSIVE
    try:
        eng4 = make_engine(omega_tighten=20)
        state4 = compute_trading_state(eng4, {"volatility": 0.01})
        assert state4 == TradingState.DEFENSIVE
        ok("T6.4 omega_tighten ≥ 15 → DEFENSIVE")
    except Exception as e:
        fail("T6.4", e)

    # T6.5 - GLOBAL_TRADE_DISABLE → NO_TRADE
    try:
        with patch.dict(os.environ, {"GLOBAL_TRADE_DISABLE": "true"}):
            eng5 = make_engine()
            state5 = compute_trading_state(eng5, {"volatility": 0.01})
            assert state5 == TradingState.NO_TRADE
        ok("T6.5 GLOBAL_TRADE_DISABLE → NO_TRADE")
    except Exception as e:
        fail("T6.5", e)

except ImportError as e:
    fail("T6.x state_machine import", e)

# ══════════════════════════════════════════════════════════════════
# 7. POSITION SIZER
# ══════════════════════════════════════════════════════════════════

section("TEST 7: PositionSizer")

try:
    from super_otonom.position_sizer import PositionSizer

    # T7.1 - temel hesap
    try:
        sizer = PositionSizer(max_position_pct=0.05, min_notional=10.0)
        size = sizer.calculate("BTC/USDT", equity=10000.0, volatility=0.02, ai_conf=0.7)
        assert size >= 0
        ok(f"T7.1 calculate çalışıyor size={size:.2f}")
    except Exception as e:
        fail("T7.1", e)

    # T7.2 - sıfır equity → 0
    try:
        size2 = sizer.calculate("BTC/USDT", equity=0.0)
        assert size2 == 0.0
        ok("T7.2 sıfır equity → 0")
    except Exception as e:
        fail("T7.2", e)

    # T7.3 - Kelly fallback (yetersiz trade log)
    try:
        sizer3 = PositionSizer(min_notional=5.0)
        sizer3.set_trade_log([])
        size3 = sizer3.calculate("ETH/USDT", equity=5000.0, volatility=0.015)
        assert size3 >= 0
        ok(f"T7.3 Kelly fallback çalışıyor size={size3:.2f}")
    except Exception as e:
        fail("T7.3", e)

    # T7.4 - calculate_with_slippage boş order book
    try:
        size4 = sizer.calculate_with_slippage("BTC/USDT", 10000.0, {"asks": [], "bids": []})
        ok(f"T7.4 boş order book güvenli size={size4}")
    except Exception as e:
        fail("T7.4", e)

    # T7.5 - validate_and_calculate eski timestamp → 0
    try:
        old_ts = (time.time() - 100) * 1000
        ob = {"bids": [[100, 1.0]], "asks": [[101, 1.0]]}
        size5 = sizer.validate_and_calculate(
            "BTC/USDT", 10000.0, ob, old_ts, max_candle_age_ms=100, volatility=0.02, ai_conf=0.7
        )
        assert size5 == 0.0
        ok("T7.5 eski timestamp → 0 (zaman senkronizasyon filtresi)")
    except Exception as e:
        fail("T7.5", e)

    # T7.6 - validate_and_calculate flash crash (imbalance düşük) → 0
    try:
        fresh_ts = time.time() * 1000
        ob_thin = {"bids": [[100, 0.01]], "asks": [[101, 10.0]]}
        size6 = sizer.validate_and_calculate(
            "BTC/USDT",
            10000.0,
            ob_thin,
            fresh_ts,
            min_bid_imbalance=0.5,
            volatility=0.02,
            ai_conf=0.7,
        )
        assert size6 == 0.0
        ok("T7.6 imbalance düşük → 0 (flash crash koruması)")
    except Exception as e:
        fail("T7.6", e)

    # T7.7 - can_open
    try:
        can = sizer.can_open(100.0, 10000.0, {}, max_total_pct=0.80)
        assert can is True
        ok("T7.7 can_open True döndü")
    except Exception as e:
        fail("T7.7", e)

    # T7.8 - total_exposure
    try:
        positions = {"BTC/USDT": {"size": 500}, "ETH/USDT": {"size": 300}}
        exp = sizer.total_exposure(positions)
        assert exp == 800
        ok("T7.8 total_exposure doğru")
    except Exception as e:
        fail("T7.8", e)

except ImportError as e:
    fail("T7.x position_sizer import", e)

# ══════════════════════════════════════════════════════════════════
# 8. CORRELATION MANAGER
# ══════════════════════════════════════════════════════════════════

section("TEST 8: CorrelationManager")

try:
    from super_otonom.correlation_manager import CorrelationManager

    # T8.1 - update_returns ve summary
    try:
        cm = CorrelationManager(threshold=0.75)
        for i in range(50):
            cm.update_returns("BTC/USDT", 100.0 + i)
            cm.update_returns("ETH/USDT", 50.0 + i * 0.5)
        s = cm.summary()
        assert s["tracked_symbols"] == 2
        ok("T8.1 update_returns ve summary çalışıyor")
    except Exception as e:
        fail("T8.1", e)

    # T8.2 - get_returns_df
    try:
        df = cm.get_returns_df()
        assert not df.empty
        ok(f"T8.2 get_returns_df satır={len(df)}")
    except Exception as e:
        fail("T8.2", e)

    # T8.3 - get_correlated_pairs
    try:
        pairs = cm.get_correlated_pairs()
        ok(f"T8.3 get_correlated_pairs çalışıyor pairs={len(pairs)}")
    except Exception as e:
        fail("T8.3", e)

    # T8.4 - adjust_risk_exposure yeterli veri
    try:
        mult = cm.adjust_risk_exposure("BTC/USDT", ["ETH/USDT"])
        assert 0.2 <= mult <= 1.0
        ok(f"T8.4 adjust_risk_exposure mult={mult:.2f}")
    except Exception as e:
        fail("T8.4", e)

    # T8.5 - correlation_matrix
    try:
        matrix = cm.correlation_matrix()
        assert matrix is not None
        ok("T8.5 correlation_matrix döndü")
    except Exception as e:
        fail("T8.5", e)

    # T8.6 - yetersiz veri
    try:
        cm2 = CorrelationManager()
        pairs2 = cm2.get_correlated_pairs()
        assert pairs2 == []
        ok("T8.6 yetersiz veri → boş pairs")
    except Exception as e:
        fail("T8.6", e)

except ImportError as e:
    fail("T8.x correlation_manager import", e)

# ══════════════════════════════════════════════════════════════════
# 9. WFA MANAGER
# ══════════════════════════════════════════════════════════════════

section("TEST 9: WFAManager")

try:
    import pandas as pd

    from super_otonom.wfa_manager import WFAManager

    # T9.1 - fold üretimi
    try:
        data = pd.DataFrame({"close": [float(i) for i in range(500)]})
        wfa = WFAManager(data, window_size=100, step_size=50)
        folds = wfa.get_folds()
        assert len(folds) > 0
        ok(f"T9.1 WFAManager fold üretildi: {len(folds)} fold")
    except Exception as e:
        fail("T9.1", e)

    # T9.2 - record_result
    try:
        fold = folds[0]
        wfa.record_result(fold, {"param": 1}, train_score=0.8, test_score=0.7)
        ok("T9.2 record_result çalışıyor")
    except Exception as e:
        fail("T9.2", e)

    # T9.3 - summary
    try:
        s = wfa.summary()
        assert "folds" in s
        assert s["folds"] >= 1
        ok(f"T9.3 summary folds={s['folds']}")
    except Exception as e:
        fail("T9.3", e)

    # T9.4 - best_params
    try:
        bp = wfa.best_params()
        assert isinstance(bp, dict)
        ok("T9.4 best_params çalışıyor")
    except Exception as e:
        fail("T9.4", e)

    # T9.5 - results_dataframe
    try:
        df2 = wfa.results_dataframe()
        assert not df2.empty
        ok(f"T9.5 results_dataframe satır={len(df2)}")
    except Exception as e:
        fail("T9.5", e)

    # T9.6 - boş results
    try:
        wfa2 = WFAManager(data, window_size=100, step_size=50)
        s2 = wfa2.summary()
        assert s2["status"] == "no_results"
        ok("T9.6 boş results → no_results")
    except Exception as e:
        fail("T9.6", e)

    # T9.7 - hatalı parametreler
    try:
        raised = False
        try:
            WFAManager(data, window_size=-1, step_size=50)
        except ValueError:
            raised = True
        assert raised
        ok("T9.7 negatif window_size ValueError fırlattı")
    except Exception as e:
        fail("T9.7", e)

except ImportError as e:
    fail("T9.x wfa_manager import", e)

# ══════════════════════════════════════════════════════════════════
# 10. AI CONFIDENCE BRIDGE
# ══════════════════════════════════════════════════════════════════

section("TEST 10: AIConfidenceBridge")

try:
    from super_otonom.ai_confidence_bridge import blend_omega_confidence

    # T10.1 - no external ML
    try:
        conf, note = blend_omega_confidence(0.7, {})
        assert note == "no_external_ml"
        assert conf == 0.7
        ok("T10.1 no_external_ml doğru")
    except Exception as e:
        fail("T10.1", e)

    # T10.2 - ml_score ile blend
    try:
        conf2, note2 = blend_omega_confidence(0.6, {"ml_score": 0.8})
        assert "ml_fusion" in note2
        assert 0.6 < conf2 < 0.8  # blend ortada olmalı
        ok(f"T10.2 ml_fusion blend conf={conf2:.3f}")
    except Exception as e:
        fail("T10.2", e)

    # T10.3 - geçersiz ml_score
    try:
        conf3, note3 = blend_omega_confidence(0.6, {"ml_score": "invalid"})
        assert note3 == "ml_score_invalid"
        ok("T10.3 geçersiz ml_score güvenli")
    except Exception as e:
        fail("T10.3", e)

    # T10.4 - omega_ml_score alternatif alan
    try:
        conf4, note4 = blend_omega_confidence(0.5, {"omega_ml_score": 0.9})
        assert "ml_fusion" in note4
        ok(f"T10.4 omega_ml_score kullanıldı conf={conf4:.3f}")
    except Exception as e:
        fail("T10.4", e)

except ImportError as e:
    fail("T10.x ai_confidence_bridge import", e)

# ══════════════════════════════════════════════════════════════════
# 11. AI LAYER
# ══════════════════════════════════════════════════════════════════

section("TEST 11: AILayer")

try:
    from super_otonom.ai_layer import AILayer

    # T11.1 - oluşturma (model yok → fallback)
    try:
        ai = AILayer(model_path="nonexistent_model.pt")
        assert ai.enabled is False
        ok("T11.1 AILayer model yok → fallback modu")
    except Exception as e:
        fail("T11.1", e)

    # T11.2 - validate_signal noisy rejim → HOLD
    try:
        sig, conf, reason = ai.validate_signal("BTC/USDT", "BUY", {"regime": "NOISY"})
        assert sig == "HOLD"
        assert reason == "REGIME_BLOCKED_NOISY"
        ok("T11.2 NOISY rejim → HOLD")
    except Exception as e:
        fail("T11.2", e)

    # T11.3 - mean reverting → HOLD
    try:
        sig3, conf3, reason3 = ai.validate_signal("BTC/USDT", "BUY", {"regime": "MEAN_REVERTING"})
        assert sig3 == "HOLD"
        assert reason3 == "REGIME_BLOCKED_MEAN_REVERTING"
        ok("T11.3 MEAN_REVERTING → HOLD")
    except Exception as e:
        fail("T11.3", e)

    # T11.4 - trending fallback (model yok)
    try:
        sig4, conf4, reason4 = ai.validate_signal("BTC/USDT", "BUY", {"regime": "TRENDING"})
        assert sig4 == "BUY"  # fallback → base_signal
        ok(f"T11.4 trending fallback sig={sig4} conf={conf4:.2f}")
    except Exception as e:
        fail("T11.4", e)

    # T11.5 - update_buffer
    try:
        candle = {"open": 100, "high": 102, "low": 99, "close": 101, "volume": 50}
        analysis = {"rsi": 55, "ema_diff": 0.01, "vol_ratio": 1.2, "bb_pct_b": 0.6}
        ai.update_buffer("BTC/USDT", candle, analysis)
        assert len(ai._buffer["BTC/USDT"]) == 1
        ok("T11.5 update_buffer çalışıyor")
    except Exception as e:
        fail("T11.5", e)

    # T11.6 - get_decision_reason
    try:
        reason = ai.get_decision_reason("HOLD", 0.5, {"regime": "TRENDING", "hurst": 0.4})
        assert isinstance(reason, str)
        ok(f"T11.6 get_decision_reason={reason}")
    except Exception as e:
        fail("T11.6", e)

    # T11.7 - explain
    try:
        exp = ai.explain(
            "BTC/USDT",
            "BUY",
            {"regime": "TRENDING", "hurst": 0.6, "volatility": 0.02},
            "BUY",
            0.7,
            "TECHNICAL",
        )
        assert "BTC/USDT" in exp
        ok("T11.7 explain çalışıyor")
    except Exception as e:
        fail("T11.7", e)

except ImportError as e:
    fail("T11.x ai_layer import", e)

# ══════════════════════════════════════════════════════════════════
# 12. HEALTH SUMMARY
# ══════════════════════════════════════════════════════════════════

section("TEST 12: HealthSummary")

try:
    from super_otonom.health_summary import format_durum_line, format_tick_health

    status = {
        "equity": 10500.0,
        "total_pnl": 500.0,
        "pnl_pct": 5.0,
        "peak_drawdown_pct": 2.1,
        "exposure_pct": 15.0,
        "total_trades": 10,
        "emergency_stop": False,
        "emergency_code_line": "—",
        "hard_limits": {"orders_in_window": 1, "order_limit": 5, "window_sec": 1.0},
        "rate_limit": {"rl_streak": 0, "rl_trip": 5},
    }

    # T12.1 - format_durum_line
    try:
        line = format_durum_line(status)
        assert "eq=" in line
        assert "pnl=" in line
        ok("T12.1 format_durum_line çalışıyor")
    except Exception as e:
        fail("T12.1", e)

    # T12.2 - format_tick_health
    try:
        dctx = {
            "symbol": "BTC/USDT",
            "tick_id": 42,
            "final_signal": "BUY",
            "entry_scale": "full",
            "liquidity_ratio": 0.8,
            "signal_quality": 75,
            "adj_signal_quality": 70,
            "effective_quality_min": 40,
            "omega_ai_log": "",
        }
        line2 = format_tick_health(status, dctx)
        assert "[OK]" in line2
        assert "BTC/USDT" in line2
        ok("T12.2 format_tick_health çalışıyor")
    except Exception as e:
        fail("T12.2", e)

    # T12.3 - emergency durumu
    try:
        status_em = dict(status)
        status_em["emergency_stop"] = True
        dctx_em = {"emergency_code": "EMERGENCY_STOP:drawdown"}
        line3 = format_tick_health(status_em, dctx_em)
        assert "[HALT]" in line3
        ok("T12.3 emergency → [HALT]")
    except Exception as e:
        fail("T12.3", e)

    # T12.4 - dctx None güvenli
    try:
        line4 = format_tick_health(status, None)
        assert isinstance(line4, str)
        ok("T12.4 dctx=None güvenli")
    except Exception as e:
        fail("T12.4", e)

except ImportError as e:
    fail("T12.x health_summary import", e)

# ══════════════════════════════════════════════════════════════════
# 13. REDIS BRIDGE
# ══════════════════════════════════════════════════════════════════

section("TEST 13: RedisBridge (mock)")

try:
    from super_otonom.redis_bridge import RedisBridge

    # T13.1 - Redis yok → graceful
    try:
        bridge = RedisBridge(url="redis://localhost:9999/0")
        assert bridge.is_connected is False
        ok("T13.1 Redis yok → is_connected=False")
    except Exception as e:
        fail("T13.1", e)

    # T13.2 - get_kline bağlantısız → None
    try:
        result = bridge.get_kline("BTCUSDT")
        assert result is None
        ok("T13.2 get_kline bağlantısız → None")
    except Exception as e:
        fail("T13.2", e)

    # T13.3 - get_all_klines
    try:
        all_k = bridge.get_all_klines()
        assert isinstance(all_k, dict)
        ok("T13.3 get_all_klines bağlantısız → dict")
    except Exception as e:
        fail("T13.3", e)

    # T13.4 - status
    try:
        s = bridge.status()
        assert s["connected"] is False
        ok("T13.4 status bağlantısız doğru")
    except Exception as e:
        fail("T13.4", e)

    # T13.5 - close güvenli
    try:
        bridge.close()
        ok("T13.5 close güvenli")
    except Exception as e:
        fail("T13.5", e)

    # T13.6 - subscribe bağlantısız → uyarı
    try:
        bridge.subscribe(lambda x: None)
        ok("T13.6 subscribe bağlantısız güvenli")
    except Exception as e:
        fail("T13.6", e)

except ImportError as e:
    fail("T13.x redis_bridge import", e)

# ══════════════════════════════════════════════════════════════════
# 14. ML CLIENT
# ══════════════════════════════════════════════════════════════════

section("TEST 14: MLClient")

try:
    from super_otonom.ml_client import (
        MLClient,
        format_ml_inference_payload,
        get_ml_client,
        reset_ml_client_for_tests,
    )

    # T14.1 - disabled client
    try:
        client = MLClient(enabled=False)
        result = asyncio.run(client.fetch_inference("BTC/USDT", {}))
        assert result.error == "disabled"
        assert result.score is None
        ok("T14.1 disabled client → error=disabled")
    except Exception as e:
        fail("T14.1", e)

    # T14.2 - format_ml_inference_payload
    try:
        analysis = {"signal": "BUY", "hurst": 0.6, "regime": "TRENDING"}
        payload = format_ml_inference_payload("BTC/USDT", analysis, tick_id=5)
        assert payload["symbol"] == "BTC/USDT"
        assert payload["tick_id"] == 5
        assert payload["schema"] == "super_otonom.ml.inference.v1"
        ok("T14.2 format_ml_inference_payload doğru")
    except Exception as e:
        fail("T14.2", e)

    # T14.3 - from_env
    try:
        reset_ml_client_for_tests()
        client3 = MLClient.from_env()
        assert client3._enabled is False  # URL yok
        ok("T14.3 from_env (URL yok → disabled)")
    except Exception as e:
        fail("T14.3", e)

    # T14.4 - enrich_analysis disabled
    try:
        analysis4 = {"signal": "BUY"}
        asyncio.run(client.enrich_analysis("BTC/USDT", analysis4))
        assert "ml_score" not in analysis4
        ok("T14.4 enrich_analysis disabled → ml_score yok")
    except Exception as e:
        fail("T14.4", e)

    # T14.5 - get_ml_client singleton
    try:
        reset_ml_client_for_tests()
        c1 = get_ml_client()
        c2 = get_ml_client()
        assert c1 is c2
        ok("T14.5 get_ml_client singleton")
    except Exception as e:
        fail("T14.5", e)

except ImportError as e:
    fail("T14.x ml_client import", e)

# ══════════════════════════════════════════════════════════════════
# 15. EXCHANGE ASYNC (CircuitBreaker)
# ══════════════════════════════════════════════════════════════════

section("TEST 15: CircuitBreaker / AsyncExchangeHandler")

try:
    from super_otonom.exchange_async import (
        AsyncExchangeHandler,
        CircuitBreaker,
        _fake_ohlcv,
        ohlcv_to_candles,
    )

    # T15.1 - CircuitBreaker başlangıç
    try:
        cb = CircuitBreaker(failure_threshold=3, recovery_time=60.0)
        assert cb.can_proceed() is True
        assert cb.state == "CLOSED"
        ok("T15.1 CircuitBreaker başlangıç CLOSED")
    except Exception as e:
        fail("T15.1", e)

    # T15.2 - failure → OPEN
    try:
        for _ in range(3):
            cb.record_failure()
        assert cb.is_open is True
        assert cb.can_proceed() is False
        ok("T15.2 3 hata → devre OPEN")
    except Exception as e:
        fail("T15.2", e)

    # T15.3 - success → CLOSED
    try:
        cb2 = CircuitBreaker(failure_threshold=3)
        cb2.record_failure()
        cb2.record_success()
        assert cb2.is_open is False
        assert cb2.failures == 0
        ok("T15.3 başarı → CLOSED")
    except Exception as e:
        fail("T15.3", e)

    # T15.4 - ohlcv_to_candles
    try:
        raw = [[1000, 100, 102, 99, 101, 50], [2000, 101, 103, 100, 102, 60]]
        candles = ohlcv_to_candles(raw)
        assert len(candles) == 2
        assert candles[0]["close"] == 101.0
        ok("T15.4 ohlcv_to_candles doğru")
    except Exception as e:
        fail("T15.4", e)

    # T15.5 - _fake_ohlcv
    try:
        fake = _fake_ohlcv("BTC/USDT", 10)
        assert len(fake) == 10
        ok("T15.5 _fake_ohlcv 10 mum üretildi")
    except Exception as e:
        fail("T15.5", e)

    # T15.6 - AsyncExchangeHandler simule mod (ccxt yok)
    try:
        handler = AsyncExchangeHandler("binance", testnet=True)
        result = asyncio.run(handler.fetch_all_ohlcv(["BTC/USDT"], limit=5))
        assert "BTC/USDT" in result
        ok("T15.6 AsyncExchangeHandler simule mod çalışıyor")
    except Exception as e:
        fail("T15.6", e)

    # T15.7 - circuit_breaker_status
    try:
        cb_status = handler.circuit_breaker_status()
        assert isinstance(cb_status, dict)
        ok("T15.7 circuit_breaker_status çalışıyor")
    except Exception as e:
        fail("T15.7", e)

except ImportError as e:
    fail("T15.x exchange_async import", e)

# ══════════════════════════════════════════════════════════════════
# 16. BACKTESTER
# ══════════════════════════════════════════════════════════════════

section("TEST 16: Backtester")

try:
    import numpy as np

    from super_otonom.backtester import (
        BacktestReport,
        _compute_max_drawdown_pct,
        _compute_sharpe,
        run_backtest,
    )

    # T16.1 - _compute_sharpe
    try:
        returns = np.array([0.01, 0.02, -0.01, 0.015, 0.005])
        sharpe = _compute_sharpe(returns, 252.0)
        assert isinstance(sharpe, float)
        ok(f"T16.1 _compute_sharpe={sharpe:.4f}")
    except Exception as e:
        fail("T16.1", e)

    # T16.2 - _compute_max_drawdown_pct
    try:
        equity = np.array([100, 110, 105, 95, 100, 115])
        dd = _compute_max_drawdown_pct(equity)
        assert dd > 0
        ok(f"T16.2 max_drawdown={dd:.2f}%")
    except Exception as e:
        fail("T16.2", e)

    # T16.3 - yetersiz mum → boş rapor
    try:
        candles = make_candles(10)
        report = run_backtest(candles, symbol="BTC/USDT", initial_capital=10000.0, min_bars=35)
        assert isinstance(report, BacktestReport)
        assert report.bars_simulated == 0
        ok("T16.3 yetersiz mum → boş rapor")
    except Exception as e:
        fail("T16.3", e)

    # T16.4 - tam backtest (yeterli mum)
    try:
        candles = make_candles(100)
        report2 = run_backtest(candles, symbol="BTC/USDT", initial_capital=10000.0, min_bars=35)
        assert isinstance(report2, BacktestReport)
        assert report2.bars_simulated > 0
        ok(f"T16.4 tam backtest bars={report2.bars_simulated} return={report2.total_return_pct}%")
    except Exception as e:
        fail("T16.4", e)

except ImportError as e:
    fail("T16.x backtester import", e)

# ══════════════════════════════════════════════════════════════════
# ÖZET
# ══════════════════════════════════════════════════════════════════

total = PASS + FAIL
print(f"""
{"=" * 60}
TOPLAM : {total}
GEÇEN  : {PASS}
FAIL   : {FAIL}
{"=" * 60}
{"✓ TÜM TESTLER GEÇTİ" if FAIL == 0 else f"✗ {FAIL} TEST BAŞARISIZ"}
""")

if FAIL > 0:
    sys.exit(1)
