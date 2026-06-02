"""PROMPT-1.3 — VcFundTracker + Faz 17 entegrasyonu testleri (ağsız)."""

from __future__ import annotations

import json

import pytest
from super_otonom.signals.vc_fund_tracker import (
    DIR_ACQUIRE,
    DIR_DISTRIBUTE,
    DIR_DISTRIBUTE_CEX,
    DIR_DISTRIBUTE_DEX,
    VcFundRegistry,
    VcFundTracker,
    VcTransfer,
    compute_vc_net_flow_usd,
    parse_vc_transfers,
    run_vc_fund_phase,
    token_conviction,
)

# Registry'deki gerçek etiketli adresler
_A16Z = "0x05e793ce0c6027323ac150f6d45c2344d28b6019"  # vc
_PARADIGM = "0x6cc8dd59e8b7c2b8b3e7d8f1f9e2a3b4c5d6e7f8"  # vc
_JUMP = "0xf584f8728b874a6a5c7a8d4d387c9aae9172d621"  # fund
_UNIV2 = "0x7a250d5630b4cf539739df2c5dacb4c659f2488d"  # dex
_BINANCE = "0x28c6c06298d514db089934071355e5743bf21d60"  # cex
_OUTSIDER = "0xabcabcabcabcabcabcabcabcabcabcabcabcabca"
_DAY = 86_400_000


@pytest.fixture
def registry() -> VcFundRegistry:
    return VcFundRegistry.from_file()


# ── Registry ──────────────────────────────────────────────────────────────────


def test_registry_loads(registry: VcFundRegistry) -> None:
    assert len(registry) >= 18


def test_registry_vc_fund_venue(registry: VcFundRegistry) -> None:
    assert registry.lookup(_A16Z.upper()).is_vc is True
    assert registry.lookup(_JUMP).is_fund is True
    assert registry.lookup(_UNIV2).is_dex is True
    assert registry.lookup(_BINANCE).is_cex is True
    assert registry.lookup(_A16Z).is_tracked is True
    assert registry.lookup(_UNIV2).is_tracked is False


def test_registry_tracked_entities(registry: VcFundRegistry) -> None:
    ents = registry.tracked_entities()
    assert "a16z Crypto" in ents and "Jump Trading" in ents
    assert "Uniswap" not in ents  # venue, izlenen değil


def test_registry_missing(registry: VcFundRegistry, tmp_path) -> None:
    assert registry.lookup("0xdead") is None
    assert registry.lookup(None) is None
    assert len(VcFundRegistry.from_file(tmp_path / "no.json")) == 0


# ── parse_vc_transfers: yön sınıflandırma ────────────────────────────────────


def _tx(frm: str, to: str, token: str = "FOO", value: str = str(10**18), ts: str = "1700000000") -> dict:
    return {"hash": "h", "from": frm, "to": to, "value": value, "tokenDecimal": "18",
            "tokenSymbol": token, "timeStamp": ts}


def test_parse_acquire(registry: VcFundRegistry) -> None:
    payload = {"result": [_tx(_OUTSIDER, _A16Z)]}
    tr = parse_vc_transfers(payload, registry, price_usd=200_000.0)
    assert len(tr) == 1
    assert tr[0].direction == DIR_ACQUIRE
    assert tr[0].vc_entity == "a16z Crypto"
    assert tr[0].is_acquire is True


def test_parse_distribute_dex(registry: VcFundRegistry) -> None:
    payload = {"result": [_tx(_A16Z, _UNIV2)]}
    tr = parse_vc_transfers(payload, registry, price_usd=200_000.0)
    assert tr[0].direction == DIR_DISTRIBUTE_DEX
    assert tr[0].is_distribute is True


def test_parse_distribute_cex(registry: VcFundRegistry) -> None:
    payload = {"result": [_tx(_JUMP, _BINANCE)]}
    tr = parse_vc_transfers(payload, registry, price_usd=200_000.0)
    assert tr[0].direction == DIR_DISTRIBUTE_CEX


def test_parse_distribute_other(registry: VcFundRegistry) -> None:
    payload = {"result": [_tx(_A16Z, _OUTSIDER)]}
    tr = parse_vc_transfers(payload, registry, price_usd=200_000.0)
    assert tr[0].direction == DIR_DISTRIBUTE


def test_parse_skips_non_vc(registry: VcFundRegistry) -> None:
    payload = {"result": [_tx(_OUTSIDER, "0xanother")]}
    assert parse_vc_transfers(payload, registry, price_usd=200_000.0) == []


def test_parse_zero_price_skips(registry: VcFundRegistry) -> None:
    assert parse_vc_transfers({"result": [_tx(_OUTSIDER, _A16Z)]}, registry, price_usd=0.0) == []


def test_parse_invalid(registry: VcFundRegistry) -> None:
    assert parse_vc_transfers("x", registry, price_usd=1.0) == []
    assert parse_vc_transfers({"result": "bad"}, registry, price_usd=1.0) == []
    assert parse_vc_transfers(None, registry, price_usd=1.0) == []


