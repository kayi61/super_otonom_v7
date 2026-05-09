"""
super_otonom v7.0 — Ana döngü
────────────────────────────────────────────────────────────────
v6.1 → analyze_v5_1, validate_and_calculate, sentiment/corr loglama
v6.2 → MTF config.MTF, OrderTracker, exchange→BotEngine, vb.
v7.0 → Sürüm numaraları __version__ / GENERAL / pyproject ile hizalı
v8.1 → Windows SIGINT/KeyboardInterrupt, CB_OPEN tick atlama, prep_symbol modül düzeyi
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from super_otonom import __version__ as _PKG_VERSION
from super_otonom.analyzer import MarketAnalyzer
from super_otonom.bot_engine import BotEngine
from super_otonom.config import ASYNC_EXCHANGE, GENERAL, MTF, PAIRS, RISK
from super_otonom.exchange_async import AsyncExchangeHandler, ohlcv_to_candles
from super_otonom.health_summary import (
    ensure_health_file_logger,
    format_durum_line,
    log_tick_health,
)
from super_otonom.kill_switch import apply_storm_trip_to_risk
from super_otonom.omega_regime import compute_omega_regime
from super_otonom.signal_fusion_engine import record_analyzer_snapshot

log = logging.getLogger("super_otonom.main")
logging.basicConfig(
    level=getattr(logging, GENERAL["log_level"], logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
)

# Sprint 4 M3 — Exchange heartbeat
_LAST_SUCCESSFUL_FETCH: float = 0.0
_HEARTBEAT_TIMEOUT_SEC: int   = int(os.getenv("HEARTBEAT_TIMEOUT_SEC", "120"))

# Sprint 4 M4 — Rate limit adaptive throttle
_RATE_LIMIT_HITS:    int   = 0
_ADAPTIVE_POLL_SEC:  float = float(_POLL_INTERVAL if "_POLL_INTERVAL" in dir() else 30)
logging.basicConfig(
    level=getattr(logging, GENERAL["log_level"], logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
)

if not GENERAL.get("paper_mode", True) and GENERAL.get("live_confirm") != "YES":
    log.critical(
        "LIVE mod aktif ama LIVE_CONFIRM=YES degil. "
        "Cikiliyor. Gercek emir gondermek icin .env dosyasina "
        "LIVE_CONFIRM=YES ekleyin."
    )
    sys.exit(1)

_POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SEC", "30"))
_shutdown = asyncio.Event()
_loop_counter = 0
_CB_OPEN_MSG = "CB_OPEN: %s atlandi"


def _handle_signal(*_: Any) -> None:
    log.warning("Kapatma sinyali alindi — temiz kapanış baslatiliyor...")
    _shutdown.set()


def _circuit_breaker_open(handler: AsyncExchangeHandler, symbol: str) -> bool:
    st = handler.circuit_breaker_status().get(symbol, "")
    return bool(st.startswith("OPEN"))


def _is_stale_data(candles_1h: List[Dict[str, float]], symbol: str) -> bool:
    """Stale data kontrolü. True ise veri çok eski."""
    if not candles_1h:
        return False
    _STALE_THRESHOLD_SEC = int(os.getenv("STALE_DATA_THRESHOLD_SEC", "300"))
    _last_candle_ts = float(candles_1h[-1].get("timestamp", 0)) / 1000.0
    _data_age_sec   = time.time() - _last_candle_ts
    if _last_candle_ts > 0 and _data_age_sec > _STALE_THRESHOLD_SEC:
        log.warning(
            "STALE_DATA | %s | veri_yasi=%.0fs > esik=%ds | tick atlandi",
            symbol, _data_age_sec, _STALE_THRESHOLD_SEC,
        )
        return True
    return False


def _apply_ob_safe_size(
    engine: Any, symbol: str, ob: Dict[str, Any],
    candles_1h: List[Dict[str, float]], analysis: Dict[str, Any],
    vol: float, ai_conf: float,
) -> None:
    """OB'dan güvenli boyut hesaplar ve analysis'e yazar."""
    if ob["asks"] and candles_1h:
        engine.sizer.set_trade_log(engine.trade_log)
        try:
            from super_otonom.redis_bridge import RedisBridge
            _rb = RedisBridge()
            _kline = _rb.get_kline(symbol.replace("/", ""))
            if _kline and _kline.get("updated_at"):

                last_ts = float(_kline["updated_at"])
            else:
                last_ts = float(candles_1h[-1].get("timestamp", time.time() * 1000))
        except Exception:
            last_ts = float(candles_1h[-1].get("timestamp", time.time() * 1000))
        safe_size = engine.sizer.validate_and_calculate(
            symbol=symbol, equity=engine.equity, order_book=ob,
            last_candle_ts=last_ts, volatility=vol, ai_conf=ai_conf,
        )
        analysis["ob_safe_size"] = safe_size
    elif ob["asks"]:
        engine.sizer.set_trade_log(engine.trade_log)
        analysis["ob_safe_size"] = engine.sizer.calculate_with_slippage(
            symbol=symbol, equity=engine.equity, order_book=ob,
            volatility=vol, ai_conf=0.55,
        )


async def prep_symbol_for_tick(
    symbol: str,
    handler: AsyncExchangeHandler,
    analyzer: MarketAnalyzer,
    engine: BotEngine,
    raw_data_1h: Dict[str, Any],
    raw_data_mtf: Dict[str, Any],
) -> Optional[Tuple[str, Dict[str, Any], List[Dict[str, float]]]]:
    """
    Tek sembol: mumlar → analiz → OB → likidite bağlamı.
    CB açık veya 1H yok → None (CB için CB_OPEN logu).
    """
    raw_1h = raw_data_1h.get(symbol)
    if not raw_1h:
        if _circuit_breaker_open(handler, symbol):
            log.warning(_CB_OPEN_MSG, symbol)
        else:
            log.debug("1H veri yok: %s", symbol)
        return None

    if _circuit_breaker_open(handler, symbol):
        log.warning(_CB_OPEN_MSG, symbol)
        return None

    candles_1h  = ohlcv_to_candles(raw_1h)
    raw_mtf     = raw_data_mtf.get(symbol, [])
    candles_mtf = ohlcv_to_candles(raw_mtf) if raw_mtf else []

    if _is_stale_data(candles_1h, symbol):
        return None

    if candles_mtf and MTF["enabled"]:
        analysis = analyzer.analyze_v5_1(symbol, candles_1h, candles_mtf)
    else:
        analysis = analyzer.analyze(symbol, candles_1h)

    log.debug(
        "ANALİZ | %s | regime=%s | hurst=%.3f | sinyal=%s | mtf=%s | mtf_filtered=%s",
        symbol,
        analysis.get("regime", "?"),
        analysis.get("hurst", 0.0),
        analysis.get("signal", "HOLD"),
        analysis.get("high_tf_trend", "N/A"),
        analysis.get("mtf_filtered", False),
    )

    record_analyzer_snapshot(symbol, analysis)

    ob = await handler.fetch_order_book(symbol, limit=ASYNC_EXCHANGE["ob_limit"])
    if apply_storm_trip_to_risk(engine.risk):
        log.critical("EMERGENCY_STOP | code=rate_limit_storm | order_book sonrasi")

    ai_conf = float(RISK.get("entry_min_confidence", 0.55))
    vol     = float(analysis.get("volatility", 0.01))

    _apply_ob_safe_size(engine, symbol, ob, candles_1h, analysis, vol, ai_conf)

    # Kelly/vol hedefi — apply_liquidity_context OB tavanı ile birleştirir
    technical_notional = engine.sizer.calculate(
        symbol,
        equity=engine.equity,
        volatility=vol,
        ai_conf=ai_conf,
    )
    analyzer.apply_liquidity_context(
        analysis,
        analysis.get("ob_safe_size"),
        technical_notional,
    )
    # Faz 71-80 zinciri (execution_pipeline) OB'yi analysis üzerinden okur
    analysis["order_book"] = ob
    return symbol, analysis, candles_1h


def _log_elite_startup(engine: Any) -> None:
    """
    Runbook (Elite): kalp atışı, OMEGA örnek satırı, kill-switch hazır.
    Canlı rejim/quality/size — her tick'te health / omega_ai_log.
    """
    log.info("[OK] Heartbeat | Status: Active (Kalp atışı başladı)")
    if GENERAL.get("dry_run"):
        log.info("[OK] DRY_RUN | Gercek emir yok, simulasyon (paper=on)")
    demo = {
        "regime": "TRENDING",
        "hurst": 0.6,
        "volatility": 0.02,
        "flash_crash": False,
    }
    oreg, _qm, sf, adj, _omlog = compute_omega_regime(demo, 74)
    log.info(
        "[OK] [OMEGA-AI] Rehber | Regime: %s | Quality: %d | SizeFactor: %.1f "
        "(ornek; canli degerler tick basina guncellenir)",
        oreg,
        adj,
        sf,
    )
    if not GENERAL.get("ml_service_enabled", False):
        log.info("[OK] Neural Link | ML_SERVICE_ENABLED=false (no_external_ml beklenir)")
    emg = bool(getattr(getattr(engine, "risk", None), "emergency_stop", False))
    if not emg:
        log.info("[OK] Monitoring Active | Kill-Switch: Ready (Zırhlar kuşanıldı)")
    else:
        log.warning("Monitoring | Kill-Switch: emergency_stop aktif — kontrol edin")


def _setup_signal_handlers(loop: Any) -> None:
    """Platform bazlı sinyal işleyicileri kurar."""
    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _handle_signal)
    else:
        log.info("Windows: ek SIGINT isleyicisi + KeyboardInterrupt ile temiz kapanis.")
        try:
            signal.signal(signal.SIGINT, lambda _s, _f: _handle_signal())
        except (ValueError, OSError, AttributeError) as exc:
            log.debug("Windows SIGINT baglanamadi: %s", exc)


def _update_adaptive_throttle(
    handler: Any, engine: Any
) -> None:
    """Rate limit CB durumuna göre poll interval'i günceller."""
    global _RATE_LIMIT_HITS, _ADAPTIVE_POLL_SEC
    cb_open_count = sum(
        1 for s in handler.circuit_breaker_status().values()
        if s.startswith("OPEN")
    )
    if cb_open_count > 0:
        _RATE_LIMIT_HITS += 1
        _ADAPTIVE_POLL_SEC = min(
            300, _POLL_INTERVAL * (1.5 ** min(_RATE_LIMIT_HITS, 5))
        )
        log.warning(
            "ADAPTIVE_THROTTLE | cb_open=%d | hits=%d | poll=%.0fs",
            cb_open_count, _RATE_LIMIT_HITS, _ADAPTIVE_POLL_SEC,
        )
        if engine.alerts is not None:
            engine.alerts.circuit_breaker(
                "MULTIPLE" if cb_open_count > 1 else "SINGLE",
                "OPEN",
                reason=f"{cb_open_count} sembol CB açık",
            )
    else:
        _RATE_LIMIT_HITS = max(0, _RATE_LIMIT_HITS - 1)
        _ADAPTIVE_POLL_SEC = max(_POLL_INTERVAL, _ADAPTIVE_POLL_SEC * 0.9)


