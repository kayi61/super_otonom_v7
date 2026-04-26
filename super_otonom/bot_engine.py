from __future__ import annotations

"""
BotEngine v8.0 (davranış v6.2 ile uyumlu; mimari genişletme)
─────────────────────────────────────────────────────────────────────────────
v6.2 → OrderTracker, ExecutionSimulator, TradeLogger (önceki notlar)
v8   → tick → process_signal / apply_filters / calculate_position / execute_trade;
         pipelines (risk, signal, execution); state_machine görünümü; AI explain / TRADE_WHY
"""

import asyncio
import json
import logging
import os
import random
import time
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from super_otonom.ai_layer import AILayer
from super_otonom.config import METRICS, RISK
from super_otonom.correlation_manager import CorrelationManager
from super_otonom.decision_context import DecisionContext, DecisionStage
from super_otonom.kill_switch import HardLimitTracker, get_rate_limit_storm_tracker
from super_otonom.metrics_exporter import MetricsExporter
from super_otonom.omega_regime import compute_omega_regime  # noqa: F401 — test patch hedefi
from super_otonom.pipelines import execution_pipeline, risk_pipeline, signal_pipeline
from super_otonom.pre_trade_gate import (
    gate_buy_signal_and_slots,
    gate_buy_size_and_exposure,
    gate_global_trade_disable,  # noqa: F401 — test patch
    merge_entry_notional,
)
from super_otonom.sentiment_layer import SentimentLayer
from super_otonom.signal_quality_scorer import compute_signal_quality  # noqa: F401 — test patch
from super_otonom.state_machine import compute_trading_state

log = logging.getLogger("super_otonom.engine")

_TAKE_PROFIT_PCT    = RISK.get("take_profit_pct", 0.03)
_STOP_LOSS_PCT      = RISK.get("stop_loss_pct", 0.015)
_MAX_OPEN_POSITIONS = RISK.get("max_open_positions", 1)
_STATE_FILE         = "data/bot_state.json"
_TRADE_LOG_FILE     = "data/trades.log"

VALID_BUY_SIGNALS  = {"BUY"}
VALID_SELL_SIGNALS = {"SELL", "CLOSE_ALL"}


def _min_entry_confidence() -> float:
    try:
        v = float(
            os.getenv("ENTRY_MIN_CONFIDENCE", str(RISK.get("entry_min_confidence", 0.55))) or 0.55
        )
    except ValueError:
        v = 0.55
    return max(0.45, min(0.95, v))


# ── Core modüller — lazy import ───────────────────────────────────────────────
try:
    from super_otonom.position_sizer import PositionSizer
    from super_otonom.risk_manager import RiskManager
    _CORE_AVAILABLE = True
except ImportError:
    try:
        from super_otonom.core.position_sizer import PositionSizer
        from super_otonom.core.risk_manager import RiskManager
        _CORE_AVAILABLE = True
    except ImportError:
        _CORE_AVAILABLE = False
        log.warning("BotEngine: core modüller bulunamadı — stub modları aktif.")

        class _StubSizer:
            min_notional = 10.0

            def __init__(self, *a, **k):
                pass

            def set_trade_log(self, tl): pass
            def calculate(self, sym, equity, **kw): return 0.0
            def calculate_with_slippage(self, **kw): return 0.0
            def validate_and_calculate(self, *a, **kw): return 0.0
            def can_open(self, *a, **kw): return False

        class _StubRisk:
            emergency_stop = False
            emergency_reason = None

            def __init__(self, capital: float = 0.0, *a, **k):
                pass

            def trigger_emergency(self, code, silent=False):
                self.emergency_stop = True
                self.emergency_reason = code
            def get_last_deny(self):
                return ""
            def check_risk(self, *a, **kw): return True
            def should_trailing_stop(self, *a): return False
            def record_pnl(self, pnl): pass
            def status_dict(self): return {
                "var_95": 0.0, "daily_loss": 0.0,
                "emergency_stop": False, "emergency_reason": None,
                "last_risk_deny": None, "dynamic_daily_limit_pct": 3.0,
                "omega_qmin_tighten": 0,
            }
            def get_omega_effective_qmin(self, b):
                return int(b)
            def record_omega_trade_outcome(self, pnl):
                pass

        PositionSizer = _StubSizer   # type: ignore
        RiskManager   = _StubRisk    # type: ignore

