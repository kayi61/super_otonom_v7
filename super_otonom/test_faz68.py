from __future__ import annotations


def test_faz68_clean_path_allow() -> None:
    from super_otonom.safety_policy_engine import evaluate_safety_policy

    r = evaluate_safety_policy(
        symbol="BTC/USDT",
        analysis={
            "volatility": 0.02,
            "exp_pct": 0.10,
            "max_gross_exposure_pct": 0.95,
            "event_ts": 1_700_000_000_000,
            "half_life_ms": 30_000,
        },
    )
    assert r.trade_permission == "ALLOW"
    assert r.max_position_check is True
    assert r.news_kill_switch is False
    assert r.volatility_kill_switch is False
    assert r.approval_required is False
    assert 0 <= r.alpha_score <= 100
    assert 0 <= r.risk_score <= 100
    assert 0.0 <= r.confidence <= 1.0
    assert 0.0 <= r.data_health <= 1.0


def test_faz68_news_halts() -> None:
    from super_otonom.safety_policy_engine import evaluate_safety_policy

    r = evaluate_safety_policy(
        symbol="BTC/USDT",
        analysis={"news_kill_switch": True, "volatility": 0.02, "exp_pct": 0.0},
    )
    assert r.trade_permission == "HALT"
    assert r.news_kill_switch is True


def test_faz68_volatility_blocks() -> None:
    from super_otonom.safety_policy_engine import evaluate_safety_policy

    r = evaluate_safety_policy(
        symbol="ETH/USDT",
        analysis={"volatility": 0.20, "volatility_kill_threshold": 0.15, "exp_pct": 0.0},
    )
    assert r.trade_permission == "BLOCK"
    assert r.volatility_kill_switch is True


def test_faz68_exposure_blocks() -> None:
    from super_otonom.safety_policy_engine import evaluate_safety_policy

    r = evaluate_safety_policy(
        symbol="BTC/USDT",
        analysis={"volatility": 0.02, "exp_pct": 0.99, "max_gross_exposure_pct": 0.80},
    )
    assert r.trade_permission == "BLOCK"
    assert r.max_position_check is False


def test_faz68_approval_blocks() -> None:
    from super_otonom.safety_policy_engine import evaluate_safety_policy

    r = evaluate_safety_policy(
        symbol="BTC/USDT",
        analysis={"approval_required": True, "volatility": 0.02, "exp_pct": 0.0},
    )
    assert r.trade_permission == "BLOCK"
    assert r.approval_required is True
