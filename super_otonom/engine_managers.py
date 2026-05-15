"""
BotEngine alt bileşenleri: durum kalıcılığı, emir yürütme, pozisyon metrikleri.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import time
from typing import Any, Dict, List, Tuple

from super_otonom.capital_engine import CapitalEngine
from super_otonom.config import RISK
from super_otonom.risk_ontology import RiskOntology

log = logging.getLogger("super_otonom.engine")


def _state_file_path() -> str:
    from super_otonom import bot_engine as be

    return be._STATE_FILE


def atomic_write_json(path: str, payload: Dict[str, Any]) -> None:
    """JSON dosyasını atomik yazar (tmp + fsync + replace)."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=".bot_state_",
        suffix=".tmp",
        dir=directory,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            if os.path.isfile(tmp_path):
                os.unlink(tmp_path)
        except OSError:
            pass
        raise


class StateManager:
    """Kalıcı state, günlük sıfırlama ve safe-mode bayrakları."""

    def __init__(self, engine: Any) -> None:
        self._e = engine

    def save(self) -> None:
        try:
            state = {
                "equity": self._e.equity,
                "free_capital": self._e.free_capital,
                "peak_equity": self._e._peak_equity,
                "open_positions": self._e.open_positions,
                "trade_log": self._e.trade_log[-200:],
                "timestamp": time.time(),
                "mode": self._e.mode,
                "capital_engine": self._e.capital.to_dict(),
                "risk_ontology": self._e.onto.to_dict(),
                "pnl_history": self._e.risk._pnl_history[-500:],
                "vol_history": self._e.risk._vol_history[-200:],
            }
            atomic_write_json(_state_file_path(), state)
        except Exception as e:
            log.error("BotEngine._save_state hatasi: %s", e)

    def load(self) -> None:
        path = _state_file_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read()
            try:
                state = json.loads(raw)
            except json.JSONDecodeError as je:
                self._e._state_corrupt_fallback = True
                try:
                    bak = path + ".bak"
                    shutil.copy2(path, bak)
                    log.warning("BotEngine._load_state: bozuk dosya yedeklendi | %s", bak)
                except OSError as copy_err:
                    log.warning("BotEngine._load_state: .bak yazilamadi | %s", copy_err)
                log.error(
                    "BotEngine._load_state: JSON bozuk — bos state ile devam | %s | offset=%s",
                    je,
                    getattr(je, "pos", None),
                )
                return
            if state.get("mode") != self._e.mode:
                log.warning(
                    "BotEngine._load_state: mod uyumsuzlugu (kayit=%s, aktif=%s), atlaniyor.",
                    state.get("mode"),
                    self._e.mode,
                )
                return
            self._e.equity = float(state.get("equity", self._e.equity))
            self._e.free_capital = float(state.get("free_capital", self._e.free_capital))
            self._e._peak_equity = float(state.get("peak_equity", self._e._peak_equity))
            self._e.open_positions = state.get("open_positions", {})
            self._e.trade_log = state.get("trade_log", [])
            if "capital_engine" in state:
                self._e.capital = CapitalEngine.from_dict(
                    state["capital_engine"],
                    max_position_pct=RISK.get("max_position_pct", 0.95),
                    reserve_pct=RISK.get("capital_reserve_pct", 0.05),
                )
                self._e.equity = self._e.capital.nav
                self._e.free_capital = self._e.capital.available_cash
                self._e.initial_capital = float(self._e.capital.initial_capital)
                self._e.risk.initial_capital = self._e.initial_capital
            else:
                # Eski düz snapshot: equity dosyadan gelir; CapitalEngine hâlâ ctor NAV'ında kalırsa
                # tick() capital.nav ile shadow eder — ledger + ontology hizala.
                self._sync_legacy_flat_state_to_ledger()
            if "risk_ontology" in state:
                self._e.onto = RiskOntology.from_dict(state["risk_ontology"])
                self._e.risk.set_ontology(self._e.onto)
                log.info("RiskOntology yuklendi | nav=%.2f", self._e.onto.nav)
            if "pnl_history" in state:
                self._e.risk._pnl_history = [float(x) for x in state["pnl_history"]]
                onto = getattr(self._e, "onto", None)
                if onto is not None:
                    onto._pnl_history = list(self._e.risk._pnl_history)
                    onto.var_1d = onto._calc_var()
                log.info("VaR gecmisi yuklendi | %d kayit", len(self._e.risk._pnl_history))
            if "vol_history" in state:
                self._e.risk._vol_history = [float(x) for x in state["vol_history"]]
            log.info(
                "BotEngine: durum geri yuklendi | equity=%.2f | acik_poz=%d | islem=%d",
                self._e.equity,
                len(self._e.open_positions),
                len(self._e.trade_log),
            )
        except Exception as e:
            log.error("BotEngine._load_state hatasi: %s", e)

    def _sync_legacy_flat_state_to_ledger(self) -> None:
        """``capital_engine`` alanı olmayan state: NAV ile CapitalEngine / RiskOntology uyumu."""
        eq = float(self._e.equity)
        if not self._e.open_positions:
            self._e.capital._cash = eq
            self._e.capital._margin_used = 0.0
            self._e.capital._unrealized_pnl = 0.0
        self._e.capital.initial_capital = eq
        self._e.initial_capital = eq
        self._e.risk.initial_capital = eq
        self._e.equity = self._e.capital.nav
        self._e.free_capital = self._e.capital.available_cash
        onto = getattr(self._e, "onto", None)
        if onto is not None:
            try:
                onto.update(nav=eq)
            except Exception:
                log.debug("RiskOntology.update(nav) atlandi (legacy state)", exc_info=True)

    def reset_daily_if_needed(self) -> None:
        from super_otonom import bot_engine as _be

        today = _be.date.today()
        if today != self._e._today:
            if self._e.reconciler is not None:
                report = self._e.reconciler.run(
                    capital_snapshot=self._e.capital.snapshot(),
                    audit_summary=self._e.audit.today_summary() if self._e.audit else None,
                )
                if not report.passed:
                    log.warning("RECONCILE | gün sonu FAILED | %s", report.warnings)
                self._e.reconciler.reset_for_new_day(self._e.capital.nav)
            if self._e.audit is not None:
                self._e.audit.system_event("DAY_RESET", nav=self._e.capital.nav)
            self._e._today = today
            self._e._trades_today = 0

    def set_safe_mode_block_new_entries(self, active: bool, reason: str = "") -> None:
        self._e._safe_mode_block_new_entries = bool(active)
        self._e._safe_mode_reason = reason or None
        log.warning(
            "SAFE_MODE | block_new_entries=%s | %s",
            active,
            reason or "—",
        )