def _process_tick_result(
    symbol: str,
    result: Dict[str, Any],
    candles_1h: List[Dict[str, float]],
    engine: Any,
) -> None:
    """Tek sembol tick sonucunu logla ve metrikleri güncelle."""
    hst = engine.status()
    log_tick_health(hst, result.get("decision_context"))

    reason = result.get("decision_reason", "")
    if reason:
        log.info(
            "AI KARAR | %s | sinyal=%s | guven=%.3f | gerekce=%s",
            symbol,
            result.get("final_signal", "HOLD"),
            result.get("ai_confidence") or 0.0,
            reason,
        )

    sent_status = result.get("sentiment_status", "UNKNOWN")
    corr_mult = result.get("corr_multiplier", 1.0)
    if sent_status not in ("N/A", "UNKNOWN") or corr_mult < 1.0:
        log.info(
            "V6 DURUM | %s | sentiment=%s | corr_mult=%.2f",
            symbol, sent_status, corr_mult,
        )

    if result.get("actions"):
        for act in result["actions"]:
            log.info("EYLEM | %s", act)
            act_type = act.get("type", "")
            if act_type in ("BUY", "SELL") and candles_1h:
                expected = float(candles_1h[-1]["close"])
                actual = float(act.get("price", expected))
                engine.metrics.record_slippage(symbol, expected, actual)


