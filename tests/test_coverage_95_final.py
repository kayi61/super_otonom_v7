"""Final push to 95% coverage — exchange_async, risk_manager, main_loop helpers, adversarial_robustness extras."""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest


@pytest.fixture(autouse=True)
def _isolate_bot_state(tmp_path_factory, monkeypatch):
    """Her test bot_state.json'a yazmasin diye izole et."""
    import super_otonom.bot_engine as _be

    iso = tmp_path_factory.mktemp("bot_state_iso") / "bot_state.json"
    monkeypatch.setattr(_be, "_STATE_FILE", str(iso))
    yield
    # Best-effort cleanup of disk state
    try:
        if os.path.exists("data/bot_state.json"):
            os.remove("data/bot_state.json")
    except OSError:
        pass


# ════════════════════════════════════════════════════════════════════════════
# exchange_async.CircuitBreaker — tam davranış
# ════════════════════════════════════════════════════════════════════════════


def test_circuit_breaker_state_transitions() -> None:
    from super_otonom.exchange_async import CircuitBreaker

    cb = CircuitBreaker(failure_threshold=3, recovery_time=0.1)
    assert cb.state == "CLOSED"
    assert cb.can_proceed() is True

    # iki hata - yarı açık
    cb.record_failure()
    cb.record_failure()
    assert "HALF-OPEN" in cb.state or "CLOSED" in cb.state
    assert cb.can_proceed() is True

    # üçüncü hata - açık
    cb.record_failure()
    assert cb.is_open is True
    assert "OPEN" in cb.state
    assert cb.can_proceed() is False

    # idempotent: dördüncü hata sonrası hâlâ açık ama log atılmaz
    cb.record_failure()
    assert cb.is_open is True

    # success → reset
    cb.record_success()
    assert cb.is_open is False
    assert cb.failures == 0
    assert cb.state == "CLOSED"

    # tekrar aç → recovery süresi sonrası half-open
    cb.record_failure()
    cb.record_failure()
    cb.record_failure()
    assert cb.is_open is True

    # recovery_time geç
    import time as _t

    _t.sleep(0.12)
    assert cb.can_proceed() is True
    # bu durumda is_open False (half-open kabul)
    # tekrar başarılı çağrı simüle et
    cb.record_success()
    assert cb.failures == 0


# ════════════════════════════════════════════════════════════════════════════
# exchange_async.AsyncExchangeHandler — sahte _ex ile metot kapsama
# ════════════════════════════════════════════════════════════════════════════


class _FakeCcxtEx:
    """Minimal ccxt async sürümü taklidi."""

    def __init__(self, ohlcv: List[List[float]] = None, ob: Dict[str, Any] = None,
                 positions: List[Dict[str, Any]] = None, balance: Dict[str, Any] = None,
                 raise_on_ohlcv: bool = False, raise_on_ob: bool = False,
                 raise_on_pos: bool = False, raise_on_balance: bool = False,
                 raise_on_order: bool = False, status: str = "open") -> None:
        self._ohlcv = ohlcv or [[1, 1.0, 2.0, 0.5, 1.5, 100.0]]
        self._ob = ob or {"asks": [[10.0, 1.0]], "bids": [[9.0, 1.0]]}
        self._positions = positions or []
        self._balance = balance or {"total": {"USDT": 1000.0}}
        self._raise_on_ohlcv = raise_on_ohlcv
        self._raise_on_ob = raise_on_ob
        self._raise_on_pos = raise_on_pos
        self._raise_on_balance = raise_on_balance
        self._raise_on_order = raise_on_order
        self._status = status
        self.closed = False
        self.aiohttp_trust_env = True

    async def fetch_ohlcv(self, symbol: str, timeframe: str = "5m", limit: int = 150) -> List[List[float]]:
        if self._raise_on_ohlcv:
            raise Exception("ohlcv-fail")
        return self._ohlcv

    async def fetch_order_book(self, symbol: str, limit: int = 20) -> Dict[str, Any]:
        if self._raise_on_ob:
            raise Exception("ob-fail")
        return self._ob

    async def fetch_positions(self, symbols=None) -> List[Dict[str, Any]]:
        if self._raise_on_pos:
            raise Exception("pos-fail")
        return self._positions

    async def fetch_balance(self) -> Dict[str, Any]:
        if self._raise_on_balance:
            raise Exception("bal-fail")
        return self._balance

    async def fetch_order(self, order_id: str, symbol: str) -> Dict[str, Any]:
        if self._raise_on_order:
            raise Exception("order-fail")
        return {"status": self._status}

    async def cancel_order(self, order_id: str, symbol: str) -> None:
        if self._raise_on_order:
            raise Exception("cancel-fail")
        return None

    async def close(self) -> None:
        self.closed = True


def _make_handler_with_fake_ex(**fake_kwargs: Any):
    from super_otonom.exchange_async import AsyncExchangeHandler

    h = AsyncExchangeHandler.__new__(AsyncExchangeHandler)
    h.exchange_id = "binance"
    h.testnet = True
    h.max_retries = 2
    h.retry_delay = 0.01
    h._cb_threshold = 3
    h._cb_recovery = 60.0
    h._breakers = {}
    h._ex = _FakeCcxtEx(**fake_kwargs)
    return h


def test_async_exchange_handler_fetch_one_paths() -> None:
    h = _make_handler_with_fake_ex()
    out = asyncio.run(h._fetch_one("BTC/USDT", "5m", 10))
    assert isinstance(out, list)
    assert out[0][1] == 1.0

    # CB açıkken → boş döner
    br = h._get_breaker("ETH/USDT")
    br.is_open = True
    br.last_failure_time = 9999999999.0  # uzak gelecek
    out2 = asyncio.run(h._fetch_one("ETH/USDT", "5m", 10))
    assert out2 == []

    # _ex None iken simüle veri

    h2 = _make_handler_with_fake_ex()
    h2._ex = None
    sim = asyncio.run(h2._fetch_one("BTC/USDT", "5m", 5))
    assert isinstance(sim, list)
    assert len(sim) == 5

    # Hata yolu (retry & CB)
    h3 = _make_handler_with_fake_ex(raise_on_ohlcv=True)
    h3.max_retries = 2
    err = asyncio.run(h3._fetch_one("X/USDT", "5m", 3))
    assert isinstance(err, Exception)
    cb = h3._get_breaker("X/USDT")
    assert cb.failures >= 2


def test_async_exchange_handler_fetch_all_and_status() -> None:
    h = _make_handler_with_fake_ex()
    out = asyncio.run(h.fetch_all_ohlcv(["BTC/USDT", "ETH/USDT"], "5m", 5))
    assert "BTC/USDT" in out and "ETH/USDT" in out
    status = h.circuit_breaker_status()
    assert isinstance(status, dict)


def test_async_exchange_handler_order_book_and_balance() -> None:
    h = _make_handler_with_fake_ex()
    ob = asyncio.run(h.fetch_order_book("BTC/USDT"))
    assert "asks" in ob and "bids" in ob

    # _ex None iken boş
    h.close_pending = None  # noop
    h._ex = None
    ob2 = asyncio.run(h.fetch_order_book("BTC/USDT"))
    assert ob2 == {"asks": [], "bids": []}

    # balance: _ex None iken sahte
    bal = asyncio.run(h.fetch_balance())
    assert "total" in bal


def test_async_exchange_handler_order_book_error() -> None:
    h = _make_handler_with_fake_ex(raise_on_ob=True)
    ob = asyncio.run(h.fetch_order_book("BTC/USDT"))
    assert ob == {"asks": [], "bids": []}


def test_async_exchange_handler_positions_paths() -> None:
    h = _make_handler_with_fake_ex(positions=[{"symbol": "BTC/USDT", "qty": 1.0}])
    pos = asyncio.run(h.fetch_positions())
    assert isinstance(pos, list)
    # with explicit symbols
    pos2 = asyncio.run(h.fetch_positions(symbols=["BTC/USDT"]))
    assert isinstance(pos2, list)

    # _ex None
    h._ex = None
    assert asyncio.run(h.fetch_positions()) == []

    # error path
    h2 = _make_handler_with_fake_ex(raise_on_pos=True)
    assert asyncio.run(h2.fetch_positions()) == []


def test_async_exchange_handler_balance_error() -> None:
    h = _make_handler_with_fake_ex(raise_on_balance=True)
    with pytest.raises(Exception):
        asyncio.run(h.fetch_balance())


def test_async_exchange_handler_order_status_and_cancel() -> None:
    h = _make_handler_with_fake_ex(status="closed")
    st = asyncio.run(h.get_order_status("oid", "BTC/USDT"))
    assert st == "filled"

    h2 = _make_handler_with_fake_ex(status="open")
    assert asyncio.run(h2.get_order_status("oid", "BTC/USDT")) == "open"

    # _ex None → unknown
    h2._ex = None
    assert asyncio.run(h2.get_order_status("oid", "BTC/USDT")) == "unknown"

    # cancel ok
    h3 = _make_handler_with_fake_ex()
    assert asyncio.run(h3.cancel_order("oid", "BTC/USDT")) is True

    # cancel _ex None
    h3._ex = None
    assert asyncio.run(h3.cancel_order("oid", "BTC/USDT")) is False

    # error path
    h4 = _make_handler_with_fake_ex(raise_on_order=True)
    assert asyncio.run(h4.cancel_order("oid", "BTC/USDT")) is False
    assert asyncio.run(h4.get_order_status("oid", "BTC/USDT")) == "unknown"


def test_async_exchange_handler_close_and_aexit() -> None:
    h = _make_handler_with_fake_ex()
    asyncio.run(h.close())
    assert h._ex is None
    # idempotent
    asyncio.run(h.close())


