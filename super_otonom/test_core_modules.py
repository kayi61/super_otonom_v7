# -*- coding: utf-8 -*-
"""
test_core_modules.py
bot_engine, analyzer, main_loop coverage testleri
Çalıştırma: python test_core_modules.py
"""

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from unittest.mock import AsyncMock, MagicMock, patch

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


def make_candles(n=60, base_price=100.0):
    candles = []
    p = base_price
    ts = time.time() * 1000 - n * 300_000
    for i in range(n):
        o = p
        h = p * 1.005
        lo = p * 0.995
        c = p * (1 + (0.002 if i % 3 == 0 else -0.001))
        candles.append(
            {"timestamp": ts, "open": o, "high": h, "low": lo, "close": c, "volume": 100.0 + i}
        )
        p = c
        ts += 300_000
    return candles


# ══════════════════════════════════════════════════════════════════
# 1. ANALYZER — teknik gösterge fonksiyonları
# ══════════════════════════════════════════════════════════════════

section("TEST 1: Analyzer — teknik göstergeler")

try:
    from super_otonom.analyzer import (
        MarketAnalyzer,
        _atr,
        _bollinger,
        _calculate_hurst,
        _ema,
        _empty,
        _falling_last_two_closes,
        _rising_last_two_closes,
        _rsi,
        _volume_ratio,
        detect_market_regime,
    )

    # T1.1 - _ema
    try:
        v = _ema([100.0, 102.0, 104.0, 103.0], period=3)
        assert isinstance(v, float) and v > 0
        ok(f"T1.1 _ema={v:.2f}")
    except Exception as e:
        fail("T1.1", e)

    # T1.2 - _ema boş liste
    try:
        v2 = _ema([], period=3)
        assert v2 == 0.0
        ok("T1.2 _ema boş → 0.0")
    except Exception as e:
        fail("T1.2", e)

    # T1.3 - _rsi yeterli veri
    try:
        closes = [100.0 + i * 0.5 for i in range(30)]
        rsi = _rsi(closes, period=14)
        assert 0 <= rsi <= 100
        ok(f"T1.3 _rsi={rsi:.2f}")
    except Exception as e:
        fail("T1.3", e)

    # T1.4 - _rsi yetersiz veri → 50
    try:
        rsi2 = _rsi([100.0, 101.0], period=14)
        assert rsi2 == 50.0
        ok("T1.4 _rsi yetersiz → 50.0")
    except Exception as e:
        fail("T1.4", e)

    # T1.5 - _bollinger
    try:
        closes = [100.0 + i for i in range(25)]
        mid, upper, lower, pct_b = _bollinger(closes, period=20)
        assert upper > mid > lower
        assert 0 <= pct_b <= 1
        ok(f"T1.5 _bollinger mid={mid:.2f} pct_b={pct_b:.2f}")
    except Exception as e:
        fail("T1.5", e)

    # T1.6 - _atr
    try:
        candles = make_candles(20)
        atr = _atr(candles, period=14)
        assert atr > 0
        ok(f"T1.6 _atr={atr:.4f}")
    except Exception as e:
        fail("T1.6", e)

    # T1.7 - _volume_ratio
    try:
        candles = make_candles(30)
        vr = _volume_ratio(candles, short=5, long=20)
        assert vr > 0
        ok(f"T1.7 _volume_ratio={vr:.2f}")
    except Exception as e:
        fail("T1.7", e)

    # T1.8 - _calculate_hurst
    try:
        import random

        random.seed(42)
        ts = [100.0 + i * 0.5 + random.uniform(-2, 2) for i in range(100)]
        h = _calculate_hurst(ts)
        assert 0 < h < 1
        ok(f"T1.8 hurst={h:.3f}")
    except Exception as e:
        fail("T1.8", e)

    # T1.9 - _rising / _falling
    try:
        assert _rising_last_two_closes([100.0, 101.0, 102.0]) is True
        assert _falling_last_two_closes([102.0, 101.0, 100.0]) is True
        assert _rising_last_two_closes([102.0, 101.0]) is False
        ok("T1.9 _rising/_falling doğru")
    except Exception as e:
        fail("T1.9", e)

    # T1.10 - detect_market_regime
    try:
        assert detect_market_regime(0.6) == "TRENDING"
        assert detect_market_regime(0.4) == "MEAN_REVERTING"
        assert detect_market_regime(0.5) == "NOISY"
        ok("T1.10 detect_market_regime doğru")
    except Exception as e:
        fail("T1.10", e)

    # T1.11 - _empty
    try:
        e = _empty("BTC/USDT")
        assert e["signal"] == "HOLD"
        assert e["symbol"] == "BTC/USDT"
        ok("T1.11 _empty doğru")
    except Exception as e:
        fail("T1.11", e)