try:
    from super_otonom.core.market_models import SlippageModel
except ImportError:
    class SlippageModel:                             # type: ignore
        def adjusted_price(self, side, price, **kw):
            return price


# ── FIX 4: ExecutionSimulator — latency + partial fill ───────────────────────
class ExecutionSimulator:
    """
    Paper trading için gerçekçi emir simülasyonu.
    Latency, slippage ve kısmi dolumu simüle eder.
    """
    def __init__(
        self,
        slippage_range: Tuple[float, float] = (0.0001, 0.001),
        latency_range:  Tuple[float, float] = (0.05, 0.3),
        fill_ratio_range: Tuple[float, float] = (0.7, 1.0),
    ):
        self.slippage_range   = slippage_range
        self.latency_range    = latency_range
        self.fill_ratio_range = fill_ratio_range

    async def simulate_order(
        self,
        side: str,
        price: float,
        size: float,
        spread: float = 0.0002,
        paper: bool = True,
    ) -> Dict[str, Any]:
        """
        Emir simülasyonu (async).
        paper=False ise latency beklenmez (gerçek modda exchange zaten bekler).
        asyncio.sleep kullanır — event loop'u bloke etmez.
        Dönüş: {executed_price, filled_size, fill_ratio, latency, slippage}
        """
        latency = random.uniform(*self.latency_range)
        if paper:
            await asyncio.sleep(latency)

        slip = random.uniform(*self.slippage_range)
        if side == "buy":
            executed_price = price * (1 + spread + slip)
        else:
            executed_price = price * (1 - spread - slip)

        fill_ratio  = random.uniform(*self.fill_ratio_range)
        filled_size = size * fill_ratio

        log.debug(
            "ExecutionSimulator | side=%s price=%.6f→%.6f slip=%.5f%% "
            "fill=%.1f%% latency=%.0fms",
            side, price, executed_price, slip * 100,
            fill_ratio * 100, latency * 1000,
        )
        return {
            "executed_price": executed_price,
            "filled_size":    filled_size,
            "fill_ratio":     fill_ratio,
            "latency":        latency,
            "slippage":       slip,
        }


# ── FIX 5: TradeLogger — satır bazlı JSON + bellek yedeklemesi ───────────────
class TradeLogger:
    """
    Çift kayıt sistemi:
    - Her işlemde trades.log dosyasına satır ekler (bot çökse bile güvende)
    - BotEngine.trade_log bellek listesini de günceller
    """
    def __init__(self, filepath: str = _TRADE_LOG_FILE):
        self.filepath = filepath
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)

    def log_trade(self, trade_data: Dict[str, Any]) -> None:
        trade_data.setdefault("logged_at", time.time())
        try:
            with open(self.filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(trade_data, ensure_ascii=False) + "\n")
        except Exception as exc:
            log.error("TradeLogger: dosya yazma hatasi: %s", exc)


