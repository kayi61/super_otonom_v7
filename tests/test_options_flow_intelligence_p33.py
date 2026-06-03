"""PROMPT-3.3 — Options Flow Intelligence + alternative_data_engine (Faz 27)."""

from __future__ import annotations

import json

import pytest
from super_otonom.signals.alternative_data_engine import analyze_alternative_data
from super_otonom.signals.options_flow_intelligence import (
    DIR_BEARISH,
    DIR_BULLISH,
    SENT_FEAR,
    SENT_GREED,
    SENT_NEUTRAL,
    TERM_BACKWARDATION,
    TERM_CONTANGO,
    OptionsFlowCollector,
    OptionTrade,
    analyze_iv,
    analyze_max_pain,
    analyze_options_flow,
    analyze_pcr,
    classify_pcr,
    compute_max_pain,
    detect_whale_options,
    parse_deribit_summary,
)

# ── PCR ──────────────────────────────────────────────────────────────────────


def test_classify_pcr() -> None:
    assert classify_pcr(1.5) == SENT_FEAR
    assert classify_pcr(0.4) == SENT_GREED
    assert classify_pcr(0.9) == SENT_NEUTRAL


def test_analyze_pcr_fear_contrarian_bullish() -> None:
    p = analyze_pcr(pcr=1.5)
    assert p.sentiment == SENT_FEAR
    assert p.contrarian_bias > 0  # korku → kontraryan bullish


def test_analyze_pcr_greed_contrarian_bearish() -> None:
    p = analyze_pcr(pcr=0.4)
    assert p.sentiment == SENT_GREED
    assert p.contrarian_bias < 0


def test_analyze_pcr_from_volumes() -> None:
    p = analyze_pcr(put_volume=150, call_volume=100)
    assert p.pcr == pytest.approx(1.5)


def test_analyze_pcr_trend() -> None:
    assert analyze_pcr(pcr=1.5, pcr_history=[1.0, 1.2, 1.5]).trend == "rising"
    assert analyze_pcr(pcr=0.8, pcr_history=[1.5, 1.0, 0.8]).trend == "falling"
    assert analyze_pcr(pcr=1.0, pcr_history=[1.0, 1.0]).trend == "flat"


def test_analyze_pcr_zero_call() -> None:
    p = analyze_pcr(put_volume=100, call_volume=0)
    assert p.pcr == 1.0  # division guard


# ── Whale options ────────────────────────────────────────────────────────────


def test_whale_bullish_call_buy() -> None:
    w = detect_whale_options([{"option_type": "call", "side": "buy", "notional_usd": 2e6}])
    assert w.whale_trade_count == 1
    assert w.net_direction == DIR_BULLISH


def test_whale_bearish_put_buy() -> None:
    w = detect_whale_options([{"option_type": "put", "side": "buy", "notional_usd": 3e6}])
    assert w.net_direction == DIR_BEARISH


def test_whale_below_threshold_ignored() -> None:
    w = detect_whale_options([{"option_type": "call", "side": "buy", "notional_usd": 500_000}])
    assert w.whale_trade_count == 0


def test_whale_unusual_activity() -> None:
    w = detect_whale_options([], current_volume=300, avg_volume=80)
    assert w.unusual_activity is True
    assert w.volume_ratio == pytest.approx(3.75)


def test_whale_dataclass_input() -> None:
    w = detect_whale_options([OptionTrade("call", "buy", 2e6)])
    assert w.whale_trade_count == 1


# ── Max pain ─────────────────────────────────────────────────────────────────


def test_compute_max_pain() -> None:
    chain = [
        {"strike": 48000, "call_oi": 100, "put_oi": 500},
        {"strike": 50000, "call_oi": 300, "put_oi": 300},
        {"strike": 52000, "call_oi": 500, "put_oi": 100},
    ]
    assert compute_max_pain(chain) == 50000.0


def test_compute_max_pain_empty() -> None:
    assert compute_max_pain([]) is None
    assert compute_max_pain([{"bad": 1}]) is None


def test_analyze_max_pain_distance_and_pull() -> None:
    chain = [{"strike": 50000, "call_oi": 300, "put_oi": 300}]
    mp = analyze_max_pain(chain, spot=49000, hours_to_expiry=12)
    assert mp.max_pain_price == 50000.0
    assert mp.distance_pct == pytest.approx((50000 - 49000) / 49000)
    assert mp.pull_strength > 0.9   # 12h → expiry yakın
    assert mp.gamma_squeeze_risk > 0  # < 24h


def test_analyze_max_pain_far_expiry_no_gamma() -> None:
    chain = [{"strike": 50000, "call_oi": 100, "put_oi": 100}]
    mp = analyze_max_pain(chain, spot=50000, hours_to_expiry=200)
    assert mp.gamma_squeeze_risk == 0.0
    assert mp.pull_strength == 0.0


# ── IV ───────────────────────────────────────────────────────────────────────


def test_iv_skew() -> None:
    iv = analyze_iv(put_iv=80, call_iv=60)
    assert iv.iv_skew == pytest.approx(20.0)


def test_iv_term_structure() -> None:
    assert analyze_iv(short_iv=85, long_iv=70).term_structure == TERM_BACKWARDATION
    assert analyze_iv(short_iv=60, long_iv=75).term_structure == TERM_CONTANGO


def test_iv_vol_risk_premium() -> None:
    iv = analyze_iv(short_iv=80, realized_vol=55)
    assert iv.vol_risk_premium == pytest.approx(25.0)