except ImportError as e:
    fail("T1.x analyzer import", e)

# ══════════════════════════════════════════════════════════════════
# 2. ANALYZER — MarketAnalyzer sınıfı
# ══════════════════════════════════════════════════════════════════

section("TEST 2: MarketAnalyzer sınıfı")

try:
    from super_otonom.analyzer import MarketAnalyzer

    # T2.1 - analyze yeterli mum
    try:
        analyzer = MarketAnalyzer()
        candles = make_candles(60)
        result = analyzer.analyze("BTC/USDT", candles)
        assert result["symbol"] == "BTC/USDT"
        assert result["signal"] in ("BUY", "SELL", "HOLD")
        assert "hurst" in result
        assert "regime" in result
        ok(f"T2.1 analyze signal={result['signal']} regime={result['regime']}")
    except Exception as e:
        fail("T2.1", e)

    # T2.2 - analyze yetersiz mum
    try:
        result2 = analyzer.analyze("ETH/USDT", make_candles(5))
        assert result2["signal"] == "HOLD"
        ok("T2.2 yetersiz mum → HOLD")
    except Exception as e:
        fail("T2.2", e)

    # T2.3 - analyze_v5_1 (MTF)
    try:
        candles_1h = make_candles(60)
        candles_4h = make_candles(50, base_price=100.0)
        result3 = analyzer.analyze_v5_1("BTC/USDT", candles_1h, candles_4h)
        assert result3["signal"] in ("BUY", "SELL", "HOLD")
        assert "high_tf_trend" in result3
        ok(f"T2.3 analyze_v5_1 signal={result3['signal']} mtf={result3.get('high_tf_trend')}")
    except Exception as e:
        fail("T2.3", e)

    # T2.4 - apply_liquidity_context
    try:
        analysis = {"signal": "BUY", "ob_safe_size": 500.0}
        analyzer.apply_liquidity_context(analysis, ob_safe=500.0, target_notional=1000.0)
        assert "liquidity_ratio" in analysis
        ok(f"T2.4 apply_liquidity_context liq={analysis.get('liquidity_ratio'):.2f}")
    except Exception as e:
        fail("T2.4", e)

    # T2.5 - score_signal_quality
    try:
        candles = make_candles(60)
        result = analyzer.analyze("BTC/USDT", candles)
        score, penalties, components, main = analyzer.score_signal_quality(result)
        assert 0 <= score <= 100
        ok(f"T2.5 score_signal_quality score={score}")
    except Exception as e:
        fail("T2.5", e)

    # T2.6 - summary
    try:
        s = analyzer.summary()
        assert isinstance(s, str)
        ok("T2.6 summary çalışıyor")
    except Exception as e:
        fail("T2.6", e)

    # T2.7 - boş mum listesi
    try:
        result7 = analyzer.analyze("SOL/USDT", [])
        assert result7["signal"] == "HOLD"
        ok("T2.7 boş mum → HOLD")
    except Exception as e:
        fail("T2.7", e)

    # T2.8 - trending up sinyal
    try:
        trending = make_candles(60, base_price=100.0)
        for i in range(len(trending)):
            trending[i]["close"] = 100.0 + i * 0.5
            trending[i]["high"] = trending[i]["close"] * 1.002
            trending[i]["low"] = trending[i]["close"] * 0.998
        result8 = analyzer.analyze("BTC/USDT", trending)
        ok(f"T2.8 trending analiz signal={result8['signal']}")
    except Exception as e:
        fail("T2.8", e)