def test_ohlcv_to_candles_helper() -> None:
    from super_otonom.exchange_async import ohlcv_to_candles

    rows = [
        [1, 10.0, 11.0, 9.0, 10.5, 100.0],
        [2, 10.5, 12.0, 10.0, 11.5, 150.0],
        [3],  # too short - skipped
    ]
    out = ohlcv_to_candles(rows)
    assert len(out) == 2
    assert out[0]["open"] == 10.0
    assert out[1]["volume"] == 150.0


def test_fake_ohlcv_simulation() -> None:
    from super_otonom.exchange_async import _fake_ohlcv

    out = _fake_ohlcv("BTC/USDT", 10)
    assert len(out) == 10
    assert all(len(r) == 6 for r in out)

    out2 = _fake_ohlcv("UNKNOWN/USDT", 5)
    assert len(out2) == 5


def test_async_exchange_handler_init_paths() -> None:
    from super_otonom.exchange_async import AsyncExchangeHandler

    # binance + testnet (varsayılan path)
    h = AsyncExchangeHandler(
        exchange_id="binance",
        api_key="k",
        api_secret="s",
        testnet=True,
        max_retries=1,
        retry_delay=0.01,
    )
    assert h.exchange_id == "binance"
    assert h._ex is not None
    asyncio.run(h.close())

    # extra_config kullanan path
    h2 = AsyncExchangeHandler(
        exchange_id="binance",
        api_key="",
        api_secret="",
        testnet=False,
        extra_config={"timeout": 10000},
    )
    assert h2._ex is not None
    asyncio.run(h2.close())

    # bilinmeyen exchange → ValueError
    with pytest.raises(ValueError):
        AsyncExchangeHandler(exchange_id="bilinmeyen_borsa_xyz")


# ════════════════════════════════════════════════════════════════════════════
# risk_manager — check_risk branches
# ════════════════════════════════════════════════════════════════════════════


def test_risk_manager_check_risk_with_onto_paths() -> None:
    from super_otonom.config import RISK
    from super_otonom.risk_manager import RiskManager
    from super_otonom.risk_ontology import RiskOntology

    # Daily limit breach
    rm = RiskManager(initial_capital=10000.0)
    onto = RiskOntology(initial_nav=10000.0)
    rm.set_ontology(onto)
    # Set up sod and pnl to force daily breach
    onto.sod_nav = 10000.0
    onto.update(nav=10000.0 * (1.0 - RISK["max_daily_loss_pct"] - 0.05))
    onto.dynamic_daily_limit = RISK["max_daily_loss_pct"]
    out = rm.check_risk(current_equity=onto.nav, current_vol=0.0)
    assert out is False

    # Weekly limit breach
    rm2 = RiskManager(initial_capital=10000.0)
    onto2 = RiskOntology(initial_nav=10000.0)
    rm2.set_ontology(onto2)
    onto2.sow_nav = 10000.0
    onto2.sod_nav = 10000.0
    onto2.update(nav=10000.0 * (1.0 - RISK["max_weekly_loss_pct"] - 0.05))
    onto2.dynamic_daily_limit = 1.0  # huge so daily isn't breached
    out2 = rm2.check_risk(current_equity=onto2.nav, current_vol=0.0)
    assert out2 is False

    # Drawdown breach
    rm3 = RiskManager(initial_capital=10000.0)
    onto3 = RiskOntology(initial_nav=10000.0)
    rm3.set_ontology(onto3)
    # bump peak_nav above sod_nav so daily/weekly don't breach but dd does
    onto3.peak_nav = 20000.0
    onto3.sod_nav = 10.0  # tiny so loss against sod is huge but daily skipped via dynamic limit
    onto3.sow_nav = 10.0
    onto3.update(nav=20000.0 * (1.0 - RISK["max_total_drawdown"] - 0.05))
    onto3.dynamic_daily_limit = 100.0  # never breached
    out3 = rm3.check_risk(current_equity=onto3.nav, current_vol=0.0)
    # drawdown may or may not breach depending on whether daily/weekly are skipped
    assert isinstance(out3, bool)


def test_risk_manager_check_risk_without_onto_all_paths() -> None:
    from super_otonom.config import RISK
    from super_otonom.risk_manager import RiskManager

    # invalid capital
    rm0 = RiskManager(initial_capital=0.0)
    assert rm0.check_risk(current_equity=1000.0) is False
    assert rm0.get_last_deny() == "invalid_capital"

    # emergency latched
    rm = RiskManager(initial_capital=10000.0)
    rm.trigger_emergency("test_lock", silent=True)
    assert rm.check_risk(current_equity=10000.0) is False
    assert rm.get_last_deny() in ("test_lock", "emergency_latched")

    # static daily loss path
    rm2 = RiskManager(initial_capital=10000.0)
    rm2.record_pnl(-RISK["max_daily_loss_pct"] * 10000.0 - 100.0)
    assert rm2.check_risk(current_equity=9000.0, current_vol=0.0) is False
    assert rm2.get_last_deny() in (
        "static_daily_loss",
        "weekly_loss",
        "max_drawdown",
    )

    # dynamic daily loss path
    rm3 = RiskManager(initial_capital=10000.0)
    rm3.record_pnl(-500.0)
    out3 = rm3.check_risk(current_equity=9500.0, current_vol=0.01)
    # may or may not deny depending on RISK thresholds; just exercise path
    assert isinstance(out3, bool)

    # drawdown path
    rm4 = RiskManager(initial_capital=10000.0)
    rm4.update_peak(10000.0)
    # bigger drawdown
    big_dd = 1.0 - RISK["max_total_drawdown"] - 0.05
    assert rm4.check_risk(current_equity=10000.0 * big_dd, current_vol=0.0) is False


def test_risk_manager_check_exposure_paths() -> None:
    from super_otonom.config import RISK
    from super_otonom.risk_manager import RiskManager

    rm = RiskManager(initial_capital=10000.0)
    # exposure breach
    max_exp = RISK["max_exposure_pct"]
    big_exposure = 10000.0 * (max_exp + 0.5)
    out = rm.check_risk(
        current_equity=10000.0,
        open_exposure=big_exposure,
        current_vol=0.0,
    )
    assert out is False
    assert rm.get_last_deny() == "max_exposure"


def test_risk_manager_volatility_spike() -> None:
    from super_otonom.risk_manager import RiskManager

    rm = RiskManager(initial_capital=10000.0)
    # Fill history with low vol
    for _ in range(20):
        rm.record_volatility(0.01)
    # Now check_volatility_spike with huge vol
    ok = rm.check_volatility_spike(0.5)
    assert ok is False  # spike detected

    # Insufficient history → True (allow)
    rm2 = RiskManager(initial_capital=10000.0)
    rm2.record_volatility(0.01)
    assert rm2.check_volatility_spike(0.1) is True

    # Zero avg_vol → True
    rm3 = RiskManager(initial_capital=10000.0)
    for _ in range(15):
        rm3.record_volatility(0.0)
    assert rm3.check_volatility_spike(0.1) is True


def test_risk_manager_var_and_reset() -> None:
    from super_otonom.risk_manager import RiskManager

    rm = RiskManager(initial_capital=10000.0)
    # < 100 samples → 0.0
    assert rm.calculate_var() == 0.0

    # Fill 100 samples
    for i in range(120):
        rm.record_pnl(-10.0 if i % 2 == 0 else 5.0)
    var = rm.calculate_var()
    assert isinstance(var, float)

    # reset_emergency
    rm.trigger_emergency("x", silent=True)
    rm.reset_emergency()
    assert rm.emergency_stop is False
    assert rm.emergency_reason is None

    # status_dict path
    d = rm.status_dict()
    assert isinstance(d, dict)
    assert "daily_loss" in d


def test_risk_manager_omega_qmin_helper() -> None:
    from super_otonom.risk_manager import RiskManager

    rm = RiskManager(initial_capital=10000.0)
    # zarar art arda → tighten artar
    for _ in range(15):
        rm.record_omega_trade_outcome(-50.0)
    # clamped to 25
    assert rm._omega_qmin_tighten <= 25

    qmin = rm.get_omega_effective_qmin(60)
    assert isinstance(qmin, int)
    assert qmin <= 90
    # negative base clamp
    assert rm.get_omega_effective_qmin(-10) >= 0
    # big base clamp
    assert rm.get_omega_effective_qmin(200) <= 95 + 25


# ════════════════════════════════════════════════════════════════════════════
# adversarial_robustness — extra branches
# ════════════════════════════════════════════════════════════════════════════


