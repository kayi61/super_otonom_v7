from __future__ import annotations

"""
BotEngine v8.0 (davranış v6.2 ile uyumlu; mimari genişletme)
─────────────────────────────────────────────────────────────────────────────
v6.2 → OrderTracker, ExecutionSimulator, TradeLogger (önceki notlar)
v8   → tick → process_signal / apply_filters / calculate_position / execute_trade;
         pipelines (risk, signal, execution); state_machine görünümü; AI explain / TRADE_WHY
A11  → self-feedback: ``_tick_impl`` + donmuş çekirdek + ``tick()`` reentrancy guard
         (`self_feedback_guard`)

Audit 8 (god class): tek ``BotEngine`` sınıfı tick/giriş/çıkış/risk/state taşır;
``engine_managers`` + ``pipelines`` kısmi delegasyondur — kurumsal tek-sorumluluk iddiası yok.
Ölçüm: ``python -m super_otonom.bot_engine_topology`` · manifest: data/bot_engine_topology_manifest.json
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
from super_otonom.capital_engine import CapitalEngine
from super_otonom.config import METRICS, RISK
from super_otonom.correlation_manager import CorrelationManager
from super_otonom.decision_context import DecisionContext, DecisionStage
from super_otonom.engine_managers import (
    EntryOrchestrator,
    PositionManager,
    StateManager,
    TradeExecutor,
)
from super_otonom.hard_safety_contract import (
    enforce_entry_leverage_cap,
    enforce_entry_prechecks,  # noqa: F401 — test patch target
    enforce_entry_size_safety,  # noqa: F401 — test patch target
    gate_global_trade_disable,  # noqa: F401 — test patch
    merge_entry_notional,  # noqa: F401 — test patch target
)
from super_otonom.kill_switch import HardLimitTracker
from super_otonom.metrics_exporter import MetricsExporter
from super_otonom.omega_regime import compute_omega_regime  # noqa: F401 — test patch hedefi
from super_otonom.order_engine import OrderEngine
from super_otonom.pipelines import execution_pipeline, signal_pipeline
from super_otonom.pipelines.override_phase_bridge import attach_override_phases_to_analysis
from super_otonom.risk_ontology import RiskOntology
from super_otonom.self_feedback_guard import (
    attach_tick_frozen_mark,
    audit_intratick_frozen_core,
)
from super_otonom.sentiment_layer import SentimentLayer
from super_otonom.signal_fusion_engine import run_signal_fusion_phase
from super_otonom.signal_quality_scorer import compute_signal_quality  # noqa: F401 — test patch
from super_otonom.state_machine import compute_trading_state
from super_otonom.tick_timing import span as _tick_span
from super_otonom.unified_system_core import run_system_gate_phase

log = logging.getLogger("super_otonom.engine")

# Sprint 1 — AuditLog + DailyReconciler entegrasyonu
try:
    from super_otonom.audit_log import AuditLog, DailyReconciler

    _AUDIT_AVAILABLE = True
except ImportError:
    _AUDIT_AVAILABLE = False
    log.warning("BotEngine: audit_log modülü bulunamadı — audit devre dışı")

# Sprint 4 — AlertManager
try:
    from super_otonom.alert_manager import AlertManager

    _ALERT_AVAILABLE = True
except ImportError:
    _ALERT_AVAILABLE = False
    log.warning("BotEngine: alert_manager modülü bulunamadı — alarmlar devre dışı")

_TAKE_PROFIT_PCT = RISK.get("take_profit_pct", 0.03)
_STOP_LOSS_PCT = RISK.get("stop_loss_pct", 0.015)
_MAX_OPEN_POSITIONS = RISK.get("max_open_positions", 1)
_STATE_FILE = "data/bot_state.json"
_TRADE_LOG_FILE = "data/trades.log"

VALID_BUY_SIGNALS = {"BUY"}
VALID_SELL_SIGNALS = {"SELL", "CLOSE_ALL"}


def _compact_phase_chain_for_attribution(
    phase_chain: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Dict[str, Any]]]:
    """PROMPT-A5 — BUY anı ``dctx.phase_chain`` özeti (haftalık proxy için)."""
    if not phase_chain or not isinstance(phase_chain, dict):
        return None
    out: Dict[str, Dict[str, Any]] = {}
    for k, v in phase_chain.items():
        if not isinstance(v, dict):
            continue
        tp = v.get("trade_permission")
        row: Dict[str, Any] = {
            "trade_permission": str(tp).upper() if tp is not None else "UNKNOWN",
        }
        for extra in ("reason", "block_reason", "final_action", "alpha_score", "risk_score"):
            if extra in v and v[extra] is not None:
                ev = v[extra]
                if isinstance(ev, (int, float, str, bool)):
                    row[extra] = ev
        out[str(k)] = row
    return out or None


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

            def __init__(self, *_a, **_k):  # noqa
                pass  # intentionally empty — stub implementation

            def set_trade_log(self, _tl):
                # intentionally empty stub — no trade log in stub mode
                pass

            def calculate(self, _sym, _equity, **_kw):
                return 0.0

            def calculate_with_slippage(self, **_kw):
                return 0.0

            def validate_and_calculate(self, *_a, **_kw):
                return 0.0

            def can_open(self, *_a, **_kw):
                return False

        class _StubRisk:
            emergency_stop = False
            emergency_reason = None

            def __init__(self, capital: float = 0.0, *_a, **_k):  # noqa
                self._returns_history: list[float] = []

            def trigger_emergency(self, code: str, *, silent: bool = False) -> None:  # noqa
                # RiskManager ile aynı yüzey (keyword-only silent) + ilk tetik latch
                if not self.emergency_stop:
                    self.emergency_stop = True
                    self.emergency_reason = code

            def get_last_deny(self):
                return ""

            def check_risk(self, *_a, **_kw):
                return True

            def should_trailing_stop(self, *_a):
                return False

            def record_pnl(self, _pnl):
                # intentionally empty stub — no PnL tracking in stub mode
                pass

            def status_dict(self):
                return {
                    "var_95": 0.0,
                    "daily_loss": 0.0,
                    "emergency_stop": self.emergency_stop,
                    "emergency_reason": self.emergency_reason,
                    "last_risk_deny": None,
                    "dynamic_daily_limit_pct": 3.0,
                    "omega_qmin_tighten": 0,
                }

            def get_omega_effective_qmin(self, b):
                return int(b)

            def record_omega_trade_outcome(self, _pnl):
                # intentionally empty stub — no omega tracking in stub mode
                pass

            def set_ontology(self, _onto):
                # intentionally empty stub — no ontology in stub mode
                pass

            def set_risk_engine(self, _engine):
                # intentionally empty stub — no risk engine in stub mode
                pass

            def record_return(self, _ret):
                # intentionally empty stub — no return tracking in stub mode
                pass

        PositionSizer = _StubSizer  # type: ignore
        RiskManager = _StubRisk  # type: ignore

try:
    from super_otonom.core.market_models import SlippageModel
except ImportError:

    class SlippageModel:  # type: ignore
        """Çekirdek market_models yok — fiyatı olduğu gibi döndür (stub)."""

        def adjusted_price(self, _side, price, **_kw):
            return float(price)


# ── FIX 4: ExecutionSimulator — latency + partial fill ───────────────────────
class ExecutionSimulator:
    """
    Paper trading için gerçekçi emir simülasyonu.
    Latency, slippage ve kısmi dolumu simüle eder.

    Sprint 1 — Deterministik seed:
        seed=None  → production (her çalışmada farklı RNG örneği)
        seed=42    → test/backtesting (tekrarlanabilir)
        ``random.Random.uniform`` birim testlerde monkeypatch ile sabitlenebilir.
    """

    def __init__(
        self,
        slippage_range: Tuple[float, float] = (0.0001, 0.001),
        latency_range: Tuple[float, float] = (0.05, 0.3),
        fill_ratio_range: Tuple[float, float] = (0.7, 1.0),
        seed: Optional[int] = None,
    ):
        self.slippage_range = slippage_range
        self.latency_range = latency_range
        self.fill_ratio_range = fill_ratio_range
        self._seed = seed
        self._rng = random.Random(seed) if seed is not None else random.Random()

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
        latency = float(self._rng.uniform(*self.latency_range))
        if paper:
            await asyncio.sleep(latency)

        slip = float(self._rng.uniform(*self.slippage_range))
        if side == "buy":
            executed_price = price * (1 + spread + slip)
        else:
            executed_price = price * (1 - spread - slip)

        fill_ratio = float(self._rng.uniform(*self.fill_ratio_range))
        filled_size = size * fill_ratio

        log.debug(
            "ExecutionSimulator | side=%s price=%.6f→%.6f slip=%.5f%% fill=%.1f%% latency=%.0fms",
            side,
            price,
            executed_price,
            slip * 100,
            fill_ratio * 100,
            latency * 1000,
        )
        return {
            "executed_price": executed_price,
            "filled_size": filled_size,
            "fill_ratio": fill_ratio,
            "latency": latency,
            "slippage": slip,
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
        order_snapshot = dict(self.active_orders)
        for oid, info in order_snapshot.items():
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

    **Aktif tick zinciri (özet)** — ayrıntı: ``docs/ACTIVE_PIPELINE.md``.

    1. ``tick`` → ``_tick_impl``: unrealized / funding / ontology / correlation güncelle
    2. ``run_system_gate_phase`` (unified_system_core) → kill / risk erken çıkış
    3. ``process_signal`` → ``signal_pipeline.process_signal_phase`` (+ fusion / gates içerde)
    4. ``apply_filters``
    5. ``calculate_position`` + trailing
    6. ``execute_trade`` → ``execution_pipeline.execute_trade_phase`` → ``_handle_exit`` / ``_handle_entry``

    Hard safety (AI override edemez): ``hard_safety_contract`` + ``RISK`` / env;
    giriş yolunda ``gate_leverage_notional``, ``gate_entry_cooldown``, ``pre_trade_gate`` zinciri.

    Kalıcılık: ``data/bot_state.json`` atomik yazılır; bozuk JSON'da boş state + uyarı;
    mutabakat pozisyon uyumsuzluğunda ``_safe_mode_block_new_entries`` ile yeni BUY bloklanır.
    """

    def __init__(
        self,
        capital: float,
        paper: bool = True,
        corr_threshold: float = 0.75,
        sentiment_mock_score: Optional[float] = None,
        exchange_handler: Any = None,
        *,
        paper_fee_bps_per_side: float = 0.0,
        exec_slippage_range: Optional[Tuple[float, float]] = None,
        exec_latency_range: Optional[Tuple[float, float]] = None,
        exec_seed: Optional[int] = None,
    ):
        self.mode = "PAPER" if paper else "LIVE"
        self.initial_capital = float(capital)
        self.paper_fee_bps_per_side = float(paper_fee_bps_per_side or 0.0)
        # v9 — CapitalEngine: kurumsal sermaye muhasebesi
        journal_sink = None
        if os.getenv("TIMESCALE_JOURNAL_MIRROR", "").lower() in ("1", "true", "yes"):
            try:
                from super_otonom.timescale_bridge import TimescaleBridge

                _tsb = TimescaleBridge()
                if _tsb.status().get("available"):
                    journal_sink = _tsb.make_capital_journal_sink()
                    log.info("CapitalEngine journal → TimescaleDB yansıtması aktif.")
            except Exception as exc:
                log.debug("Timescale journal mirror atlanıyor: %s", exc)

        self.capital = CapitalEngine(
            initial_capital=capital,
            max_position_pct=RISK.get("max_position_pct", 0.95),
            reserve_pct=RISK.get("capital_reserve_pct", 0.05),
            journal_sink=journal_sink,
        )
        # v9 — RiskOntology: tek NAV kaynağı, tutarlı denominators
        self.onto = RiskOntology(initial_nav=capital)
        # Geriye dönük uyumluluk
        self.equity = float(capital)
        self.free_capital = float(capital)
        self._peak_equity = float(capital)

        self.open_positions: Dict[str, Dict[str, Any]] = {}
        self.trade_log: List[Dict[str, Any]] = []

        self.risk = RiskManager(capital)
        self.risk.set_ontology(self.onto)  # v5.2 — tek NAV kaynağını bağla

        # ── VR-19/27 — RiskEngine + RegimeDetector → RiskManager wiring ──
        try:
            from super_otonom.risk.regime_detector import RegimeDetector as _RD
            from super_otonom.risk.regime_var import RegimeConditionalVaR as _RCV
            from super_otonom.risk.risk_engine import RiskEngine as _RE

            self._risk_engine = _RE()
            self.risk.set_risk_engine(self._risk_engine)
            self._regime_detector = _RD()
            self._regime_var = _RCV()
            self._regime_fitted = False
        except Exception:
            self._risk_engine = None
            self._regime_detector = None
            self._regime_var = None
            self._regime_fitted = False

        self._prev_nav: float = float(capital)
        self._var_suite_interval: int = 60
        self.ai = AILayer()
        self.sizer = PositionSizer(
            max_position_pct=RISK["max_position_pct"],
            min_notional=RISK["min_notional"],
            max_leverage=float(RISK.get("max_leverage", 1.0)),
        )
        self.slippage = SlippageModel()

        # FIX 4: ExecutionSimulator entegre edildi (geri testte slip aralığı/tekrar üretilebilirlik)
        _slip_rng = (
            exec_slippage_range if exec_slippage_range is not None else (0.0001, 0.001)
        )
        _lat_rng = (
            exec_latency_range if exec_latency_range is not None else (0.05, 0.3)
        )
        self.exec_sim = ExecutionSimulator(
            slippage_range=_slip_rng,
            latency_range=_lat_rng,
            seed=exec_seed,
        )

        # Gerçek emir yönetimi (LIVE mod için)
        self.order_engine = OrderEngine()

        # FIX 5: TradeLogger entegre edildi
        self.trade_logger = TradeLogger()

        self.metrics = MetricsExporter(
            port=METRICS.get("prometheus_port", 8000),
            namespace=METRICS.get("namespace", "bot"),
        )
        try:
            from super_otonom.ops_metrics import bind_metrics, refresh_dependencies

            bind_metrics(self.metrics)
            refresh_dependencies()
        except Exception:
            pass

        self.correlation_mgr = CorrelationManager(threshold=corr_threshold)
        self.sentiment_layer = SentimentLayer(mock_score=sentiment_mock_score)

        # FIX 2: OrderTracker + LIVE emir yolu (TradeExecutor) aynı handler
        self.exchange = exchange_handler
        self._order_tracker: Optional[OrderTracker] = None
        if exchange_handler is not None:
            self._order_tracker = OrderTracker(exchange_handler)
            log.info("BotEngine: OrderTracker aktif.")
        else:
            log.info("BotEngine: exchange_handler verilmedi — OrderTracker pasif.")

        self._today = date.today()
        self._trades_today = 0
        self._tick_counter = 0
        self._a11_tick_depth = 0  # PROMPT-A11 — tick() reentrancy (aynı engine)
        self._a11_audit_analysis: Optional[Dict[str, Any]] = None
        self._last_order_bar_ts: dict = {}  # Faz 3: same-bar duplicate koruması
        # Hard safety: son başarılı giriş zamanı (monotonic); AI bu sözlüğü sıfırlamaz — yalnızca başarılı BUY sonrası güncellenir
        self._last_entry_wall_ts: Dict[str, float] = {}
        self._hard_limits = HardLimitTracker.from_config()
        # State / mutabakat: bozuk state dosyası veya borsa↔ledger pozisyon farkı
        self._state_corrupt_fallback: bool = False
        self._safe_mode_block_new_entries: bool = False
        self._safe_mode_reason: Optional[str] = None

        # Sprint 1 — AuditLog + DailyReconciler
        if _AUDIT_AVAILABLE:
            self.audit = AuditLog()
            self.reconciler = DailyReconciler()
            self.reconciler.set_sod(self.capital.nav)
            log.info("BotEngine: AuditLog + DailyReconciler aktif")
        else:
            self.audit = None
            self.reconciler = None

        # Sprint 4 M1 — AlertManager
        if _ALERT_AVAILABLE:
            self.alerts = AlertManager()
            self.alerts.system("BOT_START", f"mod={self.mode} capital={capital:.0f}")
        else:
            self.alerts = None

        # _load_state içi veya eski kod yolları için güvenli başlangıç (RiskManager._onto ile karıştırılmaz).
        self._onto = None
        self._state_mgr = StateManager(self)
        self._trade_exec = TradeExecutor(self)
        self._position_mgr = PositionManager(self)
        self._entry_orch = EntryOrchestrator(self)
        self._state_mgr.load()
        self._onto = self.onto

    def set_exchange_handler(self, exchange_handler: Any) -> None:
        """Exchange handler sonradan da verilebilir (main_loop esnekliği için)."""
        self.exchange = exchange_handler
        self._order_tracker = OrderTracker(exchange_handler)
        log.info("BotEngine: OrderTracker set_exchange_handler ile aktifleştirildi.")

    def shutdown(self) -> None:
        self.ai.stop()
        self._save_state()

    async def emergency_liquidate(self, reason: str = "emergency_stop") -> Dict[str, Any]:
        """
        Sprint 3 M1 — Emergency liquidation.
        Tüm açık pozisyonları piyasa fiyatından kapatır.
        Emergency stop tetiklendiğinde çağrılır.

        Dönüş: {liquidated: [symbol], failed: [symbol], total_pnl: float}
        """
        result = {"liquidated": [], "failed": [], "total_pnl": 0.0}
        if not self.open_positions:
            log.info("EmergencyLiquidate | açık pozisyon yok")
            return result

        log.critical(
            "EMERGENCY_LIQUIDATE | %d pozisyon kapatılıyor | sebep=%s",
            len(self.open_positions),
            reason,
        )

        # Sprint 4 M1 — Alarm gönder
        if self.alerts is not None:
            self.alerts.emergency(
                code=reason,
                nav=self.capital.nav,
                detail=f"{len(self.open_positions)} pozisyon kapatılıyor",
            )

        if self.audit is not None:
            self.audit.system_event(
                "EMERGENCY_LIQUIDATE",
                reason=reason,
                nav=self.capital.nav,
                meta={"open_positions": list(self.open_positions.keys())},
            )

        dummy_out = {"actions": [], "final_signal": "HOLD"}
        dummy_analysis = {"avg_volume": 1.0, "volatility": 0.01, "fee": 0.0}

        positions_snapshot = list(self.open_positions)
        for symbol in positions_snapshot:
            try:
                pos = self.open_positions.get(symbol, {})
                price = float(pos.get("entry", 0))  # son bilinen fiyat
                await self._close(
                    symbol,
                    price,
                    dummy_out,
                    f"EMERGENCY_LIQUIDATE:{reason}",
                    dummy_analysis,
                )
                result["liquidated"].append(symbol)
                log.warning(
                    "EMERGENCY_LIQUIDATE | kapatıldı | %s | price=%.4f",
                    symbol,
                    price,
                )
            except Exception as exc:
                result["failed"].append(symbol)
                log.error("EMERGENCY_LIQUIDATE | HATA | %s | %s", symbol, exc)

        result["total_pnl"] = round(self.capital._realized_pnl, 4)
        self._save_state()
        return result

    # ── Durum kaydetme / yükleme ─────────────────────────────────────────────

    def _save_state(self) -> None:
        self._state_mgr.save()

    def _load_state(self) -> None:
        self._state_mgr.load()

    def set_safe_mode_block_new_entries(self, active: bool, reason: str = "") -> None:
        """Mutabakat uyumsuzluğunda yeni BUY açılmasını engeller; çıkış/trailing çalışır."""
        self._state_mgr.set_safe_mode_block_new_entries(active, reason)

    # ── Yardımcılar ──────────────────────────────────────────────────────────

    def _reset_daily_if_needed(self) -> None:
        self._state_mgr.reset_daily_if_needed()

    def _open_exposure(self, prices: Dict[str, float]) -> float:
        return self._position_mgr.open_exposure(prices)

    def _avg_volume(self, candles: List[Dict[str, float]], n: int = 30) -> float:
        return self._position_mgr.avg_volume(candles, n=n)

    # ── v8: faz bölünmüş tick (pipelines + durum makinesi) ───────────────────

    async def process_signal(
        self,
        symbol: str,
        analysis: Dict[str, Any],
        candles: List[Dict[str, float]],
        dctx: DecisionContext,
        out: Dict[str, Any],
    ) -> None:
        await run_signal_fusion_phase(self, symbol, analysis, candles, dctx, out)

    async def apply_filters(
        self,
        symbol: str,
        analysis: Dict[str, Any],
        price: float,
        dctx: DecisionContext,
        out: Dict[str, Any],
    ) -> bool:
        return await signal_pipeline.apply_filters_phase(self, symbol, analysis, price, dctx, out)

    def calculate_position(self, symbol: str, final_signal: str) -> float:
        """
        Korelasyon bazlı pozisyon çarpanı.
        Sprint 2 Madde 5: Drawdown bazlı scaling eklendi.
        Drawdown arttıkça pozisyon büyüklüğü otomatik küçülür.

        Drawdown scaling:
            dd < %5  → scale = 1.0  (tam boyut)
            dd = %10 → scale = 0.75
            dd = %15 → scale = 0.5  (yarı boyut)
            dd >= %20 → scale = 0.25 (çeyrek boyut)
        """
        if final_signal != "BUY":
            return 1.0

        corr_mult = self.correlation_mgr.adjust_risk_exposure(
            symbol, list(self.open_positions.keys())
        )

        # Drawdown scaling — onto aktifse kullan
        dd_scale = 1.0
        if hasattr(self, "onto") and self.onto is not None:
            dd_pct = self.onto.intraday_dd_pct * 100  # yüzde olarak
            if dd_pct >= 20:
                dd_scale = 0.25
            elif dd_pct >= 15:
                dd_scale = 0.50
            elif dd_pct >= 10:
                dd_scale = 0.75
            else:
                dd_scale = 1.0

            if dd_scale < 1.0:
                log.info(
                    "DRAWDOWN_SCALING | %s | dd=%.1f%% → size_scale=%.2f",
                    symbol,
                    dd_pct,
                    dd_scale,
                )

        return round(corr_mult * dd_scale, 4)

    async def execute_trade(
        self,
        symbol: str,
        price: float,
        analysis: Dict[str, Any],
        out: Dict[str, Any],
        corr_multiplier: float,
        dctx: DecisionContext,
        candles: List[Dict[str, Any]],
    ) -> None:
        await execution_pipeline.execute_trade_phase(
            self, symbol, price, analysis, out, corr_multiplier, dctx, candles
        )

    def _tick_update_unrealized(self, symbol: str, price: float) -> None:
        """Açık pozisyonların unrealized PnL'ini günceller."""
        self._position_mgr.tick_update_unrealized(symbol, price)

    def _tick_apply_funding_rate(self, analysis: Dict[str, Any]) -> None:
        """Funding rate / swap maliyetini uygular."""
        self._position_mgr.tick_apply_funding_rate(analysis)

    def _tick_check_trailing_stops(self, symbol: str):
        """Diğer açık pozisyonlar için trailing stop kontrolü."""
        return self._position_mgr.tick_check_trailing_stops(symbol)

    def _tick_handle_risk_block(self, symbol: str, out: Dict[str, Any]) -> None:
        """Risk bloğunda audit log ve emergency liquidation."""
        if self.audit is not None:
            self.audit.risk_block(
                symbol=symbol,
                reason=self.risk.get_last_deny() or "portfolio_risk",
                signal=out.get("final_signal", ""),
                nav=self.capital.nav,
            )
        if self.risk.emergency_stop and self.open_positions:
            log.critical(
                "EMERGENCY_LIQUIDATE | risk_deny=%s | pozisyonlar kapatılıyor",
                self.risk.get_last_deny(),
            )
            import asyncio as _asyncio

            _liquidate_task = _asyncio.ensure_future(
                self.emergency_liquidate(self.risk.get_last_deny() or "risk_block")
            )
            out["_liquidate_task"] = _liquidate_task

    def _attach_signal_lineage(
        self,
        symbol: str,
        out: Dict[str, Any],
        dctx: Optional[DecisionContext],
        analysis: Dict[str, Any],
        event_ts: float,
        gate: Optional[str],
        completion: str,
    ) -> None:
        """PROMPT-A7 — ``out['signal_lineage']`` + log + ``decision_context`` yenileme."""
        from super_otonom.signal_lineage import build_signal_lineage, log_signal_lineage

        tid = int(dctx.tick_id) if dctx is not None else int(self._tick_counter)
        payload = build_signal_lineage(
            symbol=symbol,
            tick_id=tid,
            out=out,
            dctx=dctx,
            analysis=analysis,
            event_ts=float(event_ts),
            gate=gate,
            completion=completion,
        )
        out["signal_lineage"] = payload
        log_signal_lineage(payload)
        if dctx is not None:
            dctx.signal_lineage = payload
            out["decision_context"] = dctx.to_dict()

    async def tick(
        self,
        symbol: str,
        analysis: Dict[str, Any],
        candles: List[Dict[str, float]],
    ) -> Dict[str, Any]:
        self._reset_daily_if_needed()

        out: Dict[str, Any] = {
            "symbol": symbol,
            "actions": [],
            "ai_confidence": None,
            "final_signal": "HOLD",
            "decision_reason": "",
            "sentiment_status": "UNKNOWN",
            "corr_multiplier": 1.0,
            "decision_context": None,
            "ai_explain": "",
        }

        if not candles:
            self._tick_counter += 1
            self._attach_signal_lineage(
                symbol, out, None, analysis or {}, float(time.time()), None, "no_candles"
            )
            return out

        if self._a11_tick_depth >= 1:
            log.critical(
                "PROMPT-A11 | tick() re-entry blocked | sym=%s depth=%s",
                symbol,
                self._a11_tick_depth,
            )
            out["final_signal"] = "HOLD"
            out["decision_reason"] = "A11_REENTRANT_TICK"
            self._attach_signal_lineage(
                symbol, out, None, analysis or {}, float(time.time()), None, "a11_reentrant"
            )
            return out

        self._tick_counter += 1
        self._a11_tick_depth += 1
        self._a11_audit_analysis = None
        try:
            out = await self._tick_impl(symbol, analysis, candles, out)
        finally:
            _a11_msg = audit_intratick_frozen_core(self._a11_audit_analysis)
            if _a11_msg:
                log.error("PROMPT-A11 | %s | sym=%s", _a11_msg, symbol)
            self._a11_audit_analysis = None
            self._a11_tick_depth -= 1

        return out

    async def _tick_impl(
        self,
        symbol: str,
        analysis: Dict[str, Any],
        candles: List[Dict[str, float]],
        out: Dict[str, Any],
    ) -> Dict[str, Any]:
        price = float(candles[-1]["close"])
        candle_ts_ms = float(candles[-1].get("timestamp", time.time() * 1000))
        candle_ts_s = candle_ts_ms / 1000.0
        analysis = dict(analysis or {})
        analysis["avg_volume"] = float(analysis.get("avg_volume") or self._avg_volume(candles))
        analysis["candle_ts"] = candle_ts_s

        with _tick_span(analysis, "pre_system_gate"):
            attach_tick_frozen_mark(analysis, tick_id=self._tick_counter, symbol=symbol)
            self._a11_audit_analysis = analysis

            dctx = DecisionContext.start(symbol, self._tick_counter, analysis)
            dctx.add_trace("start", f"close={price:.4f}")
            dctx.trading_state = compute_trading_state(self, analysis).value

            # Unrealized PnL güncelle
            self._tick_update_unrealized(symbol, price)
            if self.equity > self._peak_equity:
                self._peak_equity = self.equity
                self.risk.update_peak(self.capital.nav)

            # Funding rate / swap maliyeti
            self._tick_apply_funding_rate(analysis)

            # RiskOntology güncelle
            self.onto.update(
                nav=self.capital.nav,
                positions=self.open_positions,
                current_vol=float(analysis.get("volatility", 0.0)),
            )

            self.correlation_mgr.update_returns(symbol, price)

        # ── VR-19/27 — return kaydı + regime detection (delegated) ──
        from super_otonom.bot_engine_risk_bridge import tick_record_return_and_regime

        tick_record_return_and_regime(self)

        with _tick_span(analysis, "system_gate"):
            gate = run_system_gate_phase(self, symbol, price, dctx, out, analysis)
        if gate == "kill":
            self._attach_signal_lineage(symbol, out, dctx, analysis, candle_ts_s, "kill", "kill")
            return out
        if gate == "risk":
            self._tick_handle_risk_block(symbol, out)
            self._attach_signal_lineage(symbol, out, dctx, analysis, candle_ts_s, "risk", "risk")
            return out

        with _tick_span(analysis, "process_signal"):
            await self.process_signal(symbol, analysis, candles, dctx, out)

        with _tick_span(analysis, "apply_filters"):
            _filters_ok = await self.apply_filters(symbol, analysis, price, dctx, out)
        if not _filters_ok:
            self._attach_signal_lineage(symbol, out, dctx, analysis, candle_ts_s, None, "filters")
            return out

        with _tick_span(analysis, "position_trailing"):
            fs = out["final_signal"]
            corr_multiplier = self.calculate_position(symbol, fs)
            if fs == "BUY":
                out["corr_multiplier"] = corr_multiplier
                dctx.corr_multiplier = corr_multiplier
                dctx.add_trace(DecisionStage.CORRELATION.value, f"mult={corr_multiplier:.3f}")

            # Trailing stop — diğer semboller
            for _sym, _pos in self._tick_check_trailing_stops(symbol):
                _entry = float(_pos.get("entry", 0))
                _peak = float(_pos.get("peak", _entry))
                _cur = float(_pos.get("entry", 0))
                if _entry > 0 and self.risk.should_trailing_stop(_entry, _cur, _peak):
                    log.info(
                        "TRAILING_STOP | otomatik | %s | entry=%.4f peak=%.4f",
                        _sym,
                        _entry,
                        _peak,
                    )
                    _exit_analysis = {"avg_volume": 1.0, "volatility": 0.01, "fee": 0.0}
                    await self._close(_sym, _cur, out, "TRAILING_STOP", _exit_analysis)

        with _tick_span(analysis, "override_bridge"):
            attach_override_phases_to_analysis(
                analysis, engine=self, dctx=dctx, out=out, symbol=symbol
            )

        with _tick_span(analysis, "execute_trade"):
            await self.execute_trade(symbol, price, analysis, out, corr_multiplier, dctx, candles)

        with _tick_span(analysis, "finalize"):
            dctx.final_signal = out.get("final_signal", fs)
            dctx.decision_reason = out.get("decision_reason", dctx.decision_reason)
            self._attach_signal_lineage(symbol, out, dctx, analysis, candle_ts_s, None, "full")

            self.metrics.update(self.status())
            self.metrics.record_analysis(analysis)

            # ── VR-21 — Prometheus VaR/CVaR full suite (delegated) ──
            from super_otonom.bot_engine_risk_bridge import tick_record_var_suite

            tick_record_var_suite(self)

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

    def _entry_check_gates(self, symbol, signal, confidence, candles, dctx) -> tuple:
        return self._entry_orch.check_gates(symbol, signal, confidence, candles, dctx)

    def _entry_calculate_size(self, symbol, analysis, confidence, corr_multiplier, dctx) -> tuple:
        return self._entry_orch.calculate_size(symbol, analysis, confidence, corr_multiplier, dctx)

    def _entry_safety_checks(self, symbol, size, raw_size, analysis, dctx) -> bool:
        return self._entry_orch.safety_checks(symbol, size, raw_size, analysis, dctx)

    async def _entry_execute_order(
        self,
        _symbol: str,
        price: float,
        size: float,
        analysis: Dict,
    ) -> tuple:
        """Emir simülasyonu/gerçek dolum. (fill_price, qty) döner."""
        return await self._trade_exec.entry_execute_order(_symbol, price, size, analysis)

    def _entry_kill_switch_check(self, symbol: str, dctx: Optional[Any]) -> bool:
        return self._entry_orch.kill_switch_check(symbol, dctx)

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
        candles: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        if signal not in VALID_BUY_SIGNALS:
            return

        if self._safe_mode_block_new_entries:
            log.warning(
                "SAFE_MODE | BUY bloklandi | %s | %s",
                symbol,
                self._safe_mode_reason or "recon_or_operator",
            )
            if dctx is not None:
                dctx.entry_blocked = "SAFE_MODE_BLOCK_NEW_ENTRIES"
                dctx.add_trace(DecisionStage.ENTRY.value, "safe_mode")
            out.setdefault("decision_reason", "SAFE_MODE_BLOCK_NEW_ENTRIES")
            return

        ok, bar_ts = self._entry_check_gates(symbol, signal, confidence, candles, dctx)
        if not ok:
            return

        size, raw_size, ok_size = self._entry_calculate_size(
            symbol, analysis, confidence, corr_multiplier, dctx
        )
        if not ok_size:
            return

        # VR-18 — VaR-aware position sizing (skip in _StubRisk fallback)
        if _CORE_AVAILABLE and self._risk_engine is not None:
            from super_otonom.bot_engine_risk_bridge import run_var_cap_sizing

            size = run_var_cap_sizing(self, symbol, size, dctx)
            if size <= 0:
                if dctx is not None:
                    dctx.entry_blocked = "VAR_CAP_ZERO_SIZE"
                    dctx.add_trace(DecisionStage.ENTRY.value, "var_cap_zero")
                return

        ok_lv, block_lv = enforce_entry_leverage_cap(
            self.equity,
            max(float(size), float(raw_size)),
        )
        if not ok_lv:
            if dctx is not None:
                dctx.entry_blocked = block_lv
                dctx.add_trace(DecisionStage.ENTRY.value, f"hard:{block_lv}")
            log.info("GIRIS | engellendi | symbol=%s | neden=%s", symbol, block_lv)
            return

        if not self._entry_safety_checks(symbol, size, raw_size, analysis, dctx):
            return

        if self._entry_kill_switch_check(symbol, dctx):
            return

        # VR-17 — Pre-trade marginal VaR gate (skip in _StubRisk fallback)
        if _CORE_AVAILABLE and self._risk_engine is not None:
            from super_otonom.bot_engine_risk_bridge import run_pre_trade_var_gate

            if not run_pre_trade_var_gate(self, symbol, size, dctx):
                return

        self._last_order_bar_ts[symbol] = bar_ts

        _order_id_attempt = f"{symbol}_{int(time.time() * 1000)}_attempt"
        if not self.capital.reserve_margin(_order_id_attempt, size):
            log.warning("GIRIS | rezervasyon basarisiz | %s | size=%.2f", symbol, size)
            return

        fill_price, qty = await self._entry_execute_order(symbol, price, size, analysis)

        # Pozisyon kaydı
        order_id = f"{symbol}_{int(time.time() * 1000)}"
        pos: Dict[str, Any] = {
            "entry": fill_price,
            "qty": qty,
            "size": size,
            "initial_qty": qty,
            "peak": fill_price,
            "hold_bars": 0,
            "exit_stage": 0,
            "stage_defer_bars": 0,
            "order_id": order_id,
        }
        _ds = out.get("dynamic_stop")
        if _ds is not None:
            try:
                pos["dynamic_stop"] = float(_ds)
            except (TypeError, ValueError):
                pass
        _snap = _compact_phase_chain_for_attribution(
            getattr(dctx, "phase_chain", None) if dctx is not None else None
        )
        if _snap:
            pos["entry_phase_chain"] = _snap
        # PROMPT-A9 — BUY anı meta_regime özeti (rejim × aile × PnL korelasyonu için)
        try:
            from super_otonom.meta_regime_orchestrator import (
                compact_meta_regime_for_attribution,
            )

            _mr_snap = compact_meta_regime_for_attribution(analysis.get("meta_regime"))
            if _mr_snap:
                pos["entry_meta_regime"] = _mr_snap
        except ImportError:
            pass
        self.open_positions[symbol] = pos
        # CapitalEngine ledger
        self.capital.release_reservation(_order_id_attempt, size)
        self.capital.open_position(
            symbol=symbol,
            order_id=order_id,
            entry_price=fill_price,
            qty=qty,
            notional=size,
            fee=float(analysis.get("fee", 0.0)),
        )
        self.free_capital = self.capital.available_cash
        self.equity = self.capital.nav

        self.metrics.record_slippage(symbol, price, fill_price)

        # TCA anomali tespiti
        _expected_slip_pct = float(analysis.get("volatility", 0.01)) * 0.1 * 100
        _actual_slip_pct = abs(fill_price - price) / max(price, 1e-9) * 100
        if _actual_slip_pct > _expected_slip_pct * 3 and self.alerts is not None:
            self.alerts.tca_anomaly(symbol, _expected_slip_pct, _actual_slip_pct)

        # AuditLog: TRADE_OPEN
        if self.audit is not None:
            self.audit.trade_open(
                symbol=symbol,
                order_id=order_id,
                price=fill_price,
                qty=qty,
                notional=size,
                fee=float(analysis.get("fee", 0.0)),
                confidence=float(confidence),
                nav=self.capital.nav,
                cash=self.capital._cash,
                open_positions=len(self.open_positions),
                meta={
                    "sizing_source": dctx.sizing_source if dctx else "",
                    "signal": out.get("final_signal", "BUY"),
                },
            )

        action = {
            "type": "BUY",
            "symbol": symbol,
            "price": fill_price,
            "qty": qty,
            "size": size,
            "corr_multiplier": corr_multiplier,
            "sizing_source": dctx.sizing_source if dctx is not None else "",
            "notional_merged": raw_size,
            "notional_tech": dctx.notional_technical if dctx is not None else None,
            "ai_explain": out.get("ai_explain", ""),
        }
        out["actions"].append(action)
        self._hard_limits.record_order()

        log.info(
            "GIRIS | buy | symbol=%s | fiyat=%.6f | tutar=%.2f (birlesik=%.2f × corr=%.2f) "
            "| src=%s | qty=%.8f | guven=%.3f | slip=%.5f%%",
            symbol,
            fill_price,
            size,
            raw_size,
            corr_multiplier,
            dctx.sizing_source if dctx else "?",
            qty,
            confidence,
            abs(fill_price - price) / (price + 1e-9) * 100,
        )
        log.info("TRADE_WHY | BUY | %s | %s", symbol, out.get("ai_explain", ""))
        self._last_entry_wall_ts[symbol] = time.monotonic()
        self._save_state()

    # ── Çıkış ────────────────────────────────────────────────────────────────

    async def _handle_exit(
        self, symbol: str, price: float, signal: str, out: Dict, analysis: Dict
    ) -> None:
        from super_otonom.staged_exit import apply_staged_exit

        await apply_staged_exit(self, symbol, price, signal, out, analysis)

    async def _close_partial(
        self,
        symbol: str,
        price: float,
        ratio: float,
        out: Dict,
        reason: str,
        analysis: Dict,
        new_stage: int,
    ) -> None:
        await self._trade_exec.close_partial(
            symbol, price, ratio, out, reason, analysis, new_stage
        )

    async def _close(
        self, symbol: str, price: float, out: Dict, reason: str, analysis: Dict
    ) -> None:
        await self._trade_exec.close(symbol, price, out, reason, analysis)

    async def close_on_strategy_change(
        self,
        symbol: str,
        candles: List[Dict[str, float]],
        analysis: Dict[str, Any],
    ) -> Dict[str, Any]:
        self._reset_daily_if_needed()
        out: Dict[str, Any] = {
            "symbol": symbol,
            "actions": [],
            "ai_confidence": None,
            "final_signal": "HOLD",
            "decision_reason": "STRATEGY_CHANGE",
            "sentiment_status": "N/A",
            "corr_multiplier": 1.0,
        }
        if not candles or symbol not in self.open_positions:
            return out
        analysis = dict(analysis or {})
        price = float(candles[-1]["close"])
        analysis["avg_volume"] = float(analysis.get("avg_volume") or self._avg_volume(candles))
        analysis.setdefault("strategist", "trend")
        await self._close(symbol, price, out, "STRATEGY_CHANGE", analysis)
        return out

    # ── Durum ────────────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        from super_otonom.bot_engine_status import compute_engine_status

        return compute_engine_status(self)

    def _calc_wr_rr(self) -> Tuple[Optional[float], Optional[float], str]:
        from super_otonom.bot_engine_status import calc_wr_rr

        return calc_wr_rr(self.trade_log)