except ImportError as e:
    fail("T2.x MarketAnalyzer import", e)

# ══════════════════════════════════════════════════════════════════
# 3. EXECUTION SIMULATOR
# ══════════════════════════════════════════════════════════════════

section("TEST 3: ExecutionSimulator")

try:
    from super_otonom.bot_engine import ExecutionSimulator

    # T3.1 - BUY simülasyonu
    try:
        sim = ExecutionSimulator(seed=42)
        result = asyncio.run(sim.simulate_order("buy", 100.0, 1000.0, paper=True))
        assert result["executed_price"] > 100.0
        assert 0 < result["fill_ratio"] <= 1.0
        assert result["slippage"] >= 0
        ok(
            f"T3.1 BUY sim fill_ratio={result['fill_ratio']:.2f} price={result['executed_price']:.2f}"
        )
    except Exception as e:
        fail("T3.1", e)

    # T3.2 - SELL simülasyonu
    try:
        result2 = asyncio.run(sim.simulate_order("sell", 100.0, 1000.0, paper=True))
        assert result2["executed_price"] < 100.0
        ok(f"T3.2 SELL sim price={result2['executed_price']:.2f}")
    except Exception as e:
        fail("T3.2", e)

    # T3.3 - paper=False (no sleep)
    try:
        result3 = asyncio.run(sim.simulate_order("buy", 50.0, 500.0, paper=False))
        assert result3["executed_price"] > 0
        ok("T3.3 paper=False çalışıyor")
    except Exception as e:
        fail("T3.3", e)

    # T3.4 - deterministik seed
    try:
        sim1 = ExecutionSimulator(seed=123)
        sim2 = ExecutionSimulator(seed=123)
        r1 = asyncio.run(sim1.simulate_order("buy", 100.0, 1000.0, paper=False))
        r2 = asyncio.run(sim2.simulate_order("buy", 100.0, 1000.0, paper=False))
        assert abs(r1["executed_price"] - r2["executed_price"]) < 1e-9
        ok("T3.4 deterministik seed çalışıyor")
    except Exception as e:
        fail("T3.4", e)

except ImportError as e:
    fail("T3.x ExecutionSimulator import", e)

# ══════════════════════════════════════════════════════════════════
# 4. TRADE LOGGER
# ══════════════════════════════════════════════════════════════════

section("TEST 4: TradeLogger")

try:
    import tempfile

    from super_otonom.bot_engine import TradeLogger

    # T4.1 - log_trade
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            tmp_path = f.name
        logger = TradeLogger(filepath=tmp_path)
        logger.log_trade({"symbol": "BTC/USDT", "pnl": 10.5, "reason": "TAKE_PROFIT"})
        with open(tmp_path, encoding="utf-8") as f:
            content = f.read()
        assert "BTC/USDT" in content
        ok("T4.1 log_trade dosyaya yazdı")
    except Exception as e:
        fail("T4.1", e)

    # T4.2 - çoklu kayıt
    try:
        logger.log_trade({"symbol": "ETH/USDT", "pnl": -5.0})
        logger.log_trade({"symbol": "SOL/USDT", "pnl": 3.0})
        with open(tmp_path, encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) >= 3
        ok(f"T4.2 çoklu kayıt satır={len(lines)}")
    except Exception as e:
        fail("T4.2", e)

except ImportError as e:
    fail("T4.x TradeLogger import", e)

# ══════════════════════════════════════════════════════════════════
# 5. BOT ENGINE — temel işlemler
# ══════════════════════════════════════════════════════════════════