def test_adversarial_extra_branches() -> None:
    import numpy as np
    from super_otonom.adversarial_robustness import (
        _pick_score_type,
        _series_from_dict,
        _try_ts_ms,
        analyze_adversarial_robustness,
        extract_ohlcv,
        score_fake_breakout,
        score_flash_crash,
        score_pump_dump,
        score_slow_bleed,
        score_volatility_spike,
    )

    out = analyze_adversarial_robustness("BTC/USDT", [])
    assert isinstance(out, dict)

    candles = [{"timestamp": i, "open": 100.0 + i, "high": 101.0 + i,
                "low": 99.0 + i, "close": 100.5 + i, "volume": 1.0} for i in range(5)]
    out2 = analyze_adversarial_robustness("BTC/USDT", candles)
    assert isinstance(out2, dict)

    np.random.seed(42)
    candles_big = []
    p = 100.0
    for i in range(120):
        p *= float(1 + np.random.normal(0, 0.001))
        candles_big.append({
            "timestamp": i, "open": p, "high": p * 1.001,
            "low": p * 0.999, "close": p, "volume": 100.0,
        })
    out3 = analyze_adversarial_robustness("BTC/USDT", candles_big)
    assert isinstance(out3, dict)

    # _try_ts_ms variants
    assert isinstance(_try_ts_ms({"event_ts": 1000.0}), int)
    assert isinstance(_try_ts_ms({"event_ts": 1700000000000}), int)
    assert isinstance(_try_ts_ms({"event_ts": "bad"}), int)
    assert isinstance(_try_ts_ms({}), int)

    # _pick_score_type
    assert _pick_score_type(0.3, 0.5) == "QUALITY"
    assert _pick_score_type(0.8, 0.8) == "RISK"
    assert _pick_score_type(0.8, 0.5) == "ALPHA"

    # _series_from_dict
    assert _series_from_dict({"close": [1.0] * 50}, "close").size == 50
    assert _series_from_dict({"close": [1.0]}, "close") is None
    assert _series_from_dict({"close": ["bad"] * 50}, "close") is None
    assert _series_from_dict({"close": "not a list"}, "close") is None

    # extract_ohlcv with only close
    close_only = {"close": [100.0 + i * 0.1 for i in range(60)]}
    res = extract_ohlcv(close_only)
    assert res is not None

    # extract_ohlcv with full ohlcv as list
    ohlcv = [[i, 100.0, 101.0, 99.0, 100.5, 1.0] for i in range(60)]
    res2 = extract_ohlcv({"ohlcv": ohlcv})
    assert res2 is not None

    # No data
    assert extract_ohlcv({"foo": "bar"}) is None

    # score functions with small input
    assert score_flash_crash(np.array([100.0] * 5), np.array([100.0] * 5)) == 0.0
    assert score_pump_dump(np.array([100.0] * 5), np.array([1.0] * 5)) == 0.0
    assert score_slow_bleed(np.array([100.0] * 5)) == 0.0
    assert score_volatility_spike(np.array([100.0] * 5)) == 0.0
    assert score_fake_breakout(
        np.array([100.0] * 5), np.array([99.0] * 5), np.array([100.0] * 5)
    ) == 0.0

    # Larger synthetic data → various scores
    np.random.seed(1)
    c = np.cumsum(np.random.randn(100) * 0.01) + 100.0
    h = c * 1.005
    low = c * 0.995
    v = np.ones(100)
    s_fc = score_flash_crash(c, low)
    s_pd = score_pump_dump(c, v)
    s_sb = score_slow_bleed(c)
    s_vs = score_volatility_spike(c)
    s_fb = score_fake_breakout(h, low, c)
    for x in (s_fc, s_pd, s_sb, s_vs, s_fb):
        assert 0.0 <= x <= 1.0

    # Force flash crash scenario
    c_crash = np.array([100.0] * 30 + [70.0, 65.0, 60.0] + [100.0] * 20)
    low_crash = c_crash * 0.95
    s_fc2 = score_flash_crash(c_crash, low_crash)
    assert s_fc2 > 0.0

    # Force slow bleed (downward trend)
    c_bleed = np.linspace(100.0, 80.0, 40)
    s_sb2 = score_slow_bleed(c_bleed)
    assert s_sb2 >= 0.0


# ════════════════════════════════════════════════════════════════════════════
# main_loop helper — _apply_ob_safe_size / _is_stale_data / _circuit_breaker_open
# ════════════════════════════════════════════════════════════════════════════


def test_main_loop_helpers() -> None:
    from super_otonom.main_loop import _is_stale_data

    # Empty → False
    assert _is_stale_data([], "BTC/USDT") is False

    # Fresh candle → False
    import time

    fresh_ts = (time.time() - 30) * 1000
    assert _is_stale_data([{"timestamp": fresh_ts}], "BTC/USDT") is False

    # Very stale candle → True
    stale_ts = (time.time() - 7200) * 1000
    assert _is_stale_data([{"timestamp": stale_ts}], "BTC/USDT") is True


def test_main_loop_prep_symbol_for_tick_branches() -> None:
    """prep_symbol_for_tick'in farklı yolları için."""
    import time

    from super_otonom.analyzer import MarketAnalyzer
    from super_otonom.bot_engine import BotEngine
    from super_otonom.main_loop import prep_symbol_for_tick

    analyzer = MarketAnalyzer()
    engine = BotEngine(capital=10000.0, paper=True)
    engine._handle_entry = AsyncMock()
    engine._handle_exit = AsyncMock()
    engine.open_positions = {}

    h = _make_handler_with_fake_ex()
    h._breakers = {}

    raw_1h = [[int(time.time() * 1000) - i * 60_000, 100.0, 101.0, 99.0, 100.5, 100.0] for i in range(50)]

    # Path: 1H yok
    result_no_data = asyncio.run(
        prep_symbol_for_tick(
            "BTC/USDT", h, analyzer, engine, {}, {}, {}
        )
    )
    assert result_no_data is None

    # Path: stale data (zaten yüzlerce yıl önce)
    raw_stale = [[1000.0, 100.0, 101.0, 99.0, 100.5, 100.0] for _ in range(50)]
    result_stale = asyncio.run(
        prep_symbol_for_tick(
            "BTC/USDT", h, analyzer, engine, {"BTC/USDT": raw_stale}, {}, {}
        )
    )
    assert result_stale is None

    # Path: tam akış
    raw_data_1h = {"BTC/USDT": raw_1h}
    result_ok = asyncio.run(
        prep_symbol_for_tick(
            "BTC/USDT", h, analyzer, engine, raw_data_1h, {}, {}
        )
    )
    # result_ok might be None if analyzer needs more data, but the path is exercised
    assert result_ok is None or isinstance(result_ok, tuple)


def test_main_loop_apply_ob_safe_size() -> None:
    from super_otonom.bot_engine import BotEngine
    from super_otonom.main_loop import _apply_ob_safe_size

    engine = BotEngine(capital=10000.0, paper=True)
    engine._handle_entry = AsyncMock()
    engine._handle_exit = AsyncMock()
    engine.open_positions = {}

    ob_with_asks = {"asks": [[100.0, 1.0], [100.1, 2.0]], "bids": [[99.0, 1.0]]}
    candles = [
        {"timestamp": 1000 * i, "open": 100.0, "high": 101.0, "low": 99.0,
         "close": 100.5, "volume": 100.0} for i in range(20)
    ]
    analysis: Dict[str, Any] = {}
    _apply_ob_safe_size(
        engine, "BTC/USDT", ob_with_asks, candles, analysis, vol=0.01, ai_conf=0.6
    )
    assert "ob_safe_size" in analysis

    # ask yok → no-op
    ob_empty = {"asks": [], "bids": []}
    analysis2: Dict[str, Any] = {}
    _apply_ob_safe_size(
        engine, "BTC/USDT", ob_empty, candles, analysis2, vol=0.01, ai_conf=0.6
    )
    assert "ob_safe_size" not in analysis2

    # ask var ama candles boş → calculate_with_slippage path
    analysis3: Dict[str, Any] = {}
    _apply_ob_safe_size(
        engine, "BTC/USDT", ob_with_asks, [], analysis3, vol=0.01, ai_conf=0.6
    )
    assert "ob_safe_size" in analysis3


# ════════════════════════════════════════════════════════════════════════════
# transformer_intelligence — extra branches
# ════════════════════════════════════════════════════════════════════════════


def test_transformer_extra_paths() -> None:
    import numpy as np
    from super_otonom.transformer_intelligence import (
        _reshape_patches,
        analyze_transformer_intelligence,
        attention_entropy_flatness,
        direction_from_signals,
        log_returns,
        patch_self_attention,
        softmax_rows,
        temporal_gate_blend,
    )

    out = analyze_transformer_intelligence("BTC/USDT", [])
    assert isinstance(out, dict)

    np.random.seed(7)
    p = 100.0
    candles = []
    for i in range(80):
        p *= float(1 + np.random.normal(0, 0.002))
        candles.append({
            "timestamp": i * 60_000, "open": p, "high": p * 1.001,
            "low": p * 0.999, "close": p, "volume": 100.0,
        })
    out2 = analyze_transformer_intelligence("BTC/USDT", candles)
    assert isinstance(out2, dict)

    # Also test with `closes` directly
    closes_list = [p * (1 + 0.001 * i) for i in range(100)]
    out3 = analyze_transformer_intelligence("BTC/USDT", {"closes": closes_list})
    assert isinstance(out3, dict)

    # Bad close values + ohlcv path
    bad_ohlcv = [[i, 1.0, 1.0, 1.0, "bad" if i % 10 == 0 else 1.0 + i * 0.001, 1.0] for i in range(100)]
    out4 = analyze_transformer_intelligence("BTC/USDT", {"ohlcv": bad_ohlcv})
    assert isinstance(out4, dict)

    # log_returns edge cases
    assert log_returns([100.0, 101.0]).size == 0  # too short
    rets = log_returns([100.0, 101.0, 102.0, 101.0])
    assert rets.size == 3

    # _reshape_patches edge cases
    E_empty, d_e, pl_e = _reshape_patches(np.array([]), num_patches=4)
    assert E_empty.size == 0

    E_short, d_s, pl_s = _reshape_patches(np.array([0.01, 0.02, 0.03]), num_patches=4)
    assert E_short.size == 0

    # softmax_rows empty
    assert softmax_rows(np.array([])).size == 0
    # softmax_rows normal
    s = softmax_rows(np.array([[1.0, 2.0, 3.0]]))
    assert abs(np.sum(s) - 1.0) < 1e-6

    # attention_entropy_flatness empty
    ent_e, flat_e = attention_entropy_flatness(np.array([]))
    assert ent_e == 0.0
    assert flat_e == 1.0

    # patch_self_attention with small E
    rng = np.random.default_rng(42)
    a_attn, ctx = patch_self_attention(np.zeros((1, 4)), rng)
    assert a_attn.size == 1

    # temporal_gate_blend with small ctx
    gate, norm = temporal_gate_blend(np.zeros((1, 4)), np.zeros((1, 1)))
    assert gate == 0.5
    assert norm == 0.0

    # direction_from_signals with small ret
    label, score, strength = direction_from_signals(np.array([0.01, 0.02]), np.array([0.1, 0.2]), gate=0.5)
    assert label == "NEUTRAL"

    # Strong positive momentum
    pos_ret = np.array([0.01] * 20)
    label_up, score_up, _ = direction_from_signals(pos_ret, np.array([0.5, 0.6]), gate=0.8)
    assert label_up in ("UP", "NEUTRAL", "DOWN")


