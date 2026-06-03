"""PROMPT-4.1 — Twitter/X Crypto KOL Tracker + social_signal (Faz 16)."""

from __future__ import annotations

import json

import pytest
from super_otonom.signals.kol_tracker import (
    BEARISH,
    BULLISH,
    BUY,
    DIVERGENT,
    KOL_REGISTRY,
    NEUTRAL,
    SELL,
    KolCollector,
    analyze_kol,
    analyze_sentiment,
    analyze_tweet,
    backtest_kol_timing,
    compute_consensus,
    detect_action,
    detect_buy_rumor_sell_news,
    engagement_weight,
    get_kol,
    parse_cashtags,
    parse_nitter_rss,
    parse_twitter_api_v2,
    resolve_kol,
)
from super_otonom.signals.social_signal import analyze_social_signal

# ── 1) KOL listesi + ağırlıklandırma ─────────────────────────────────────────


def test_registry_has_three_tiers() -> None:
    tiers = {k.tier for k in KOL_REGISTRY.values()}
    assert tiers == {1, 2, 3}
    assert len(KOL_REGISTRY) >= 11


def test_get_kol_normalizes_handle() -> None:
    assert get_kol("@CZ_Binance").name == "CZ"
    assert get_kol("https://x.com/saylor").name == "Michael Saylor"
    assert get_kol("unknown_person_xyz") is None


def test_tier1_outweighs_tier3() -> None:
    cz = get_kol("cz_binance")
    planb = get_kol("100trillionUSD")
    assert cz.weight > planb.weight
    assert 0.0 < planb.weight <= 1.0


def test_resolve_unknown_kol_default() -> None:
    k = resolve_kol("some_random_anon")
    assert k.tier == 3 and 0.0 < k.weight <= 1.0


def test_accuracy_increases_weight() -> None:
    from super_otonom.signals.kol_tracker import KOL

    lo = KOL("a", "a", 1, 0.1)
    hi = KOL("b", "b", 1, 0.9)
    assert hi.weight > lo.weight


# ── 2) Tweet analizi (NLP) ───────────────────────────────────────────────────


def test_parse_cashtags() -> None:
    assert parse_cashtags("$BTC looking strong, also $eth and $SOL") == ["BTC", "ETH", "SOL"]
    assert parse_cashtags("no cashtags here") == []
    assert parse_cashtags("$BTC $btc dedup") == ["BTC"]


def test_detect_action() -> None:
    assert detect_action("time to buy $BTC") == BUY
    assert detect_action("accumulate the dip") == BUY
    assert detect_action("I am shorting this") == SELL
    assert detect_action("just chilling") is None
    assert detect_action("don't sell, accumulate") is None  # karışık → belirsiz


def test_analyze_sentiment_bullish_bearish() -> None:
    s_bull, l_bull = analyze_sentiment("super bullish, accumulate, moon soon")
    s_bear, l_bear = analyze_sentiment("bearish dump incoming, sell now, crash")
    assert s_bull > 0 and l_bull == BULLISH
    assert s_bear < 0 and l_bear == BEARISH
    assert analyze_sentiment("")[1] == NEUTRAL


def test_analyze_sentiment_negation_flips() -> None:
    s, label = analyze_sentiment("not bullish at all")
    assert s < 0 and label == BEARISH


def test_engagement_weight_monotonic() -> None:
    low = engagement_weight(10, 1)
    high = engagement_weight(40000, 8000)
    assert 0.0 <= low < high <= 1.0
    assert engagement_weight(0, 0) == 0.0


def test_analyze_tweet_action_reinforces_sentiment() -> None:
    t = analyze_tweet({"handle": "cz_binance", "text": "accumulate $BTC", "likes": 5000, "retweets": 1000})
    assert t.action == BUY
    assert t.sentiment >= 0.35
    assert "BTC" in t.tokens
    assert t.influence > 0