section("TEST 5: BotEngine — temel işlemler")

try:
    from super_otonom.bot_engine import BotEngine

    # T5.1 - oluşturma
    try:
        if os.path.exists("data/bot_state.json"):
            os.remove("data/bot_state.json")
        engine = BotEngine(capital=10000.0, paper=True)
        assert engine.equity == 10000.0
        assert engine.mode == "PAPER"
        ok("T5.1 BotEngine oluşturuldu")
    except Exception as e:
        fail("T5.1", e)

    # T5.2 - status
    try:
        st = engine.status()
        assert st["equity"] == 10000.0
        assert st["mode"] == "PAPER"
        assert "open_positions" in st
        ok("T5.2 status çalışıyor")
    except Exception as e:
        fail("T5.2", e)

    # T5.3 - _calc_wr_rr boş trade_log
    try:
        wr, rr, guven = engine._calc_wr_rr()
        assert wr is None
        assert guven == "kapanan_islem_yok"
        ok("T5.3 _calc_wr_rr boş → None")
    except Exception as e:
        fail("T5.3", e)

    # T5.4 - _calc_wr_rr veri var
    try:
        engine.trade_log = [
            {"pnl": 10.0},
            {"pnl": -5.0},
            {"pnl": 8.0},
            {"pnl": -3.0},
            {"pnl": 12.0},
            {"pnl": 6.0},
        ]
        wr2, rr2, guven2 = engine._calc_wr_rr()
        assert wr2 is not None
        assert rr2 is not None
        ok(f"T5.4 _calc_wr_rr wr={wr2:.2f} rr={rr2:.2f}")
    except Exception as e:
        fail("T5.4", e)

    # T5.5 - _avg_volume
    try:
        candles = make_candles(40)
        avg_vol = engine._avg_volume(candles)
        assert avg_vol > 0
        ok(f"T5.5 _avg_volume={avg_vol:.2f}")
    except Exception as e:
        fail("T5.5", e)

    # T5.6 - _open_exposure boş pozisyon
    try:
        exp = engine._open_exposure({"BTC/USDT": 50000.0})
        assert exp == 0.0
        ok("T5.6 _open_exposure boş → 0")
    except Exception as e:
        fail("T5.6", e)

    # T5.7 - calculate_position HOLD → 1.0
    try:
        mult = engine.calculate_position("BTC/USDT", "HOLD")
        assert mult == 1.0
        ok("T5.7 calculate_position HOLD → 1.0")
    except Exception as e:
        fail("T5.7", e)

    # T5.8 - calculate_position BUY
    try:
        mult2 = engine.calculate_position("BTC/USDT", "BUY")
        assert 0 < mult2 <= 1.2
        ok(f"T5.8 calculate_position BUY mult={mult2:.3f}")
    except Exception as e:
        fail("T5.8", e)

    # T5.9 - tick boş candles
    try:
        result = asyncio.run(engine.tick("BTC/USDT", {}, []))
        assert result["final_signal"] == "HOLD"
        ok("T5.9 tick boş candles → HOLD")
    except Exception as e:
        fail("T5.9", e)

    # T5.10 - tick normal
    try:
        engine2 = BotEngine(capital=10000.0, paper=True)
        candles = make_candles(60)
        analysis = {
            "signal": "HOLD",
            "regime": "NOISY",
            "volatility": 0.02,
            "hurst": 0.5,
            "rsi": 50.0,
            "avg_volume": 100.0,
        }
        result2 = asyncio.run(engine2.tick("BTC/USDT", analysis, candles))
        assert result2["symbol"] == "BTC/USDT"
        assert "final_signal" in result2
        ok(f"T5.10 tick normal signal={result2['final_signal']}")
    except Exception as e:
        fail("T5.10", e)

    # T5.11 - _reset_daily_if_needed
    try:
        engine3 = BotEngine(capital=10000.0, paper=True)
        engine3._reset_daily_if_needed()
        ok("T5.11 _reset_daily_if_needed güvenli")
    except Exception as e:
        fail("T5.11", e)

    # T5.12 - shutdown
    try:
        engine4 = BotEngine(capital=5000.0, paper=True)
        engine4.shutdown()
        ok("T5.12 shutdown çalışıyor")
    except Exception as e:
        fail("T5.12", e)

    # T5.13 - set_exchange_handler
    try:
        mock_handler = MagicMock()
        mock_handler.get_order_status = AsyncMock(return_value="filled")
        mock_handler.cancel_order = AsyncMock(return_value=True)
        engine5 = BotEngine(capital=10000.0, paper=True)
        engine5.set_exchange_handler(mock_handler)
        assert engine5._order_tracker is not None
        ok("T5.13 set_exchange_handler çalışıyor")
    except Exception as e:
        fail("T5.13", e)

    # T5.14 - tick_async
    try:
        engine6 = BotEngine(capital=10000.0, paper=True)
        candles = make_candles(60)
        result6 = asyncio.run(engine6.tick_async("BTC/USDT", {}, candles))
        assert "final_signal" in result6
        ok("T5.14 tick_async çalışıyor")
    except Exception as e:
        fail("T5.14", e)

    # T5.15 - _tick_update_unrealized boş pozisyon
    try:
        engine7 = BotEngine(capital=10000.0, paper=True)
        engine7._tick_update_unrealized("BTC/USDT", 50000.0)
        ok("T5.15 _tick_update_unrealized boş pozisyon güvenli")
    except Exception as e:
        fail("T5.15", e)

    # T5.16 - _tick_check_trailing_stops
    try:
        engine8 = BotEngine(capital=10000.0, paper=True)
        engine8.open_positions = {
            "ETH/USDT": {"entry": 3000.0, "qty": 1.0, "size": 3000.0, "peak": 3100.0}
        }
        stops = engine8._tick_check_trailing_stops("BTC/USDT")
        assert len(stops) == 1
        ok("T5.16 _tick_check_trailing_stops çalışıyor")
    except Exception as e:
        fail("T5.16", e)

    # T5.17 - emergency_liquidate boş pozisyon
    try:
        engine9 = BotEngine(capital=10000.0, paper=True)
        result9 = asyncio.run(engine9.emergency_liquidate("test"))
        assert result9["liquidated"] == []
        ok("T5.17 emergency_liquidate boş pozisyon güvenli")
    except Exception as e:
        fail("T5.17", e)

