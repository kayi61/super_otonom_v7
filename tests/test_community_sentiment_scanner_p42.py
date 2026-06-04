"""PROMPT-4.2 — Reddit & Telegram Community Sentiment Scanner + entegrasyon."""

from __future__ import annotations

import json

from super_otonom.signals.community_sentiment_scanner import (
    EXTREME_FEAR,
    EXTREME_GREED,
    FEAR,
    FNG_NEUTRAL,
    GREED,
    SIGNAL_BUY,
    SIGNAL_REDUCE,
    CommunityCollector,
    analyze_community,
    analyze_community_data,
    analyze_fear_greed,
    analyze_google_trends,
    analyze_reddit,
    analyze_telegram,
    classify_fng,
    parse_alternative_me,
)
from super_otonom.signals.sentiment_layer import SentimentLayer
from super_otonom.signals.social_signal import analyze_social_signal

# ── 1) Reddit ────────────────────────────────────────────────────────────────


def test_reddit_mention_spike() -> None:
    r = analyze_reddit(mention_count=1000, mention_baseline=100)
    assert r.mention_spike > 0.8
    assert 0.0 <= r.heat <= 1.0


def test_reddit_no_baseline_full_spike() -> None:
    r = analyze_reddit(mention_count=500, mention_baseline=0)
    assert r.mention_spike == 1.0


def test_reddit_comment_sentiment() -> None:
    bull = analyze_reddit(comment_texts=["very bullish, buy and accumulate", "moon soon, long"])
    bear = analyze_reddit(comment_texts=["bearish dump, sell, scam", "crash incoming"])
    assert bull.comment_sentiment > 0
    assert bear.comment_sentiment < 0


def test_reddit_award_anomaly() -> None:
    r = analyze_reddit(award_count=50, award_baseline=5)
    assert r.award_anomaly > 0.7


def test_reddit_empty() -> None:
    r = analyze_reddit()
    assert r.heat == 0.0 and r.sentiment == 0.0


# ── 2) Telegram ──────────────────────────────────────────────────────────────


def test_telegram_fomo_fud() -> None:
    tg = analyze_telegram(
        message_texts=["pump it to the moon, buy now", "lambo soon 100x", "scam? no, moon"]
    )
    assert tg.fomo_score > 0.5
    assert tg.sentiment > 0


def test_telegram_fud_negative() -> None:
    tg = analyze_telegram(message_texts=["scam rug pull", "dump incoming, exit", "ponzi avoid"])
    assert tg.fud_score > 0.5
    assert tg.sentiment < 0


def test_telegram_manipulation_risk() -> None:
    tg = analyze_telegram(
        message_texts=["pump now moon", "buy now lambo"], bot_ratio=0.8
    )
    assert tg.manipulation_risk > 0.6


def test_telegram_freq_spike() -> None:
    tg = analyze_telegram(message_count=5000, message_baseline=500)
    assert tg.freq_spike > 0.8


# ── 3) Fear & Greed ──────────────────────────────────────────────────────────


def test_classify_fng() -> None:
    assert classify_fng(10) == EXTREME_FEAR
    assert classify_fng(30) == FEAR
    assert classify_fng(50) == FNG_NEUTRAL
    assert classify_fng(70) == GREED
    assert classify_fng(90) == EXTREME_GREED


def test_fng_extreme_fear_contrarian_buy() -> None:
    fg = analyze_fear_greed(12)
    assert fg.classification == EXTREME_FEAR
    assert fg.contrarian_signal == SIGNAL_BUY
    assert fg.bias > 0


def test_fng_extreme_greed_reduce_risk() -> None:
    fg = analyze_fear_greed(92)
    assert fg.classification == EXTREME_GREED
    assert fg.contrarian_signal == SIGNAL_REDUCE
    assert fg.bias < 0
    assert fg.risk_score >= 0.5


def test_fng_trend() -> None:
    fg = analyze_fear_greed(60, history_7d=[40, 45, 50], history_30d=[30, 35])
    assert fg.trend_7d > 0
    assert fg.trend_30d > 0


def test_fng_none() -> None:
    assert analyze_fear_greed(None) is None


def test_parse_alternative_me() -> None:
    payload = {"data": [{"value": "15", "value_classification": "Extreme Fear"},
                        {"value": "20"}, {"value": "25"}]}
    out = parse_alternative_me(json.dumps(payload))
    assert out["value"] == 15
    assert out["history_7d"][:3] == [15, 20, 25]


def test_parse_alternative_me_garbage() -> None:
    assert parse_alternative_me("not json") is None
    assert parse_alternative_me({"no_data": 1}) is None


# ── 4) Google Trends ─────────────────────────────────────────────────────────


def test_trends_retail_fomo_spike() -> None:
    t = analyze_google_trends(interest=95, interest_baseline=20)
    assert t.retail_fomo is True
    assert t.bias < 0  # geç girişçi → contrarian negatif


def test_trends_accumulation_zone() -> None:
    t = analyze_google_trends(interest=10, interest_baseline=50, price_low=True)
    assert t.accumulation_zone is True
    assert t.bias > 0


def test_trends_none() -> None:
    assert analyze_google_trends() is None


# ── Birleşik analiz ──────────────────────────────────────────────────────────


def test_analyze_community_extreme_fear_bullish() -> None:
    sig = analyze_community(fear_greed=analyze_fear_greed(10))
    assert sig is not None
    assert sig.alpha_bias > 0
    assert any("Extreme Fear" in r for r in sig.reasons)