def test_analyze_tweet_accuracy_override() -> None:
    t = analyze_tweet({"handle": "elonmusk", "text": "$DOGE", "accuracy": 0.0})
    t2 = analyze_tweet({"handle": "elonmusk", "text": "$DOGE", "accuracy": 1.0})
    assert t2.kol_weight > t.kol_weight


# ── 3) KOL consensus ─────────────────────────────────────────────────────────


def _tw(handle: str, text: str, likes: int = 1000, rts: int = 200, ts_ms=None) -> dict:
    return {"handle": handle, "text": text, "likes": likes, "retweets": rts, "ts_ms": ts_ms}


def test_consensus_bullish() -> None:
    tweets = [
        _tw("cz_binance", "buy $BTC, bullish"),
        _tw("saylor", "accumulate $BTC forever"),
        _tw("woonomic", "$BTC bottom is in, long"),
    ]
    analyses = [analyze_tweet(t) for t in tweets]
    cons = compute_consensus(analyses, "BTC")
    assert cons.kol_count == 3
    assert cons.label == BULLISH
    assert cons.weighted_sentiment > 0


def test_consensus_divergence() -> None:
    tweets = [
        _tw("cz_binance", "super bullish $ETH, buy"),
        _tw("hsakatrades", "shorting $ETH, bearish dump"),
    ]
    analyses = [analyze_tweet(t) for t in tweets]
    cons = compute_consensus(analyses, "ETH")
    assert cons.bullish_kols == 1 and cons.bearish_kols == 1
    assert cons.divergence > 0.5
    assert cons.label == DIVERGENT


def test_consensus_window_filters_old() -> None:
    now = 1_000_000_000_000.0
    tweets = [
        _tw("cz_binance", "buy $BTC", ts_ms=now),
        _tw("saylor", "buy $BTC", ts_ms=now - 48 * 3_600_000),  # 48h önce → dışarıda
    ]
    analyses = [analyze_tweet(t) for t in tweets]
    cons = compute_consensus(analyses, "BTC", now_ms=now, window_hours=24.0)
    assert cons.kol_count == 1


def test_consensus_token_filter() -> None:
    tweets = [_tw("cz_binance", "buy $BTC"), _tw("saylor", "buy $ETH")]
    analyses = [analyze_tweet(t) for t in tweets]
    cons = compute_consensus(analyses, "BTC")
    assert cons.kol_count == 1


def test_consensus_dedup_same_kol() -> None:
    tweets = [_tw("cz_binance", "buy $BTC"), _tw("cz_binance", "still buying $BTC")]
    analyses = [analyze_tweet(t) for t in tweets]
    cons = compute_consensus(analyses, "BTC")
    assert cons.kol_count == 1 and cons.tweet_count == 2


def test_consensus_empty() -> None:
    cons = compute_consensus([], "BTC")
    assert cons.kol_count == 0 and cons.label == NEUTRAL


# ── 4) Timing sinyali ────────────────────────────────────────────────────────


def test_detect_buy_rumor_sell_news() -> None:
    assert detect_buy_rumor_sell_news(peak_pct=0.05, final_pct=0.005) is True
    assert detect_buy_rumor_sell_news(peak_pct=0.05, final_pct=0.045) is False
    assert detect_buy_rumor_sell_news(peak_pct=0.005, final_pct=0.0) is False  # pump yetersiz


def test_backtest_timing_avg_and_hitrate() -> None:
    events = [
        {"sentiment": 0.8, "move_pct": 0.03, "lag_minutes": 20},
        {"sentiment": 0.7, "move_pct": 0.01, "lag_minutes": 40},
        {"sentiment": -0.6, "move_pct": -0.02, "lag_minutes": 30},
    ]
    sig = backtest_kol_timing(events)
    assert sig.sample_size == 3
    assert sig.hit_rate == pytest.approx(1.0)
    assert sig.avg_lag_minutes == pytest.approx(30.0)


