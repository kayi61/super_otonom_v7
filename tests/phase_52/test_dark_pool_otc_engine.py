"""Faz 52 — dark_pool_otc_engine birim testleri."""

from __future__ import annotations

from phases.phase_52.dark_pool_otc_engine import analyze, validate_market_data


def _schema_keys() -> set:
    return {
        "phase", "module", "trade_permission", "alpha_score", "risk_score",
        "score_type", "confidence", "data_health", "event_ts", "half_life_ms",
        "analysis", "reason",
    }


def _otc(size: float, side: str, delay: float = 100.0) -> dict:
    return {"size_usd": size, "side": side, "delay_ms": delay}


def _block(size: float, side: str, impact: float = 0.5) -> dict:
    return {"size_usd": size, "side": side, "price_impact_pct": impact}


def _mint(amount: float, mtype: str = "mint", ts: float = 1.0) -> dict:
    return {"amount_usd": amount, "type": mtype, "ts": ts}


def _base_market_data() -> dict:
    return {
        "otc_trades": [_otc(1e6, "buy"), _otc(500_000, "sell")],
        "block_trades": [_block(2e6, "buy", 0.3)],
        "stablecoin_mints": [_mint(5e7, "mint"), _mint(1e7, "burn")],
        "current_price": 50000.0,
        "adv_usd": 1e9,
    }


class TestValidation:
    def test_none_invalid(self) -> None:
        ok, _ = validate_market_data(None)
        assert not ok

    def test_missing_field(self) -> None:
        d = _base_market_data()
        del d["current_price"]
        ok, _ = validate_market_data(d)
        assert not ok

    def test_zero_price(self) -> None:
        d = _base_market_data()
        d["current_price"] = 0.0
        ok, err = validate_market_data(d)
        assert not ok
        assert "non_positive" in err

    def test_invalid_otc_side(self) -> None:
        d = _base_market_data()
        d["otc_trades"] = [_otc(1e6, "LONG")]
        ok, err = validate_market_data(d)
        assert not ok
        assert "side" in err

    def test_invalid_mint_type(self) -> None:
        d = _base_market_data()
        d["stablecoin_mints"] = [_mint(1e6, "create")]
        ok, err = validate_market_data(d)
        assert not ok
        assert "type" in err

    def test_valid(self) -> None:
        ok, err = validate_market_data(_base_market_data())
        assert ok


class TestAnalyze:
    def test_none_blocked(self) -> None:
        r = analyze(None)
        assert r["trade_permission"] == "BLOCK"
        assert r["phase"] == 52
        assert _schema_keys() <= set(r.keys())

    def test_valid_allow(self) -> None:
        r = analyze(_base_market_data())
        assert r["trade_permission"] == "ALLOW"
        assert 0.0 <= r["alpha_score"] <= 1.0

    def test_burn_dominance_blocks(self) -> None:
        d = _base_market_data()
        d["stablecoin_mints"] = [_mint(1e6, "mint"), _mint(5e6, "burn")]
        r = analyze(d)
        assert r["trade_permission"] == "BLOCK"
        assert r["reason"] == "burn_dominance"

    def test_otc_imbalance_buy_heavy(self) -> None:
        d = _base_market_data()
        d["otc_trades"] = [_otc(10e6, "buy")]
        r = analyze(d)
        assert r["analysis"]["otc_imbalance"] > 0.5

    def test_block_impact_negative(self) -> None:
        d = _base_market_data()
        d["block_trades"] = [_block(2e6, "sell", 5.0)]
        r = analyze(d)
        assert r["analysis"]["net_block_impact"] < 0.0

    def test_empty_otc_trades(self) -> None:
        d = _base_market_data()
        d["otc_trades"] = []
        r = analyze(d)
        assert r["analysis"]["avg_delay_ms"] == 0.0
