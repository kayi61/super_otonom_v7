"""Sharpe annualize — kripto 7/24 TF uyumu (audit madde 1)."""

from __future__ import annotations

import io
import json
import math
from contextlib import redirect_stdout

import numpy as np
import pytest
from super_otonom.backtester import _compute_sharpe, build_backtest_report, run_backtest
from super_otonom.bot_engine import BotEngine
from super_otonom.data_freshness import (
    LEGACY_PERIODS_PER_YEAR_STOCK_5M,
    infer_timeframe_from_candles,
    periods_per_year_from_timeframe,
    resolve_periods_per_year,
    sharpe_annualize_factor_vs_legacy,
)
from super_otonom.edge_evidence import main as edge_main

pytestmark = pytest.mark.fastrun


def _synthetic_5m_candles(n: int = 80) -> list[dict]:
    out: list[dict] = []
    ts = 1_700_000_000_000.0
    p = 100.0
    for i in range(n):
        c = p * (1.0 + 0.0005 * (1 if i % 4 else -1))
        out.append(
            {
                "timestamp": ts + i * 300_000,
                "open": p,
                "high": max(p, c) * 1.001,
                "low": min(p, c) * 0.999,
                "close": c,
                "volume": 1000.0,
            }
        )
        p = c
    return out


def test_legacy_constant_is_72576() -> None:
    assert LEGACY_PERIODS_PER_YEAR_STOCK_5M == 72_576.0


def test_periods_per_year_5m_matches_crypto_24_7() -> None:
    assert periods_per_year_from_timeframe("5m") == pytest.approx(105_192.0, rel=1e-4)


def test_sharpe_scales_with_sqrt_periods_ratio() -> None:
    rng = np.random.default_rng(7)
    ret = rng.normal(0.0002, 0.01, 120)
    ppy_old = LEGACY_PERIODS_PER_YEAR_STOCK_5M
    ppy_new = periods_per_year_from_timeframe("5m")
    s_old = _compute_sharpe(ret, ppy_old)
    s_new = _compute_sharpe(ret, ppy_new)
    expected = math.sqrt(ppy_new / ppy_old)
    assert s_new / s_old == pytest.approx(expected, rel=1e-6)


def test_sharpe_factor_vs_legacy_5m_about_1_2() -> None:
    f = sharpe_annualize_factor_vs_legacy("5m")
    assert 1.19 < f < 1.22


def test_infer_timeframe_from_5m_candles() -> None:
    assert infer_timeframe_from_candles(_synthetic_5m_candles(20)) == "5m"


def test_resolve_periods_from_candles_without_explicit_tf(monkeypatch) -> None:
    monkeypatch.delenv("EXCHANGE_TIMEFRAME", raising=False)
    monkeypatch.setenv("TIMEFRAME", "1h")
    ppy = resolve_periods_per_year(candles=_synthetic_5m_candles(30))
    assert ppy == pytest.approx(periods_per_year_from_timeframe("5m"))


def test_build_backtest_report_wrong_tf_inflates_sharpe_vs_inferred() -> None:
    rng = np.random.default_rng(99)
    eq = list(10_000.0 + np.cumsum(rng.normal(0, 40, 100)))
    eng = BotEngine(10_000.0, paper=True)
    r_wrong = build_backtest_report(
        eng,
        eq,
        10_000.0,
        bars_simulated=len(eq),
        timeframe="1h",
    )
    r_right = build_backtest_report(
        eng,
        eq,
        10_000.0,
        bars_simulated=len(eq),
        timeframe="5m",
    )
    ratio = r_right.sharpe_ratio / r_wrong.sharpe_ratio
    expected = math.sqrt(
        periods_per_year_from_timeframe("5m") / periods_per_year_from_timeframe("1h")
    )
    assert ratio == pytest.approx(expected, rel=1e-5)


def test_run_backtest_infers_5m_from_candle_spacing(tmp_path, monkeypatch) -> None:
    import super_otonom.bot_engine as bemod

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bemod, "_STATE_FILE", str(tmp_path / "st.json"))
    monkeypatch.setattr(bemod, "_TRADE_LOG_FILE", str(tmp_path / "tr.log"))
    monkeypatch.setenv("TIMEFRAME", "1h")
    candles = _synthetic_5m_candles(50)
    r_env = run_backtest(candles, min_bars=35)
    r_inf = run_backtest(candles, min_bars=35, timeframe="5m")
    assert r_env.sharpe_ratio == pytest.approx(r_inf.sharpe_ratio, rel=1e-9)


def test_edge_evidence_json_includes_timeframe_and_ppy() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = edge_main(
            [
                "--source",
                "synthetic",
                "--timeframe",
                "5m",
                "--limit",
                "200",
                "--no-wfa",
                "--json",
            ]
        )
    assert code == 0
    payload = json.loads(buf.getvalue())
    assert payload["timeframe"] == "5m"
    assert payload["periods_per_year"] == pytest.approx(105_192.0, rel=1e-3)
    assert payload["legacy_periods_per_year_wrong"] == 72_576.0
    assert payload["full_sample"]["sharpe_ratio"] is not None