def test_parse_post_unlock_flag(registry: VcFundRegistry) -> None:
    unlock_ts = 1_700_000_000_000
    # distribute 1 gün sonra → post_unlock True
    payload = {"result": [_tx(_A16Z, _UNIV2, token="LOCKD", ts=str(1_700_000_000 + 86_400))]}
    tr = parse_vc_transfers(
        payload, registry, price_usd=200_000.0,
        unlock_events={"LOCKD": unlock_ts}, unlock_window_ms=3 * _DAY,
    )
    assert tr[0].is_post_unlock is True


def test_parse_post_unlock_outside_window(registry: VcFundRegistry) -> None:
    unlock_ts = 1_700_000_000_000
    payload = {"result": [_tx(_A16Z, _UNIV2, token="LOCKD", ts=str(1_700_000_000 + 10 * 86_400))]}
    tr = parse_vc_transfers(
        payload, registry, price_usd=200_000.0,
        unlock_events={"LOCKD": unlock_ts}, unlock_window_ms=3 * _DAY,
    )
    assert tr[0].is_post_unlock is False


# ── Net flow / conviction ─────────────────────────────────────────────────────


def _mk(entity: str, token: str, amount: float, direction: str) -> VcTransfer:
    return VcTransfer(tx_hash="h", vc_entity=entity, vc_type="vc", token=token,
                      amount_usd=amount, direction=direction)


def test_compute_net_flow() -> None:
    tr = [
        _mk("a16z", "FOO", 5e6, DIR_ACQUIRE),
        _mk("paradigm", "FOO", 2e6, DIR_ACQUIRE),
        _mk("a16z", "BAR", 3e6, DIR_DISTRIBUTE_DEX),
    ]
    assert compute_vc_net_flow_usd(tr) == pytest.approx(5e6 + 2e6 - 3e6)


def test_token_conviction() -> None:
    tr = [
        _mk("a16z", "FOO", 1e6, DIR_ACQUIRE),
        _mk("paradigm", "FOO", 1e6, DIR_ACQUIRE),
        _mk("a16z", "BAR", 1e6, DIR_DISTRIBUTE),
    ]
    c = token_conviction(tr)
    assert c["FOO"] == 2
    assert c["BAR"] == 0  # net dağıtım → conviction yok


def test_conviction_net_negative_excluded() -> None:
    # aynı VC hem alıp hem satıyor, net negatif → conviction sayılmaz
    tr = [
        _mk("a16z", "FOO", 1e6, DIR_ACQUIRE),
        _mk("a16z", "FOO", 3e6, DIR_DISTRIBUTE_DEX),
    ]
    assert token_conviction(tr)["FOO"] == 0


# ── analyze: 3 sinyal kuralı ─────────────────────────────────────────────────


def test_analyze_early_alpha() -> None:
    trk = VcFundTracker(min_usd=100_000)
    sig = trk.analyze([_mk("a16z", "FOO", 500_000, DIR_ACQUIRE)])
    assert any("early alpha" in r for r in sig.reasons)
    assert sig.alpha_tokens["FOO"] == pytest.approx(500_000)


def test_analyze_bulk_sell_risk() -> None:
    trk = VcFundTracker(bulk_sell_usd=5e6)
    sig = trk.analyze([_mk("jump", "BAR", 6e6, DIR_DISTRIBUTE_CEX)])
    assert any("toplu satış" in r for r in sig.reasons)
    assert sig.vc_net_flow_usd < 0


def test_analyze_conviction() -> None:
    trk = VcFundTracker(conviction_min=2, min_usd=1)
    sig = trk.analyze([
        _mk("a16z", "FOO", 1e6, DIR_ACQUIRE),
        _mk("paradigm", "FOO", 1e6, DIR_ACQUIRE),
    ])
    assert any("conviction" in r for r in sig.reasons)
    assert sig.conviction["FOO"] == 2


# ── Fetch ─────────────────────────────────────────────────────────────────────


def test_fetch_no_key(registry: VcFundRegistry, monkeypatch) -> None:
    monkeypatch.delenv("ETHERSCAN_API_KEY", raising=False)
    trk = VcFundTracker(registry=registry, http_get=lambda u, t: "x")
    assert trk._fetch_transfers(price_usd=100.0) == []


def test_fetch_zero_price(registry: VcFundRegistry, monkeypatch) -> None:
    monkeypatch.setenv("ETHERSCAN_API_KEY", "k")
    monkeypatch.setenv("ETHERSCAN_API_URL", "http://x")
    trk = VcFundTracker(registry=registry, http_get=lambda u, t: "x")
    assert trk._fetch_transfers(price_usd=0.0) == []


def test_fetch_injected(registry: VcFundRegistry, monkeypatch) -> None:
    monkeypatch.setenv("ETHERSCAN_API_KEY", "k")
    monkeypatch.setenv("ETHERSCAN_API_URL", "http://x")
    payload = {"result": [_tx(_OUTSIDER, _A16Z)]}
    trk = VcFundTracker(registry=registry, http_get=lambda u, t: json.dumps(payload))
    assert len(trk._fetch_transfers(price_usd=200_000.0)) == 1


# ── Alerts ────────────────────────────────────────────────────────────────────


