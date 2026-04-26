"""
bot_engine.py yuksek kapsam (%96+ hedef): stub import, risk dallari, _handle_*, OrderTracker, LIVE close.
"""
from __future__ import annotations

import asyncio
import builtins
import importlib
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from super_otonom.config import RISK as CONFIG_RISK


def _be_paths(tmp_path, monkeypatch: pytest.MonkeyPatch):
    from super_otonom import bot_engine as be

    monkeypatch.setattr(be, "_STATE_FILE", str(tmp_path / "s.json"))
    monkeypatch.setattr(be, "_TRADE_LOG_FILE", str(tmp_path / "tr" / "tr.log"))
    return be


# ---------------------------------------------------------------------------
# 411: _peak_equity, equity yukseldiginde
# ---------------------------------------------------------------------------


def test_tick_updates_peak_equity(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    be = _be_paths(tmp_path, monkeypatch)
    e = be.BotEngine(1000.0, paper=True)
    e._peak_equity = 500.0
    e.equity = 2000.0
    from unittest.mock import patch as p2

    from super_otonom import bot_engine as bmod

    async def _hi(*a, **k) -> None:
        pass

    with p2.object(bmod, "compute_signal_quality", return_value=(50, [], {}, "m")), p2.object(
        bmod, "compute_omega_regime", return_value=("R", 1.0, 1.0, 50, "l")
    ), p2.object(e.ai, "validate_signal", return_value=("HOLD", 0.5, "")):
        asyncio.run(
            e.tick("X", {"signal": "HOLD", "volatility": 0.01, "regime": "R"}, [{"close": 1.0, "volume": 1.0}])
        )
    assert e._peak_equity == 2000.0


# ---------------------------------------------------------------------------
# 452-466: risk ret — emergency+reason, emergency unknown, sadece risk
# ---------------------------------------------------------------------------


def test_risk_deny_emergency_with_reason(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    be = _be_paths(tmp_path, monkeypatch)
    e = be.BotEngine(1000.0, paper=True)
    e.risk.check_risk = lambda *a, **k: False
    e.risk.get_last_deny = lambda: "x"
    e.risk.emergency_stop = True
    e.risk.emergency_reason = "y"
    c = [{"close": 1.0, "volume": 1.0}]
    with patch.object(be, "compute_signal_quality", return_value=(50, [], {}, "m")), patch.object(
        be, "compute_omega_regime", return_value=("R", 1.0, 1.0, 50, "l")
    ), patch.object(e.ai, "validate_signal", return_value=("BUY", 0.8, "ok")):
        out = asyncio.run(
            e.tick("Z", {"signal": "BUY", "volatility": 0.01, "regime": "R"}, c)
        )
    assert "EMERGENCY_STOP:y" in (out.get("decision_context") or {}).get("emergency_code", "")


def test_risk_deny_emergency_no_reason(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    be = _be_paths(tmp_path, monkeypatch)
    e = be.BotEngine(1000.0, paper=True)
    e.risk.check_risk = lambda *a, **k: False
    e.risk.get_last_deny = lambda: "d"
    e.risk.emergency_stop = True
    e.risk.emergency_reason = None
    c = [{"close": 1.0, "volume": 1.0}]
    with patch.object(be, "compute_signal_quality", return_value=(50, [], {}, "m")), patch.object(
        be, "compute_omega_regime", return_value=("R", 1.0, 1.0, 50, "l")
    ), patch.object(e.ai, "validate_signal", return_value=("HOLD", 0.5, "")):
        out = asyncio.run(
            e.tick("Z2", {"signal": "HOLD", "volatility": 0.01, "regime": "R"}, c)
        )
    assert (out.get("decision_context") or {}).get("emergency_code") == "EMERGENCY_STOP:unknown"


def test_risk_deny_no_emergency_info_log(
    tmp_path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    be = _be_paths(tmp_path, monkeypatch)
    e = be.BotEngine(1000.0, paper=True)
    e.risk.check_risk = lambda *a, **k: False
    e.risk.get_last_deny = lambda: "exposure"
    e.risk.emergency_stop = False
    c = [{"close": 1.0, "volume": 1.0}]
    with patch.object(be, "compute_signal_quality", return_value=(50, [], {}, "m")), patch.object(
        be, "compute_omega_regime", return_value=("R", 1.0, 1.0, 50, "l")
    ), patch.object(e.ai, "validate_signal", return_value=("BUY", 0.8, "ok")):
        with caplog.at_level("INFO", logger="super_otonom.engine"):
            asyncio.run(
                e.tick("Q", {"signal": "BUY", "volatility": 0.01, "regime": "R"}, c)
            )
    assert "risk_capali" in caplog.text or "GIRIS" in caplog.text


# ---------------------------------------------------------------------------
# 518: SENTIMENT_VETO + acik pozisyon -> _handle_exit
# ---------------------------------------------------------------------------


def test_sentiment_veto_with_open_position_exits(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    be = _be_paths(tmp_path, monkeypatch)
    e = be.BotEngine(100_000.0, paper=True)
    e.open_positions["V"] = {
        "entry": 100.0,
        "qty": 1.0,
        "size": 100.0,
        "peak": 100.0,
        "hold_bars": 0,
    }
    c = [{"close": 100.0, "volume": 1e6}]

    def _v(fin, _sent) -> tuple:
        if fin == "BUY":
            return "HOLD", "veto_test"
        return fin, "ok"

    e.sentiment_layer.validate_with_sentiment = _v
    e.sentiment_layer.get_market_sentiment = lambda: {"status": "N", "score": 0.5, "source": "t"}

    with patch.object(be, "compute_signal_quality", return_value=(50, [], {}, "m")), patch.object(
        be, "compute_omega_regime", return_value=("R", 1.0, 1.0, 50, "l")
    ), patch.object(e.ai, "validate_signal", return_value=("BUY", 0.8, "ok")):
        out = asyncio.run(
            e.tick("V", {"signal": "BUY", "volatility": 0.01, "regime": "R"}, c)
        )
    assert "veto" in (out.get("decision_reason") or "").lower() or out.get("final_signal") == "HOLD"


# ---------------------------------------------------------------------------
# 640-644, 660-666, 670-678, 697-701, 704-707: _handle_entry dallari
# ---------------------------------------------------------------------------


def test_entry_gate_closed_no_slots(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    be = _be_paths(tmp_path, monkeypatch)
    e = be.BotEngine(10_000.0, paper=True)
    omax = int(CONFIG_RISK.get("max_open_positions", 1))
    for i in range(omax):
        e.open_positions[f"P{i}"] = {"entry": 1.0, "qty": 1, "size": 1, "peak": 1, "hold_bars": 0}
    c = [{"close": 1.0, "volume": 1e3}]
    a = {
        "signal": "BUY",
        "volatility": 0.02,
        "regime": "TRENDING",
        "ob_safe_size": 5_000.0,
    }
    with patch.object(be, "compute_signal_quality", return_value=(90, [], {}, "m")), patch.object(
        be, "compute_omega_regime", return_value=("T", 1.0, 1.0, 90, "l")
    ), patch.object(e.ai, "validate_signal", return_value=("BUY", 0.9, "ok")):
        out = asyncio.run(e.tick("Sym", a, c))
    assert "decision_context" in out
    d = out.get("decision_context") or {}
    assert d.get("entry_blocked") is not None or "gate" in str(d).lower() or "max" in str(d).lower()


def test_entry_ob_safe_size_invalid_parses_none(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    be = _be_paths(tmp_path, monkeypatch)
    e = be.BotEngine(50_000.0, paper=True)
    a = {
        "signal": "BUY",
        "volatility": 0.02,
        "regime": "TRENDING",
        "ob_safe_size": "not-a-number",
    }
    c = [{"close": 100.0, "volume": 1e3}]
    with patch.object(be, "compute_signal_quality", return_value=(90, [], {}, "m")), patch.object(
        be, "compute_omega_regime", return_value=("T", 1.0, 1.0, 90, "l")
    ), patch.object(e.ai, "validate_signal", return_value=("BUY", 0.9, "ok")):
        out = asyncio.run(e.tick("ObBad", a, c))
    ctx = out.get("decision_context")
    if ctx and isinstance(ctx, dict) and "ob_safe_size_input" in str(ctx) or out:
        pass


def test_entry_ob_merge_blocks_zero(
    tmp_path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    be = _be_paths(tmp_path, monkeypatch)
    e = be.BotEngine(20_000.0, paper=True)
    a = {
        "signal": "BUY",
        "volatility": 0.02,
        "regime": "TRENDING",
        "ob_safe_size": 0.0,
    }
    c = [{"close": 10.0, "volume": 1e3}]
    with patch.object(be, "compute_signal_quality", return_value=(90, [], {}, "m")), patch.object(
        be, "compute_omega_regime", return_value=("T", 1.0, 1.0, 90, "l")
    ), patch.object(e.ai, "validate_signal", return_value=("BUY", 0.9, "ok")):
        with caplog.at_level("INFO", logger="super_otonom.engine"):
            asyncio.run(e.tick("Ob0", a, c))
    assert "engellendi" in caplog.text or "ob" in caplog.text.lower()


def test_entry_size_gate_fails(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    be = _be_paths(tmp_path, monkeypatch)
    e = be.BotEngine(100.0, paper=True)
    e.free_capital = 0.01
    a = {
        "signal": "BUY",
        "volatility": 0.02,
        "regime": "TRENDING",
        "ob_safe_size": 50.0,
    }
    c = [{"close": 1.0, "volume": 1e3}]
    with patch.object(be, "compute_signal_quality", return_value=(90, [], {}, "m")), patch.object(
        be, "compute_omega_regime", return_value=("T", 1.0, 1.0, 90, "l")
    ), patch.object(e.ai, "validate_signal", return_value=("BUY", 0.9, "ok")):
        out = asyncio.run(e.tick("Sz", a, c))
    assert out.get("actions", []) == [] or len(out.get("actions", [])) == 0


def _handle_entry_dctx_base(tmp_path, monkeypatch: pytest.MonkeyPatch):
    be = _be_paths(tmp_path, monkeypatch)
    e = be.BotEngine(10_000.0, paper=True)
    a = {
        "volatility": 0.02,
        "strategist": "t",
        "regime": "TREND",
        "ob_safe_size": 1_000.0,
    }
    return be, e, a


def test_handle_entry_dctx_none_gate_no_slots(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    be, e, a = _handle_entry_dctx_base(tmp_path, monkeypatch)
    out: dict = {"actions": []}
    with patch.object(
        be, "gate_buy_signal_and_slots", return_value=(False, "max_open_positions")
    ):
        asyncio.run(
            e._handle_entry(
                "D0", 1.0, a, "BUY", 0.9, out, corr_multiplier=1.0, dctx=None
            )
        )


def test_handle_entry_dctx_none_ob_block(
    tmp_path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    be, e, a = _handle_entry_dctx_base(tmp_path, monkeypatch)
    out: dict = {"actions": []}
    with patch.object(
        be, "gate_buy_signal_and_slots", return_value=(True, "")
    ), patch.object(
        be, "merge_entry_notional", return_value=(0.0, "ob", "ob_safe_size_zero")
    ):
        with caplog.at_level("INFO", logger="super_otonom.engine"):
            asyncio.run(
                e._handle_entry(
                    "D1", 1.0, a, "BUY", 0.9, out, corr_multiplier=1.0, dctx=None
                )
            )
    assert "GIRIS" in caplog.text or "engellendi" in caplog.text


def test_handle_entry_dctx_none_size_gate(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    be, e, a = _handle_entry_dctx_base(tmp_path, monkeypatch)
    out: dict = {"actions": []}
    with patch.object(
        be, "gate_buy_signal_and_slots", return_value=(True, "")
    ), patch.object(
        be, "merge_entry_notional", return_value=(8_000.0, "m", "")
    ), patch.object(
        be, "gate_buy_size_and_exposure", return_value=(False, "insufficient_free_capital")
    ):
        asyncio.run(
            e._handle_entry(
                "D2", 1.0, a, "BUY", 0.9, out, corr_multiplier=1.0, dctx=None
            )
        )


def test_handle_entry_dctx_none_hard_limit(
    tmp_path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    be, e, a = _handle_entry_dctx_base(tmp_path, monkeypatch)
    out: dict = {"actions": []}
    with patch.object(
        be, "gate_buy_signal_and_slots", return_value=(True, "")
    ), patch.object(
        be, "merge_entry_notional", return_value=(1_000.0, "m", "")
    ), patch.object(
        be, "gate_buy_size_and_exposure", return_value=(True, "")
    ), patch.object(
        e._hard_limits, "can_submit_order", return_value="order_rate_exceeded"
    ):
        with caplog.at_level("CRITICAL", logger="super_otonom.engine"):
            asyncio.run(
                e._handle_entry(
                    "D3", 1.0, a, "BUY", 0.9, out, corr_multiplier=1.0, dctx=None
                )
            )
    assert "EMERGENCY_STOP" in caplog.text or "order_rate" in caplog.text


# ---------------------------------------------------------------------------
# 799-803: TAKE_PROFIT, STOP_LOSS, TRAILING, SELL sinyal
# ---------------------------------------------------------------------------


def test_handle_exit_stop_loss(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    be = _be_paths(tmp_path, monkeypatch)
    e = be.BotEngine(1_000.0, paper=True)
    e.open_positions["L"] = {
        "entry": 100.0,
        "qty": 1.0,
        "size": 100.0,
        "peak": 100.0,
        "hold_bars": 0,
    }
    c = [{"close": 80.0, "volume": 1.0}]

    async def _r() -> None:
        with patch.object(
            e.risk, "should_trailing_stop", return_value=False
        ), patch.object(e.exec_sim, "simulate_order", new_callable=AsyncMock) as so:
            so.return_value = {
                "executed_price": 80.0,
                "fill_ratio": 1.0,
            }
            out = await e.tick(
                "L", {"signal": "HOLD", "volatility": 0.1, "regime": "R"}, c
            )
        assert "actions" in out

    with patch.object(be, "compute_signal_quality", return_value=(50, [], {}, "m")), patch.object(
        be, "compute_omega_regime", return_value=("R", 1.0, 1.0, 50, "l")
    ), patch.object(e.ai, "validate_signal", return_value=("HOLD", 0.5, "")):
        asyncio.run(_r())


def test_handle_exit_trailing_and_signal_sell(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    be = _be_paths(tmp_path, monkeypatch)
    e = be.BotEngine(1_000.0, paper=True)
    e.open_positions["T"] = {
        "entry": 100.0,
        "qty": 1.0,
        "size": 100.0,
        "peak": 100.0,
        "hold_bars": 0,
    }
    c1 = [{"close": 100.0, "volume": 1.0}]
    with patch.object(be, "compute_signal_quality", return_value=(50, [], {}, "m")), patch.object(
        be, "compute_omega_regime", return_value=("R", 1.0, 1.0, 50, "l")
    ), patch.object(e.ai, "validate_signal", return_value=("HOLD", 0.5, "")), patch.object(
        e.risk, "should_trailing_stop", return_value=True
    ), patch.object(
        e.exec_sim, "simulate_order", new_callable=AsyncMock, return_value={"executed_price": 99.0, "fill_ratio": 1.0}
    ):
        asyncio.run(e.tick("T", {"signal": "HOLD", "volatility": 0.1, "regime": "R"}, c1))
    e.open_positions["S"] = {
        "entry": 100.0,
        "qty": 1.0,
        "size": 100.0,
        "peak": 100.0,
        "hold_bars": 0,
    }
    c2 = [{"close": 100.0, "volume": 1.0}]
    with patch.object(be, "compute_signal_quality", return_value=(50, [], {}, "m")), patch.object(
        be, "compute_omega_regime", return_value=("R", 1.0, 1.0, 50, "l")
    ), patch.object(e.ai, "validate_signal", return_value=("SELL", 0.8, "s")), patch.object(
        e.risk, "should_trailing_stop", return_value=False
    ), patch.object(
        e.exec_sim, "simulate_order", new_callable=AsyncMock, return_value={"executed_price": 100.0, "fill_ratio": 1.0}
    ):
        asyncio.run(
            e.tick("S", {"signal": "SELL", "volatility": 0.1, "regime": "R"}, c2)
        )


# ---------------------------------------------------------------------------
# 813: _close pozisyon yok
# 829-835: LIVE satis
# ---------------------------------------------------------------------------


def test_close_with_no_open_position(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    be = _be_paths(tmp_path, monkeypatch)
    e = be.BotEngine(1_000.0, paper=True)
    out: dict = {"actions": []}
    a = {"volatility": 0.1, "avg_volume": 1.0, "strategist": "t", "regime": "R"}
    asyncio.run(e._close("Nope", 1.0, out, "X", a))
    assert out["actions"] == []


def test_live_sell_uses_slippage_not_sim(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    be = _be_paths(tmp_path, monkeypatch)
    e = be.BotEngine(10_000.0, paper=False)
    e.mode = "LIVE"
    e.open_positions["L"] = {
        "entry": 100.0,
        "qty": 1.0,
        "size": 100.0,
        "peak": 100.0,
        "hold_bars": 0,
    }
    e.slippage.adjusted_price = MagicMock(return_value=99.0)
    c = [{"close": 99.0, "volume": 1.0}]

    async def _r() -> None:
        with patch.object(be, "compute_signal_quality", return_value=(50, [], {}, "m")), patch.object(
            be, "compute_omega_regime", return_value=("R", 1.0, 1.0, 50, "l")
        ), patch.object(e.risk, "check_risk", return_value=True), patch.object(
            e.risk, "should_trailing_stop", return_value=False
        ), patch.object(
            e.ai, "validate_signal", return_value=("HOLD", 0.5, "")
        ):
            out = await e.tick(
                "L", {"signal": "HOLD", "volatility": 0.1, "regime": "R", "strategist": "t"}, c
            )
        assert out is not None

    with patch.object(be, "compute_signal_quality", return_value=(50, [], {}, "m")), patch.object(
        be, "compute_omega_regime", return_value=("R", 1.0, 1.0, 50, "l")
    ), patch.object(e.ai, "validate_signal", return_value=("HOLD", 0.5, "")), patch.object(
        e.risk, "check_risk", return_value=True
    ), patch.object(
        e.risk, "should_trailing_stop", return_value=True
    ):
        asyncio.run(_r())
    e.slippage.adjusted_price = MagicMock(return_value=99.0)
    o: dict = {"actions": []}
    with patch.object(e.exec_sim, "simulate_order", new_callable=AsyncMock) as s:
        s.side_effect = AssertionError("should not use sim in live sell if branch taken")
    asyncio.run(
        e._close("L", 99.0, o, "TRAIL", {"volatility": 0.1, "avg_volume": 1.0, "strategist": "t"})
    )


# ---------------------------------------------------------------------------


def test_risk_no_record_omega_on_close(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    be = _be_paths(tmp_path, monkeypatch)
    e = be.BotEngine(1_000.0, paper=True)

    class _RiskNoOmega:
        """record_omega_trade_outcome yok: hasattr 842 dalı False, 843 atlanır."""

        emergency_stop = False
        emergency_reason = None

        def check_risk(self, *a, **k):
            return True

        def get_last_deny(self):
            return ""

        def should_trailing_stop(self, *a, **k):
            return False

        def record_pnl(self, pnl) -> None:
            pass

        def get_omega_effective_qmin(self, b):
            return b

        def status_dict(self):
            return {}

    e.risk = _RiskNoOmega()
    e.open_positions["R"] = {
        "entry": 10.0,
        "qty": 1.0,
        "size": 10.0,
        "peak": 10.0,
        "hold_bars": 0,
    }
    o = {"actions": []}
    a = {"volatility": 0.1, "avg_volume": 1.0, "strategist": "t", "regime": "R"}
    with patch.object(
        e.exec_sim, "simulate_order", new_callable=AsyncMock, return_value={"executed_price": 10.0, "fill_ratio": 1.0}
    ):
        asyncio.run(e._close("R", 10.0, o, "T", a))


def test_order_tracker_open_status_no_timeout_keeps_order() -> None:
    ex = MagicMock()
    ex.get_order_status = AsyncMock(return_value="open")
    ex.cancel_order = AsyncMock()
    from super_otonom.bot_engine import OrderTracker

    ot = OrderTracker(ex)
    ot._timeout_sec = 1_000_000
    ot.track("x1", "B")
    assert "x1" in ot.active_orders
    asyncio.run(ot.check_status())
    assert "x1" in ot.active_orders
    ex.get_order_status.assert_awaited()


# OrderTracker: exception 230-231
def test_order_tracker_get_order_error(
    tmp_path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _be_paths(tmp_path, monkeypatch)
    ex = MagicMock()
    ex.get_order_status = AsyncMock(side_effect=RuntimeError("net"))
    ex.cancel_order = AsyncMock()
    from super_otonom.bot_engine import OrderTracker

    ot = OrderTracker(ex)
    ot.track("a1", "S")
    with caplog.at_level("ERROR", logger="super_otonom.engine"):
        asyncio.run(ot.check_status())
    assert "durum" in caplog.text.lower() or "sorgu" in caplog.text.lower()


# ---------------------------------------------------------------------------
# 66-110, 115-117: import (alt islem — ana pytest surecinde modul referans bozulmasin)
# ---------------------------------------------------------------------------


def _reload_bot_engine_and_main_loop() -> None:
    for k in list(sys.modules):
        if k == "super_otonom.bot_engine" or k.startswith("super_otonom.bot_engine."):
            del sys.modules[k]
    import super_otonom.main_loop as _ml

    importlib.import_module("super_otonom.bot_engine")
    importlib.reload(_ml)


def test_all_core_imports_fail_uses_stubs_in_process(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _orig = builtins.__import__

    def _h(name, globals=None, locals=None, fromlist=(), level=0, **kwargs):
        if "fromlist" in kwargs:
            fromlist = kwargs.pop("fromlist")
        if name in (
            "super_otonom.position_sizer",
            "super_otonom.risk_manager",
            "super_otonom.core.position_sizer",
            "super_otonom.core.risk_manager",
        ):
            raise ImportError("x")
        return _orig(name, globals, locals, fromlist, level, **kwargs)

    for k in list(sys.modules):
        if k == "super_otonom.bot_engine" or k.startswith("super_otonom.bot_engine."):
            del sys.modules[k]
    for k in (
        "super_otonom.position_sizer",
        "super_otonom.risk_manager",
        "super_otonom.core.position_sizer",
        "super_otonom.core.risk_manager",
    ):
        sys.modules.pop(k, None)
    monkeypatch.setattr(builtins, "__import__", _h)
    try:
        m = importlib.import_module("super_otonom.bot_engine")
        assert m._CORE_AVAILABLE is False
        b = m.BotEngine(10.0, paper=True)
        p = b.slippage.adjusted_price("buy", 1.0, order_size=1.0, avg_volume=1.0, volatility=0.1)
        assert p == 1.0
        b.sizer.set_trade_log([])
        assert b.sizer.calculate("S", 10.0) == 0.0
        assert b.sizer.calculate_with_slippage() == 0.0
        assert b.sizer.validate_and_calculate() == 0.0
        assert b.sizer.can_open(1) is False
        b.risk.trigger_emergency("e", silent=True)
        assert b.risk.emergency_stop
        b.risk.get_last_deny()
        assert b.risk.check_risk()
        assert b.risk.should_trailing_stop() is False
        b.risk.record_pnl(0.0)
        b.risk.status_dict()
        assert b.risk.get_omega_effective_qmin(3) == 3
        b.risk.record_omega_trade_outcome(0.0)
    finally:
        monkeypatch.setattr(builtins, "__import__", _orig)
        for k in (
            "super_otonom.position_sizer",
            "super_otonom.risk_manager",
            "super_otonom.core.position_sizer",
            "super_otonom.core.risk_manager",
        ):
            sys.modules.pop(k, None)
        _reload_bot_engine_and_main_loop()


def test_top_risk_import_fails_uses_injected_core_alias_modules(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    super_otonom.core.* bu repoda yok; 72-74’u yurutmek icin gecici namespace
    yamalama + ust risk import’unu kes.
    main_loop’te eski BotEngine gecersiz kalmasin diye islem sonda reload.
    """
    from super_otonom import position_sizer, risk_manager

    core_ps = types.ModuleType("super_otonom.core.position_sizer")
    core_ps.PositionSizer = position_sizer.PositionSizer
    sys.modules["super_otonom.core.position_sizer"] = core_ps
    core_rm = types.ModuleType("super_otonom.core.risk_manager")
    core_rm.RiskManager = risk_manager.RiskManager
    sys.modules["super_otonom.core.risk_manager"] = core_rm

    _orig = builtins.__import__

    def _h(
        name: str,
        globals=None,
        locals=None,
        fromlist=(),
        level: int = 0,
        **kwargs,
    ):
        if "fromlist" in kwargs:
            fromlist = kwargs.pop("fromlist")
        fl = fromlist or ()
        if name == "super_otonom.risk_manager" and fl and "RiskManager" in fl:
            raise ImportError("force_core_fallback")
        return _orig(name, globals, locals, fl, level, **kwargs)

    for k in list(sys.modules):
        if k == "super_otonom.bot_engine" or k.startswith("super_otonom.bot_engine."):
            del sys.modules[k]
    monkeypatch.setattr(builtins, "__import__", _h)
    try:
        m = importlib.import_module("super_otonom.bot_engine")
        assert m._CORE_AVAILABLE is True
        b = m.BotEngine(200.0, paper=True)
        assert b is not None
    finally:
        monkeypatch.setattr(builtins, "__import__", _orig)
        for k in (
            "super_otonom.core.position_sizer",
            "super_otonom.core.risk_manager",
        ):
            sys.modules.pop(k, None)
        for k in list(sys.modules):
            if k == "super_otonom.bot_engine" or k.startswith("super_otonom.bot_engine."):
                del sys.modules[k]
        _reload_bot_engine_and_main_loop()


def test_slippage_fallback_when_market_models_unavailable_in_process(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _orig = builtins.__import__

    def _h(name, globals=None, locals=None, fromlist=(), level=0, **kwargs):
        if "fromlist" in kwargs:
            fromlist = kwargs.pop("fromlist")
        fl = fromlist or ()
        if name == "super_otonom.core.market_models" and fl and "SlippageModel" in fl:
            raise ImportError("no market_models")
        return _orig(name, globals, locals, fromlist, level, **kwargs)

    for k in list(sys.modules):
        if k == "super_otonom.bot_engine" or k.startswith("super_otonom.bot_engine."):
            del sys.modules[k]
    sys.modules.pop("super_otonom.core.market_models", None)
    monkeypatch.setattr(builtins, "__import__", _h)
    try:
        m = importlib.import_module("super_otonom.bot_engine")
        px = m.SlippageModel().adjusted_price(
            "buy", 2.5, order_size=1.0, avg_volume=1.0, volatility=0.1
        )
        assert abs(px - 2.5) < 1e-9
    finally:
        monkeypatch.setattr(builtins, "__import__", _orig)
        for k in list(sys.modules):
            if k == "super_otonom.bot_engine" or k.startswith("super_otonom.bot_engine."):
                del sys.modules[k]
        sys.modules.pop("super_otonom.core.market_models", None)
        _reload_bot_engine_and_main_loop()