def test_iv_crush_near_expiry_high_iv() -> None:
    iv = analyze_iv(short_iv=120, realized_vol=60, hours_to_expiry=6)
    assert iv.iv_crush_risk > 0.5


def test_iv_no_crush_far() -> None:
    iv = analyze_iv(short_iv=120, hours_to_expiry=200)
    assert iv.iv_crush_risk == 0.0


# ── Deribit parse ────────────────────────────────────────────────────────────


def test_parse_deribit_summary() -> None:
    payload = {
        "result": [
            {"instrument_name": "BTC-27DEC24-50000-C", "volume": 100, "open_interest": 500,
             "mark_iv": 65, "underlying_price": 49000},
            {"instrument_name": "BTC-27DEC24-48000-P", "volume": 200, "open_interest": 300, "mark_iv": 70},
        ]
    }
    c = parse_deribit_summary(payload)
    assert len(c) == 2
    assert c[0].strike == 50000 and c[0].option_type == "call"
    assert c[1].option_type == "put"


def test_parse_deribit_invalid() -> None:
    assert parse_deribit_summary("x") == []
    assert parse_deribit_summary({"result": "bad"}) == []
    assert parse_deribit_summary({"result": [{"instrument_name": "BAD"}]}) == []


def test_parse_deribit_string() -> None:
    payload = json.dumps({"result": [{"instrument_name": "ETH-1JAN25-3000-C", "volume": 5}]})
    assert len(parse_deribit_summary(payload)) == 1


# ── Collector ────────────────────────────────────────────────────────────────


def test_collector_fetch_and_pcr() -> None:
    payload = {
        "result": [
            {"instrument_name": "BTC-27DEC24-50000-C", "volume": 100},
            {"instrument_name": "BTC-27DEC24-48000-P", "volume": 150},
        ]
    }
    col = OptionsFlowCollector(http_get=lambda u, t: json.dumps(payload))
    contracts = col.fetch_contracts("BTC")
    assert len(contracts) == 2
    pcr = OptionsFlowCollector.aggregate_pcr(contracts)
    assert pcr.pcr == pytest.approx(1.5)  # 150 put / 100 call


def test_collector_fetch_none_graceful() -> None:
    col = OptionsFlowCollector(http_get=lambda u, t: None)
    assert col.fetch_contracts() == []


# ── Combined ─────────────────────────────────────────────────────────────────


def test_analyze_options_flow_combined() -> None:
    sig = analyze_options_flow(
        pcr=analyze_pcr(pcr=1.5),
        whale=detect_whale_options(
            [{"option_type": "call", "side": "buy", "notional_usd": 2e6}],
            current_volume=300, avg_volume=80,
        ),
        max_pain=analyze_max_pain([{"strike": 50000, "call_oi": 1, "put_oi": 1}], spot=49000, hours_to_expiry=12),
        iv=analyze_iv(short_iv=85, long_iv=70),
    )
    assert sig.alpha_bias > 0  # fear contrarian + whale bullish
    assert sig.risk_score > 0
    assert len(sig.reasons) >= 2
    d = sig.to_dict()
    assert d["pcr_sentiment"] == SENT_FEAR
    assert d["whale_direction"] == DIR_BULLISH


def test_analyze_options_flow_empty() -> None:
    sig = analyze_options_flow()
    assert sig.alpha_bias == 0.0 and sig.risk_score == 0.0


# ── alternative_data_engine (Faz 27) entegrasyonu ────────────────────────────


def test_faz27_options_flow_deep_fields() -> None:
    data = {"options_flow": {
        "put_volume": 150, "call_volume": 100, "pcr_history": [1.0, 1.3, 1.5],
        "whale_trades": [{"option_type": "call", "side": "buy", "notional_usd": 2e6}],
        "current_volume": 300, "avg_volume": 80,
        "option_chain": [{"strike": 50000, "call_oi": 300, "put_oi": 300}],
        "spot": 49000, "hours_to_expiry": 12,
        "put_iv": 80, "call_iv": 60, "short_iv": 85, "long_iv": 70, "realized_vol": 55,
    }}
    out = analyze_alternative_data("BTCUSDT", data, {"signal": "BUY"})
    ofd = out["alternative_data"]["options_flow_deep"]
    assert ofd["pcr_sentiment"] == SENT_FEAR
    assert ofd["whale_direction"] == DIR_BULLISH
    assert ofd["max_pain_price"] == 50000.0
    assert ofd["iv_term_structure"] == TERM_BACKWARDATION


def test_faz27_backward_compat() -> None:
    out = analyze_alternative_data("BTCUSDT", {"adoption": {"active_addresses": 1000}}, {"signal": "BUY"})
    assert "options_flow_deep" not in out["alternative_data"]


def test_faz27_legacy_options_still_works() -> None:
    # Eski tek put_call_ratio alanı → deep analiz PCR'yi yakalar
    out = analyze_alternative_data("BTCUSDT", {"put_call_ratio": 1.5}, {"signal": "BUY"})
    assert "options_flow_deep" in out["alternative_data"]
    assert out["alternative_data"]["options_flow_deep"]["pcr_sentiment"] == SENT_FEAR


def test_faz27_graceful_bad_chain() -> None:
    data = {"options_flow": {"put_call_ratio": 1.0, "option_chain": "bad"}}
    out = analyze_alternative_data("BTCUSDT", data, {"signal": "BUY"})
    assert out["trade_permission"] in ("ALLOW", "BLOCK", "HALT")