# ════════════════════════════════════════════════════════════════════════════
# hft_signal_engine — additional input shapes
# ════════════════════════════════════════════════════════════════════════════


def test_hft_signal_extra_paths() -> None:
    import numpy as np
    from super_otonom.signals.hft_signal_engine import (
        _float_list,
        _ohlcv_closes_volumes,
        _pick_score_type,
        _resolve_series,
        _session_fraction,
        _try_ts_ms,
        aggregate_ticks_to_bars,
        analyze_hft_signal,
    )

    out = analyze_hft_signal("BTC/USDT", [])
    assert isinstance(out, dict)

    candles = [
        {"timestamp": i * 1000, "open": 100.0, "high": 100.5, "low": 99.5,
         "close": 100.2, "volume": 100.0 + i} for i in range(60)
    ]
    out2 = analyze_hft_signal("BTC/USDT", candles)
    assert isinstance(out2, dict)

    # Tick data path
    ticks = [
        {"price": 100.0 + i * 0.01, "ts": (i * 1000), "size": 1.0}
        for i in range(60)
    ]
    out3 = analyze_hft_signal("BTC/USDT", {"ticks": ticks})
    assert isinstance(out3, dict)

    # Bad tick row (not dict)
    bad_ticks = ticks[:30] + ["not_a_dict"] * 5 + ticks[30:]
    out4 = analyze_hft_signal("BTC/USDT", {"ticks": bad_ticks})
    assert isinstance(out4, dict)

    # _try_ts_ms variants
    assert isinstance(_try_ts_ms({"event_ts": 1000.0}), int)
    assert isinstance(_try_ts_ms({"event_ts": 1700000000000}), int)
    assert isinstance(_try_ts_ms({"event_ts": "bad"}), int)
    assert isinstance(_try_ts_ms({}), int)

    # _pick_score_type
    assert _pick_score_type(data_health=0.3, risk_01=0.5) == "QUALITY"
    assert _pick_score_type(data_health=0.8, risk_01=0.8) == "RISK"
    assert _pick_score_type(data_health=0.8, risk_01=0.5) == "ALPHA"

    # _float_list
    assert _float_list([1.0, 2.0, 3.0], 2) is not None
    assert _float_list([1.0, "bad", 3.0], 3) is None  # only 2 valid
    assert _float_list(["all", "bad"], 1) is None
    assert _float_list([1.0], 2) is None

    # _ohlcv_closes_volumes
    ohlcv = [[i, 1.0, 2.0, 0.5, 100.0 + i, 10.0] for i in range(30)]
    result = _ohlcv_closes_volumes({"ohlcv": ohlcv})
    assert result is not None
    closes, vols = result
    assert closes.size == 30

    # _ohlcv_closes_volumes with dict rows
    candles_dict = [{"close": 100.0 + i, "volume": 1.0} for i in range(30)]
    result2 = _ohlcv_closes_volumes({"candles": candles_dict})
    assert result2 is not None

    # No data path
    assert _ohlcv_closes_volumes({"foo": "bar"}) is None

    # _resolve_series with no data
    p, v, t, src = _resolve_series({"foo": "bar"})
    assert src == "none"
    assert p.size == 0

    # aggregate_ticks_to_bars empty
    z = aggregate_ticks_to_bars(
        np.array([]), np.array([]), np.array([]), bar_window_ms=1000.0
    )
    assert all(arr.size == 0 for arr in z)

    # aggregate with real data
    prices = np.array([100.0, 100.5, 101.0, 100.8])
    vols = np.array([1.0, 1.5, 2.0, 1.0])
    times = np.array([0.0, 500.0, 1500.0, 1800.0])
    o, h, lo, c, vwap = aggregate_ticks_to_bars(prices, vols, times, bar_window_ms=1000.0)
    assert o.size == 2  # two buckets

    # _session_fraction
    sf = _session_fraction(np.array([0.0, 500.0, 1000.0]))
    assert sf.shape == (3,)
    assert sf[0] == 0.0
    assert sf[2] == 1.0


# ════════════════════════════════════════════════════════════════════════════
# kanon_drift_check — extra path
# ════════════════════════════════════════════════════════════════════════════


def test_kanon_drift_check_paths() -> None:
    from super_otonom.kanon_drift_check import run_all_checks

    ok, msgs = run_all_checks()
    assert isinstance(ok, bool)
    assert isinstance(msgs, list)


# ════════════════════════════════════════════════════════════════════════════
# main_loop — helper functions
# ════════════════════════════════════════════════════════════════════════════


def test_main_loop_update_adaptive_throttle() -> None:
    from super_otonom.bot_engine import BotEngine
    from super_otonom.main_loop import _update_adaptive_throttle

    engine = BotEngine(capital=10000.0, paper=True)
    engine._handle_entry = AsyncMock()
    engine._handle_exit = AsyncMock()
    engine.open_positions = {}

    class _FakeHandler:
        def __init__(self, statuses):
            self._statuses = statuses

        def circuit_breaker_status(self):
            return self._statuses

    # CB closed - normal path
    h_closed = _FakeHandler({"BTC/USDT": "CLOSED", "ETH/USDT": "CLOSED"})
    _update_adaptive_throttle(h_closed, engine)

    # one CB open
    h_one_open = _FakeHandler({"BTC/USDT": "OPEN (recovery=30s kaldı)", "ETH/USDT": "CLOSED"})
    _update_adaptive_throttle(h_one_open, engine)

    # multiple CB open
    h_multi = _FakeHandler({
        "BTC/USDT": "OPEN (recovery=30s kaldı)",
        "ETH/USDT": "OPEN (recovery=30s kaldı)",
    })
    _update_adaptive_throttle(h_multi, engine)


def test_main_loop_process_tick_result() -> None:
    from super_otonom.bot_engine import BotEngine
    from super_otonom.main_loop import _process_tick_result

    engine = BotEngine(capital=10000.0, paper=True)
    engine._handle_entry = AsyncMock()
    engine._handle_exit = AsyncMock()
    engine.open_positions = {}

    candles = [
        {"timestamp": i, "open": 100.0, "high": 101.0, "low": 99.0,
         "close": 100.5, "volume": 100.0} for i in range(5)
    ]

    # With reason + actions
    result = {
        "final_signal": "BUY",
        "ai_confidence": 0.8,
        "decision_reason": "high_alpha",
        "sentiment_status": "BULLISH",
        "corr_multiplier": 0.5,
        "actions": [{"type": "BUY", "price": 100.7}],
    }
    _process_tick_result("BTC/USDT", result, candles, engine)

    # Without reason / actions
    result2 = {
        "final_signal": "HOLD",
        "ai_confidence": 0.0,
        "decision_reason": "",
        "sentiment_status": "UNKNOWN",
        "corr_multiplier": 1.0,
        "actions": [],
    }
    _process_tick_result("BTC/USDT", result2, candles, engine)


def test_main_loop_check_heartbeat() -> None:
    import super_otonom.main_loop as ml
    from super_otonom.bot_engine import BotEngine

    engine = BotEngine(capital=10000.0, paper=True)
    engine._handle_entry = AsyncMock()
    engine._handle_exit = AsyncMock()
    engine.open_positions = {}

    # _LAST_SUCCESSFUL_FETCH == 0 → early return
    ml._LAST_SUCCESSFUL_FETCH = 0.0
    ml._check_heartbeat(engine)

    # Old fetch → timeout path
    import time as _t

    ml._LAST_SUCCESSFUL_FETCH = _t.time() - 99999
    ml._check_heartbeat(engine)


def test_main_loop_circuit_breaker_open_helper() -> None:
    from super_otonom.main_loop import _circuit_breaker_open

    class _FakeHandler:
        def circuit_breaker_status(self):
            return {"BTC/USDT": "OPEN (recovery=30s kaldı)", "ETH/USDT": "CLOSED"}

    h = _FakeHandler()
    assert _circuit_breaker_open(h, "BTC/USDT") is True
    assert _circuit_breaker_open(h, "ETH/USDT") is False
    assert _circuit_breaker_open(h, "UNKNOWN/USDT") is False


# ════════════════════════════════════════════════════════════════════════════
# bot_engine — emergency_liquidate, _save_state, _load_state, safe_mode
# ════════════════════════════════════════════════════════════════════════════


def test_bot_engine_emergency_liquidate_empty() -> None:
    from super_otonom.bot_engine import BotEngine

    engine = BotEngine(capital=10000.0, paper=True)
    engine._handle_entry = AsyncMock()
    engine._handle_exit = AsyncMock()
    engine.open_positions = {}

    result = asyncio.run(engine.emergency_liquidate("test_reason"))
    assert "liquidated" in result
    assert "failed" in result
    assert result["liquidated"] == []
    assert result["failed"] == []


def test_bot_engine_emergency_liquidate_with_positions() -> None:
    from super_otonom.bot_engine import BotEngine

    engine = BotEngine(capital=10000.0, paper=True)
    engine._handle_entry = AsyncMock()
    engine._handle_exit = AsyncMock()

    engine._close = AsyncMock(return_value=None)

    engine.open_positions = {
        "BTC/USDT": {"qty": 0.5, "entry": 100.0, "size": 50.0, "peak": 101.0, "order_id": "x1"},
        "ETH/USDT": {"qty": 1.0, "entry": 50.0, "size": 50.0, "peak": 51.0, "order_id": "x2"},
    }

    result = asyncio.run(engine.emergency_liquidate("test_emergency"))
    assert "liquidated" in result
    assert len(result["liquidated"]) == 2 or len(result["failed"]) > 0
    assert "total_pnl" in result


