"""
super_otonom v7.0 — Ana döngü
────────────────────────────────────────────────────────────────
v6.1 → analyze_v5_1, validate_and_calculate, sentiment/corr loglama
v6.2 → MTF config.MTF, OrderTracker, exchange→BotEngine, vb.
v7.0 → Sürüm numaraları __version__ / GENERAL / pyproject ile hizalı
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time
from typing import Any, Dict

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

log = logging.getLogger("super_otonom.main")
logging.basicConfig(
    level=getattr(logging, GENERAL["log_level"], logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
)

if not GENERAL.get("paper_mode", True):
    if GENERAL.get("live_confirm") != "YES":
        log.critical(
            "LIVE mod aktif ama LIVE_CONFIRM=YES degil. "
            "Cikiliyor. Gercek emir gondermek icin .env dosyasina "
            "LIVE_CONFIRM=YES ekleyin."
        )
        sys.exit(1)

_POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SEC", "30"))
_shutdown       = asyncio.Event()
_loop_counter   = 0


def _handle_signal(*_: Any) -> None:
    log.warning("Kapatma sinyali alindi — temiz kapanış baslatiliyor...")
    _shutdown.set()


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
        oreg, adj, sf,
    )
    if not GENERAL.get("ml_service_enabled", False):
        log.info("[OK] Neural Link | ML_SERVICE_ENABLED=false (no_external_ml beklenir)")
    emg = bool(getattr(getattr(engine, "risk", None), "emergency_stop", False))
    if not emg:
        log.info("[OK] Monitoring Active | Kill-Switch: Ready (Zırhlar kuşanıldı)")
    else:
        log.warning("Monitoring | Kill-Switch: emergency_stop aktif — kontrol edin")


async def main() -> None:
    global _loop_counter
    loop = asyncio.get_running_loop()
    # Windows (ProactorEventLoop): add_signal_handler desteklenmez → NotImplementedError
    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _handle_signal)
    else:
        log.info(
            "Windows: SIGINT/SIGTERM asyncio ile baglanmadi; "
            "Cikis: Ctrl+C veya gorev yoneticisinden sonlandir."
        )

    analyzer = MarketAnalyzer()
    engine   = BotEngine(
        capital=float(os.getenv("INITIAL_CAPITAL", "1000")),
        paper=GENERAL["paper_mode"],
    )

    from super_otonom.config import EXCHANGES
    ex_cfg = EXCHANGES.get(GENERAL["default_exchange"], {})

    async with AsyncExchangeHandler(
        exchange_id          = GENERAL["default_exchange"],
        api_key              = ex_cfg.get("api_key", ""),
        api_secret           = ex_cfg.get("api_secret", ""),
        testnet              = ex_cfg.get("testnet", True),
        max_retries          = ASYNC_EXCHANGE["max_retries"],
        retry_delay          = ASYNC_EXCHANGE["retry_delay"],
        cb_failure_threshold = int(os.getenv("CB_FAILURE_THRESHOLD", "5")),
        cb_recovery_time     = float(os.getenv("CB_RECOVERY_TIME", "60")),
    ) as handler:

        # FIX: OrderTracker için exchange handler BotEngine'e ilet
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

        while not _shutdown.is_set():
            _loop_counter += 1
            try:
                # ── 1. Tüm pariteleri paralel çek ────────────────────────────
                raw_data_1h: Dict[str, Any] = await handler.fetch_all_ohlcv(
                    symbols   = PAIRS,
                    timeframe = ASYNC_EXCHANGE["timeframe"],
                    limit     = ASYNC_EXCHANGE["limit"],
                )

                # FIX: 4H timeframe artık config.MTF'den geliyor
                raw_data_mtf: Dict[str, Any] = {}
                if MTF["enabled"]:
                    raw_data_mtf = await handler.fetch_all_ohlcv(
                        symbols   = PAIRS,
                        timeframe = MTF["timeframe"],
                        limit     = MTF["candle_limit"],
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

                # ── 2. Her parite için analiz + engine tick ───────────────────
                for symbol in PAIRS:
                    raw_1h = raw_data_1h.get(symbol)
                    if not raw_1h:
                        log.debug("1H veri yok: %s", symbol)
                        continue

                    candles_1h  = ohlcv_to_candles(raw_1h)
                    raw_mtf     = raw_data_mtf.get(symbol, [])
                    candles_mtf = ohlcv_to_candles(raw_mtf) if raw_mtf else []

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

                    ob = await handler.fetch_order_book(
                        symbol, limit=ASYNC_EXCHANGE["ob_limit"]
                    )
                    if apply_storm_trip_to_risk(engine.risk):
                        log.critical(
                            "EMERGENCY_STOP | code=rate_limit_storm | order_book sonrasi",
                        )

                    if ob["asks"] and candles_1h:
                        engine.sizer.set_trade_log(engine.trade_log)
                        last_ts = float(candles_1h[-1].get("timestamp", time.time() * 1000))
                        safe_size = engine.sizer.validate_and_calculate(
                            symbol         = symbol,
                            equity         = engine.equity,
                            order_book     = ob,
                            last_candle_ts = last_ts,
                            volatility     = float(analysis.get("volatility", 0.01)),
                            ai_conf        = float(RISK.get("entry_min_confidence", 0.55)),
                        )
                        analysis["ob_safe_size"] = safe_size
                    elif ob["asks"]:
                        engine.sizer.set_trade_log(engine.trade_log)
                        analysis["ob_safe_size"] = engine.sizer.calculate_with_slippage(
                            symbol     = symbol,
                            equity     = engine.equity,
                            order_book = ob,
                            volatility = float(analysis.get("volatility", 0.01)),
                            ai_conf    = 0.55,
                        )

                    target_notional = engine.sizer.calculate(
                        symbol,
                        equity=engine.equity,
                        volatility=float(analysis.get("volatility", 0.01)),
                        ai_conf=float(RISK.get("entry_min_confidence", 0.55)),
                    )
                    analyzer.apply_liquidity_context(
                        analysis,
                        analysis.get("ob_safe_size"),
                        target_notional,
                    )

                    result = await engine.tick(symbol, analysis, candles_1h)

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
                    corr_mult   = result.get("corr_multiplier", 1.0)
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
                                actual   = float(act.get("price", expected))
                                engine.metrics.record_slippage(symbol, expected, actual)

                # FIX: OrderTracker her 10 döngüde bir çağrılır (async düzgün await edilir)
                if _loop_counter % 10 == 0:
                    await engine.check_orders()
                    log.debug("OrderTracker kontrol edildi (loop=%d)", _loop_counter)

                # ── 3. Döngü sonu — kokpit (sigortalar + 429) ─────────────────
                st = engine.status()
                log.info(
                    "DURUM | %s | corr_semb=%d | order_tracker=%s",
                    format_durum_line(st),
                    st.get("corr_tracked_symbols", 0),
                    "aktif" if st.get("order_tracker_active") else "pasif",
                )

            except Exception as exc:
                log.exception("Ana dongu hatasi: %s", exc)

            try:
                await asyncio.wait_for(_shutdown.wait(), timeout=_POLL_INTERVAL)
            except asyncio.TimeoutError:
                pass

    log.info("Bot kapatiliyor...")
    engine.shutdown()
    log.info("Kapatma tamamlandi.")


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
