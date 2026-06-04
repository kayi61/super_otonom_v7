"""PROMPT-5.2 — Exchange Listing & Delisting Detector + Faz 23 entegrasyonu."""

from __future__ import annotations

from super_otonom.signals.listing_intelligence import (
    CLOSE,
    OPEN_SMALL,
    SCALE_UP,
    TAKE_PROFIT,
    ListingCollector,
    analyze_listing,
    analyze_listing_data,
    classify_exchange_tier,
    delisting_risk,
    detect_new_symbols,
    listing_impact,
    listing_probability,
    parse_announcement,
)
from super_otonom.signals.news_event_intelligence import analyze_news_event

# ── Tier sınıflandırma ───────────────────────────────────────────────────────


def test_classify_exchange_tier() -> None:
    assert classify_exchange_tier("Binance") == 1
    assert classify_exchange_tier("Coinbase Pro") == 1
    assert classify_exchange_tier("KuCoin") == 2
    assert classify_exchange_tier("okx") == 2
    assert classify_exchange_tier("RandomDex") == 3
    assert classify_exchange_tier(None) == 3


# ── 1) Listing olasılığı ─────────────────────────────────────────────────────


def test_listing_probability_signals() -> None:
    prob, reasons = listing_probability(announcement_detected=True, api_symbol_added=True)
    assert prob > 0.6
    assert len(reasons) >= 2


def test_listing_probability_tier2_implies_tier1() -> None:
    prob, reasons = listing_probability(tier2_listing_count=3)
    assert prob > 0
    assert any("Tier-1" in r for r in reasons)


def test_listing_probability_confirmed() -> None:
    prob, _ = listing_probability(confirmed_listing=True)
    assert prob >= 0.95


# ── 2) Delisting riski ───────────────────────────────────────────────────────


def test_delisting_risk_announced() -> None:
    risk, reasons = delisting_risk(delisting_announced=True)
    assert risk >= 0.9 and reasons


def test_delisting_risk_regulatory() -> None:
    risk, _ = delisting_risk(regulatory_action=True)
    assert risk >= 0.8


def test_delisting_risk_volume_drop() -> None:
    risk, _ = delisting_risk(volume_drop_pct=0.75)
    assert risk >= 0.7


def test_delisting_risk_dev_stall() -> None:
    risk, _ = delisting_risk(dev_inactive=True, volume_dry=True)
    assert risk >= 0.5


# ── 3) Listing impact ────────────────────────────────────────────────────────


def test_listing_impact_tier1() -> None:
    imp = listing_impact(1)
    assert imp.expected_move_pct >= 0.4
    assert imp.buy_rumor_window is True
    assert imp.dump_window_hours > 0


def test_listing_impact_history_override() -> None:
    imp = listing_impact(1, history=[{"post_move_pct": 0.2}, {"post_move_pct": 0.4}])
    assert abs(imp.expected_move_pct - 0.3) < 1e-9


def test_listing_impact_confirmed_closes_rumor() -> None:
    assert listing_impact(1, confirmed=True).buy_rumor_window is False


# ── 4) Birleşik analiz + aksiyon ─────────────────────────────────────────────


def test_analyze_high_prob_opens_small() -> None:
    sig = analyze_listing(announcement_detected=True, api_symbol_added=True, exchange="binance")
    assert sig is not None
    assert sig.action == OPEN_SMALL
    assert sig.alpha_bias > 0
    assert sig.buy_rumor_window is True
    assert sig.predicted_tier == 1


def test_analyze_confirmed_scales_up() -> None:
    sig = analyze_listing(confirmed_listing=True, exchange="binance")
    assert sig.action == SCALE_UP
    assert sig.position_size_hint >= 0.5


def test_analyze_confirmed_post_listing_takes_profit() -> None:
    sig = analyze_listing(confirmed_listing=True, exchange="binance", post_listing_hours=12)
    assert sig.action == TAKE_PROFIT
    assert sig.risk_score >= 0.5


def test_analyze_delisting_closes_and_halts() -> None:
    sig = analyze_listing(delisting_announced=True, exchange="binance")
    assert sig.action == CLOSE
    assert sig.trade_permission == "HALT"
    assert sig.alpha_bias < 0
    assert sig.urgent is True


def test_analyze_delisting_volume_blocks() -> None:
    sig = analyze_listing(volume_drop_pct=0.8)
    assert sig.action == CLOSE
    assert sig.trade_permission == "BLOCK"  # urgent değil (duyuru/regülasyon yok)


def test_analyze_no_signal_none() -> None:
    assert analyze_listing() is None


# ── Köprü (analyze_listing_data) ─────────────────────────────────────────────