except ImportError as e:
    fail("T5.x BotEngine import", e)

# ══════════════════════════════════════════════════════════════════
# 6. MAIN LOOP — yardımcı fonksiyonlar
# ══════════════════════════════════════════════════════════════════

section("TEST 6: MainLoop yardımcı fonksiyonlar")

try:
    from super_otonom.main_loop import (
        _apply_ob_safe_size,
        _check_heartbeat,
        _circuit_breaker_open,
        _is_stale_data,
        _process_tick_result,
        _update_adaptive_throttle,
    )

    # T6.1 - _circuit_breaker_open False
    try:
        mock_handler = MagicMock()
        mock_handler.circuit_breaker_status.return_value = {"BTC/USDT": "CLOSED"}
        result = _circuit_breaker_open(mock_handler, "BTC/USDT")
        assert result is False
        ok("T6.1 _circuit_breaker_open CLOSED → False")
    except Exception as e:
        fail("T6.1", e)

    # T6.2 - _circuit_breaker_open True
    try:
        mock_handler2 = MagicMock()
        mock_handler2.circuit_breaker_status.return_value = {"BTC/USDT": "OPEN (recovery=30s)"}
        result2 = _circuit_breaker_open(mock_handler2, "BTC/USDT")
        assert result2 is True
        ok("T6.2 _circuit_breaker_open OPEN → True")
    except Exception as e:
        fail("T6.2", e)

    # T6.3 - _is_stale_data boş liste
    try:
        result3 = _is_stale_data([], "BTC/USDT")
        assert result3 is False
        ok("T6.3 _is_stale_data boş → False")
    except Exception as e:
        fail("T6.3", e)

    # T6.4 - _is_stale_data taze veri
    try:
        fresh_candles = [{"timestamp": time.time() * 1000}]
        result4 = _is_stale_data(fresh_candles, "BTC/USDT")
        assert result4 is False
        ok("T6.4 _is_stale_data taze → False")
    except Exception as e:
        fail("T6.4", e)

    # T6.5 - _is_stale_data eski veri
    try:
        with patch.dict(os.environ, {"STALE_DATA_THRESHOLD_SEC": "60"}):
            old_candles = [{"timestamp": (time.time() - 400) * 1000}]
            result5 = _is_stale_data(old_candles, "BTC/USDT")
            assert result5 is True
        ok("T6.5 _is_stale_data eski → True")
    except Exception as e:
        fail("T6.5", e)

    # T6.6 - _process_tick_result
    try:
        mock_engine = MagicMock()
        mock_engine.status.return_value = {
            "equity": 10000.0,
            "pnl_pct": 1.0,
            "exposure_pct": 10.0,
            "emergency_stop": False,
            "hard_limits": {"orders_in_window": 0, "order_limit": 5, "window_sec": 1.0},
            "rate_limit": {"rl_streak": 0, "rl_trip": 5},
            "peak_drawdown_pct": 0.5,
            "total_trades": 5,
            "total_pnl": 100.0,
            "emergency_code_line": "—",
        }
        mock_engine.metrics = MagicMock()
        result6 = {
            "final_signal": "BUY",
            "decision_reason": "test",
            "ai_confidence": 0.7,
            "sentiment_status": "NEUTRAL",
            "corr_multiplier": 1.0,
            "actions": [],
            "decision_context": None,
        }
        _process_tick_result("BTC/USDT", result6, make_candles(10), mock_engine)
        ok("T6.6 _process_tick_result çalışıyor")
    except Exception as e:
        fail("T6.6", e)

    # T6.7 - _check_heartbeat
    try:
        mock_engine2 = MagicMock()
        _check_heartbeat(mock_engine2)
        ok("T6.7 _check_heartbeat çalışıyor")
    except Exception as e:
        fail("T6.7", e)

    # T6.8 - _apply_ob_safe_size boş ob
    try:
        mock_engine3 = MagicMock()
        mock_engine3.equity = 10000.0
        mock_engine3.trade_log = []
        ob_empty = {"asks": [], "bids": []}
        analysis = {}
        _apply_ob_safe_size(
            mock_engine3, "BTC/USDT", ob_empty, make_candles(10), analysis, 0.02, 0.6
        )
        assert "ob_safe_size" not in analysis
        ok("T6.8 _apply_ob_safe_size boş ob → ob_safe_size yok")
    except Exception as e:
        fail("T6.8", e)

    # T6.9 - _update_adaptive_throttle
    try:
        mock_handler3 = MagicMock()
        mock_handler3.circuit_breaker_status.return_value = {}
        mock_engine4 = MagicMock()
        mock_engine4.alerts = None
        _update_adaptive_throttle(mock_handler3, mock_engine4)
        ok("T6.9 _update_adaptive_throttle çalışıyor")
    except Exception as e:
        fail("T6.9", e)

    # T6.10 - _process_tick_result actions ile
    try:
        mock_engine5 = MagicMock()
        mock_engine5.status.return_value = {
            "equity": 10000.0,
            "pnl_pct": 1.0,
            "exposure_pct": 10.0,
            "emergency_stop": False,
            "hard_limits": {"orders_in_window": 0, "order_limit": 5, "window_sec": 1.0},
            "rate_limit": {"rl_streak": 0, "rl_trip": 5},
            "peak_drawdown_pct": 0.0,
            "total_trades": 1,
            "total_pnl": 50.0,
            "emergency_code_line": "—",
        }
        mock_engine5.metrics = MagicMock()
        result10 = {
            "final_signal": "BUY",
            "decision_reason": "",
            "ai_confidence": 0.8,
            "sentiment_status": "N/A",
            "corr_multiplier": 0.8,
            "actions": [{"type": "BUY", "price": 100.0, "symbol": "BTC/USDT"}],
            "decision_context": None,
        }
        _process_tick_result("BTC/USDT", result10, make_candles(10), mock_engine5)
        ok("T6.10 _process_tick_result actions ile çalışıyor")
    except Exception as e:
        fail("T6.10", e)