def test_backtest_timing_buy_rumor_sell_news() -> None:
    events = [
        {"sentiment": 0.8, "move_pct": 0.001, "peak_pct": 0.05, "final_pct": 0.001},
        {"sentiment": 0.7, "move_pct": 0.0, "peak_pct": 0.04, "final_pct": 0.0},
    ]
    sig = backtest_kol_timing(events)
    assert sig.buy_rumor_sell_news is True
    assert sig.rumor_fade_rate == pytest.approx(1.0)


def test_backtest_timing_empty() -> None:
    sig = backtest_kol_timing([])
    assert sig.sample_size == 0 and sig.buy_rumor_sell_news is False


# ── Birleşik analiz (analyze_kol) ────────────────────────────────────────────


def test_analyze_kol_bullish_consensus() -> None:
    tweets = [_tw("cz_binance", "buy $BTC"), _tw("saylor", "accumulate $BTC"), _tw("cobie", "$BTC long")]
    sig = analyze_kol(tweets, "BTC")
    assert sig is not None
    assert sig.alpha_bias > 0
    assert sig.consensus.label == BULLISH


def test_analyze_kol_bearish_raises_risk() -> None:
    tweets = [_tw("cz_binance", "sell $BTC, bearish dump"), _tw("hsakatrades", "shorting $BTC crash")]
    sig = analyze_kol(tweets, "BTC")
    assert sig is not None
    assert sig.risk_score > 0.0
    assert sig.consensus.label == BEARISH


def test_analyze_kol_divergence_cuts_alpha() -> None:
    tweets = [_tw("cz_binance", "bullish buy $SOL"), _tw("gicantrebirth", "bearish short $SOL dump")]
    sig = analyze_kol(tweets, "SOL")
    assert sig is not None
    assert sig.consensus.label == DIVERGENT
    assert sig.risk_score >= 0.3


def test_analyze_kol_rumor_sell_news_dampens() -> None:
    tweets = [_tw("cz_binance", "buy $BTC"), _tw("saylor", "accumulate $BTC")]
    timing = [
        {"sentiment": 0.8, "move_pct": 0.001, "peak_pct": 0.05, "final_pct": 0.0},
        {"sentiment": 0.7, "move_pct": 0.0, "peak_pct": 0.04, "final_pct": 0.0},
    ]
    plain = analyze_kol(tweets, "BTC")
    damp = analyze_kol(tweets, "BTC", timing_events=timing)
    assert damp.alpha_bias < plain.alpha_bias  # sell-the-news alpha'yı kısar
    assert damp.timing is not None and damp.timing.buy_rumor_sell_news is True


def test_analyze_kol_empty_returns_none() -> None:
    assert analyze_kol([], "BTC") is None
    assert analyze_kol([{"handle": "cz_binance", "text": "buy $ETH"}], "BTC") is None  # token yok


# ── Parser'lar ───────────────────────────────────────────────────────────────


def test_parse_twitter_api_v2() -> None:
    payload = {
        "data": [
            {"text": "buy $BTC", "author_id": "1", "public_metrics": {"like_count": 100, "retweet_count": 20},
             "created_at": "2026-06-03T12:00:00.000Z"},
        ],
        "includes": {"users": [{"id": "1", "username": "cz_binance"}]},
    }
    out = parse_twitter_api_v2(json.dumps(payload))
    assert len(out) == 1
    assert out[0]["handle"] == "cz_binance"
    assert out[0]["likes"] == 100
    assert out[0]["ts_ms"] is not None


def test_parse_twitter_api_v2_garbage() -> None:
    assert parse_twitter_api_v2("not json") == []
    assert parse_twitter_api_v2({"no_data": 1}) == []


def test_parse_nitter_rss() -> None:
    rss = """<rss><channel>
      <item><title>buy $BTC now</title><dc:creator>@cz_binance</dc:creator></item>
      <item><description>$ETH &lt;b&gt;bearish&lt;/b&gt;</description><creator>saylor</creator></item>
    </channel></rss>"""
    out = parse_nitter_rss(rss)
    assert len(out) == 2
    assert out[0]["handle"] == "@cz_binance"
    assert "$BTC" in out[0]["text"]