def test_listing_data_block() -> None:
    sig = analyze_listing_data(
        {"listing": {"announcement_detected": True, "api_symbol_added": True, "exchange": "binance"}}
    )
    assert sig is not None and sig.action == OPEN_SMALL


def test_listing_data_delisting_block() -> None:
    sig = analyze_listing_data({"delisting": {"delisting_announced": True}})
    assert sig is not None and sig.action == CLOSE


def test_listing_data_flat_keys() -> None:
    sig = analyze_listing_data({"api_symbol_added": True, "tier2_listing_count": 3})
    assert sig is not None


def test_listing_data_bare_flag_no_activation() -> None:
    """Yalın is_exchange_listing → yeni modül tetiklenmez (eski Faz 23 korunur)."""
    assert analyze_listing_data({"is_exchange_listing": True}) is None


def test_listing_data_empty_none() -> None:
    assert analyze_listing_data({}) is None
    assert analyze_listing_data("nope") is None


# ── Parser'lar ───────────────────────────────────────────────────────────────


def test_parse_announcement() -> None:
    assert parse_announcement("Binance will list TOKEN (TKN)")["listing_announced"] is True
    assert parse_announcement("Notice of delisting of XYZ")["delisting_announced"] is True
    assert parse_announcement("random text")["listing_announced"] is False


def test_detect_new_symbols() -> None:
    new = detect_new_symbols(["BTCUSDT", "ETHUSDT", "NEWUSDT"], ["BTCUSDT", "ETHUSDT"])
    assert new == ["NEWUSDT"]
    assert detect_new_symbols(["BTCUSDT"], ["BTCUSDT"]) == []


# ── Collector ────────────────────────────────────────────────────────────────


def test_collector_announcement() -> None:
    col = ListingCollector(http_get=lambda u, t: "Coinbase will list ARB")
    out = col.fetch_announcement("https://example.com/blog")
    assert out["listing_announced"] is True


def test_collector_symbols() -> None:
    import json
    payload = json.dumps({"symbols": [{"symbol": "BTCUSDT"}, {"symbol": "ARBUSDT"}]})
    col = ListingCollector(http_get=lambda u, t: payload)
    syms = col.fetch_exchange_symbols()
    assert "ARBUSDT" in syms


def test_collector_none_graceful() -> None:
    col = ListingCollector(http_get=lambda u, t: None)
    assert col.fetch_exchange_symbols() == []
    assert col.fetch_announcement("x")["listing_announced"] is False


# ── Faz 23 (news_event_intelligence) entegrasyonu ────────────────────────────


def test_faz23_listing_block_attached() -> None:
    news = {
        "headline": "Potential Binance listing rumor for TKN",
        "listing": {"announcement_detected": True, "api_symbol_added": True, "exchange": "binance"},
    }
    r = analyze_news_event("TKN/USDT", news, {"signal": "BUY"}, attach_to_analysis=False)
    assert "listing_intelligence" in r["news"]
    assert r["news"]["listing_intelligence"]["action"] == OPEN_SMALL


def test_faz23_delisting_halts() -> None:
    news = {
        "headline": "Exchange announces delisting",
        "delisting": {"delisting_announced": True},
    }
    r = analyze_news_event("XYZ/USDT", news, {}, attach_to_analysis=False)
    assert r["trade_permission"] == "HALT"
    assert r["news"]["listing_intelligence"]["action"] == CLOSE


def test_faz23_listing_raises_alpha() -> None:
    base = {"headline": "Some neutral crypto news today"}
    listed = {
        "headline": "Some neutral crypto news today",
        "listing": {"announcement_detected": True, "exchange": "binance"},
    }
    r_base = analyze_news_event("TKN/USDT", base, {"signal": "BUY"}, attach_to_analysis=False)
    r_list = analyze_news_event("TKN/USDT", listed, {"signal": "BUY"}, attach_to_analysis=False)
    assert r_list["alpha_score"] >= r_base["alpha_score"]


def test_faz23_backward_compat_bare_listing_flag() -> None:
    """is_exchange_listing bayrağı tek başına → listing_intelligence bloğu eklenmez."""
    news = {"headline": "Exchange listing news", "is_exchange_listing": True}
    r = analyze_news_event("TKN/USDT", news, {"signal": "BUY"}, attach_to_analysis=False)
    assert "listing_intelligence" not in r["news"]
    assert r["news"]["exchange_listing_detected"] is True  # eski davranış korunur


def test_faz23_backward_compat_no_listing() -> None:
    news = {"headline": "Bitcoin price analysis for today"}
    r = analyze_news_event("BTC/USDT", news, {}, attach_to_analysis=False)
    assert "listing_intelligence" not in r["news"]