except ImportError as e:
    fail("T6.x main_loop import", e)

# ══════════════════════════════════════════════════════════════════
# 7. BOT ENGINE — close_on_strategy_change
# ══════════════════════════════════════════════════════════════════

section("TEST 7: BotEngine — close_on_strategy_change")

try:
    from super_otonom.bot_engine import BotEngine

    # T7.1 - boş pozisyon
    try:
        eng = BotEngine(capital=10000.0, paper=True)
        candles = make_candles(60)
        result = asyncio.run(eng.close_on_strategy_change("BTC/USDT", candles, {}))
        assert result["final_signal"] == "HOLD"
        ok("T7.1 close_on_strategy_change boş pozisyon")
    except Exception as e:
        fail("T7.1", e)

    # T7.2 - boş candles
    try:
        eng2 = BotEngine(capital=10000.0, paper=True)
        result2 = asyncio.run(eng2.close_on_strategy_change("BTC/USDT", [], {}))
        assert result2["final_signal"] == "HOLD"
        ok("T7.2 close_on_strategy_change boş candles")
    except Exception as e:
        fail("T7.2", e)

except ImportError as e:
    fail("T7.x import", e)

# ══════════════════════════════════════════════════════════════════
# 8. ORDER TRACKER
# ══════════════════════════════════════════════════════════════════

