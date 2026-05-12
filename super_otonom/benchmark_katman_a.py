"""
Katman A — uçtan uca süre ölçümü.

Modlar:
- Mock OB (varsayılan): ağ yok, fetch_order_book anında sahte OB.
- --live-ob: AsyncExchangeHandler ile tek sembol order book çekilir; süre ayrı raporlanır.

Ölçümler:
- order_book_fetch: sadece await fetch_order_book (ağ + borsa RTT; ccxt yoksa ~0)
- prep_local: analyze + ob_safe_size + liquidity (OB zaten elde)
- tick: tam BotEngine.tick (entry/exit mock)

Çalıştırma:
  python -m super_otonom.benchmark_katman_a --iter 150 --scenario normal
  python -m super_otonom.benchmark_katman_a --live-ob --symbol BTC/USDT --iter 30
  DEFAULT_EXCHANGE / API anahtarları .env üzerinden (main_loop ile aynı).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import statistics
import time
from typing import Any, Dict, List, Tuple
from unittest.mock import AsyncMock

from super_otonom.analyzer import MarketAnalyzer
from super_otonom.bot_engine import BotEngine
from super_otonom.config import ASYNC_EXCHANGE, EXCHANGES, GENERAL, RISK
from super_otonom.exchange_async import AsyncExchangeHandler
from super_otonom.fake_order_book_scenarios import make_scenario
from super_otonom.main_loop import _apply_ob_safe_size
from super_otonom.omega_regime import compute_omega_regime


def _make_candles(n: int = 80, base: float = 100.0) -> List[Dict[str, float]]:
    candles: List[Dict[str, float]] = []
    ts = time.time() * 1000 - n * 60_000
    p = base
    for i in range(n):
        o = p
        c = p * (1.0 + (0.001 if i % 4 != 0 else -0.0005))
        h = max(o, c) * 1.002
        lo = min(o, c) * 0.998
        candles.append(
            {
                "timestamp": ts,
                "open": o,
                "high": h,
                "low": lo,
                "close": c,
                "volume": 100.0 + i,
            }
        )
        p = c
        ts += 60_000
    return candles


class _MockExchangeHandler:
    def __init__(self, order_book: Dict[str, Any]) -> None:
        self._ob = order_book

    async def fetch_order_book(self, symbol: str, limit: int = 20) -> Dict[str, Any]:
        _ = symbol
        _ = limit
        return self._ob

    def circuit_breaker_status(self) -> Dict[str, str]:
        return {}


async def _prep_from_order_book(
    symbol: str,
    analyzer: MarketAnalyzer,
    engine: BotEngine,
    candles_1h: List[Dict[str, float]],
    scenario_overlay: Dict[str, Any],
    ob: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[Dict[str, float]]]:
    """analyze + OB alanları + sizer + liquidity; analysis['order_book'] = ob."""
    analysis_core = analyzer.analyze(symbol, candles_1h)
    analysis = {**analysis_core, **scenario_overlay}
    ai_conf = float(RISK.get("entry_min_confidence", 0.55))
    vol = float(analysis.get("volatility", 0.01))
    _apply_ob_safe_size(engine, symbol, ob, candles_1h, analysis, vol, ai_conf)
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
    analysis["order_book"] = ob
    return analysis, candles_1h


def _percentile(sorted_ms: List[float], p: float) -> float:
    if not sorted_ms:
        return 0.0
    k = (len(sorted_ms) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_ms) - 1)
    if f == c:
        return sorted_ms[f]
    return sorted_ms[f] + (sorted_ms[c] - sorted_ms[f]) * (k - f)


def _summarize(name: str, xs: List[float]) -> None:
    xs_sorted = sorted(xs)
    print(
        f"{name}: n={len(xs)} "
        f"median={statistics.median(xs_sorted):.3f}ms "
        f"p95={_percentile(xs_sorted, 95):.3f}ms "
        f"p99={_percentile(xs_sorted, 99):.3f}ms "
        f"max={max(xs_sorted):.3f}ms"
    )


async def _run_mock_benchmark(
    *,
    iterations: int,
    warmup: int,
    scenario: str,
    symbol: str,
) -> None:
    candles = _make_candles(80, base=100.0)
    analyzer = MarketAnalyzer()
    engine = BotEngine(capital=10_000.0, paper=True)
    engine._handle_entry = AsyncMock()
    engine._handle_exit = AsyncMock()

    ob, scenario_analysis = make_scenario(
        scenario=scenario,  # type: ignore[arg-type]
        symbol=symbol,
        mid_price=float(candles[-1]["close"]),
        seed=42,
    )
    handler = _MockExchangeHandler(ob)
    overlay = dict(scenario_analysis)
    ob_limit = int(ASYNC_EXCHANGE.get("ob_limit", 20))

    prep_times: List[float] = []
    tick_times: List[float] = []
    total_times: List[float] = []

    for _ in range(warmup):
        ob2 = await handler.fetch_order_book(symbol, limit=ob_limit)
        a, c = await _prep_from_order_book(symbol, analyzer, engine, candles, overlay, ob2)
        await engine.tick(symbol, a, c)

    for _ in range(iterations):
        t0 = time.perf_counter()
        ob2 = await handler.fetch_order_book(symbol, limit=ob_limit)
        t_prep0 = time.perf_counter()
        analysis, c2 = await _prep_from_order_book(symbol, analyzer, engine, candles, overlay, ob2)
        t_prep1 = time.perf_counter()
        await engine.tick(symbol, analysis, c2)
        t2 = time.perf_counter()
        prep_times.append((t_prep1 - t_prep0) * 1000.0)
        tick_times.append((t2 - t_prep1) * 1000.0)
        total_times.append((t2 - t0) * 1000.0)

    print(f"Katman A benchmark | scenario={scenario} | symbol={symbol} | OB=MOCK")
    print("order_book_fetch: mock (ağ yok, ~0ms — ayrı satır yok)\n")
    _summarize("prep_local (analyze + sizer + liquidity)", prep_times)
    _summarize("tick (BotEngine.tick, entry/exit mock)", tick_times)
    _summarize("total (mock fetch + prep_local + tick)", total_times)
    _print_omega_micro()


async def _run_live_ob_benchmark(
    *,
    iterations: int,
    warmup: int,
    scenario: str,
    symbol: str,
    exchange_id: str,
) -> None:
    candles = _make_candles(80, base=100.0)
    analyzer = MarketAnalyzer()
    engine = BotEngine(capital=10_000.0, paper=True)
    engine._handle_entry = AsyncMock()
    engine._handle_exit = AsyncMock()

    _, scenario_analysis = make_scenario(
        scenario=scenario,  # type: ignore[arg-type]
        symbol=symbol,
        mid_price=float(candles[-1]["close"]),
        seed=42,
    )
    overlay = dict(scenario_analysis)
    ob_limit = int(ASYNC_EXCHANGE.get("ob_limit", 20))

    ex_cfg = EXCHANGES.get(exchange_id, {})
    extra: Dict[str, Any] = {}
    if exchange_id == "kucoin" and ex_cfg.get("api_passphrase"):
        extra["password"] = ex_cfg["api_passphrase"]
    if exchange_id == "okx" and ex_cfg.get("api_password"):
        extra["password"] = ex_cfg["api_password"]

    network_times: List[float] = []
    prep_times: List[float] = []
    tick_times: List[float] = []
    total_times: List[float] = []
    empty_ob_warn = 0

    async with AsyncExchangeHandler(
        exchange_id=exchange_id,
        api_key=ex_cfg.get("api_key", ""),
        api_secret=ex_cfg.get("api_secret", ""),
        testnet=ex_cfg.get("testnet", True),
        extra_config=extra if extra else None,
        max_retries=ASYNC_EXCHANGE["max_retries"],
        retry_delay=ASYNC_EXCHANGE["retry_delay"],
        cb_failure_threshold=int(os.getenv("CB_FAILURE_THRESHOLD", "5")),
        cb_recovery_time=float(os.getenv("CB_RECOVERY_TIME", "60")),
    ) as handler:
        # Isıtma: TLS / rate limit
        for _ in range(max(1, warmup)):
            await handler.fetch_order_book(symbol, limit=ob_limit)

        for _ in range(iterations):
            t0 = time.perf_counter()
            ob = await handler.fetch_order_book(symbol, limit=ob_limit)
            t_net = time.perf_counter()
            network_times.append((t_net - t0) * 1000.0)

            if not ob.get("asks") and not ob.get("bids"):
                empty_ob_warn += 1

            t_prep0 = time.perf_counter()
            analysis, c2 = await _prep_from_order_book(
                symbol, analyzer, engine, candles, overlay, ob
            )
            t_prep1 = time.perf_counter()
            await engine.tick(symbol, analysis, c2)
            t2 = time.perf_counter()

            prep_times.append((t_prep1 - t_prep0) * 1000.0)
            tick_times.append((t2 - t_prep1) * 1000.0)
            total_times.append((t2 - t0) * 1000.0)

    print(
        f"Katman A benchmark | scenario={scenario} | symbol={symbol} | "
        f"OB=LIVE (AsyncExchangeHandler) | exchange={exchange_id}"
    )
    if empty_ob_warn:
        print(
            f"UYARI: {empty_ob_warn}/{iterations} çağrıda boş order book "
            "(ccxt yok, CB, ağ hatası veya sembol)."
        )
    print("")
    _summarize("order_book_fetch (ağ + borsa API, tek çağrı)", network_times)
    _summarize("prep_local (analyze + sizer + liquidity, ağ hariç)", prep_times)
    _summarize("tick (BotEngine.tick, entry/exit mock)", tick_times)
    _summarize("total (fetch + prep_local + tick)", total_times)
    _print_omega_micro()


def _print_omega_micro() -> None:
    t_om0 = time.perf_counter()
    for _ in range(100):
        compute_omega_regime(
            {"regime": "TRENDING", "hurst": 0.6, "volatility": 0.02, "flash_crash": False},
            74,
        )
    t_om1 = time.perf_counter()
    print(f"\ncompute_omega_regime ort/çağrı: {((t_om1 - t_om0) / 100) * 1000:.4f}ms")


async def _run_benchmark(
    *,
    iterations: int,
    warmup: int,
    scenario: str,
    symbol: str,
    live_ob: bool,
    exchange_id: str,
) -> None:
    logging.getLogger().setLevel(logging.CRITICAL)
    print("Katman A hedefi: A <50ms (CPU dilimi); canlı OB satırı ağ RTT içerir.\n")
    if live_ob:
        await _run_live_ob_benchmark(
            iterations=iterations,
            warmup=warmup,
            scenario=scenario,
            symbol=symbol,
            exchange_id=exchange_id,
        )
    else:
        await _run_mock_benchmark(
            iterations=iterations,
            warmup=warmup,
            scenario=scenario,
            symbol=symbol,
        )


def main() -> None:
    p = argparse.ArgumentParser(description="Katman A benchmark")
    p.add_argument("--iter", type=int, default=150)
    p.add_argument("--warmup", type=int, default=20)
    p.add_argument(
        "--scenario",
        choices=("normal", "flash_crash", "pump_dump", "low_liquidity"),
        default="normal",
    )
    p.add_argument("--symbol", type=str, default="BTC/USDT")
    p.add_argument(
        "--live-ob",
        action="store_true",
        help="Gerçek AsyncExchangeHandler ile order book çek; süre ayrı satırda.",
    )
    p.add_argument(
        "--exchange",
        type=str,
        default="",
        help="Borsa id (ccxt), boşsa GENERAL['default_exchange']",
    )
    args = p.parse_args()
    ex = args.exchange.strip() or GENERAL.get("default_exchange", "binance")
    asyncio.run(
        _run_benchmark(
            iterations=max(1, args.iter),
            warmup=max(0, args.warmup),
            scenario=args.scenario,
            symbol=args.symbol.strip() or "BTC/USDT",
            live_ob=bool(args.live_ob),
            exchange_id=ex,
        )
    )


if __name__ == "__main__":
    main()