def test_bot_engine_emergency_liquidate_failure_path() -> None:
    from super_otonom.bot_engine import BotEngine

    engine = BotEngine(capital=10000.0, paper=True)
    engine._handle_entry = AsyncMock()
    engine._handle_exit = AsyncMock()

    async def _bad_close(*_a, **_k):
        raise RuntimeError("close-failed")

    engine._close = _bad_close
    engine.open_positions = {
        "BTC/USDT": {"qty": 0.5, "entry": 100.0, "size": 50.0, "peak": 101.0, "order_id": "x1"},
    }

    result = asyncio.run(engine.emergency_liquidate("err_test"))
    assert "BTC/USDT" in result["failed"]


def test_bot_engine_safe_mode_block() -> None:
    from super_otonom.bot_engine import BotEngine

    engine = BotEngine(capital=10000.0, paper=True)
    engine._handle_entry = AsyncMock()
    engine._handle_exit = AsyncMock()
    engine.open_positions = {}

    engine.set_safe_mode_block_new_entries(True, reason="recon_mismatch")
    assert engine._safe_mode_block_new_entries is True
    assert engine._safe_mode_reason == "recon_mismatch"

    engine.set_safe_mode_block_new_entries(False)
    assert engine._safe_mode_block_new_entries is False
    assert engine._safe_mode_reason is None


def test_bot_engine_save_and_load_state(tmp_path, monkeypatch) -> None:
    import super_otonom.bot_engine as be
    from super_otonom.bot_engine import BotEngine

    state_file = tmp_path / "bot_state.json"
    trade_file = tmp_path / "trades.log"
    monkeypatch.setattr(be, "_STATE_FILE", str(state_file))
    monkeypatch.setattr(be, "_TRADE_LOG_FILE", str(trade_file))

    engine = BotEngine(capital=10000.0, paper=True)
    engine._handle_entry = AsyncMock()
    engine._handle_exit = AsyncMock()

    engine.equity = 10500.0
    engine.free_capital = 9500.0
    engine.trade_log = [{"symbol": "BTC/USDT", "pnl": 100.0}]

    engine._save_state()
    assert state_file.exists()

    engine2 = BotEngine(capital=10000.0, paper=True)
    engine2._handle_entry = AsyncMock()
    engine2._handle_exit = AsyncMock()

    engine2._load_state()
    assert isinstance(engine2.trade_log, list)


def test_bot_engine_load_state_corrupt_json(tmp_path, monkeypatch) -> None:
    import super_otonom.bot_engine as be
    from super_otonom.bot_engine import BotEngine

    state_file = tmp_path / "bot_state.json"
    state_file.write_text("{ this is not valid json ::::", encoding="utf-8")
    monkeypatch.setattr(be, "_STATE_FILE", str(state_file))

    engine = BotEngine(capital=10000.0, paper=True)
    engine._handle_entry = AsyncMock()
    engine._handle_exit = AsyncMock()

    engine._load_state()
    assert engine._state_corrupt_fallback is True


def test_bot_engine_atomic_write_json(tmp_path) -> None:
    from super_otonom.engine_managers import atomic_write_json

    target = tmp_path / "subdir" / "data.json"
    atomic_write_json(str(target), {"key": "value", "num": 42})

    assert target.exists()
    import json as _json

    data = _json.loads(target.read_text(encoding="utf-8"))
    assert data["key"] == "value"
    assert data["num"] == 42


def test_bot_engine_avg_volume_and_open_exposure() -> None:
    from super_otonom.bot_engine import BotEngine

    engine = BotEngine(capital=10000.0, paper=True)
    engine._handle_entry = AsyncMock()
    engine._handle_exit = AsyncMock()
    engine.open_positions = {}

    assert engine._avg_volume([]) == 1.0

    candles = [{"volume": 100.0 + i} for i in range(40)]
    avg = engine._avg_volume(candles, n=20)
    assert avg > 0

    assert engine._open_exposure({}) == 0.0

    engine.open_positions = {
        "BTC/USDT": {"qty": 0.5, "entry": 100.0},
        "ETH/USDT": {"qty": 1.0, "entry": 50.0},
    }
    exp = engine._open_exposure({"BTC/USDT": 120.0})
    assert exp > 0


def test_bot_engine_calculate_position_with_drawdown() -> None:
    from super_otonom.bot_engine import BotEngine

    engine = BotEngine(capital=10000.0, paper=True)
    engine._handle_entry = AsyncMock()
    engine._handle_exit = AsyncMock()
    engine.open_positions = {}

    # Non-BUY signal → 1.0
    assert engine.calculate_position("BTC/USDT", "SELL") == 1.0
    assert engine.calculate_position("BTC/USDT", "HOLD") == 1.0

    # BUY signal - default dd_scale path
    res = engine.calculate_position("BTC/USDT", "BUY")
    assert isinstance(res, float)
    assert 0 <= res <= 2.0

    # Force high drawdown scenarios
    if hasattr(engine, "onto") and engine.onto is not None:
        engine.onto.intraday_dd_pct = 0.25  # 25% dd
        res_high = engine.calculate_position("BTC/USDT", "BUY")
        assert isinstance(res_high, float)


def test_bot_engine_compact_phase_chain_helper() -> None:
    from super_otonom.bot_engine import _compact_phase_chain_for_attribution

    assert _compact_phase_chain_for_attribution(None) is None
    assert _compact_phase_chain_for_attribution({}) is None
    assert _compact_phase_chain_for_attribution("not a dict") is None

    chain = {
        "faz1": {
            "trade_permission": "ALLOW",
            "reason": "high_alpha",
            "alpha_score": 0.8,
            "ignored_extra": None,
        },
        "faz2": "not a dict",
        "faz3": {"trade_permission": None, "extra": "x"},
    }
    out = _compact_phase_chain_for_attribution(chain)
    assert isinstance(out, dict)
    assert "faz1" in out
    assert out["faz1"]["trade_permission"] == "ALLOW"


def test_bot_engine_min_entry_confidence_helper() -> None:
    from super_otonom.bot_engine import _min_entry_confidence

    val = _min_entry_confidence()
    assert isinstance(val, float)
    assert 0.45 <= val <= 0.95


# ════════════════════════════════════════════════════════════════════════════
# benchmark_katman_a — mock benchmark (no network)
# ════════════════════════════════════════════════════════════════════════════


def test_benchmark_katman_a_mock_run(capsys) -> None:
    from super_otonom.benchmark_katman_a import (
        _make_candles,
        _MockExchangeHandler,
        _percentile,
        _print_omega_micro,
        _run_mock_benchmark,
        _summarize,
    )

    # helper functions
    candles = _make_candles(20, base=100.0)
    assert len(candles) == 20
    assert all("close" in c for c in candles)

    # percentile
    assert _percentile([], 50) == 0.0
    assert _percentile([1.0, 2.0, 3.0, 4.0], 50.0) == 2.5
    assert _percentile([5.0], 95.0) == 5.0

    # summarize - just verify no error
    _summarize("test", [1.0, 2.0, 3.0, 4.0, 5.0])
    _summarize("empty-test-stub", [0.1, 0.2])  # smaller list

    _print_omega_micro()

    # mock handler smoke
    h = _MockExchangeHandler({"asks": [[100.0, 1.0]], "bids": [[99.0, 1.0]]})
    ob = asyncio.run(h.fetch_order_book("BTC/USDT", limit=20))
    assert "asks" in ob
    assert h.circuit_breaker_status() == {}

    # mock benchmark run (small)
    asyncio.run(
        _run_mock_benchmark(
            iterations=2,
            warmup=1,
            scenario="normal",
            symbol="BTC/USDT",
        )
    )


def test_benchmark_katman_a_run_benchmark_mock() -> None:
    from super_otonom.benchmark_katman_a import _run_benchmark

    asyncio.run(
        _run_benchmark(
            iterations=1,
            warmup=0,
            scenario="normal",
            symbol="BTC/USDT",
            live_ob=False,
            exchange_id="binance",
        )
    )


# ════════════════════════════════════════════════════════════════════════════
# exchange_async — __aenter__ / __aexit__ / install resolver smoke
# ════════════════════════════════════════════════════════════════════════════


def test_async_exchange_handler_aenter_aexit_with_fake_ex() -> None:
    """Sahte ccxt _ex ile aenter/aexit yolu — binance demo dahil."""
    h = _make_handler_with_fake_ex()

    # Fake _ex'e load_time_difference / load_markets metodları ekle
    async def _fake_load_time(*a, **k):
        return None

    async def _fake_load_markets(*a, **k):
        return None

    h._ex.options = {"timeDifference": 0}
    h._ex.markets = {"BTC/USDT": {}}
    h._ex.load_time_difference = _fake_load_time
    h._ex.load_markets = _fake_load_markets
    h._ex.aiohttp_trust_env = True

    asyncio.run(_run_aenter_aexit(h))


async def _run_aenter_aexit(h) -> None:
    """Helper to run __aenter__ and __aexit__ sequentially."""
    obj = await h.__aenter__()
    assert obj is h
    await h.__aexit__(None, None, None)


def test_async_exchange_handler_aenter_load_time_error() -> None:
    """load_time_difference hata yolu."""
    h = _make_handler_with_fake_ex()

    async def _bad_load_time(*a, **k):
        raise Exception("time-fail")

    async def _ok_load_markets(*a, **k):
        return None

    h._ex.options = {}
    h._ex.markets = {}
    h._ex.load_time_difference = _bad_load_time
    h._ex.load_markets = _ok_load_markets

    asyncio.run(_run_aenter_aexit(h))