class PositionManager:
    """Açık pozisyon metrikleri, unrealized, funding, trailing yardımcıları."""

    def __init__(self, engine: Any) -> None:
        self._e = engine

    def tick_update_unrealized(self, symbol: str, price: float) -> None:
        if not self._e.open_positions:
            return
        prices = {
            sym: price if sym == symbol else float(self._e.open_positions[sym].get("entry", 0))
            for sym in self._e.open_positions
        }
        self._e.capital.update_unrealized(prices)
        self._e.equity = self._e.capital.nav

    def tick_apply_funding_rate(self, analysis: Dict[str, Any]) -> None:
        if not self._e.open_positions:
            return
        _swap_rate = float(analysis.get("funding_rate", RISK.get("swap_rate_daily", 0.0003)))
        if _swap_rate <= 0:
            return
        for _sym, _pos in self._e.open_positions.items():
            _notional = float(_pos.get("size", 0))
            _swap_cost = _notional * _swap_rate
            if _swap_cost > 0.001:
                self._e.capital.record_fee(
                    _sym,
                    f"swap_{_sym}_{self._e._tick_counter}",
                    _swap_cost,
                    note=f"swap/funding rate | rate={_swap_rate:.6f}",
                )
                log.debug(
                    "FUNDING | %s | notional=%.2f rate=%.6f cost=%.4f",
                    _sym,
                    _notional,
                    _swap_rate,
                    _swap_cost,
                )

    def tick_check_trailing_stops(self, symbol: str) -> List[Tuple[str, Dict[str, Any]]]:
        return [(_sym, _pos) for _sym, _pos in self._e.open_positions.items() if _sym != symbol]

    def open_exposure(self, prices: Dict[str, float]) -> float:
        total = 0.0
        for sym, pos in self._e.open_positions.items():
            p = prices.get(sym, float(pos.get("entry", 0)))
            total += float(pos.get("qty", 0)) * float(p)
        return float(total)

    def avg_volume(self, candles: List[Dict[str, float]], n: int = 30) -> float:
        if not candles:
            return 1.0
        tail = candles[-n:]
        vols = [float(c.get("volume") or 0.0) for c in tail]
        return max(1.0, sum(vols) / max(len(vols), 1))


