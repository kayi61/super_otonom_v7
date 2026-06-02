"""PROMPT-1.1 — WhaleFeedCollector + Faz 17 feed entegrasyonu testleri (ağsız)."""

from __future__ import annotations

import json

import pytest
from super_otonom.signals.whale_feed_collector import (
    DIR_COLD_STORAGE,
    DIR_FROM_EXCHANGE,
    DIR_INTERNAL,
    DIR_TO_EXCHANGE,
    WalletRegistry,
    WhaleAlert,
    WhaleFeedCollector,
    WhaleTransfer,
    parse_blockchain_btc,
    parse_etherscan_transfers,
    parse_whale_alert,
    run_whale_phase,
)

# Registry'deki gerçek etiketli adresler
_BINANCE = "0x28c6c06298d514db089934071355e5743bf21d60"  # exchange
_BINANCE_COLD = "0xf977814e90da44bfa03b6295a0616a897441acec"  # exchange_cold
_JUMP = "0xd793281182a0e3e023116004778f45c29fc14f19"  # fund


@pytest.fixture
def registry() -> WalletRegistry:
    return WalletRegistry.from_file()


# ── WalletRegistry ────────────────────────────────────────────────────────────


def test_registry_loads_from_file(registry: WalletRegistry) -> None:
    assert len(registry) >= 20


def test_registry_lookup_case_insensitive(registry: WalletRegistry) -> None:
    lbl = registry.lookup(_BINANCE.upper())
    assert lbl is not None
    assert lbl.entity == "Binance"
    assert lbl.is_exchange is True
    assert lbl.is_cold is False


def test_registry_cold_and_fund(registry: WalletRegistry) -> None:
    cold = registry.lookup(_BINANCE_COLD)
    assert cold is not None and cold.is_cold is True and cold.is_exchange is True
    fund = registry.lookup(_JUMP)
    assert fund is not None and fund.is_fund is True


def test_registry_lookup_missing(registry: WalletRegistry) -> None:
    assert registry.lookup("0xdeadbeef") is None
    assert registry.lookup(None) is None
    assert registry.lookup("") is None


def test_registry_from_missing_file_graceful(tmp_path) -> None:
    reg = WalletRegistry.from_file(tmp_path / "nope.json")
    assert len(reg) == 0


# ── Direction sınıflandırma (parse_whale_alert üzerinden) ─────────────────────


def _wa(amount: float, from_meta: dict, to_meta: dict, ts: int = 1700000000) -> dict:
    return {
        "transactions": [
            {
                "hash": "0xh",
                "amount_usd": amount,
                "symbol": "eth",
                "blockchain": "ethereum",
                "timestamp": ts,
                "from": from_meta,
                "to": to_meta,
            }
        ]
    }


def test_classify_to_exchange(registry: WalletRegistry) -> None:
    p = _wa(1e6, {"owner": "w", "owner_type": "unknown"}, {"owner": "binance", "owner_type": "exchange"})
    t = parse_whale_alert(p, registry)[0]
    assert t.direction == DIR_TO_EXCHANGE


def test_classify_from_exchange(registry: WalletRegistry) -> None:
    p = _wa(1e6, {"owner": "binance", "owner_type": "exchange"}, {"owner": "w", "owner_type": "unknown"})
    t = parse_whale_alert(p, registry)[0]
    assert t.direction == DIR_FROM_EXCHANGE


def test_classify_cold_storage_via_registry(registry: WalletRegistry) -> None:
    p = _wa(
        1e6,
        {"owner": "w", "owner_type": "unknown"},
        {"owner": "binance", "owner_type": "unknown", "address": _BINANCE_COLD},
    )
    t = parse_whale_alert(p, registry)[0]
    assert t.direction == DIR_COLD_STORAGE


def test_classify_internal(registry: WalletRegistry) -> None:
    p = _wa(1e6, {"owner": "a", "owner_type": "unknown"}, {"owner": "b", "owner_type": "unknown"})
    t = parse_whale_alert(p, registry)[0]
    assert t.direction == DIR_INTERNAL