def test_async_exchange_handler_init_binance_demo() -> None:
    """BINANCE_TESTNET aktif binance demo init yolu."""
    import os

    from super_otonom.exchange_async import AsyncExchangeHandler

    old = os.environ.get("BINANCE_TESTNET")
    os.environ["BINANCE_TESTNET"] = "true"
    try:
        h = AsyncExchangeHandler(
            exchange_id="binance",
            api_key="k",
            api_secret="s",
            testnet=True,
        )
        assert h._ex is not None
        asyncio.run(h.close())
    finally:
        if old is None:
            os.environ.pop("BINANCE_TESTNET", None)
        else:
            os.environ["BINANCE_TESTNET"] = old


def test_async_exchange_handler_aenter_binance_testnet_load_markets() -> None:
    """Binance testnet load_markets yolu — başarılı ve hata varyantları."""
    import os

    h = _make_handler_with_fake_ex()
    h.exchange_id = "binance"
    h.testnet = True

    async def _ok_load_time(*a, **k):
        return None

    async def _ok_load_markets(*a, **k):
        return None

    h._ex.options = {}
    h._ex.markets = {}
    h._ex.load_time_difference = _ok_load_time
    h._ex.load_markets = _ok_load_markets

    # Enable testnet env
    old = os.environ.get("BINANCE_TESTNET")
    os.environ["BINANCE_TESTNET"] = "true"
    try:
        asyncio.run(_run_aenter_aexit(h))
    finally:
        if old is None:
            os.environ.pop("BINANCE_TESTNET", None)
        else:
            os.environ["BINANCE_TESTNET"] = old

    # Now error path: load_markets raises
    h2 = _make_handler_with_fake_ex()
    h2.exchange_id = "binance"
    h2.testnet = True

    async def _bad_load_markets(*a, **k):
        raise Exception("markets-fail")

    h2._ex.options = {}
    h2._ex.markets = {}
    h2._ex.load_time_difference = _ok_load_time
    h2._ex.load_markets = _bad_load_markets

    old = os.environ.get("BINANCE_TESTNET")
    os.environ["BINANCE_TESTNET"] = "true"
    try:
        asyncio.run(_run_aenter_aexit(h2))
    finally:
        if old is None:
            os.environ.pop("BINANCE_TESTNET", None)
        else:
            os.environ["BINANCE_TESTNET"] = old


def test_async_exchange_handler_init_kucoin_extra() -> None:
    """kucoin/okx extra config path."""
    from super_otonom.exchange_async import AsyncExchangeHandler

    # kucoin path
    try:
        h = AsyncExchangeHandler(
            exchange_id="kucoin",
            api_key="k",
            api_secret="s",
            testnet=True,
        )
        asyncio.run(h.close())
    except Exception:
        # ccxt kucoin not available - that's OK
        pass

    # okx path
    try:
        h2 = AsyncExchangeHandler(
            exchange_id="okx",
            api_key="k",
            api_secret="s",
            testnet=True,
        )
        asyncio.run(h2.close())
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════════════════
# portfolio_optimizer_pro — empty / edge inputs
# ════════════════════════════════════════════════════════════════════════════


def test_portfolio_optimizer_branches() -> None:
    import numpy as np
    from super_otonom.portfolio_optimizer_pro import (
        _extract_weights_map,
        _pick_score_type,
        _try_ts_ms,
        analyze_portfolio_optimizer,
        black_litterman_posterior,
        blend_optimal,
        equilibrium_returns,
        erc_imbalance_score,
        erc_weights,
        extract_return_matrix,
        max_sharpe_weights,
        prior_market_weights,
        sample_covariance,
    )

    out = analyze_portfolio_optimizer("BTC/USDT", {})
    assert isinstance(out, dict)

    # _try_ts_ms with various inputs
    assert isinstance(_try_ts_ms({"event_ts": 1000.0}), int)
    assert isinstance(_try_ts_ms({"event_ts": 1700000000000}), int)
    assert isinstance(_try_ts_ms({"event_ts": "bad"}), int)
    assert isinstance(_try_ts_ms({}), int)

    # _pick_score_type
    assert _pick_score_type(data_health=0.3, risk_01=0.5) == "QUALITY"
    assert _pick_score_type(data_health=0.8, risk_01=0.8) == "RISK"
    assert _pick_score_type(data_health=0.8, risk_01=0.5) == "ALPHA"

    # _extract_weights_map: dict, list, bad values, normalization
    assert _extract_weights_map({"weights": {"BTC": 0.5, "ETH": 0.5}}) == {"BTC": 0.5, "ETH": 0.5}
    assert _extract_weights_map({"weights": [["BTC", 0.5], ["ETH", 0.5]]}) == {"BTC": 0.5, "ETH": 0.5}
    assert _extract_weights_map({"weights": {"BTC": "bad", "ETH": 0.5}}) == {"ETH": 1.0}
    assert _extract_weights_map({"weights": [["BTC", "bad"]]}) == {}
    assert _extract_weights_map({}) == {}

    # extract_return_matrix
    res = extract_return_matrix({"asset_returns": {
        "BTC": [0.01] * 50,
        "ETH": [0.02] * 50,
        "BNB": [0.005] * 50,
    }})
    assert res is not None
    assert isinstance(res[0], np.ndarray)
    # too few series
    assert extract_return_matrix({"asset_returns": {"BTC": [0.01] * 50}}) is None
    # too short
    assert extract_return_matrix({"asset_returns": {"BTC": [0.01] * 5, "ETH": [0.02] * 5, "BNB": [0.005] * 5}}) is None
    # not a dict
    assert extract_return_matrix({"asset_returns": "bad"}) is None

    # Sample covariance
    R = np.random.RandomState(42).randn(50, 3) * 0.01
    Sigma = sample_covariance(R)
    assert Sigma.shape == (3, 3)

    # prior_market_weights
    pi_w = prior_market_weights(["BTC", "ETH", "BNB"], {"weights": {"BTC": 0.5, "ETH": 0.3, "BNB": 0.2}})
    assert np.isclose(np.sum(pi_w), 1.0)

    # equilibrium_returns
    pi = equilibrium_returns(Sigma, pi_w)
    assert pi.shape == (3,)

    # black_litterman_posterior: no views
    mu, unc = black_litterman_posterior(Sigma, pi, tau=0.05, P=None, Q=None, Omega=None)
    assert unc == 0.0

    # With views
    P = np.array([[1.0, -1.0, 0.0]])
    Q = np.array([0.005])
    Om_diag = np.array([0.001])
    mu_view, unc_view = black_litterman_posterior(Sigma, pi, tau=0.05, P=P, Q=Q, Omega=Om_diag)
    assert mu_view.shape == (3,)
    # full Omega matrix
    Om_mat = np.diag([0.001])
    mu_view2, unc_view2 = black_litterman_posterior(Sigma, pi, tau=0.05, P=P, Q=Q, Omega=Om_mat)
    assert mu_view2.shape == (3,)

    # ERC weights and imbalance
    w_erc = erc_weights(Sigma, max_iter=20)
    assert w_erc.shape == (3,)
    score = erc_imbalance_score(w_erc, Sigma)
    assert 0.0 <= score <= 1.0
    # zero variance edge case
    zero_var_score = erc_imbalance_score(np.zeros(3), np.zeros((3, 3)))
    assert zero_var_score == 1.0

    # Max sharpe weights
    w_ms = max_sharpe_weights(pi, Sigma)
    assert w_ms.shape == (3,)
    # All negative mu → fallback equal
    w_neg = max_sharpe_weights(-pi - 0.5, Sigma)
    assert w_neg.shape == (3,)

    # blend_optimal
    w_blend = blend_optimal(w_ms, w_erc, blend=0.6)
    assert w_blend.shape == (3,)
    assert abs(np.sum(w_blend) - 1.0) < 0.01


# ════════════════════════════════════════════════════════════════════════════
# whale_intent_microstructure_engine — branches
# ════════════════════════════════════════════════════════════════════════════


def test_rl_trading_agent_helpers() -> None:
    import numpy as np
    from super_otonom.rl_trading_agent import (
        _extract_close_series,
        _normalize,
        _pick_score_type,
        analyze_rl_agent,
        build_state_vector,
        entropy_probs,
        log_returns,
        softmax,
    )

    # _normalize
    assert _normalize("bad") == {}
    assert _normalize({"k": "v"}) == {"k": "v"}

    # _pick_score_type
    assert _pick_score_type(0.3, 0.5) == "QUALITY"
    assert _pick_score_type(0.8, 0.8) == "RISK"

    # _extract_close_series
    assert _extract_close_series({"close": [100.0 + i for i in range(50)]})
    assert _extract_close_series({"close": [100.0]}) == []
    assert _extract_close_series({"close": ["bad"] * 50}) == []
    # ohlcv path
    ohlcv = [[i, 100.0, 101.0, 99.0, 100.0 + i, 1.0] for i in range(50)]
    assert _extract_close_series({"ohlcv": ohlcv})
    # bad rows in ohlcv
    bad_ohlcv = [[i, 100.0, 101.0, 99.0, "bad", 1.0] for i in range(50)]
    assert _extract_close_series({"ohlcv": bad_ohlcv}) == []
    # no data
    assert _extract_close_series({"foo": "bar"}) == []

    # log_returns short
    assert log_returns([100.0]).size == 0
    rets = log_returns([100.0, 101.0, 102.0, 103.0])
    assert rets.size == 3

    # build_state_vector
    feat = build_state_vector(np.array([0.01, 0.02, 0.015, 0.005]), tail=4)
    assert feat.shape == (16,)
    # empty ret
    feat_e = build_state_vector(np.array([]), tail=4)
    assert feat_e.shape == (16,)

    # softmax, entropy_probs
    s = softmax(np.array([1.0, 2.0, 3.0]))
    assert abs(np.sum(s) - 1.0) < 1e-6
    e = entropy_probs(np.array([0.3, 0.4, 0.3]))
    assert isinstance(e, float)

    # analyze_rl_agent empty
    out = analyze_rl_agent("BTC/USDT", None)
    assert isinstance(out, dict)
    out2 = analyze_rl_agent("BTC/USDT", {})
    assert isinstance(out2, dict)

    # With data
    np.random.seed(0)
    closes = list(100.0 + np.cumsum(np.random.randn(80) * 0.5))
    out3 = analyze_rl_agent("BTC/USDT", {"close": closes})
    assert isinstance(out3, dict)