def test_parse_nitter_rss_empty() -> None:
    assert parse_nitter_rss("no items") == []


# ── Collector (mock'lanabilir) ───────────────────────────────────────────────


def test_collector_twitter_no_token(monkeypatch) -> None:
    monkeypatch.delenv("TWITTER_BEARER_TOKEN", raising=False)
    col = KolCollector(http_get=lambda u, t: "{}")
    assert col.fetch_twitter_api("$BTC") == []


def test_collector_nitter_parses() -> None:
    rss = "<rss><item><title>buy $BTC</title><dc:creator>cz_binance</dc:creator></item></rss>"
    col = KolCollector(http_get=lambda u, t: rss)
    out = col.fetch_nitter("cz_binance")
    assert len(out) == 1 and "$BTC" in out[0]["text"]


def test_collector_none_graceful() -> None:
    col = KolCollector(http_get=lambda u, t: None)
    assert col.fetch_nitter("cz_binance") == []


# ── social_signal (Faz 16) entegrasyonu ──────────────────────────────────────


def test_faz16_kol_block_attached() -> None:
    d = {
        "sentiment_score": 0.5,
        "engagement_rate": 0.4,
        "kol": {"tweets": [_tw("cz_binance", "buy $BTC"), _tw("saylor", "accumulate $BTC")], "token": "BTC"},
    }
    r = analyze_social_signal("BTC/USDT", d, {}, attach_to_analysis=False)
    assert "kol" in r["social"]
    assert r["social"]["kol"]["kol_count"] == 2
    assert r["social"]["kol"]["kol_label"] == BULLISH


def test_faz16_kol_flat_tweets_key() -> None:
    d = {
        "sentiment_score": 0.5,
        "engagement_rate": 0.4,
        "kol_tweets": [_tw("cz_binance", "buy $BTC")],
        "kol_token": "BTC",
    }
    r = analyze_social_signal("BTC/USDT", d, {}, attach_to_analysis=False)
    assert "kol" in r["social"]


def test_faz16_kol_bearish_raises_risk() -> None:
    base = {"sentiment_score": 0.5, "engagement_rate": 0.4}
    bear = dict(base)
    bear["kol"] = {
        "tweets": [_tw("cz_binance", "sell $BTC bearish dump"), _tw("hsakatrades", "short $BTC crash")],
        "token": "BTC",
    }
    r_base = analyze_social_signal("BTC/USDT", base, {}, attach_to_analysis=False)
    r_bear = analyze_social_signal("BTC/USDT", bear, {}, attach_to_analysis=False)
    assert r_bear["risk_score"] >= r_base["risk_score"]


def test_faz16_backward_compat_no_kol() -> None:
    """KOL verisi yoksa social payload'da kol anahtarı olmaz; davranış değişmez."""
    d = {"sentiment_score": 0.52, "mention_momentum": 0.0, "engagement_rate": 0.35, "sentiment_trend": "flat"}
    r = analyze_social_signal("ETH/USDT", d, {}, attach_to_analysis=False)
    assert "kol" not in r["social"]
    assert r["trade_permission"] == "ALLOW"


def test_faz16_kol_token_defaults_to_symbol() -> None:
    d = {"sentiment_score": 0.5, "engagement_rate": 0.4, "kol_tweets": [_tw("cz_binance", "buy $BTC")]}
    r = analyze_social_signal("BTC/USDT", d, {}, attach_to_analysis=False)
    assert "kol" in r["social"]  # token verilmese de symbol'den BTC çözülür


def test_faz16_kol_empty_tweets_ignored() -> None:
    d = {"sentiment_score": 0.5, "engagement_rate": 0.4, "kol": {"tweets": []}}
    r = analyze_social_signal("BTC/USDT", d, {}, attach_to_analysis=False)
    assert "kol" not in r["social"]
