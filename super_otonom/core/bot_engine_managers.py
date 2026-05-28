"""
PROMPT-05 — BotEngine tick / entry / exit sorumluluk ayrımı.

``engine_managers`` (StateManager, EntryOrchestrator, TradeExecutor) alt seviye yardımcılardır;
bu modül üst düzey tick/giriş/çıkış orkestrasyonunu taşır. BotEngine yalnızca compose + ince delegasyon.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from super_otonom.decision_context import DecisionContext, DecisionStage
from super_otonom.hard_safety_contract import enforce_entry_leverage_cap
from super_otonom.pipelines.override_phase_bridge import attach_override_phases_to_analysis
from super_otonom.self_feedback_guard import attach_tick_frozen_mark
from super_otonom.state_machine import compute_trading_state
from super_otonom.tick_timing import span as _tick_span
from super_otonom.unified_system_core import run_system_gate_phase

log = logging.getLogger("super_otonom.engine")

VALID_BUY_SIGNALS = frozenset({"BUY"})


def _compact_phase_chain_for_attribution(
    phase_chain: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Dict[str, Any]]]:
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


def _core_available() -> bool:
    from super_otonom.core.bot_engine import _CORE_AVAILABLE

    return bool(_CORE_AVAILABLE)


class TickProcessor:
    """Tick gövdesi: unrealized/funding, risk bridge, sinyal→execution fazları."""

    def __init__(self, engine: Any) -> None:
        self._e = engine

    def attach_signal_lineage(
        self,
        symbol: str,
        out: Dict[str, Any],
        dctx: Optional[DecisionContext],
        analysis: Dict[str, Any],
        event_ts: float,
        gate: Optional[str],
        completion: str,
    ) -> None:
        from super_otonom.signals.signal_lineage import build_signal_lineage, log_signal_lineage

        tid = int(dctx.tick_id) if dctx is not None else int(self._e._tick_counter)
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

    def update_unrealized(self, symbol: str, price: float) -> None:
        self._e._position_mgr.tick_update_unrealized(symbol, price)

    def apply_funding_rate(self, analysis: Dict[str, Any]) -> None:
        self._e._position_mgr.tick_apply_funding_rate(analysis)

    def handle_risk_block(self, symbol: str, out: Dict[str, Any]) -> None:
        if self._e.audit is not None:
            self._e.audit.risk_block(
                symbol=symbol,
                reason=self._e.risk.get_last_deny() or "portfolio_risk",
                signal=out.get("final_signal", ""),
                nav=self._e.capital.nav,
            )
        if self._e.risk.emergency_stop and self._e.open_positions:
            log.critical(
                "EMERGENCY_LIQUIDATE | risk_deny=%s | pozisyonlar kapatılıyor",
                self._e.risk.get_last_deny(),
            )
            _liquidate_task = asyncio.ensure_future(
                self._e.emergency_liquidate(self._e.risk.get_last_deny() or "risk_block")
            )
            out["_liquidate_task"] = _liquidate_task

    async def tick_impl(
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
        analysis["avg_volume"] = float(
            analysis.get("avg_volume") or self._e._avg_volume(candles)
        )
        analysis["candle_ts"] = candle_ts_s

        with _tick_span(analysis, "pre_system_gate"):
            attach_tick_frozen_mark(analysis, tick_id=self._e._tick_counter, symbol=symbol)
            self._e._a11_audit_analysis = analysis

            dctx = DecisionContext.start(symbol, self._e._tick_counter, analysis)
            dctx.add_trace("start", f"close={price:.4f}")
            dctx.trading_state = compute_trading_state(self._e, analysis).value

            self.update_unrealized(symbol, price)
            if self._e.equity > self._e._peak_equity:
                self._e._peak_equity = self._e.equity
                self._e.risk.update_peak(self._e.capital.nav)

            self.apply_funding_rate(analysis)

            self._e.onto.update(
                nav=self._e.capital.nav,
                positions=self._e.open_positions,
                current_vol=float(analysis.get("volatility", 0.0)),
            )

            self._e.correlation_mgr.update_returns(symbol, price)

        from super_otonom.bot_engine_risk_bridge import (
            tick_portfolio_risk_phase,
            tick_record_return_and_regime,
        )

        tick_record_return_and_regime(self._e)

        with _tick_span(analysis, "portfolio_risk"):
            tick_portfolio_risk_phase(self._e, symbol, analysis)

        with _tick_span(analysis, "system_gate"):
            gate = run_system_gate_phase(self._e, symbol, price, dctx, out, analysis)
        if gate == "kill":
            self.attach_signal_lineage(
                symbol, out, dctx, analysis, candle_ts_s, "kill", "kill"
            )
            return out
        if gate == "risk":
            self.handle_risk_block(symbol, out)
            self.attach_signal_lineage(
                symbol, out, dctx, analysis, candle_ts_s, "risk", "risk"
            )
            return out

        with _tick_span(analysis, "process_signal"):
            await self._e.process_signal(symbol, analysis, candles, dctx, out)

        with _tick_span(analysis, "apply_filters"):
            _filters_ok = await self._e.apply_filters(symbol, analysis, price, dctx, out)
        if not _filters_ok:
            self.attach_signal_lineage(
                symbol, out, dctx, analysis, candle_ts_s, None, "filters"
            )
            return out

        with _tick_span(analysis, "position_trailing"):
            fs = out["final_signal"]
            corr_multiplier = self._e.calculate_position(symbol, fs)
            if fs == "BUY":
                out["corr_multiplier"] = corr_multiplier
                dctx.corr_multiplier = corr_multiplier
                dctx.add_trace(DecisionStage.CORRELATION.value, f"mult={corr_multiplier:.3f}")

            for _sym, _pos in self._e._exit_mgr.tick_check_trailing_stops(symbol):
                _entry = float(_pos.get("entry", 0))
                _peak = float(_pos.get("peak", _entry))
                _cur = float(_pos.get("entry", 0))
                if _entry > 0 and self._e.risk.should_trailing_stop(_entry, _cur, _peak):
                    log.info(
                        "TRAILING_STOP | otomatik | %s | entry=%.4f peak=%.4f",
                        _sym,
                        _entry,
                        _peak,
                    )
                    _exit_analysis = {"avg_volume": 1.0, "volatility": 0.01, "fee": 0.0}
                    await self._e._exit_mgr.close(
                        _sym, _cur, out, "TRAILING_STOP", _exit_analysis
                    )

        with _tick_span(analysis, "override_bridge"):
            attach_override_phases_to_analysis(
                analysis, engine=self._e, dctx=dctx, out=out, symbol=symbol
            )

        with _tick_span(analysis, "execute_trade"):
            await self._e.execute_trade(
                symbol, price, analysis, out, corr_multiplier, dctx, candles
            )

        with _tick_span(analysis, "finalize"):
            dctx.final_signal = out.get("final_signal", fs)
            dctx.decision_reason = out.get("decision_reason", dctx.decision_reason)
            self.attach_signal_lineage(
                symbol, out, dctx, analysis, candle_ts_s, None, "full"
            )

            self._e.metrics.update(self._e.status())
            self._e.metrics.record_analysis(analysis)

            from super_otonom.bot_engine_risk_bridge import (
                tick_check_var_limits,
                tick_record_var_suite,
            )

            tick_record_var_suite(self._e)
            tick_check_var_limits(self._e)

        return out


class EntryManager:
    """BUY giriş yolu: kapılar, boyut, güvenlik, emir yürütme."""

    def __init__(self, engine: Any) -> None:
        self._e = engine

    def calculate_position_scale(self, symbol: str, final_signal: str) -> float:
        if final_signal != "BUY":
            return 1.0
        corr_mult = self._e.correlation_mgr.adjust_risk_exposure(
            symbol, list(self._e.open_positions.keys())
        )
        dd_scale = 1.0
        onto = getattr(self._e, "onto", None)
        if onto is not None:
            dd_pct = onto.intraday_dd_pct * 100
            if dd_pct >= 20:
                dd_scale = 0.25
            elif dd_pct >= 15:
                dd_scale = 0.50
            elif dd_pct >= 10:
                dd_scale = 0.75
            if dd_scale < 1.0:
                log.info(
                    "DRAWDOWN_SCALING | %s | dd=%.1f%% → size_scale=%.2f",
                    symbol,
                    dd_pct,
                    dd_scale,
                )
        return round(corr_mult * dd_scale, 4)

    def check_gates(
        self, symbol: Any, signal: Any, confidence: Any, candles: Any, dctx: Any
    ) -> tuple:
        return self._e._entry_orch.check_gates(symbol, signal, confidence, candles, dctx)

    def calculate_size(
        self, symbol: Any, analysis: Any, confidence: Any, corr_multiplier: Any, dctx: Any
    ) -> tuple:
        return self._e._entry_orch.calculate_size(
            symbol, analysis, confidence, corr_multiplier, dctx
        )

    def safety_checks(
        self, symbol: Any, size: Any, raw_size: Any, analysis: Any, dctx: Any
    ) -> bool:
        return self._e._entry_orch.safety_checks(symbol, size, raw_size, analysis, dctx)

    def kill_switch_check(self, symbol: str, dctx: Optional[Any]) -> bool:
        return self._e._entry_orch.kill_switch_check(symbol, dctx)

    async def execute_order(
        self, symbol: str, price: float, size: float, analysis: Dict[str, Any]
    ) -> tuple:
        return await self._e._trade_exec.entry_execute_order(symbol, price, size, analysis)

    async def handle_entry(
        self,
        symbol: str,
        price: float,
        analysis: Dict[str, Any],
        signal: str,
        confidence: float,
        out: Dict[str, Any],
        corr_multiplier: float = 1.0,
        dctx: Optional[DecisionContext] = None,
        candles: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        if signal not in VALID_BUY_SIGNALS:
            return

        if self._e._safe_mode_block_new_entries:
            log.warning(
                "SAFE_MODE | BUY bloklandi | %s | %s",
                symbol,
                self._e._safe_mode_reason or "recon_or_operator",
            )
            if dctx is not None:
                dctx.entry_blocked = "SAFE_MODE_BLOCK_NEW_ENTRIES"
                dctx.add_trace(DecisionStage.ENTRY.value, "safe_mode")
            out.setdefault("decision_reason", "SAFE_MODE_BLOCK_NEW_ENTRIES")
            return

        if self._e._portfolio_risk_permission in ("BLOCK", "HALT"):
            log.warning(
                "FAZ-24 | BUY bloklandi | %s | perm=%s",
                symbol,
                self._e._portfolio_risk_permission,
            )
            if dctx is not None:
                dctx.entry_blocked = f"PORTFOLIO_RISK_{self._e._portfolio_risk_permission}"
                dctx.add_trace(
                    DecisionStage.ENTRY.value,
                    f"portfolio_risk_{self._e._portfolio_risk_permission.lower()}",
                )
            out.setdefault(
                "decision_reason",
                f"PORTFOLIO_RISK_{self._e._portfolio_risk_permission}",
            )
            return

        ok, bar_ts = self.check_gates(symbol, signal, confidence, candles, dctx)
        if not ok:
            return

        size, raw_size, ok_size = self.calculate_size(
            symbol, analysis, confidence, corr_multiplier, dctx
        )
        if not ok_size:
            return

        if _core_available() and self._e._risk_engine is not None:
            from super_otonom.bot_engine_risk_bridge import run_var_cap_sizing

            size = run_var_cap_sizing(self._e, symbol, size, dctx)
            if size <= 0:
                if dctx is not None:
                    dctx.entry_blocked = "VAR_CAP_ZERO_SIZE"
                    dctx.add_trace(DecisionStage.ENTRY.value, "var_cap_zero")
                return

        ok_lv, block_lv = enforce_entry_leverage_cap(
            self._e.equity,
            max(float(size), float(raw_size)),
        )
        if not ok_lv:
            if dctx is not None:
                dctx.entry_blocked = block_lv
                dctx.add_trace(DecisionStage.ENTRY.value, f"hard:{block_lv}")
            log.info("GIRIS | engellendi | symbol=%s | neden=%s", symbol, block_lv)
            return

        if not self.safety_checks(symbol, size, raw_size, analysis, dctx):
            return

        if self.kill_switch_check(symbol, dctx):
            return

        if _core_available() and self._e._risk_engine is not None:
            from super_otonom.bot_engine_risk_bridge import run_pre_trade_var_gate

            if not run_pre_trade_var_gate(self._e, symbol, size, dctx):
                return

        self._e._last_order_bar_ts[symbol] = bar_ts

        _order_id_attempt = f"{symbol}_{int(time.time() * 1000)}_attempt"
        if not self._e.capital.reserve_margin(_order_id_attempt, size):
            log.warning("GIRIS | rezervasyon basarisiz | %s | size=%.2f", symbol, size)
            return

        fill_price, qty = await self.execute_order(symbol, price, size, analysis)

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
        try:
            from super_otonom.meta_regime_orchestrator import (
                compact_meta_regime_for_attribution,
            )

            _mr_snap = compact_meta_regime_for_attribution(analysis.get("meta_regime"))
            if _mr_snap:
                pos["entry_meta_regime"] = _mr_snap
        except ImportError:
            pass
        self._e.open_positions[symbol] = pos
        self._e.capital.release_reservation(_order_id_attempt, size)
        self._e.capital.open_position(
            symbol=symbol,
            order_id=order_id,
            entry_price=fill_price,
            qty=qty,
            notional=size,
            fee=float(analysis.get("fee", 0.0)),
        )
        self._e.free_capital = self._e.capital.available_cash
        self._e.equity = self._e.capital.nav

        self._e.metrics.record_slippage(symbol, price, fill_price)

        _expected_slip_pct = float(analysis.get("volatility", 0.01)) * 0.1 * 100
        _actual_slip_pct = abs(fill_price - price) / max(price, 1e-9) * 100
        if _actual_slip_pct > _expected_slip_pct * 3 and self._e.alerts is not None:
            self._e.alerts.tca_anomaly(symbol, _expected_slip_pct, _actual_slip_pct)

        if self._e.audit is not None:
            self._e.audit.trade_open(
                symbol=symbol,
                order_id=order_id,
                price=fill_price,
                qty=qty,
                notional=size,
                fee=float(analysis.get("fee", 0.0)),
                confidence=float(confidence),
                nav=self._e.capital.nav,
                cash=self._e.capital._cash,
                open_positions=len(self._e.open_positions),
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
        self._e._hard_limits.record_order()

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
        self._e._last_entry_wall_ts[symbol] = time.monotonic()
        self._e._save_state()


class ExitManager:
    """Çıkış yolu: staged exit, kısmi/tam kapanış, trailing, strateji değişimi."""

    def __init__(self, engine: Any) -> None:
        self._e = engine

    async def emergency_liquidate(self, reason: str = "emergency_stop") -> Dict[str, Any]:
        result: Dict[str, Any] = {"liquidated": [], "failed": [], "total_pnl": 0.0}
        if not self._e.open_positions:
            log.info("EmergencyLiquidate | açık pozisyon yok")
            return result

        log.critical(
            "EMERGENCY_LIQUIDATE | %d pozisyon kapatılıyor | sebep=%s",
            len(self._e.open_positions),
            reason,
        )

        if self._e.alerts is not None:
            self._e.alerts.emergency(
                code=reason,
                nav=self._e.capital.nav,
                detail=f"{len(self._e.open_positions)} pozisyon kapatılıyor",
            )

        if self._e.audit is not None:
            self._e.audit.system_event(
                "EMERGENCY_LIQUIDATE",
                reason=reason,
                nav=self._e.capital.nav,
                meta={"open_positions": list(self._e.open_positions.keys())},
            )

        dummy_out = {"actions": [], "final_signal": "HOLD"}
        dummy_analysis = {"avg_volume": 1.0, "volatility": 0.01, "fee": 0.0}

        for symbol in list(self._e.open_positions):
            try:
                pos = self._e.open_positions.get(symbol, {})
                price = float(pos.get("entry", 0))
                await self.close(
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

        result["total_pnl"] = round(self._e.capital._realized_pnl, 4)
        self._e._save_state()
        return result

    def tick_check_trailing_stops(self, symbol: str):
        return self._e._position_mgr.tick_check_trailing_stops(symbol)

    async def handle_exit(
        self, symbol: str, price: float, signal: str, out: Dict[str, Any], analysis: Dict[str, Any]
    ) -> None:
        from super_otonom.staged_exit import apply_staged_exit

        await apply_staged_exit(self._e, symbol, price, signal, out, analysis)

    async def close_partial(
        self,
        symbol: str,
        price: float,
        ratio: float,
        out: Dict[str, Any],
        reason: str,
        analysis: Dict[str, Any],
        new_stage: int,
    ) -> None:
        await self._e._trade_exec.close_partial(
            symbol, price, ratio, out, reason, analysis, new_stage
        )

    async def close(
        self, symbol: str, price: float, out: Dict[str, Any], reason: str, analysis: Dict[str, Any]
    ) -> None:
        await self._e._trade_exec.close(symbol, price, out, reason, analysis)

    async def close_on_strategy_change(
        self,
        symbol: str,
        candles: List[Dict[str, float]],
        analysis: Dict[str, Any],
    ) -> Dict[str, Any]:
        self._e._reset_daily_if_needed()
        out: Dict[str, Any] = {
            "symbol": symbol,
            "actions": [],
            "ai_confidence": None,
            "final_signal": "HOLD",
            "decision_reason": "STRATEGY_CHANGE",
            "sentiment_status": "N/A",
            "corr_multiplier": 1.0,
        }
        if not candles or symbol not in self._e.open_positions:
            return out
        analysis = dict(analysis or {})
        price = float(candles[-1]["close"])
        analysis["avg_volume"] = float(
            analysis.get("avg_volume") or self._e._avg_volume(candles)
        )
        analysis.setdefault("strategist", "trend")
        await self.close(symbol, price, out, "STRATEGY_CHANGE", analysis)
        return out