def _check_heartbeat(engine: Any) -> None:
    """Heartbeat timeout kontrolü."""
    if _LAST_SUCCESSFUL_FETCH <= 0:
        return
    _silence = time.time() - _LAST_SUCCESSFUL_FETCH
    if _silence > _HEARTBEAT_TIMEOUT_SEC:
        log.critical(
            "HEARTBEAT_TIMEOUT | %.0fs veri yok | esik=%ds",
            _silence, _HEARTBEAT_TIMEOUT_SEC,
        )
        if engine.alerts is not None:
            engine.alerts.system(
                "HEARTBEAT_TIMEOUT",
                detail=f"{_silence:.0f}s veri alınamadı",
                level="CRITICAL",
            )


async def _run_loop_iteration(
    handler: Any, analyzer: Any, engine: Any
) -> None:
    """Tek döngü iterasyonu — veri çek, analiz et, tick."""
    global _LAST_SUCCESSFUL_FETCH, _loop_counter
    _loop_counter += 1

    raw_data_1h: Dict[str, Any] = await handler.fetch_all_ohlcv(
        symbols=PAIRS,
        timeframe=ASYNC_EXCHANGE["timeframe"],
        limit=ASYNC_EXCHANGE["limit"],
    )
    _LAST_SUCCESSFUL_FETCH = time.time()

    _update_adaptive_throttle(handler, engine)

    raw_data_mtf: Dict[str, Any] = {}
    if MTF["enabled"]:
        raw_data_mtf = await handler.fetch_all_ohlcv(
            symbols=PAIRS,
            timeframe=MTF["timeframe"],
            limit=MTF["candle_limit"],
        )

    cb_status = handler.circuit_breaker_status()
    engine.metrics.update_circuit_breakers(cb_status)
    if any(s.startswith("OPEN") for s in cb_status.values()):
        log.warning("CircuitBreaker durum: %s", cb_status)

    if apply_storm_trip_to_risk(engine.risk):
        log.critical(
            "EMERGENCY_STOP | code=rate_limit_storm | "
            "borsa 429/lim firtinasi (kill-switch)",
        )

    prepped = await asyncio.gather(
        *(
            prep_symbol_for_tick(s, handler, analyzer, engine, raw_data_1h, raw_data_mtf)
            for s in PAIRS
        )
    )

    for row in prepped:
        if row is None:
            continue
        symbol, analysis, candles_1h = row
        if _circuit_breaker_open(handler, symbol):
            log.warning(_CB_OPEN_MSG, symbol)
            continue
        result = await engine.tick(symbol, analysis, candles_1h)
        _process_tick_result(symbol, result, candles_1h, engine)

    if _loop_counter % 10 == 0:
        await engine.check_orders()
        log.debug("OrderTracker kontrol edildi (loop=%d)", _loop_counter)

    st = engine.status()
    log.info(
        "DURUM | %s | corr_semb=%d | order_tracker=%s",
        format_durum_line(st),
        st.get("corr_tracked_symbols", 0),
        "aktif" if st.get("order_tracker_active") else "pasif",
    )