def test_alert_early_alpha() -> None:
    trk = VcFundTracker(min_usd=100_000)
    sig = trk.analyze([_mk("a16z", "FOO", 500_000, DIR_ACQUIRE)])
    assert "EARLY_ALPHA" in trk.detect_alerts(sig, [])


def test_alert_bulk_sell() -> None:
    trk = VcFundTracker(bulk_sell_usd=5e6)
    sig = trk.analyze([_mk("jump", "BAR", 6e6, DIR_DISTRIBUTE_CEX)])
    assert "VC_BULK_SELL" in trk.detect_alerts(sig, [])


def test_alert_conviction() -> None:
    trk = VcFundTracker(conviction_min=2, min_usd=1)
    sig = trk.analyze([_mk("a16z", "F", 1e6, DIR_ACQUIRE), _mk("paradigm", "F", 1e6, DIR_ACQUIRE)])
    assert "CONVICTION" in trk.detect_alerts(sig, [])


def test_alert_post_unlock_dump() -> None:
    trk = VcFundTracker()
    sig = trk.analyze([])
    post = VcTransfer("h", "a16z", "vc", "LOCK", 1e6, DIR_DISTRIBUTE_DEX, is_post_unlock=True)
    assert "POST_UNLOCK_DUMP" in trk.detect_alerts(sig, [post])


def test_alert_none() -> None:
    trk = VcFundTracker(min_usd=1e9, bulk_sell_usd=1e9, conviction_min=99)
    assert trk.detect_alerts(trk.analyze([_mk("a16z", "F", 1e3, DIR_ACQUIRE)]), []) == []


# ── Dispatch ─────────────────────────────────────────────────────────────────


class _FakeAlertManager:
    def __init__(self) -> None:
        self.events = []

    def system(self, event: str, detail: str = "", level: str = "INFO") -> None:
        self.events.append((event, detail, level))


def test_dispatch() -> None:
    am = _FakeAlertManager()
    trk = VcFundTracker(alert_manager=am)
    trk._dispatch_alerts(["VC_BULK_SELL", "EARLY_ALPHA"])
    assert ("VC_VC_BULK_SELL", "VC_BULK_SELL", "WARNING") in am.events
    assert ("VC_EARLY_ALPHA", "EARLY_ALPHA", "INFO") in am.events


def test_dispatch_none_and_bad() -> None:
    VcFundTracker()._dispatch_alerts(["X"])
    VcFundTracker(alert_manager=object())._dispatch_alerts(["X"])


# ── should_update / update / Faz 17 ──────────────────────────────────────────


def test_should_update() -> None:
    trk = VcFundTracker(update_interval_sec=300)
    assert trk.should_update(now_ms=10**13) is True
    trk._last_update_ms = 10**13
    assert trk.should_update(now_ms=10**13 + 100_000) is False
    assert trk.should_update(now_ms=10**13 + 301_000) is True


def test_update_produces_faz17_data(registry: VcFundRegistry, monkeypatch) -> None:
    monkeypatch.setenv("ETHERSCAN_API_KEY", "k")
    monkeypatch.setenv("ETHERSCAN_API_URL", "http://x")
    payload = {"result": [_tx(_OUTSIDER, _A16Z)]}
    trk = VcFundTracker(registry=registry, http_get=lambda u, t: json.dumps(payload), min_usd=1)
    data = trk.update(price_usd=200_000.0)
    assert "vc_net_flow_usd" in data
    assert data["vc_net_flow_usd"] == pytest.approx(200_000.0)


def test_run_vc_fund_phase_faz17(registry: VcFundRegistry, monkeypatch) -> None:
    monkeypatch.setenv("ETHERSCAN_API_KEY", "k")
    monkeypatch.setenv("ETHERSCAN_API_URL", "http://x")
    payload = {"result": [_tx(_OUTSIDER, _A16Z)]}
    trk = VcFundTracker(registry=registry, http_get=lambda u, t: json.dumps(payload), min_usd=1)
    out = run_vc_fund_phase("ETHUSDT", trk, {}, price_usd=200_000.0)
    assert {"alpha_score", "risk_score", "trade_permission"}.issubset(out.keys())
    assert out["trade_permission"] in ("ALLOW", "BLOCK", "HALT")
    assert out["phase"] == "17"


def test_run_phase_empty(registry: VcFundRegistry, monkeypatch) -> None:
    monkeypatch.delenv("ETHERSCAN_API_KEY", raising=False)
    trk = VcFundTracker(registry=registry, http_get=lambda u, t: None)
    out = run_vc_fund_phase("ETHUSDT", trk, {})
    assert out["trade_permission"] in ("ALLOW", "BLOCK", "HALT")


def test_env_config(monkeypatch) -> None:
    monkeypatch.setenv("VC_MIN_USD", "250000")
    monkeypatch.setenv("VC_BULK_SELL_USD", "8000000")
    monkeypatch.setenv("VC_CONVICTION_MIN", "3")
    trk = VcFundTracker()
    assert trk.min_usd == 250_000.0
    assert trk.bulk_sell_usd == 8_000_000.0
    assert trk.conviction_min == 3