def test_classify_registry_address_overrides(registry: WalletRegistry) -> None:
    # owner_type yok ama adres registry'de exchange → to_exchange
    p = _wa(
        1e6,
        {"owner": "w", "owner_type": "unknown"},
        {"owner": "?", "owner_type": "unknown", "address": _BINANCE},
    )
    t = parse_whale_alert(p, registry)[0]
    assert t.direction == DIR_TO_EXCHANGE
    assert t.to_entity == "Binance"


# ── parse_whale_alert kenar durumlar ─────────────────────────────────────────


def test_parse_whale_alert_string_input(registry: WalletRegistry) -> None:
    p = json.dumps(_wa(1e6, {"owner_type": "unknown"}, {"owner_type": "exchange"}))
    assert len(parse_whale_alert(p, registry)) == 1


def test_parse_whale_alert_invalid(registry: WalletRegistry) -> None:
    assert parse_whale_alert("not-json", registry) == []
    assert parse_whale_alert(None, registry) == []
    assert parse_whale_alert(123, registry) == []
    assert parse_whale_alert({"transactions": None}, registry) == []


def test_parse_whale_alert_skips_zero_amount(registry: WalletRegistry) -> None:
    p = _wa(0, {"owner_type": "unknown"}, {"owner_type": "exchange"})
    assert parse_whale_alert(p, registry) == []


# ── parse_etherscan_transfers ─────────────────────────────────────────────────


def test_parse_etherscan_basic(registry: WalletRegistry) -> None:
    payload = {
        "status": "1",
        "result": [
            {
                "hash": "0x1",
                "from": "0xwhale",
                "to": _BINANCE,
                "value": str(10 * 10**18),  # 10 token
                "tokenDecimal": "18",
                "tokenSymbol": "LINK",
                "timeStamp": "1700000000",
            }
        ],
    }
    rows = parse_etherscan_transfers(payload, registry, price_usd=100_000.0)
    assert len(rows) == 1
    assert rows[0].amount_usd == pytest.approx(1_000_000.0)  # 10 * 100k
    assert rows[0].direction == DIR_TO_EXCHANGE


def test_parse_etherscan_zero_price_skips(registry: WalletRegistry) -> None:
    payload = {"result": [{"value": str(10**18), "tokenDecimal": "18", "from": "a", "to": "b"}]}
    assert parse_etherscan_transfers(payload, registry, price_usd=0.0) == []


def test_parse_etherscan_invalid(registry: WalletRegistry) -> None:
    assert parse_etherscan_transfers("x", registry, price_usd=1.0) == []
    assert parse_etherscan_transfers({"result": "bad"}, registry, price_usd=1.0) == []


# ── parse_blockchain_btc ──────────────────────────────────────────────────────


def test_parse_blockchain_btc(registry: WalletRegistry) -> None:
    payload = {
        "txs": [
            {
                "hash": "btc1",
                "time": 1700000000,
                "inputs": [{"prev_out": {"addr": "bc1qwhale"}}],
                "out": [{"addr": "3d2oetdnuzuqqhpjmcmddhyoqkynvsfk9r", "value": 5 * 10**8}],  # 5 BTC
            }
        ]
    }
    rows = parse_blockchain_btc(payload, registry, price_usd=60_000.0)
    assert len(rows) == 1
    assert rows[0].amount_usd == pytest.approx(300_000.0)  # 5 * 60k
    assert rows[0].asset == "BTC"
    assert rows[0].direction == DIR_TO_EXCHANGE  # → Bitfinex (exchange)


def test_parse_blockchain_btc_invalid(registry: WalletRegistry) -> None:
    assert parse_blockchain_btc("x", registry, price_usd=1.0) == []
    assert parse_blockchain_btc({"txs": None}, registry, price_usd=1.0) == []


# ── Collector: filtre / sıralama / fetch ─────────────────────────────────────


def test_collect_filters_min_usd(registry: WalletRegistry) -> None:
    payload = {
        "transactions": [
            {"hash": "a", "amount_usd": 600_000, "symbol": "eth", "blockchain": "ethereum",
             "timestamp": 2, "from": {"owner_type": "unknown"}, "to": {"owner_type": "exchange"}},
            {"hash": "b", "amount_usd": 100_000, "symbol": "eth", "blockchain": "ethereum",
             "timestamp": 1, "from": {"owner_type": "unknown"}, "to": {"owner_type": "exchange"}},
        ]
    }
    col = WhaleFeedCollector(registry=registry, http_get=lambda u, t: json.dumps(payload), min_usd=500_000)
    import os

    os.environ["WHALE_ALERT_API_KEY"] = "k"
    try:
        res = col.collect()
    finally:
        os.environ.pop("WHALE_ALERT_API_KEY", None)
    assert len(res) == 1
    assert res[0].amount_usd == 600_000


