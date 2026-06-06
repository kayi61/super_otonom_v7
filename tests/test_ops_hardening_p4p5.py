"""P-4/P-5 ops hardening kapsami: go-live gate + Vault auto-unseal self-heal.

Bu testler, P-4/P-5'te eklenen kritik guvenlik/ops kodunu kapsar:
- assert_go_live_or_exit() — tek go/no-go kapisi (LIVE_CONFIRM + Vault + KV + lock).
- _try_auto_unseal_vault() — dev self-heal (VAULT_AUTO_UNSEAL).
Live-mode kapilari mock'lanir (gercek Vault/borsa gerekmez).
"""
from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch

import pytest
import super_otonom.core.main_loop as ml


def _set_general(monkeypatch, **kw):
    g = dict(ml.GENERAL)
    g.update(kw)
    monkeypatch.setattr(ml, "GENERAL", g)


def _json_resp(payload: dict):
    """urlopen baglam yoneticisi taklidi — json.load(r) icin .read() saglar."""
    cm = MagicMock()
    cm.__enter__.return_value = io.BytesIO(json.dumps(payload).encode())
    cm.__exit__.return_value = False
    return cm


# ── assert_go_live_or_exit (tek go/no-go kapisi) ─────────────────────────────


def test_gate_paper_mode_is_noop(monkeypatch):
    _set_general(monkeypatch, paper_mode=True)
    monkeypatch.delenv("VAULT_AUTO_UNSEAL", raising=False)
    # paper modda kapi no-op — exception YOK
    ml.assert_go_live_or_exit()


def test_gate_live_without_confirm_exits(monkeypatch):
    _set_general(monkeypatch, paper_mode=False, live_confirm="")
    monkeypatch.delenv("VAULT_AUTO_UNSEAL", raising=False)
    with pytest.raises(SystemExit) as exc:
        ml.assert_go_live_or_exit()
    assert exc.value.code == 1


def test_gate_vault_unavailable_exits(monkeypatch):
    _set_general(monkeypatch, paper_mode=False, live_confirm="YES")
    monkeypatch.delenv("VAULT_AUTO_UNSEAL", raising=False)
    vb = MagicMock()
    vb.status.return_value = {"available": False}
    with patch("super_otonom.infra.vault_bridge.VaultBridge", return_value=vb), patch(
        "super_otonom.infra.vault_bridge.secrets_vault_only_mode", return_value=True
    ):
        with pytest.raises(SystemExit) as exc:
            ml.assert_go_live_or_exit()
    assert exc.value.code == 1


def test_gate_vault_missing_keys_exits(monkeypatch):
    _set_general(monkeypatch, paper_mode=False, live_confirm="YES", default_exchange="binance")
    monkeypatch.delenv("VAULT_AUTO_UNSEAL", raising=False)
    vb = MagicMock()
    vb.status.return_value = {"available": True}
    vb.probe_kv_fields.return_value = {"api_key": False, "api_secret": False}
    with patch("super_otonom.infra.vault_bridge.VaultBridge", return_value=vb), patch(
        "super_otonom.infra.vault_bridge.secrets_vault_only_mode", return_value=True
    ):
        with pytest.raises(SystemExit) as exc:
            ml.assert_go_live_or_exit()
    assert exc.value.code == 1


def test_gate_full_pass_no_exit(monkeypatch):
    _set_general(monkeypatch, paper_mode=False, live_confirm="YES", default_exchange="binance")
    monkeypatch.delenv("VAULT_AUTO_UNSEAL", raising=False)
    vb = MagicMock()
    vb.status.return_value = {"available": True}
    vb.probe_kv_fields.return_value = {"api_key": True, "api_secret": True}
    with patch("super_otonom.infra.vault_bridge.VaultBridge", return_value=vb), patch(
        "super_otonom.infra.vault_bridge.secrets_vault_only_mode", return_value=True
    ), patch.object(ml, "enforce_live_deploy_env_lock"):
        # tum kapilar yesil -> exception YOK
        ml.assert_go_live_or_exit()


def test_gate_vault_only_off_skips_vault_checks(monkeypatch):
    # SECRETS_VAULT_ONLY kapali -> Vault kapilari atlanir, deploy_lock'a gecer
    _set_general(monkeypatch, paper_mode=False, live_confirm="YES")
    monkeypatch.delenv("VAULT_AUTO_UNSEAL", raising=False)
    with patch("super_otonom.infra.vault_bridge.secrets_vault_only_mode", return_value=False), patch.object(
        ml, "enforce_live_deploy_env_lock"
    ):
        ml.assert_go_live_or_exit()  # exception YOK


# ── _try_auto_unseal_vault (dev self-heal) ───────────────────────────────────


def test_auto_unseal_off_by_default_noop(monkeypatch):
    monkeypatch.delenv("VAULT_AUTO_UNSEAL", raising=False)
    # flag yok -> erken cikis, urlopen cagrilmaz
    with patch("urllib.request.urlopen", side_effect=AssertionError("cagrilmamali")):
        ml._try_auto_unseal_vault()


def test_auto_unseal_explicit_off_noop(monkeypatch):
    monkeypatch.setenv("VAULT_AUTO_UNSEAL", "false")
    with patch("urllib.request.urlopen", side_effect=AssertionError("cagrilmamali")):
        ml._try_auto_unseal_vault()