async def main() -> None:
    global _loop_counter
    loop = asyncio.get_running_loop()
    _setup_signal_handlers(loop)

    analyzer = MarketAnalyzer()
    engine = BotEngine(
        capital=float(os.getenv("INITIAL_CAPITAL", "1000")),
        paper=GENERAL["paper_mode"],
    )

    from super_otonom.config import EXCHANGES
    ex_cfg = EXCHANGES.get(GENERAL["default_exchange"], {})

    try:
        async with AsyncExchangeHandler(
            exchange_id=GENERAL["default_exchange"],
            api_key=ex_cfg.get("api_key", ""),
            api_secret=ex_cfg.get("api_secret", ""),
            testnet=ex_cfg.get("testnet", True),
            max_retries=ASYNC_EXCHANGE["max_retries"],
            retry_delay=ASYNC_EXCHANGE["retry_delay"],
            cb_failure_threshold=int(os.getenv("CB_FAILURE_THRESHOLD", "5")),
            cb_recovery_time=float(os.getenv("CB_RECOVERY_TIME", "60")),
        ) as handler:

            engine.set_exchange_handler(handler)
            log.info(
                "Bot baslatildi | mod=%s | exchange=%s | pairs=%s | poll=%ds | versiyon=%s | mtf=%s",
                engine.mode, GENERAL["default_exchange"], PAIRS, _POLL_INTERVAL,
                GENERAL.get("version", _PKG_VERSION),
                MTF["timeframe"] if MTF["enabled"] else "kapali",
            )
            ensure_health_file_logger(GENERAL.get("log_dir", "logs"))
            _log_elite_startup(engine)
            log.info(
                "Risk ozeti | SIGNAL_QUALITY_MIN=%s | max_open=%s | STOP_LOSS_PCT=%s",
                RISK.get("signal_quality_min"),
                RISK.get("max_open_positions"),
                RISK.get("stop_loss_pct"),
            )

            try:
                while not _shutdown.is_set():
                    try:
                        await _run_loop_iteration(handler, analyzer, engine)
                        engine._consecutive_errors = 0
                    except KeyboardInterrupt:
                        log.warning("KeyboardInterrupt — temiz kapanis")
                        _shutdown.set()
                        break
                    except Exception as exc:
                        log.exception("Ana dongu hatasi: %s", exc)
                        _consecutive_errors = getattr(engine, "_consecutive_errors", 0) + 1
                        engine._consecutive_errors = _consecutive_errors
                        _backoff = min(300, _POLL_INTERVAL * (2 ** min(_consecutive_errors - 1, 3)))
                        log.warning("BACKOFF | ardisik_hata=%d | bekleme=%ds", _consecutive_errors, _backoff)
                        try:
                            await asyncio.wait_for(_shutdown.wait(), timeout=_backoff)
                        except asyncio.TimeoutError:
                            pass
                        continue

                    try:
                        await asyncio.wait_for(_shutdown.wait(), timeout=_ADAPTIVE_POLL_SEC)
                    except asyncio.TimeoutError:
                        pass

                    _check_heartbeat(engine)

            except KeyboardInterrupt:
                log.warning("KeyboardInterrupt (async blok) — kapaniyor")
                _shutdown.set()
    finally:
        log.info("Bot kapatiliyor...")
        try:
            engine.shutdown()
        except Exception as exc:
            log.warning("engine.shutdown hata: %s", exc)
        log.info("Kapatma tamamlandi.")


if __name__ == "__main__":  # pragma: no cover
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.warning("KeyboardInterrupt (ust seviye) — cikildi")
        try:
            _shutdown.set()
        except Exception:
            pass