section("TEST 8: OrderTracker")

try:
    from super_otonom.bot_engine import OrderTracker

    # T8.1 - track
    try:
        mock_ex = MagicMock()
        mock_ex.get_order_status = AsyncMock(return_value="filled")
        mock_ex.cancel_order = AsyncMock(return_value=True)
        tracker = OrderTracker(mock_ex)
        tracker.track("order_001", "BTC/USDT")
        assert "order_001" in tracker.active_orders
        ok("T8.1 track çalışıyor")
    except Exception as e:
        fail("T8.1", e)

    # T8.2 - check_status filled
    try:
        asyncio.run(tracker.check_status())
        assert "order_001" not in tracker.active_orders
        ok("T8.2 check_status filled → kaldırıldı")
    except Exception as e:
        fail("T8.2", e)

    # T8.3 - check_status timeout
    try:
        mock_ex2 = MagicMock()
        mock_ex2.get_order_status = AsyncMock(return_value="open")
        mock_ex2.cancel_order = AsyncMock(return_value=True)
        tracker2 = OrderTracker(mock_ex2)
        tracker2._timeout_sec = 0
        tracker2.track("order_002", "ETH/USDT")
        tracker2.active_orders["order_002"]["start_time"] = time.time() - 100
        asyncio.run(tracker2.check_status())
        assert "order_002" not in tracker2.active_orders
        ok("T8.3 check_status timeout → iptal edildi")
    except Exception as e:
        fail("T8.3", e)

    # T8.4 - check_status hata toleransı
    try:
        mock_ex3 = MagicMock()
        mock_ex3.get_order_status = AsyncMock(side_effect=Exception("network error"))
        tracker3 = OrderTracker(mock_ex3)
        tracker3.track("order_003", "SOL/USDT")
        asyncio.run(tracker3.check_status())
        ok("T8.4 check_status hata toleransı")
    except Exception as e:
        fail("T8.4", e)

except ImportError as e:
    fail("T8.x OrderTracker import", e)

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