# ── FIX 1 & 2: OrderTracker — async düzeltmesi + BotEngine entegrasyonu ──────
class OrderTracker:
    """
    Açık emirleri takip eder.
    FIX 1: check_status artık async def — içindeki async exchange metodları
            düzgün await edilebilir.
    FIX 2: BotEngine.__init__() içinde örneklenir, tick() döngüsünde çağrılır.
    """
    def __init__(self, exchange_handler: Any):
        self.exchange = exchange_handler
        self.active_orders: Dict[str, Dict[str, Any]] = {}
        self._timeout_sec = 60

    def track(self, order_id: str, symbol: str) -> None:
        self.active_orders[order_id] = {"symbol": symbol, "start_time": time.time()}
        log.info("OrderTracker: takibe alindi order_id=%s symbol=%s", order_id, symbol)

    async def check_status(self) -> None:
        """
        FIX 1: async def olarak tanımlandı.
        get_order_status() ve cancel_order() artık düzgün await edilir.
        """
        for oid, info in list(self.active_orders.items()):
            try:
                status = await self.exchange.get_order_status(oid, info["symbol"])
                if status == "filled":
                    log.info("OrderTracker: emir doldu order_id=%s", oid)
                    del self.active_orders[oid]
                elif time.time() - info["start_time"] > self._timeout_sec:
                    log.warning("OrderTracker: timeout, iptal ediliyor order_id=%s", oid)
                    await self.exchange.cancel_order(oid, info["symbol"])
                    del self.active_orders[oid]
            except Exception as e:
                log.error("OrderTracker: durum sorgu hatasi order_id=%s err=%s", oid, e)


