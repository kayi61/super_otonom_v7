"""Faz 23 — news_event_intelligence modülü (Faz 16/17 test üslubu)."""

from __future__ import annotations

import time
from unittest.mock import patch

from super_otonom.signals.news_event_intelligence import analyze_news_event, run_news_event_phase


def test_news_empty_blocks_quality() -> None:
    """Boş veri → BLOCK, data_health 0, QUALITY."""
    a: dict = {}
    r = analyze_news_event("BTC/USDT", {}, a, attach_to_analysis=True)

    assert r["trade_permission"] == "BLOCK"
    assert r["data_health"] == 0.0
    assert r["score_type"] == "QUALITY"
    assert r.get("empty_reason") == "no_news_data"


def test_news_hack_exploit_halts() -> None:
    """Hack/exploit haberi → HALT."""
    d = {
        "headline": "Bridge exploit drains $40m from protocol vault",
        "published_at_ms": int(time.time() * 1000),
    }
    r = analyze_news_event("HACK/USDT", d, {}, attach_to_analysis=False)

    assert r["trade_permission"] == "HALT"
    assert r["news"]["hack_or_exploit_flag"] is True


def test_news_token_unlock_hours_blocks() -> None:
    """hours_until_unlock=24 → BLOCK."""
    d = {
        "headline": "Weekly market commentary",
        "hours_until_unlock": 24.0,
        "published_at_ms": int(time.time() * 1000),
    }
    r = analyze_news_event("UNLK/USDT", d, {}, attach_to_analysis=False)

    assert r["trade_permission"] == "BLOCK"


def test_news_exchange_listing_high_alpha_allow() -> None:
    """Exchange listing → yüksek alpha, ALLOW."""
    d = {
        "headline": "Major exchange announces spot listing for PROJECT token",
        "is_exchange_listing": True,
        "published_at_ms": int(time.time() * 1000),
    }
    r = analyze_news_event("LIST/USDT", d, {}, attach_to_analysis=False)

    assert r["trade_permission"] == "ALLOW"
    assert r["alpha_score"] >= 0.65
    assert r["news"]["exchange_listing_detected"] is True


def test_news_fed_cpi_raises_macro_and_risk() -> None:
    """Fed/CPI makro haberi → macro_event_risk ve risk_score artar."""
    base = {
        "headline": "Crypto markets trade sideways on quiet Thursday",
        "published_at_ms": int(time.time() * 1000),
    }
    macro = {
        "headline": "Fed Chair comments on CPI path after inflation surprise",
        "categories": ["fed", "cpi"],
        "published_at_ms": int(time.time() * 1000),
    }
    r0 = analyze_news_event("N/USDT", base, {}, attach_to_analysis=False)
    r1 = analyze_news_event("M/USDT", macro, {}, attach_to_analysis=False)

    assert r1["news"]["macro_event_risk"] > r0["news"]["macro_event_risk"]
    assert r1["risk_score"] > r0["risk_score"]


def test_news_stale_lowers_confidence_vs_fresh() -> None:
    """Eski haber → confidence düşük (aynı NLP girişi ile karşılaştırma)."""
    now_ms = int(time.time() * 1000)
    fresh_ms = now_ms - 3_600_000
    stale_ms = now_ms - int(30 * 24 * 3_600_000)

    common = {
        "headline": "Partnership announcement expected next quarter",
        "nlp_sentiment": 0.35,
    }
    rf = analyze_news_event(
        "F/USDT",
        {**common, "published_at_ms": fresh_ms},
        {},
        attach_to_analysis=False,
    )
    rs = analyze_news_event(
        "S/USDT",
        {**common, "published_at_ms": stale_ms},
        {},
        attach_to_analysis=False,
    )

    assert rf["confidence"] > rs["confidence"]
    assert rf["news"]["freshness_confidence_factor"] > rs["news"]["freshness_confidence_factor"]


def test_news_phase23_faz23_aliases() -> None:
    """phase23 / faz23 aynı payload."""
    a: dict = {}
    d = {
        "headline": "Minor upgrade deployed",
        "published_at_ms": int(time.time() * 1000),
    }
    analyze_news_event("Z/USDT", d, a, attach_to_analysis=True)

    assert "phase23" in a
    assert "faz23" in a
    assert a["phase23"] is a["faz23"]
    assert a["phase23"]["phase"] == "23"
    assert a["phase23"]["source"] == "news_event_intelligence"


def test_run_news_event_phase_matches_analyze() -> None:
    """run_news_event_phase ile analyze_news_event uyumlu."""
    a1: dict = {}
    a2: dict = {}
    fixed_pub_ms = 1_700_000_000_000
    fixed_now_ms = 1_730_000_000_000
    d = {
        "headline": "Protocol completes audit milestone",
        "published_at_ms": fixed_pub_ms,
    }
    # _news_age_hours ve unlock süreleri _now_ms() ile hesaplanır; iki ayrı çağrıda duvar saati
    # kayarsa phase23 tam eşit olmayabilir — test için süreyi dondur.
    with patch(
        "super_otonom.signals.news_event_intelligence._now_ms",
        return_value=fixed_now_ms,
    ):
        r1 = run_news_event_phase("Q/USDT", d, a1, attach_to_analysis=True, event_ts=fixed_pub_ms)
        r2 = analyze_news_event("Q/USDT", d, a2, attach_to_analysis=True, event_ts=fixed_pub_ms)

    assert r1["trade_permission"] == r2["trade_permission"]
    assert r1["alpha_score"] == r2["alpha_score"]
    assert r1["risk_score"] == r2["risk_score"]
    assert a1["phase23"] == a2["phase23"]