def test_fetch_no_api_key_returns_empty(registry: WalletRegistry, monkeypatch) -> None:
    monkeypatch.delenv("WHALE_ALERT_API_KEY", raising=False)
    col = WhaleFeedCollector(registry=registry, http_get=lambda u, t: "should-not-be-called")
    assert col._fetch_whale_alert() == []


def test_fetch_http_returns_none_graceful(registry: WalletRegistry, monkeypatch) -> None:
    monkeypatch.setenv("WHALE_ALERT_API_KEY", "k")
    col = WhaleFeedCollector(registry=registry, http_get=lambda u, t: None)
    assert col._fetch_whale_alert() == []


# ── Netflow & smart_money_data ───────────────────────────────────────────────


def _mk(amount: float, direction: str, ts: int = 0) -> WhaleTransfer:
    return WhaleTransfer(
        tx_hash="h", amount_usd=amount, asset="ETH", chain="ethereum", direction=direction, ts_ms=ts
    )


def test_compute_netflow() -> None:
    transfers = [
        _mk(10e6, DIR_TO_EXCHANGE),
        _mk(3e6, DIR_FROM_EXCHANGE),
        _mk(2e6, DIR_COLD_STORAGE),
        _mk(5e6, DIR_INTERNAL),
    ]
    nf = WhaleFeedCollector.compute_exchange_netflow_usd(transfers)
    assert nf == pytest.approx(10e6 - 3e6 - 2e6)  # internal sayılmaz


def test_to_smart_money_data_shape(registry: WalletRegistry) -> None:
    col = WhaleFeedCollector(registry=registry)
    data = col.to_smart_money_data([_mk(1e6, DIR_TO_EXCHANGE)])
    assert "whale_transfers" in data and "exchange_netflow_usd" in data
    assert data["whale_transfer_count"] == 1
    assert data["whale_transfers"][0]["direction"] == DIR_TO_EXCHANGE
    assert data["whale_transfers"][0]["amount_usd"] == 1e6


# ── Alert sistemi ─────────────────────────────────────────────────────────────


def test_alert_large_transfer(registry: WalletRegistry) -> None:
    col = WhaleFeedCollector(registry=registry, large_alert_usd=10e6)
    alerts = col.detect_alerts([_mk(12e6, DIR_TO_EXCHANGE)])
    assert any(a.kind == "LARGE_TRANSFER" and a.severity == "CRITICAL" for a in alerts)


def test_alert_trend_same_direction(registry: WalletRegistry) -> None:
    col = WhaleFeedCollector(registry=registry, large_alert_usd=10e6)
    base = 1_700_000_000_000
    transfers = [_mk(1e6, DIR_FROM_EXCHANGE, ts=base + i * 1000) for i in range(3)]
    alerts = col.detect_alerts(transfers)
    assert any(a.kind == "TREND" and a.details["direction"] == DIR_FROM_EXCHANGE for a in alerts)


def test_alert_trend_needs_three(registry: WalletRegistry) -> None:
    col = WhaleFeedCollector(registry=registry, large_alert_usd=10e6)
    transfers = [_mk(1e6, DIR_TO_EXCHANGE, ts=1000 + i) for i in range(2)]
    assert not any(a.kind == "TREND" for a in col.detect_alerts(transfers))


def test_alert_sell_pressure(registry: WalletRegistry) -> None:
    col = WhaleFeedCollector(registry=registry, large_alert_usd=10e6)
    alerts = col.detect_alerts([_mk(11e6, DIR_TO_EXCHANGE)])
    assert any(a.kind == "SELL_PRESSURE" for a in alerts)


def test_alert_none_for_small(registry: WalletRegistry) -> None:
    col = WhaleFeedCollector(registry=registry, large_alert_usd=10e6)
    assert col.detect_alerts([_mk(1e6, DIR_INTERNAL)]) == []