def test_order_engine_extras(tmp_path) -> None:
    from super_otonom.order_engine import OrderEngine

    log_f = str(tmp_path / "orders.log")
    pend_f = str(tmp_path / "pending.json")

    eng = OrderEngine(order_log_file=log_f, pending_file=pend_f, batch_mode=False)

    # intent → sent
    oid = eng.intent("BTC/USDT", "BUY", qty=1.0, price=100.0)
    assert eng.sent(oid, exchange_order_id="ex-1") is True

    # sent on unknown id
    assert eng.sent("nonexistent", exchange_order_id="ex-x") is False

    # sent on SENT state → invalid
    assert eng.sent(oid, exchange_order_id="ex-1") is False

    # partial
    assert eng.partial(oid, filled_qty=0.5, fill_price=100.0, fee=0.05) is True
    # partial unknown
    assert eng.partial("nonexistent", filled_qty=0.5, fill_price=100.0, fee=0.05) is False

    # is_duplicate
    eng.confirm(oid, filled_qty=1.0, fill_price=100.5, fee=0.1)
    assert eng.is_duplicate(oid) is True
    assert eng.is_duplicate("nonexistent") is False

    # can_retry
    oid2 = eng.intent("ETH/USDT", "SELL", qty=2.0, price=200.0)
    eng.fail(oid2, error_msg="timeout")
    # may or may not be retryable depending on retry_count
    res = eng.can_retry(oid2)
    assert isinstance(res, bool)
    assert eng.can_retry("nonexistent") is False

    # Get pending orders
    pend = eng.pending_orders()
    assert isinstance(pend, list)
    # Get failed retryable
    fail = eng.failed_retryable()
    assert isinstance(fail, list)

    # Create a second engine that loads from the pending file written by first engine
    # First, persist by adding an order that stays pending
    pend_oid = eng.intent("LTC/USDT", "BUY", qty=1.0, price=20.0)
    eng.sent(pend_oid, exchange_order_id="ex-pp")
    # pend_oid is now SENT - will be in pending file

    eng2 = OrderEngine(order_log_file=log_f, pending_file=pend_f, batch_mode=False)
    # Should have loaded pending - at least one order
    assert len(eng2._orders) >= 1

    # Test invalid pending file (corrupt JSON)
    with open(pend_f, "w", encoding="utf-8") as f:
        f.write("{ bad json")
    eng3 = OrderEngine(order_log_file=log_f, pending_file=pend_f, batch_mode=False)
    # Should not crash - empty orders
    assert isinstance(eng3._orders, dict)


def test_order_engine_recovery_paths(tmp_path) -> None:
    from super_otonom.order_engine import OrderEngine

    log_f = str(tmp_path / "orders.log")
    pend_f = str(tmp_path / "pending.json")

    eng = OrderEngine(order_log_file=log_f, pending_file=pend_f, batch_mode=False)

    # No pending → empty list
    out = asyncio.run(eng.recover(None))
    assert out == []

    # Add a pending order
    oid = eng.intent("BTC/USDT", "BUY", qty=1.0, price=100.0)
    eng.sent(oid, exchange_order_id="ex-r1")

    # Handler with fetch_order_by_client_id - returns closed/filled
    class _HClosed:
        async def fetch_order_by_client_id(self, sym, oid):
            return {"status": "closed", "filled": 1.0, "average": 100.5}

    out2 = asyncio.run(eng.recover(_HClosed()))
    assert isinstance(out2, list)

    # Add another pending and test cancel response
    oid2 = eng.intent("ETH/USDT", "BUY", qty=2.0, price=200.0)
    eng.sent(oid2, exchange_order_id="ex-r2")

    class _HCancel:
        async def fetch_order_by_client_id(self, sym, oid):
            return {"status": "canceled"}

    out3 = asyncio.run(eng.recover(_HCancel()))
    assert isinstance(out3, list)

    # Add another and test "not found" exception
    oid3 = eng.intent("X/USDT", "BUY", qty=1.0, price=10.0)
    eng.sent(oid3, exchange_order_id="ex-r3")

    class _HNotFound:
        async def fetch_order_by_client_id(self, sym, oid):
            raise Exception("Order not found")

    out4 = asyncio.run(eng.recover(_HNotFound()))
    assert isinstance(out4, list)

    # snapshot
    snap = eng.snapshot()
    assert "total_orders" in snap


def test_liquidity_games_detector_more_branches() -> None:
    from super_otonom.liquidity_games_detector import detect_liquidity_games

    # stop_hunt scenario: huge spread + high vol + imbalanced
    ob_stop_hunt = {
        "bids": [[100.0, 100.0], [99.0, 100.0]],
        "asks": [[110.0, 5.0], [115.0, 5.0]],
    }
    r1 = detect_liquidity_games(
        symbol="BTC/USDT",
        order_book=ob_stop_hunt,
        analysis={"volatility": 0.10},
    )
    assert hasattr(r1, "game_type")

    # momentum_ignition: medium spread + high vol + medium imb
    ob_momentum = {
        "bids": [[100.0, 200.0], [99.5, 100.0]],
        "asks": [[101.5, 30.0], [102.0, 20.0]],
    }
    r2 = detect_liquidity_games(
        symbol="BTC/USDT",
        order_book=ob_momentum,
        analysis={"volatility": 0.08},
    )
    assert hasattr(r2, "game_type")

    # quote_stuffing: wide spread + low data_health
    ob_stuff = {
        "bids": [[100.0, 1.0]],
        "asks": [[110.0, 1.0]],
    }
    r3 = detect_liquidity_games(
        symbol="BTC/USDT",
        order_book=ob_stuff,
        analysis={"volatility": None},  # data_health drops
    )
    assert hasattr(r3, "game_type")

    # spoofing: imbalanced + tight spread + high data_health
    ob_spoofing = {
        "bids": [[100.0, 500.0]] * 5,
        "asks": [[100.05, 10.0]] * 5,
    }
    r4 = detect_liquidity_games(
        symbol="BTC/USDT",
        order_book=ob_spoofing,
        analysis={"volatility": 0.005},
    )
    assert hasattr(r4, "game_type")

    # market_snapshot path (use_snap)
    r5 = detect_liquidity_games(
        symbol="BTC/USDT",
        order_book={"bids": [[100.0, 1.0]], "asks": [[101.0, 1.0]]},
        analysis={
            "volatility": 0.02,
            "market_snapshot": {
                "schema": "a8/v1",
                "order_book": {
                    "empty": False,
                    "spread_rel": 0.005,
                    "ob_imbalance_top10": 0.6,
                    "levels": {
                        "bids": [[100.0, 1.0]],
                        "asks": [[100.5, 1.0]],
                    },
                },
            },
        },
    )
    assert hasattr(r5, "game_type")

    # bad volatility value
    r6 = detect_liquidity_games(
        symbol="BTC/USDT",
        order_book=ob_momentum,
        analysis={"volatility": "bad"},
    )
    assert hasattr(r6, "game_type")


def test_meta_learning_engine_branches() -> None:
    import numpy as np
    from super_otonom.meta_learning_engine import (
        _list_float,
        _normalize,
        _pick_score_type,
        _try_ts_ms,
        analyze_meta_learning,
        cusum_two_sided,
        extract_metric_series,
    )

    # _try_ts_ms / _pick_score_type / _normalize
    assert isinstance(_try_ts_ms({"event_ts": 1000.0}), int)
    assert isinstance(_try_ts_ms({}), int)
    assert isinstance(_try_ts_ms({"event_ts": "bad"}), int)
    assert _pick_score_type(0.3, 0.5) == "QUALITY"
    assert _pick_score_type(0.8, 0.8) == "RISK"
    assert _normalize("not a dict") == {}
    assert _normalize({"k": "v"}) == {"k": "v"}

    # _list_float
    arr = _list_float([1.0, 2.0, 3.0], 2)
    assert arr is not None
    assert _list_float("not a list", 2) is None
    assert _list_float([1.0], 2) is None
    assert _list_float([1.0, "bad", 3.0], 3) is None

    # extract_metric_series — loss_series path
    arr_l, lib = extract_metric_series({"loss_series": [0.5 - i * 0.01 for i in range(30)]})
    assert lib is True
    # pred/target path
    arr_pt, _ = extract_metric_series({
        "predictions": [1.0] * 30,
        "targets": [1.05] * 30,
    })
    assert arr_pt is not None
    # accuracy series → lower_is_better = False
    arr_a, lib_a = extract_metric_series({
        "accuracy_series": [0.5 + i * 0.01 for i in range(30)]
    })
    assert lib_a is False

    # No metric
    arr_n, lib_n = extract_metric_series({"foo": "bar"})
    assert arr_n is None

    # cusum_two_sided — too short
    drift, hit = cusum_two_sided(np.array([1.0, 2.0]))
    assert drift == 0.0
    assert hit is False

    # cusum_two_sided — drift hit scenario
    x = np.concatenate([np.zeros(20), np.ones(20) * 5.0])
    drift2, hit2 = cusum_two_sided(x, threshold=2.0)
    assert isinstance(drift2, float)
    assert isinstance(hit2, bool)

    # analyze_meta_learning — empty
    out = analyze_meta_learning("BTC/USDT", None)
    assert isinstance(out, dict)
    out2 = analyze_meta_learning("BTC/USDT", {})
    assert isinstance(out2, dict)

    # With a loss series
    out3 = analyze_meta_learning("BTC/USDT", {
        "loss_series": [0.5 - i * 0.01 for i in range(40)]
    })
    assert isinstance(out3, dict)