def test_analyze_community_greed_raises_risk() -> None:
    sig = analyze_community(fear_greed=analyze_fear_greed(95))
    assert sig is not None
    assert sig.risk_score >= 0.5
    assert sig.alpha_bias < 0


def test_analyze_community_manipulation() -> None:
    tg = analyze_telegram(message_texts=["pump moon buy now", "lambo 100x"], bot_ratio=0.9)
    sig = analyze_community(telegram=tg)
    assert sig.manipulation_risk > 0.6
    assert sig.risk_score > 0.5


def test_analyze_community_fng_plus_whale_strong() -> None:
    fg = analyze_fear_greed(15)
    weak = analyze_community(fear_greed=fg)
    strong = analyze_community(fear_greed=fg, whale_accumulation=0.9)
    assert strong.alpha_bias > weak.alpha_bias
    assert any("whale" in r for r in strong.reasons)


def test_analyze_community_empty_none() -> None:
    assert analyze_community() is None


def test_analyze_community_data_flat() -> None:
    data = {
        "reddit": {"mention_count": 1000, "mention_baseline": 100,
                   "comment_texts": ["bullish buy moon"]},
        "telegram": {"message_texts": ["pump moon"], "bot_ratio": 0.2},
        "fear_greed": {"value": 12},
        "google_trends": {"interest": 10, "interest_baseline": 50, "price_low": True},
        "whale_accumulation": 0.8,
    }
    sig = analyze_community_data(data)
    assert sig is not None
    assert sig.reddit is not None and sig.telegram is not None
    assert sig.fear_greed.classification == EXTREME_FEAR
    assert sig.trends.accumulation_zone is True


def test_analyze_community_data_value_only_fng() -> None:
    sig = analyze_community_data({"fear_greed": 90})
    assert sig is not None and sig.fear_greed.classification == EXTREME_GREED


def test_analyze_community_data_empty_none() -> None:
    assert analyze_community_data({}) is None
    assert analyze_community_data("not a dict") is None


# ── Collector ────────────────────────────────────────────────────────────────


def test_collector_fear_greed_parses() -> None:
    payload = json.dumps({"data": [{"value": "18"}, {"value": "22"}]})
    col = CommunityCollector(http_get=lambda u, t: payload)
    out = col.fetch_fear_greed()
    assert out["value"] == 18


def test_collector_none_graceful() -> None:
    col = CommunityCollector(http_get=lambda u, t: None)
    assert col.fetch_fear_greed() is None


# ── sentiment_layer (PROMPT-4.2) entegrasyonu ────────────────────────────────


def test_sentiment_layer_seeds_fng_from_score() -> None:
    layer = SentimentLayer(mock_score=0.1)  # 0.1 → F&G 10 (extreme fear)
    out = layer.analyze_community_sentiment()
    assert out is not None
    assert out["fear_greed"]["classification"] == EXTREME_FEAR
    assert out["community_alpha_bias"] > 0


def test_sentiment_layer_greed_seed() -> None:
    layer = SentimentLayer(mock_score=0.9)  # 0.9 → F&G 90 (extreme greed)
    out = layer.analyze_community_sentiment()
    assert out["fear_greed"]["classification"] == EXTREME_GREED


def test_sentiment_layer_explicit_community_data() -> None:
    layer = SentimentLayer(mock_score=0.5)
    out = layer.analyze_community_sentiment({"telegram": {"message_texts": ["scam dump rug"]}})
    assert out is not None
    assert "telegram" in out


# ── social_signal (Faz 16) entegrasyonu ──────────────────────────────────────


def test_faz16_community_block_attached() -> None:
    d = {
        "sentiment_score": 0.5,
        "engagement_rate": 0.4,
        "community": {"fear_greed": {"value": 12}, "whale_accumulation": 0.8},
    }
    r = analyze_social_signal("BTC/USDT", d, {}, attach_to_analysis=False)
    assert "community" in r["social"]
    assert r["social"]["community"]["fear_greed"]["classification"] == EXTREME_FEAR


def test_faz16_community_flat_keys() -> None:
    d = {"sentiment_score": 0.5, "engagement_rate": 0.4, "fear_greed": {"value": 90}}
    r = analyze_social_signal("BTC/USDT", d, {}, attach_to_analysis=False)
    assert "community" in r["social"]


def test_faz16_community_greed_raises_risk() -> None:
    base = {"sentiment_score": 0.5, "engagement_rate": 0.4}
    greed = dict(base)
    greed["community"] = {"fear_greed": {"value": 95}}
    r_base = analyze_social_signal("BTC/USDT", base, {}, attach_to_analysis=False)
    r_greed = analyze_social_signal("BTC/USDT", greed, {}, attach_to_analysis=False)
    assert r_greed["risk_score"] >= r_base["risk_score"]


def test_faz16_backward_compat_no_community() -> None:
    d = {"sentiment_score": 0.52, "mention_momentum": 0.0, "engagement_rate": 0.35, "sentiment_trend": "flat"}
    r = analyze_social_signal("ETH/USDT", d, {}, attach_to_analysis=False)
    assert "community" not in r["social"]
    assert r["trade_permission"] == "ALLOW"


def test_faz16_kol_and_community_coexist() -> None:
    d = {
        "sentiment_score": 0.5,
        "engagement_rate": 0.4,
        "kol_tweets": [{"handle": "cz_binance", "text": "buy $BTC", "likes": 5000, "retweets": 1000}],
        "kol_token": "BTC",
        "community": {"fear_greed": {"value": 15}},
    }
    r = analyze_social_signal("BTC/USDT", d, {}, attach_to_analysis=False)
    assert "kol" in r["social"]
    assert "community" in r["social"]