# ── Alert dispatch ────────────────────────────────────────────────────────────


class _FakeAlertManager:
    def __init__(self) -> None:
        self.events = []

    def system(self, event: str, detail: str = "", level: str = "INFO") -> None:
        self.events.append((event, detail, level))


def test_dispatch_to_alert_manager(registry: WalletRegistry) -> None:
    am = _FakeAlertManager()
    col = WhaleFeedCollector(registry=registry, alert_manager=am, large_alert_usd=10e6)
    col._dispatch_alerts([WhaleAlert(kind="LARGE_TRANSFER", severity="CRITICAL", message="m")])
    assert am.events == [("WHALE_LARGE_TRANSFER", "m", "CRITICAL")]


def test_dispatch_none_and_bad_object(registry: WalletRegistry) -> None:
    col = WhaleFeedCollector(registry=registry)  # alert_manager=None
    col._dispatch_alerts([WhaleAlert(kind="X", severity="INFO", message="m")])  # no raise
    col2 = WhaleFeedCollector(registry=registry, alert_manager=object())
    col2._dispatch_alerts([WhaleAlert(kind="X", severity="INFO", message="m")])  # no raise


# ── should_update ─────────────────────────────────────────────────────────────


def test_should_update(registry: WalletRegistry) -> None:
    col = WhaleFeedCollector(registry=registry, update_interval_sec=300)
    assert col.should_update(now_ms=10**13) is True  # ilk çağrı
    col._last_update_ms = 10**13
    assert col.should_update(now_ms=10**13 + 100_000) is False  # 100s < 300s
    assert col.should_update(now_ms=10**13 + 301_000) is True


# ── update() + run_whale_phase (Faz 17 entegrasyonu) ─────────────────────────


def test_update_emits_alerts_and_data(registry: WalletRegistry, monkeypatch) -> None:
    monkeypatch.setenv("WHALE_ALERT_API_KEY", "k")
    am = _FakeAlertManager()
    payload = _wa(12e6, {"owner_type": "unknown"}, {"owner_type": "exchange"})
    col = WhaleFeedCollector(
        registry=registry, http_get=lambda u, t: json.dumps(payload),
        alert_manager=am, large_alert_usd=10e6,
    )
    data = col.update()
    assert data["exchange_netflow_usd"] == pytest.approx(12e6)
    assert "LARGE_TRANSFER" in data["whale_alerts"]
    assert len(am.events) >= 1


def test_run_whale_phase_faz17_output(registry: WalletRegistry, monkeypatch) -> None:
    monkeypatch.setenv("WHALE_ALERT_API_KEY", "k")
    payload = _wa(12e6, {"owner_type": "unknown"}, {"owner_type": "exchange"})
    col = WhaleFeedCollector(registry=registry, http_get=lambda u, t: json.dumps(payload), large_alert_usd=10e6)
    out = run_whale_phase("ETHUSDT", col, {})
    # Faz 17 standart çıktı sözleşmesi
    assert set(["alpha_score", "risk_score", "trade_permission"]).issubset(out.keys())
    assert 0.0 <= out["alpha_score"] <= 1.0
    assert 0.0 <= out["risk_score"] <= 1.0
    assert out["trade_permission"] in ("ALLOW", "BLOCK", "HALT")
    assert out["phase"] == "17"


def test_run_whale_phase_empty_feed(registry: WalletRegistry, monkeypatch) -> None:
    monkeypatch.delenv("WHALE_ALERT_API_KEY", raising=False)
    col = WhaleFeedCollector(registry=registry, http_get=lambda u, t: None)
    out = run_whale_phase("ETHUSDT", col, {})
    # Boş feed → Faz 17 nötr/boş ama sözleşme korunur
    assert out["trade_permission"] in ("ALLOW", "BLOCK", "HALT")
    assert "alpha_score" in out and "risk_score" in out


def test_env_driven_config(registry: WalletRegistry, monkeypatch) -> None:
    monkeypatch.setenv("WHALE_MIN_USD", "1000000")
    monkeypatch.setenv("WHALE_LARGE_ALERT_USD", "20000000")
    col = WhaleFeedCollector(registry=registry)
    assert col.min_usd == 1_000_000.0
    assert col.large_alert_usd == 20_000_000.0