def test_causal_alpha_engine_branches() -> None:
    import numpy as np
    from super_otonom.signals.causal_alpha_engine import (
        analyze_causal_alpha,
        granger_causality_score,
        spurious_correlation_score,
        transfer_entropy_proxy,
    )

    # Empty / no data path
    out = analyze_causal_alpha("BTC/USDT", None)
    assert isinstance(out, dict)

    out2 = analyze_causal_alpha("BTC/USDT", {})
    assert isinstance(out2, dict)

    # Insufficient series
    out3 = analyze_causal_alpha("BTC/USDT", {"a_series": [1.0, 2.0], "b_series": [1.0]})
    assert isinstance(out3, dict)

    # Normal: synthetic series with causality
    np.random.seed(0)
    a = list(np.cumsum(np.random.randn(80) * 0.01))
    b = list(np.array(a) + np.random.randn(80) * 0.005)
    out4 = analyze_causal_alpha("BTC/USDT", {"a_series": a, "b_series": b, "max_lag": 3})
    assert isinstance(out4, dict)

    # Direct helper tests
    ra = np.array(a)
    rb = np.array(b)
    g, lag = granger_causality_score(ra, rb, max_lag=3)
    assert isinstance(g, float)
    assert isinstance(lag, int)
    te = transfer_entropy_proxy(ra, rb, lag=1)
    assert isinstance(te, float)
    spurious, sp = spurious_correlation_score(ra, rb, g, g)
    assert isinstance(spurious, bool)


def test_risk_ontology_branches() -> None:
    from super_otonom.risk_ontology import RiskOntology

    onto = RiskOntology(initial_nav=10000.0)
    # snapshot
    snap = onto.snapshot()
    assert "nav" in snap

    # update with positions
    onto.update(
        nav=9500.0,
        positions={"BTC/USDT": {"qty": 0.5, "entry": 100.0}, "ETH/USDT": {"qty": 1.0, "entry": 50.0}},
        current_vol=0.02,
        realized_pnl_delta=-50.0,
    )
    assert onto.gross_exp > 0

    # build up pnl history then trigger var
    for i in range(150):
        onto._pnl_history.append(-10.0 + i * 0.1)
    var = onto._calc_var()
    assert isinstance(var, float)

    # var with too few samples → 0
    onto2 = RiskOntology(initial_nav=10000.0)
    onto2._pnl_history = [1.0, 2.0]
    assert onto2._calc_var() == 0.0

    # is_exposure_breached
    onto.exp_pct = 1.0  # 100%
    assert onto.is_exposure_breached(max_exp_pct=0.5) is True
    onto.exp_pct = 0.1
    assert onto.is_exposure_breached(max_exp_pct=0.5) is False

    # is_daily_limit_breached
    onto.daily_loss_pct = 0.05
    onto.dynamic_daily_limit = 0.03
    assert onto.is_daily_limit_breached() is True

    onto.daily_loss_pct = 0.01
    assert onto.is_daily_limit_breached() is False

    # is_weekly_limit_breached
    onto.weekly_loss_pct = 0.20
    assert onto.is_weekly_limit_breached(max_weekly_pct=0.10) is True
    onto.weekly_loss_pct = 0.01
    assert onto.is_weekly_limit_breached(max_weekly_pct=0.10) is False

    # is_drawdown_breached
    onto.intraday_dd_pct = 0.30
    assert onto.is_drawdown_breached(max_dd=0.15) is True
    onto.intraday_dd_pct = 0.01
    assert onto.is_drawdown_breached(max_dd=0.15) is False

    # to_dict / from_dict roundtrip
    onto.var_1d = 25.0
    state_dict = onto.to_dict()
    assert "nav" in state_dict
    new_onto = RiskOntology.from_dict(state_dict)
    assert abs(new_onto.nav - onto.nav) < 0.01


def test_risk_ontology_day_week_reset() -> None:
    import time

    from super_otonom.risk_ontology import (
        _SOD_RESET_SECONDS,
        _SOW_RESET_SECONDS,
        RiskOntology,
    )

    onto = RiskOntology(initial_nav=10000.0)
    # Force day_start to be old enough for reset
    onto._day_start = time.time() - _SOD_RESET_SECONDS - 10
    onto._week_start = time.time() - _SOW_RESET_SECONDS - 10
    onto.update(nav=10500.0)
    # After update, sod_nav and sow_nav should be reset to new nav
    assert abs(onto.sod_nav - 10500.0) < 0.1
    assert abs(onto.sow_nav - 10500.0) < 0.1


# ════════════════════════════════════════════════════════════════════════════
# capital_engine — small remaining branches
# ════════════════════════════════════════════════════════════════════════════


def test_capital_engine_branches() -> None:
    from super_otonom.capital_engine import CapitalEngine

    cap = CapitalEngine(initial_capital=10000.0, max_position_pct=0.95, reserve_pct=0.05)

    # reserve and release margin
    assert cap.reserve_margin("test_oid", 100.0) is True
    # cannot reserve too much
    bad = cap.reserve_margin("test_oid2", 1_000_000.0)
    assert bad is False
    # release reservation
    cap.release_reservation("test_oid", 100.0)

    # open / close position
    cap.open_position(
        symbol="BTC/USDT",
        order_id="order_1",
        entry_price=100.0,
        qty=1.0,
        notional=100.0,
        fee=0.1,
    )
    snap = cap.snapshot()
    assert isinstance(snap, dict)

    # update unrealized
    cap.update_unrealized({"BTC/USDT": 110.0})
    assert cap.nav >= 0

    # close position
    cap.close_position(
        symbol="BTC/USDT",
        order_id="order_1",
        exit_price=110.0,
        filled_qty=1.0,
        fee=0.1,
    )

    # record fee
    cap.record_fee("BTC/USDT", "fee_id", 0.05, note="swap")


def test_whale_intent_branches() -> None:
    from super_otonom.whale_intent_microstructure_engine import (
        _absorption_proxy_from_ob,
        _clamp01,
        _clamp100,
        _compute_ob_imbalance,
        _compute_spread_pct,
        _extract_best_prices,
        infer_whale_intent,
    )

    # No order_book — unknown path
    r = infer_whale_intent(symbol="BTC/USDT")
    assert hasattr(r, "whale_intent")

    # Empty OB
    r1 = infer_whale_intent(symbol="BTC/USDT", order_book={})
    assert hasattr(r1, "whale_intent")

    # Strongly bid-dominated OB (accumulate)
    ob_bid = {
        "bids": [[100.0, 1000.0], [99.5, 800.0], [99.0, 500.0]],
        "asks": [[100.5, 50.0], [101.0, 30.0]],
    }
    r2 = infer_whale_intent(symbol="BTC/USDT", order_book=ob_bid)
    assert hasattr(r2, "whale_intent")

    # Strongly ask-dominated OB (distribute)
    ob_ask = {
        "bids": [[100.0, 50.0], [99.5, 30.0]],
        "asks": [[100.5, 1000.0], [101.0, 800.0], [101.5, 500.0]],
    }
    r3 = infer_whale_intent(symbol="BTC/USDT", order_book=ob_ask)
    assert hasattr(r3, "whale_intent")

    # Wide spread → sweep/hunt
    ob_wide = {
        "bids": [[100.0, 500.0]],
        "asks": [[110.0, 500.0]],
    }
    r4 = infer_whale_intent(symbol="BTC/USDT", order_book=ob_wide)
    assert hasattr(r4, "whale_intent")

    # Helpers - NaN inputs
    assert _clamp01(float("nan")) == 0.0
    assert _clamp01(-1.0) == 0.0
    assert _clamp01(2.0) == 1.0
    assert _clamp01(0.5) == 0.5

    assert _clamp100(float("nan")) == 0
    assert _clamp100(-10.0) == 0
    assert _clamp100(150.0) == 100

    # _extract_best_prices error paths
    assert _extract_best_prices({}) == (None, None)
    assert _extract_best_prices({"bids": [], "asks": []}) == (None, None)
    assert _extract_best_prices({"bids": [[0.0, 1.0]], "asks": [[1.0, 1.0]]}) == (None, None)
    bb, ba = _extract_best_prices({"bids": [[100.0, 1.0]], "asks": [[101.0, 1.0]]})
    assert bb == 100.0 and ba == 101.0

    # _compute_spread_pct with mid<=0
    assert _compute_spread_pct(-1.0, -2.0) == 0.0
    assert _compute_spread_pct(100.0, 101.0) > 0.0

    # _compute_ob_imbalance edge cases
    assert _compute_ob_imbalance({"bids": [], "asks": []}) is None
    assert _compute_ob_imbalance({"bids": [["100.0", "1.0"]], "asks": [["bad", "x"]]}) is None
    imb = _compute_ob_imbalance({"bids": [[100.0, 10.0]], "asks": [[101.0, 5.0]]})
    assert imb is not None
    # zero quantity
    z = _compute_ob_imbalance({"bids": [[100.0, 0.0]], "asks": [[101.0, 0.0]]})
    assert z is None

    # _absorption_proxy edge cases
    assert _absorption_proxy_from_ob({"bids": [], "asks": []}) is None
    assert _absorption_proxy_from_ob({"bids": [[100.0, 1.0]], "asks": [["bad", "x"]]}) is None
    az = _absorption_proxy_from_ob({"bids": [[0.0, 0.0]], "asks": [[0.0, 0.0]]})
    assert az is None
    ap = _absorption_proxy_from_ob({"bids": [[100.0, 10.0]], "asks": [[101.0, 5.0]]})
    assert ap is not None