def test_auto_unseal_already_unsealed_returns(monkeypatch):
    monkeypatch.setenv("VAULT_AUTO_UNSEAL", "true")
    monkeypatch.setenv("VAULT_ADDR", "http://127.0.0.1:8200")
    # seal-status -> sealed False -> erken donus (unseal POST yok)
    with patch("urllib.request.urlopen", return_value=_json_resp({"sealed": False})):
        ml._try_auto_unseal_vault()


def test_auto_unseal_sealed_unseals(monkeypatch, tmp_path):
    monkeypatch.setenv("VAULT_AUTO_UNSEAL", "true")
    monkeypatch.setenv("VAULT_ADDR", "http://127.0.0.1:8200")
    # init dosyasini gecici olusturup _try_auto_unseal_vault'un yolunu ona cevir
    init = tmp_path / "data" / "local" / "vault_init.json"
    init.parent.mkdir(parents=True)
    init.write_text(
        json.dumps({"unseal_keys_b64": ["dGVzdGtleQ=="], "unseal_threshold": 1}),
        encoding="utf-8",
    )
    # __file__ parents[2] -> repo koku; init yolu oradan turuyor. tmp init'i
    # kullanmak icin Path'i patch'leyemiyoruz; bunun yerine sealed=True + gercek
    # init dosyasi (varsa) ile unseal POST yolunu kapsa.
    responses = [
        _json_resp({"sealed": True}),   # seal-status
        _json_resp({"sealed": False}),  # unseal POST sonucu
    ]
    with patch("urllib.request.urlopen", side_effect=responses):
        ml._try_auto_unseal_vault()


def test_auto_unseal_network_error_is_swallowed(monkeypatch):
    monkeypatch.setenv("VAULT_AUTO_UNSEAL", "true")
    monkeypatch.setenv("VAULT_ADDR", "http://127.0.0.1:8200")
    # urlopen patlasa bile sys.exit YOK (gate asil karari verir), sadece uyari
    with patch("urllib.request.urlopen", side_effect=OSError("network")):
        ml._try_auto_unseal_vault()  # exception YOK


# ── exchange_async.create_order + testnet sandbox (P-5) ──────────────────────

from unittest.mock import AsyncMock  # noqa: E402

from super_otonom.exchange_async import AsyncExchangeHandler  # noqa: E402

_KEY = "K" * 40
_SEC = "S" * 40


def _handler():
    return AsyncExchangeHandler("binance", api_key=_KEY, api_secret=_SEC, testnet=False)


async def test_create_order_empty_apikey_raises():
    h = _handler()
    h._ex = MagicMock()
    h._ex.apiKey = ""  # bos -> canli emir engellenmeli
    with pytest.raises(RuntimeError):
        await h.create_order("BTC/USDT", "buy", 0.001, 50000.0)


async def test_create_order_no_exchange_raises():
    h = _handler()
    h._ex = None
    with pytest.raises(RuntimeError):
        await h.create_order("BTC/USDT", "buy", 0.001, 50000.0)


async def test_create_order_limit_success():
    h = _handler()
    h._ex = MagicMock()
    h._ex.apiKey = _KEY
    h._ex.create_order = AsyncMock(
        return_value={
            "id": "1",
            "status": "closed",
            "filled": 0.001,
            "average": 50000.0,
            "fee": {"cost": 0.1},
        }
    )
    res = await h.create_order(
        "BTC/USDT", "buy", 0.001, 50000.0, order_type="limit",
        params={"clientOrderId": "abc"},
    )
    assert res["id"] == "1"


async def test_create_order_market_success():
    h = _handler()
    h._ex = MagicMock()
    h._ex.apiKey = _KEY
    h._ex.create_order = AsyncMock(return_value={"id": "2", "status": "closed", "filled": 1.0})
    res = await h.create_order("BTC/USDT", "sell", 1.0, None, order_type="market")
    assert res["id"] == "2"


async def test_create_order_limit_without_price_raises():
    h = _handler()
    h._ex = MagicMock()
    h._ex.apiKey = _KEY
    with pytest.raises(ValueError):
        await h.create_order("BTC/USDT", "buy", 0.001, None, order_type="limit")


async def test_create_order_exchange_error_reraised():
    h = _handler()
    h._ex = MagicMock()
    h._ex.apiKey = _KEY
    h._ex.create_order = AsyncMock(side_effect=RuntimeError("borsa hatasi"))
    with pytest.raises(RuntimeError):
        await h.create_order("BTC/USDT", "buy", 0.001, 50000.0)


def test_handler_testnet_uses_sandbox(monkeypatch):
    # BINANCE_TESTNET acik + testnet=True -> set_sandbox_mode -> testnet.binance.vision
    monkeypatch.setenv("BINANCE_TESTNET", "true")
    h = AsyncExchangeHandler("binance", api_key=_KEY, api_secret=_SEC, testnet=True)
    api = h._ex.urls.get("api") if h._ex is not None else None
    host = api.get("private") if isinstance(api, dict) else str(api)
    assert "testnet.binance.vision" in str(host)