class TradeExecutor:
    """Giriş emri simülasyonu / borsa yürütmesi ve kapanışlar."""

    def __init__(self, engine: Any) -> None:
        self._e = engine

    async def entry_execute_order(
        self,
        _symbol: str,
        price: float,
        size: float,
        analysis: Dict[str, Any],
    ) -> Tuple[float, float]:
        avg_vol = max(float(analysis.get("avg_volume") or 1.0), 1.0)

        if self._e.mode == "PAPER":
            sim_result = await self._e.exec_sim.simulate_order(
                side="buy", price=price, size=size, paper=True
            )
            fill_price = sim_result["executed_price"]
            filled_size = sim_result["filled_size"]
            qty = filled_size / float(fill_price or price)
            log.debug(
                "ExecutionSim BUY | fill_ratio=%.2f latency=%.0fms slip=%.5f%%",
                sim_result["fill_ratio"],
                sim_result["latency"] * 1000,
                sim_result["slippage"] * 100,
            )
        else:
            qty = size / float(price or 1.0)
            order_id = self._e.order_engine.intent(_symbol, "BUY", qty, price)
            try:
                result = await self._e.exchange.create_order(
                    symbol=_symbol,
                    side="buy",
                    amount=qty,
                    price=price,
                    order_type="limit",
                    params={"clientOrderId": order_id},
                )
                exchange_oid = str(result.get("id", ""))
                self._e.order_engine.sent(order_id, exchange_order_id=exchange_oid)

                status = str(result.get("status", "")).lower()
                filled = float(result.get("filled", 0) or 0)
                avg_price = float(result.get("average", 0) or 0)
                fee = float((result.get("fee") or {}).get("cost", 0))

                if status in ("closed", "filled") and filled > 0:
                    self._e.order_engine.confirm(order_id, filled, avg_price, fee, result)
                    fill_price = avg_price
                    qty = filled
                elif status == "open" and filled > 0:
                    self._e.order_engine.partial(order_id, filled, avg_price, fee)
                    fill_price = avg_price
                    qty = filled
                elif status == "open":
                    fill_price = price
                    qty = qty
                    log.warning("BUY emri açık — fill bekleniyor | %s | id=%s", _symbol, order_id)
                else:
                    fill_price = avg_price if avg_price > 0 else price
                    qty = filled if filled > 0 else qty

                log.info(
                    "LIVE BUY | %s | fill_price=%.6f qty=%.8f fee=%.6f | oid=%s",
                    _symbol,
                    fill_price,
                    qty,
                    fee,
                    order_id,
                )
            except Exception as exc:
                self._e.order_engine.fail(order_id, str(exc))
                log.error("LIVE BUY HATA | %s | err=%s | id=%s", _symbol, exc, order_id)
                fill_price = self._e.slippage.adjusted_price(
                    "buy",
                    price,
                    order_size=float(size),
                    avg_volume=avg_vol,
                    volatility=float(analysis.get("volatility", 0.01)),
                )
                qty = size / float(fill_price or price)

        return fill_price, qty

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
        pos = self._e.open_positions.get(symbol)
        if not pos:
            return

        entry = float(pos.get("entry", price))
        qty = float(pos.get("qty", 0.0) or 0.0)
        size = float(pos.get("size", 0.0) or 0.0)
        initial_qty = float(pos.get("initial_qty", qty) or qty)
        if qty <= 0 or size <= 0:
            return

        sell_qty = min(qty, max(0.0, initial_qty * float(ratio)))
        if sell_qty <= 0:
            return
        sell_ratio = sell_qty / qty
        sell_size = size * sell_ratio
        avg_vol = float(analysis.get("avg_volume") or 1.0)

        if self._e.mode == "PAPER":
            sim_result = await self._e.exec_sim.simulate_order(
                side="sell", price=price, size=sell_size, paper=True
            )
            exit_px = sim_result["executed_price"]
            filled_qty = sell_qty * sim_result["fill_ratio"]
        else:
            order_id = self._e.order_engine.intent(symbol, "SELL", sell_qty, price)
            try:
                result = await self._e.exchange.create_order(
                    symbol=symbol,
                    side="sell",
                    amount=sell_qty,
                    price=price,
                    order_type="limit",
                    params={"clientOrderId": order_id},
                )
                exchange_oid = str(result.get("id", ""))
                self._e.order_engine.sent(order_id, exchange_order_id=exchange_oid)

                filled = float(result.get("filled", 0) or 0)
                avg_price = float(result.get("average", 0) or 0)
                fee = float((result.get("fee") or {}).get("cost", 0))
                status = str(result.get("status", "")).lower()

                if status in ("closed", "filled") and filled > 0:
                    self._e.order_engine.confirm(order_id, filled, avg_price, fee, result)
                    exit_px = avg_price
                    filled_qty = filled
                else:
                    exit_px = avg_price if avg_price > 0 else price
                    filled_qty = filled if filled > 0 else sell_qty

                log.info(
                    "LIVE PARTIAL SELL | %s | exit=%.6f qty=%.8f | oid=%s",
                    symbol,
                    exit_px,
                    filled_qty,
                    order_id,
                )
            except Exception as exc:
                self._e.order_engine.fail(order_id, str(exc))
                log.error("LIVE PARTIAL SELL HATA | %s | err=%s", symbol, exc)
                exit_px = self._e.slippage.adjusted_price(
                    "sell",
                    float(price),
                    order_size=sell_size,
                    avg_volume=max(avg_vol, 1.0),
                    volatility=float(analysis.get("volatility", 0.01)),
                )
                filled_qty = sell_qty

        _cap_pnl = self._e.capital.close_partial(
            symbol=symbol,
            order_id=pos.get("order_id", f"{symbol}_partial_{int(time.time() * 1000)}"),
            exit_price=exit_px,
            ratio=filled_qty / qty if qty > 0 else 1.0,
            fee=float(analysis.get("fee", 0.0)),
        )
        pnl = _cap_pnl if _cap_pnl is not None else (exit_px - entry) * filled_qty

        pos["qty"] = max(0.0, qty - filled_qty)
        pos["size"] = max(0.0, size - sell_size)
        pos["exit_stage"] = int(new_stage)
        final_stage = int(new_stage)
        if pos["qty"] <= 1e-10 or pos["size"] <= 1e-8:
            self._e.open_positions.pop(symbol, None)
            final_stage = 3

        self._e.equity = self._e.capital.nav
        self._e.free_capital = self._e.capital.available_cash
        self._e.risk.record_pnl(pnl)
        if hasattr(self._e.risk, "record_omega_trade_outcome"):
            self._e.risk.record_omega_trade_outcome(pnl)
        self._e.onto.update(
            nav=self._e.capital.nav,
            positions=self._e.open_positions,
            realized_pnl_delta=pnl,
        )

        trade_record = {
            "symbol": symbol,
            "entry": entry,
            "exit": exit_px,
            "qty": filled_qty,
            "pnl": round(pnl, 4),
            "reason": reason,
            "partial": True,
            "exit_stage": final_stage,
            "hold_bars": int(pos.get("hold_bars", 0)),
            "regime": str(analysis.get("regime", "")),
            "pnl_pct": round((exit_px - entry) / entry * 100, 4) if entry else 0.0,
        }
        self._e.trade_log.append(trade_record)
        self._e.trade_logger.log_trade(trade_record)
        out["actions"].append(
            {
                "type": "SELL_PARTIAL",
                "symbol": symbol,
                "price": exit_px,
                "qty": filled_qty,
                "pnl": round(pnl, 4),
                "reason": reason,
                "exit_stage": final_stage,
            }
        )
        log.info(
            "CIKIS | partial | symbol=%s | fiyat=%.6f | pnl=%.4f | reason=%s | stage=%s",
            symbol,
            exit_px,
            pnl,
            reason,
            pos.get("exit_stage", new_stage),
        )
        self._e.metrics.record_slippage(symbol, price, exit_px)
        self._e.metrics.record_trade(pnl=pnl, reason=reason)
        self._e._save_state()

    async def close(
        self, symbol: str, price: float, out: Dict[str, Any], reason: str, analysis: Dict[str, Any]
    ) -> None:
        pos = self._e.open_positions.pop(symbol, None)
        if not pos:
            return

        size = float(pos.get("size") or 0.0)
        entry = float(pos.get("entry") or price)
        qty = float(pos.get("qty") or 0.0)
        avg_vol = float(analysis.get("avg_volume") or 1.0)

        if self._e.mode == "PAPER":
            sim_result = await self._e.exec_sim.simulate_order(
                side="sell", price=price, size=size, paper=True
            )
            exit_px = sim_result["executed_price"]
            filled_qty = qty * sim_result["fill_ratio"]
        else:
            order_id = self._e.order_engine.intent(symbol, "SELL", qty, price)
            try:
                result = await self._e.exchange.create_order(
                    symbol=symbol,
                    side="sell",
                    amount=qty,
                    price=price,
                    order_type="limit",
                    params={"clientOrderId": order_id},
                )
                exchange_oid = str(result.get("id", ""))
                self._e.order_engine.sent(order_id, exchange_order_id=exchange_oid)

                filled = float(result.get("filled", 0) or 0)
                avg_price = float(result.get("average", 0) or 0)
                fee = float((result.get("fee") or {}).get("cost", 0))
                status = str(result.get("status", "")).lower()

                if status in ("closed", "filled") and filled > 0:
                    self._e.order_engine.confirm(order_id, filled, avg_price, fee, result)
                    exit_px = avg_price
                    filled_qty = filled
                else:
                    exit_px = avg_price if avg_price > 0 else price
                    filled_qty = filled if filled > 0 else qty

                log.info(
                    "LIVE CLOSE | %s | exit=%.6f qty=%.8f | oid=%s",
                    symbol,
                    exit_px,
                    filled_qty,
                    order_id,
                )
            except Exception as exc:
                self._e.order_engine.fail(order_id, str(exc))
                log.error("LIVE CLOSE HATA | %s | err=%s", symbol, exc)
                exit_px = self._e.slippage.adjusted_price(
                    "sell",
                    float(price),
                    order_size=size,
                    avg_volume=max(avg_vol, 1.0),
                    volatility=float(analysis.get("volatility", 0.01)),
                )
                filled_qty = qty

        _cap_pnl = self._e.capital.close_position(
            symbol=symbol,
            order_id=pos.get("order_id", f"{symbol}_close_{int(time.time() * 1000)}"),
            exit_price=exit_px,
            filled_qty=filled_qty,
            fee=float(analysis.get("fee", 0.0)),
        )
        pnl = _cap_pnl if _cap_pnl is not None else (exit_px - entry) * filled_qty
        if _cap_pnl is None:
            log.warning("CapitalEngine: pozisyon ledgerde yok, fallback pnl=%.4f", pnl)
        self._e.equity = self._e.capital.nav
        self._e.free_capital = self._e.capital.available_cash
        self._e._trades_today += 1
        self._e.risk.record_pnl(pnl)
        if hasattr(self._e.risk, "record_omega_trade_outcome"):
            self._e.risk.record_omega_trade_outcome(pnl)
        self._e.onto.update(
            nav=self._e.capital.nav,
            positions=self._e.open_positions,
            realized_pnl_delta=pnl,
        )

        trade_record = {
            "symbol": symbol,
            "entry": entry,
            "exit": exit_px,
            "qty": filled_qty,
            "pnl": round(pnl, 4),
            "reason": reason,
            "strategist": str(analysis.get("strategist", "trend")),
            "signal_type": str(analysis.get("signal", "UNKNOWN")),
            "signal_confidence": float(analysis.get("ai_confidence", 0.0)),
            "sizing_source": str(analysis.get("sizing_source", "")),
            "hold_bars": int(pos.get("hold_bars", 0)),
            "volatility": float(analysis.get("volatility", 0.0)),
            "regime": str(analysis.get("regime", "")),
            "pnl_pct": round((exit_px - entry) / entry * 100, 4) if entry else 0.0,
            "slippage_pct": round(
                abs(exit_px - float(analysis.get("close", exit_px))) / max(exit_px, 1e-9) * 100, 4
            ),
            "entry_phase_chain": pos.get("entry_phase_chain"),
            "entry_meta_regime": pos.get("entry_meta_regime"),
        }

        self._e.trade_log.append(trade_record)

        self._e.trade_logger.log_trade(trade_record)

        if self._e.audit is not None:
            self._e.audit.trade_close(
                symbol=symbol,
                order_id=pos.get("order_id", ""),
                price=exit_px,
                qty=filled_qty,
                pnl=pnl,
                fee=float(analysis.get("fee", 0.0)),
                reason=reason,
                nav=self._e.capital.nav,
                realized_pnl=self._e.capital._realized_pnl,
                open_positions=len(self._e.open_positions),
                meta={"entry": entry, "hold_bars": pos.get("hold_bars", 0)},
            )
        if self._e.reconciler is not None:
            self._e.reconciler.record_trade(
                symbol=symbol,
                pnl=pnl,
                fee=float(analysis.get("fee", 0.0)),
                reason=reason,
            )

        out["actions"].append(
            {
                "type": "SELL",
                "symbol": symbol,
                "price": exit_px,
                "qty": filled_qty,
                "pnl": round(pnl, 4),
                "reason": reason,
                "ai_explain": out.get("ai_explain", ""),
            }
        )
        log.info(
            "CIKIS | sell | symbol=%s | fiyat=%.6f | pnl=%.4f | reason=%s | slip=%.5f%%",
            symbol,
            exit_px,
            pnl,
            reason,
            abs(exit_px - price) / (price + 1e-9) * 100,
        )
        log.info("TRADE_WHY | SELL | %s | %s", symbol, out.get("ai_explain", ""))
        self._e.metrics.record_slippage(symbol, price, exit_px)
        self._e.metrics.record_trade(pnl=pnl, reason=reason)
        self._e._save_state()