class BotEngine:
    """
    v8 — Tick; aşamalar pipelines + BotEngine üzerindeki faz metodlarıyla aynı sıra.

    Özet: risk ön kontrol → process_signal → apply_filters → calculate_position → execute_trade
    """

    def __init__(
        self,
        capital: float,
        paper: bool = True,
        corr_threshold: float = 0.75,
        sentiment_mock_score: Optional[float] = None,
        exchange_handler: Any = None,
    ):
        self.mode            = "PAPER" if paper else "LIVE"
        self.initial_capital = float(capital)
        self.equity          = float(capital)
        self.free_capital    = float(capital)
        self._peak_equity    = float(capital)

        self.open_positions: Dict[str, Dict[str, Any]] = {}
        self.trade_log:      List[Dict[str, Any]]      = []

        self.risk     = RiskManager(capital)
        self.ai       = AILayer()
        self.sizer    = PositionSizer(
            max_position_pct=RISK["max_position_pct"],
            min_notional=RISK["min_notional"],
        )
        self.slippage = SlippageModel()

        # FIX 4: ExecutionSimulator entegre edildi
        self.exec_sim = ExecutionSimulator()

        # FIX 5: TradeLogger entegre edildi
        self.trade_logger = TradeLogger()

        self.metrics = MetricsExporter(
            port=METRICS.get("prometheus_port", 8000),
            namespace=METRICS.get("namespace", "bot"),
        )

        self.correlation_mgr = CorrelationManager(threshold=corr_threshold)
        self.sentiment_layer = SentimentLayer(mock_score=sentiment_mock_score)

        # FIX 2: OrderTracker BotEngine'e entegre edildi
        self._order_tracker: Optional[OrderTracker] = None
        if exchange_handler is not None:
            self._order_tracker = OrderTracker(exchange_handler)
            log.info("BotEngine: OrderTracker aktif.")
        else:
            log.info("BotEngine: exchange_handler verilmedi — OrderTracker pasif.")

        self._today        = date.today()
        self._trades_today = 0
        self._tick_counter = 0
        self._hard_limits = HardLimitTracker.from_config()

        self._load_state()

    def set_exchange_handler(self, exchange_handler: Any) -> None:
        """Exchange handler sonradan da verilebilir (main_loop esnekliği için)."""
        self._order_tracker = OrderTracker(exchange_handler)
        log.info("BotEngine: OrderTracker set_exchange_handler ile aktifleştirildi.")

    def shutdown(self) -> None:
        self.ai.stop()
        self._save_state()

    # ── Durum kaydetme / yükleme ─────────────────────────────────────────────

    def _save_state(self) -> None:
        try:
            state = {
                "equity":         self.equity,
                "free_capital":   self.free_capital,
                "peak_equity":    self._peak_equity,
                "open_positions": self.open_positions,
                "trade_log":      self.trade_log[-200:],
                "timestamp":      time.time(),
                "mode":           self.mode,
            }
            os.makedirs(os.path.dirname(_STATE_FILE) or ".", exist_ok=True)
            with open(_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.error("BotEngine._save_state hatasi: %s", e)

    def _load_state(self) -> None:
        if not os.path.exists(_STATE_FILE):
            return
        try:
            with open(_STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
            if state.get("mode") != self.mode:
                log.warning(
                    "BotEngine._load_state: mod uyumsuzlugu (kayit=%s, aktif=%s), atlaniyor.",
                    state.get("mode"), self.mode,
                )
                return
            self.equity         = float(state.get("equity",       self.equity))
            self.free_capital   = float(state.get("free_capital", self.free_capital))
            self._peak_equity   = float(state.get("peak_equity",  self._peak_equity))
            self.open_positions = state.get("open_positions", {})
            self.trade_log      = state.get("trade_log", [])
            log.info(
                "BotEngine: durum geri yuklendi | equity=%.2f | acik_poz=%d | islem=%d",
                self.equity, len(self.open_positions), len(self.trade_log),
            )
        except Exception as e:
            log.error("BotEngine._load_state hatasi: %s", e)

    # ── Yardımcılar ──────────────────────────────────────────────────────────

    def _reset_daily_if_needed(self) -> None:
        today = date.today()
        if today != self._today:
            self._today        = today
            self._trades_today = 0

    def _open_exposure(self, prices: Dict[str, float]) -> float:
        total = 0.0
        for sym, pos in self.open_positions.items():
            p = prices.get(sym, float(pos.get("entry", 0)))
            total += float(pos.get("qty", 0)) * float(p)
        return float(total)

    def _avg_volume(self, candles: List[Dict[str, float]], n: int = 30) -> float:
        if not candles:
            return 1.0
        tail = candles[-n:]
        vols = [float(c.get("volume") or 0.0) for c in tail]
        return max(1.0, sum(vols) / max(len(vols), 1))

    # ── v8: faz bölünmüş tick (pipelines + durum makinesi) ───────────────────

    async def process_signal(
        self,
        symbol: str,
        analysis: Dict[str, Any],
        candles: List[Dict[str, float]],
        dctx: DecisionContext,
        out: Dict[str, Any],
    ) -> None:
        await signal_pipeline.process_signal_phase(
            self, symbol, analysis, candles, dctx, out
        )

    async def apply_filters(
        self,
        symbol: str,
        analysis: Dict[str, Any],
        price: float,
        dctx: DecisionContext,
        out: Dict[str, Any],
    ) -> bool:
        return await signal_pipeline.apply_filters_phase(
            self, symbol, analysis, price, dctx, out
        )

    def calculate_position(self, symbol: str, final_signal: str) -> float:
        if final_signal == "BUY":
            return self.correlation_mgr.adjust_risk_exposure(
                symbol, list(self.open_positions.keys())
            )
        return 1.0

    async def execute_trade(
        self,
        symbol: str,
        price: float,
        analysis: Dict[str, Any],
        out: Dict[str, Any],
        corr_multiplier: float,
        dctx: DecisionContext,
    ) -> None:
        await execution_pipeline.execute_trade_phase(
            self, symbol, price, analysis, out, corr_multiplier, dctx
        )

    async def tick(
        self,
        symbol: str,
        analysis: Dict[str, Any],
        candles: List[Dict[str, float]],
    ) -> Dict[str, Any]:
        self._reset_daily_if_needed()
        self._tick_counter += 1

        out: Dict[str, Any] = {
            "symbol":            symbol,
            "actions":           [],
            "ai_confidence":     None,
            "final_signal":      "HOLD",
            "decision_reason":   "",
            "sentiment_status":  "UNKNOWN",
            "corr_multiplier":   1.0,
            "decision_context":  None,
            "ai_explain":        "",
        }

        if not candles:
            return out

        price    = float(candles[-1]["close"])
        analysis = dict(analysis or {})
        analysis["avg_volume"] = float(
            analysis.get("avg_volume") or self._avg_volume(candles)
        )

        dctx = DecisionContext.start(symbol, self._tick_counter, analysis)
        dctx.add_trace("start", f"close={price:.4f}")
        dctx.trading_state = compute_trading_state(self, analysis).value

        if self.equity > self._peak_equity:
            self._peak_equity = self.equity

        self.correlation_mgr.update_returns(symbol, price)

        if risk_pipeline.tick_kill_switch_and_spike(self, symbol, price, dctx, out):
            return out

        exposure    = self._open_exposure({symbol: price})
        current_vol = float(analysis.get("volatility", 0.0))
        if not risk_pipeline.tick_portfolio_risk(
            self, symbol, exposure, current_vol, dctx, out
        ):
            return out

        await self.process_signal(symbol, analysis, candles, dctx, out)

        if not await self.apply_filters(symbol, analysis, price, dctx, out):
            return out

        fs = out["final_signal"]
        corr_multiplier = self.calculate_position(symbol, fs)
        if fs == "BUY":
            out["corr_multiplier"] = corr_multiplier
            dctx.corr_multiplier = corr_multiplier
            dctx.add_trace(DecisionStage.CORRELATION.value, f"mult={corr_multiplier:.3f}")

        await self.execute_trade(symbol, price, analysis, out, corr_multiplier, dctx)

        dctx.final_signal    = out.get("final_signal", fs)
        dctx.decision_reason = out.get("decision_reason", dctx.decision_reason)
        out["decision_context"] = dctx.to_dict()

        self.metrics.update(self.status())
        self.metrics.record_analysis(analysis)

        return out

    async def tick_async(
        self,
        symbol: str,
        analysis: Dict[str, Any],
        candles: List[Dict[str, float]],
    ) -> Dict[str, Any]:
        """
        FIX 2: async tick — OrderTracker.check_status() burada await edilir.
        main_loop.py bu metodu çağırmalı (veya tick() sonrası ayrıca check_orders çağrılabilir).
        """
        result = await self.tick(symbol, analysis, candles)

        # Her 10 tickte bir OrderTracker kontrolü
        if self._order_tracker and self._tick_counter % 10 == 0:
            await self._order_tracker.check_status()

        return result

    async def check_orders(self) -> None:
        """OrderTracker'ı manuel tetiklemek için (main_loop içinden çağrılabilir)."""
        if self._order_tracker:
            await self._order_tracker.check_status()

    # ── Giriş ────────────────────────────────────────────────────────────────

    async def _handle_entry(
        self,
        symbol: str,
        price: float,
        analysis: Dict,
        signal: str,
        confidence: float,
        out: Dict,
        corr_multiplier: float = 1.0,
        dctx: Optional[DecisionContext] = None,
    ) -> None:
        if signal not in VALID_BUY_SIGNALS:
            return
        ok_gate, block = gate_buy_signal_and_slots(
            signal, len(self.open_positions), float(confidence)
        )
        if not ok_gate:
            if dctx is not None:
                dctx.entry_blocked = block
                dctx.add_trace(DecisionStage.ENTRY.value, f"gate:{block}")
            log.debug("pre_trade_gate | %s | %s", symbol, block)
            return

        self.sizer.set_trade_log(self.trade_log)

        technical = self.sizer.calculate(
            symbol,
            equity=self.equity,
            volatility=float(analysis.get("volatility", 0.01)),
            ai_conf=float(confidence),
        )
        _osf = float(analysis.get("omega_size_factor", 1.0) or 1.0)
        _osf = max(0.2, min(1.2, _osf))
        technical = technical * _osf
        if dctx is not None:
            dctx.add_trace(DecisionStage.ENTRY.value, f"omega_size×{_osf:.2f}")
        ob_in = analysis.get("ob_safe_size")
        if dctx is not None:
            try:
                dctx.ob_safe_size_input = float(ob_in) if ob_in is not None else None
            except (TypeError, ValueError):
                dctx.ob_safe_size_input = None
            dctx.notional_technical = round(float(technical), 6)

        raw_merged, sizing_src, ob_block = merge_entry_notional(technical, ob_in)
        if dctx is not None:
            dctx.sizing_source = sizing_src
        if ob_block:
            if dctx is not None:
                dctx.entry_blocked = ob_block
                dctx.add_trace(DecisionStage.ENTRY.value, ob_block)
            log.info(
                "GIRIS | engellendi | symbol=%s | neden=%s | tahta_bazli=0",
                symbol, ob_block,
            )
            return

        raw_size = raw_merged
        if dctx is not None:
            dctx.notional_pre_corr = round(raw_size, 6)

        size = round(raw_size * corr_multiplier, 4)
        if dctx is not None:
            dctx.notional_after_corr = size

        ok_sz, block_sz = gate_buy_size_and_exposure(
            self.sizer,
            symbol,
            self.equity,
            size,
            raw_size,
            self.free_capital,
            self.open_positions,
        )
        if not ok_sz:
            if dctx is not None:
                dctx.entry_blocked = block_sz
                dctx.add_trace(DecisionStage.ENTRY.value, f"size:{block_sz}")
            log.debug("pre_trade_gate size | %s | %s", symbol, block_sz)
            return

        if dctx is not None:
            dctx.entry_blocked = None

        br = self._hard_limits.can_submit_order()
        if br:
            self.risk.trigger_emergency(br, silent=True)
            if dctx is not None:
                dctx.emergency_code = f"EMERGENCY_STOP:{br}"
                dctx.add_trace("kill_switch", br)
            log.critical("EMERGENCY_STOP | code=%s | symbol=%s", br, symbol)
            return

        avg_vol    = max(float(analysis.get("avg_volume") or 1.0), 1.0)

        # FIX 4: ExecutionSimulator ile paper modda gerçekçi dolum
        if self.mode == "PAPER":
            sim_result = await self.exec_sim.simulate_order(
                side="buy", price=price, size=size, paper=True
            )
            fill_price  = sim_result["executed_price"]
            filled_size = sim_result["filled_size"]
            qty = filled_size / float(fill_price or price)
            log.debug(
                "ExecutionSim BUY | fill_ratio=%.2f latency=%.0fms slip=%.5f%%",
                sim_result["fill_ratio"], sim_result["latency"] * 1000,
                sim_result["slippage"] * 100,
            )
        else:
            fill_price = self.slippage.adjusted_price(
                "buy", price,
                order_size=float(size),
                avg_volume=avg_vol,
                volatility=float(analysis.get("volatility", 0.01)),
            )
            qty = size / float(fill_price or price)

        self.open_positions[symbol] = {
            "entry":     fill_price,
            "qty":       qty,
            "size":      size,
            "peak":      fill_price,
            "hold_bars": 0,
        }
        self.free_capital -= size

        self.metrics.record_slippage(symbol, price, fill_price)

        action = {
            "type":            "BUY",
            "symbol":          symbol,
            "price":           fill_price,
            "qty":             qty,
            "size":            size,
            "corr_multiplier": corr_multiplier,
            "sizing_source":   dctx.sizing_source if dctx is not None else "",
            "notional_merged": raw_size,
            "notional_tech":   dctx.notional_technical if dctx is not None else None,
            "ai_explain":      out.get("ai_explain", ""),
        }
        out["actions"].append(action)
        self._hard_limits.record_order()

        log.info(
            "GIRIS | buy | symbol=%s | fiyat=%.6f | tutar=%.2f (birlesik=%.2f = min(tek,ob) × "
            "corr=%.2f) | src=%s | qty=%.8f | guven=%.3f | slip=%.5f%%",
            symbol, fill_price, size, raw_size, corr_multiplier,
            dctx.sizing_source if dctx else "?", qty, confidence,
            abs(fill_price - price) / (price + 1e-9) * 100,
        )
        log.info("TRADE_WHY | BUY | %s | %s", symbol, out.get("ai_explain", ""))
        self._save_state()

    # ── Çıkış ────────────────────────────────────────────────────────────────

    async def _handle_exit(
        self, symbol: str, price: float, signal: str, out: Dict, analysis: Dict
    ) -> None:
        pos     = self.open_positions[symbol]
        # FIX 3: .get() ile korumalı erişim
        entry   = float(pos.get("entry", price))
        pnl_pct = (price - entry) / entry if entry else 0.0

        if price > pos.get("peak", entry):
            pos["peak"] = price
        pos["hold_bars"] = pos.get("hold_bars", 0) + 1

        take_profit = pnl_pct >= _TAKE_PROFIT_PCT
        stop_loss   = pnl_pct <= -_STOP_LOSS_PCT
        trailing    = self.risk.should_trailing_stop(
            entry, price, float(pos.get("peak", entry))
        )
        signal_exit = signal in VALID_SELL_SIGNALS

        reason = None
        if take_profit:
            reason = "TAKE_PROFIT"
        elif stop_loss:
            reason = "STOP_LOSS"
        elif trailing:
            reason = "TRAILING_STOP"
        elif signal_exit:
            reason = "SIGNAL_EXIT"

        if reason:
            await self._close(symbol, price, out, reason, analysis)

    async def _close(
        self, symbol: str, price: float, out: Dict, reason: str, analysis: Dict
    ) -> None:
        pos = self.open_positions.pop(symbol, None)
        if not pos:
            return

        # FIX 3: .get() ile KeyError koruması
        size    = float(pos.get("size") or 0.0)
        entry   = float(pos.get("entry") or price)
        qty     = float(pos.get("qty") or 0.0)
        avg_vol = float(analysis.get("avg_volume") or 1.0)

        # FIX 4: Paper modda ExecutionSimulator
        if self.mode == "PAPER":
            sim_result = await self.exec_sim.simulate_order(
                side="sell", price=price, size=size, paper=True
            )
            exit_px     = sim_result["executed_price"]
            filled_qty  = qty * sim_result["fill_ratio"]
        else:
            exit_px    = self.slippage.adjusted_price(
                "sell", float(price),
                order_size=size,
                avg_volume=max(avg_vol, 1.0),
                volatility=float(analysis.get("volatility", 0.01)),
            )
            filled_qty = qty

        pnl = (exit_px - entry) * filled_qty
        self.equity        += pnl
        self.free_capital  += size + pnl
        self._trades_today += 1
        self.risk.record_pnl(pnl)
        if hasattr(self.risk, "record_omega_trade_outcome"):
            self.risk.record_omega_trade_outcome(pnl)

        trade_record = {
            "symbol":     symbol,
            "entry":      entry,
            "exit":       exit_px,
            "qty":        filled_qty,
            "pnl":        round(pnl, 4),
            "reason":     reason,
            "strategist": str(analysis.get("strategist", "trend")),
        }

        self.trade_log.append(trade_record)

        # FIX 5: TradeLogger — aynı anda dosyaya da yaz
        self.trade_logger.log_trade(trade_record)

        out["actions"].append({
            "type":       "SELL",
            "symbol":     symbol,
            "price":      exit_px,
            "qty":        filled_qty,
            "pnl":        round(pnl, 4),
            "reason":     reason,
            "ai_explain": out.get("ai_explain", ""),
        })
        log.info(
            "CIKIS | sell | symbol=%s | fiyat=%.6f | pnl=%.4f | reason=%s | slip=%.5f%%",
            symbol, exit_px, pnl, reason,
            abs(exit_px - price) / (price + 1e-9) * 100,
        )
        log.info("TRADE_WHY | SELL | %s | %s", symbol, out.get("ai_explain", ""))
        self.metrics.record_slippage(symbol, price, exit_px)
        self.metrics.record_trade(pnl=pnl, reason=reason)
        self._save_state()

    async def close_on_strategy_change(
        self,
        symbol: str,
        candles: List[Dict[str, float]],
        analysis: Dict[str, Any],
    ) -> Dict[str, Any]:
        self._reset_daily_if_needed()
        out: Dict[str, Any] = {
            "symbol":           symbol,
            "actions":          [],
            "ai_confidence":    None,
            "final_signal":     "HOLD",
            "decision_reason":  "STRATEGY_CHANGE",
            "sentiment_status": "N/A",
            "corr_multiplier":  1.0,
        }
        if not candles or symbol not in self.open_positions:
            return out
        analysis = dict(analysis or {})
        price = float(candles[-1]["close"])
        analysis["avg_volume"] = float(
            analysis.get("avg_volume") or self._avg_volume(candles)
        )
        analysis.setdefault("strategist", "trend")
        await self._close(symbol, price, out, "STRATEGY_CHANGE", analysis)
        return out

    # ── Durum ────────────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        total_pnl = self.equity - self.initial_capital
        pnl_pct   = (total_pnl / self.initial_capital) * 100.0 if self.initial_capital else 0.0
        peak_dd   = (
            (self._peak_equity - self.equity) / self._peak_equity * 100.0
            if self._peak_equity > 0 else 0.0
        )
        risk_st       = self.risk.status_dict()
        wr, rr, guven = self._calc_wr_rr()
        corr_summary  = self.correlation_mgr.summary()
        open_exp = 0.0
        for p in self.open_positions.values():
            open_exp += float(p.get("qty", 0)) * float(p.get("entry", 0))
        exp_pct = (open_exp / self.equity * 100.0) if self.equity > 0 else 0.0
        emg = bool(risk_st.get("emergency_stop"))
        er  = risk_st.get("emergency_reason")
        if emg and er:
            ecode_line = f"EMERGENCY_STOP:{er}"
        elif emg:
            ecode_line = "EMERGENCY_STOP"
        else:
            ecode_line = "—"
        return {
            "mode":                  self.mode,
            "initial_capital":       round(self.initial_capital, 2),
            "equity":                round(self.equity, 2),
            "free_capital":          round(self.free_capital, 2),
            "total_pnl":             round(total_pnl, 2),
            "pnl_pct":               round(pnl_pct, 2),
            "peak_drawdown_pct":     round(peak_dd, 2),
            "exposure_notional":     round(open_exp, 2),
            "exposure_pct":          round(exp_pct, 1),
            "open_positions":        len(self.open_positions),
            "trades_today":          self._trades_today,
            "total_trades":          len(self.trade_log),
            "win_rate":              None if wr is None else round(wr * 100, 1),
            "rr_ratio":              None if rr is None else round(rr, 2),
            "metrik_guveni":         guven,
            "var_95":                risk_st["var_95"],
            "daily_loss":            risk_st["daily_loss"],
            "emergency_stop":        risk_st["emergency_stop"],
            "emergency_reason":      risk_st.get("emergency_reason"),
            "emergency_code_line":   ecode_line,
            "last_risk_deny":        risk_st.get("last_risk_deny"),
            "omega_qmin_tighten":   risk_st.get("omega_qmin_tighten"),
            "dynamic_daily_limit":   risk_st.get("dynamic_daily_limit_pct"),
            "hard_limits":           self._hard_limits.status_line(),
            "rate_limit":            get_rate_limit_storm_tracker().status_dict(),
            "corr_tracked_symbols":  corr_summary["tracked_symbols"],
            "order_tracker_active":  self._order_tracker is not None,
        }

    def _calc_wr_rr(self) -> Tuple[Optional[float], Optional[float], str]:
        n = len(self.trade_log)
        if n == 0:
            return None, None, "kapanan_islem_yok"
        recent = self.trade_log[-50:]
        wins   = [t for t in recent if t["pnl"] > 0]
        losses = [t for t in recent if t["pnl"] <= 0]
        wr  = len(wins) / len(recent) if recent else 0.0
        aw  = sum(t["pnl"] for t in wins)        / len(wins)   if wins   else 1.0
        al  = sum(abs(t["pnl"]) for t in losses) / len(losses) if losses else 1.0
        rr  = aw / al if al > 0 else 2.0
        guven = f"dusuk_ornek n={n}" if n < 5 else f"son {len(recent)} islem_ozet"
        return float(wr), float(rr), guven
