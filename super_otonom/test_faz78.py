from __future__ import annotations


def test_faz78_decay_monotonicity() -> None:
    from super_otonom.alpha_decay_realtime_monitor import monitor_alpha_decay

    now = 1_000_000
    # Older signal should have lower freshness
    r_new = monitor_alpha_decay(symbol="BTC/USDT", analysis={"event_ts": now - 1_000, "half_life_ms": 30_000}, now_ts=now)
    r_old = monitor_alpha_decay(symbol="BTC/USDT", analysis={"event_ts": now - 90_000, "half_life_ms": 30_000}, now_ts=now)
    assert r_new.alpha_freshness_score >= r_old.alpha_freshness_score
    assert r_old.exit_urgency >= r_new.exit_urgency


def test_faz78_missing_timestamps_marks_low_health_and_blocks() -> None:
    from super_otonom.alpha_decay_realtime_monitor import monitor_alpha_decay

    r = monitor_alpha_decay(symbol="BTC/USDT", analysis={})
    assert 0.0 <= r.data_health <= 1.0
    assert r.trade_permission in ("ALLOW", "BLOCK")

