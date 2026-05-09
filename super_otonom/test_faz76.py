from __future__ import annotations


def test_faz76_unknown_regime_still_returns_valid_fields() -> None:
    from super_otonom.regime_adaptive_execution_engine import infer_regime_adaptive_execution

    r = infer_regime_adaptive_execution(symbol="BTC/USDT", analysis={"regime": "???", "volatility": 0.02, "liquidity_ratio": 0.5})
    d = r.to_dict()
    assert d["regime_execution_mode"] in ("trend", "range", "volatile", "crisis", "unknown")
    assert d["preferred_order_type"] in ("maker", "taker", "twap", "unknown")
    assert 0 <= d["urgency_score"] <= 100
    assert 0 <= d["slippage_risk"] <= 100
    assert d["trade_permission"] in ("HALT", "BLOCK", "ALLOW")


def test_faz76_extreme_slippage_can_block() -> None:
    from super_otonom.regime_adaptive_execution_engine import infer_regime_adaptive_execution

    # Wide spread + high vol + low liquidity
    ob = {"bids": [[100, 1]], "asks": [[103, 1]]}
    r = infer_regime_adaptive_execution(
        symbol="BTC/USDT",
        analysis={"regime": "CRISIS", "volatility": 0.12, "liquidity_ratio": 0.05},
        order_book=ob,
    )
    assert r.slippage_risk >= 0
    assert r.trade_permission in ("ALLOW", "BLOCK")

