"""Faz 17 — smart_money_tracker modülü."""

from __future__ import annotations

from typing import Any

from super_otonom.smart_money_tracker import analyze_smart_money, run_smart_money_phase


def _strip_event_ts_keys(obj: Any) -> Any:
    """Dict/list/tuple içinde tüm seviyelerde `event_ts` anahtarını çıkar (flake önleme)."""
    if isinstance(obj, dict):
        return {k: _strip_event_ts_keys(v) for k, v in obj.items() if k != "event_ts"}
    if isinstance(obj, list):
        return [_strip_event_ts_keys(x) for x in obj]
    if isinstance(obj, tuple):
        return tuple(_strip_event_ts_keys(x) for x in obj)
    return obj


def _assert_dicts_equal_ignore_event_ts(a: dict, b: dict) -> None:
    assert _strip_event_ts_keys(a) == _strip_event_ts_keys(b)


def test_smart_money_empty_blocks_quality() -> None:
    """Boş veri → BLOCK, data_health 0, QUALITY."""
    a: dict = {}
    r = analyze_smart_money("BTC/USDT", {}, a, attach_to_analysis=True)

    assert r["trade_permission"] == "BLOCK"
    assert r["data_health"] == 0.0
    assert r["score_type"] == "QUALITY"
    assert r.get("empty_reason") == "no_smart_money_data"


def test_smart_money_accumulation_high_alpha_allow() -> None:
    """Birikim (cold_storage + negatif borsa netflow) → yüksek alpha, ALLOW."""
    a = {"signal": "BUY"}
    d = {
        "whale_transfers": [
            {"amount_usd": 8e6, "direction": "cold_storage"},
            {"amount_usd": 7e6, "direction": "accumulation"},
            {"amount_usd": 6e6, "direction": "from_exchange"},
        ],
        "exchange_netflow_usd": -12e6,
        "etf_net_flow_usd": 15e6,
    }
    r = analyze_smart_money("ETH/USDT", d, a, attach_to_analysis=False)

    assert r["trade_permission"] == "ALLOW"
    assert r["alpha_score"] >= 0.55


def test_smart_money_exchange_dump_pressure_blocks() -> None:
    """Çoğunluk borsaya aktarım → risk yükselir, BLOCK."""
    rows = [{"amount_usd": 10e6, "direction": "to_exchange"} for _ in range(10)]
    d = {"whale_transfers": rows}
    r = analyze_smart_money("DUMP/USDT", d, {}, attach_to_analysis=False)

    assert r["risk_score"] >= 0.72
    assert r["trade_permission"] == "BLOCK"


def test_smart_money_extreme_dump_halts() -> None:
    """dump_pressure >= 0.92 ve risk >= 0.88 → HALT."""
    rows = [{"amount_usd": 500e6, "direction": "to_exchange"}]
    rows += [{"amount_usd": 5e6, "direction": "to_exchange"} for _ in range(25)]
    d = {"whale_transfers": rows}
    r = analyze_smart_money("HALT/USDT", d, {}, attach_to_analysis=False)

    assert r["smart_money"]["dump_to_exchange_pressure"] >= 0.92
    assert r["risk_score"] >= 0.88
    assert r["trade_permission"] == "HALT"


def test_smart_money_etf_vc_positive_institutional_score() -> None:
    """ETF + VC pozitif akış → institutional_vc_score > 0.5."""
    d = {
        "etf_net_flow_usd": 25e6,
        "vc_net_flow_usd": 18e6,
        "whale_transfers": [{"amount_usd": 1e6, "direction": "neutral"}],
    }
    r = analyze_smart_money("VC/USDT", d, {}, attach_to_analysis=False)

    assert r["smart_money"]["institutional_vc_score"] > 0.5


def test_smart_money_negative_exchange_netflow_bias_accumulation() -> None:
    """exchange_netflow_usd negatif → birikim proxy (bias > 0.5)."""
    d = {
        "exchange_netflow_usd": -20e6,
        "whale_transfers": [{"amount_usd": 2e6, "direction": "cold_storage"}],
    }
    r = analyze_smart_money("ACC/USDT", d, {}, attach_to_analysis=False)

    assert r["smart_money"]["exchange_netflow_usd"] == -20e6
    assert r["smart_money"]["exchange_flow_bias_01"] > 0.5


def test_smart_money_phase17_faz17_aliases() -> None:
    """phase17 / faz17 aynı nesne."""
    a: dict = {}
    d = {"etf_net_flow_usd": 5e6, "whale_transfers": [{"amount_usd": 3e6, "direction": "inflow"}]}
    analyze_smart_money("Z/USDT", d, a, attach_to_analysis=True)

    assert "phase17" in a
    assert "faz17" in a
    assert a["phase17"] is a["faz17"]
    assert a["phase17"]["phase"] == "17"
    assert a["phase17"]["source"] == "smart_money_tracker"


def test_run_smart_money_phase_matches_analyze() -> None:
    """run_smart_money_phase ile analyze_smart_money aynı çıktı."""
    a1: dict = {}
    a2: dict = {}
    d = {
        "institutional_flow_usd": 12e6,
        "whale_transfers": [{"amount_usd": 4e6, "direction": "accumulation"}],
    }
    r1 = run_smart_money_phase("Q/USDT", d, a1, attach_to_analysis=True)
    r2 = analyze_smart_money("Q/USDT", d, a2, attach_to_analysis=True)

    _assert_dicts_equal_ignore_event_ts(r1, r2)
    _assert_dicts_equal_ignore_event_ts(a1["phase17"], a2["phase17"])
