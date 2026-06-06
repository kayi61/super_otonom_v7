"""Binance testnet preflight teshisi testleri — gercek ag YOK (handler enjekte edilir)."""
from __future__ import annotations

from super_otonom.infra import binance_testnet_preflight as pf

_LONG = "K" * 40
_LONG2 = "S" * 40


class _FakeHandler:
    def __init__(self, bal=None, exc=None):
        self._bal = bal
        self._exc = exc
        self.closed = False

    async def fetch_balance(self):
        if self._exc is not None:
            raise self._exc
        return self._bal

    async def close(self):
        self.closed = True


def _factory(bal=None, exc=None):
    return lambda k, s: _FakeHandler(bal=bal, exc=exc)


# ── mask ───────────────────────────────────────────────────────────────────


def test_mask_empty():
    assert pf.mask("") == "<bos>"


def test_mask_short_fully_hidden():
    assert "gizli" in pf.mask("abc")


def test_mask_long_shows_ends_and_len():
    m = pf.mask("ABCDEFGHIJ")
    assert m.startswith("AB") and m.endswith("(10 char)")
    assert "CDEFGH" not in m  # ortasi gizli


# ── classify_key ───────────────────────────────────────────────────────────


def test_classify_empty():
    ok, reason = pf.classify_key("", "")
    assert ok is False and "BOS" in reason


def test_classify_one_char_bug():
    # KOK SEBEP: getpass paste sadece 1 char yakaladi.
    ok, reason = pf.classify_key("K", "S")
    assert ok is False and "COK KISA" in reason


def test_classify_whitespace():
    ok, reason = pf.classify_key(" " + _LONG, _LONG2)
    assert ok is False and "bosluk" in reason


def test_classify_valid():
    ok, reason = pf.classify_key(_LONG, _LONG2)
    assert ok is True


# ── diagnose_error ─────────────────────────────────────────────────────────


def test_diagnose_2014():
    assert "-2014" in pf.diagnose_error(Exception("binance {'code':-2014,'msg':'API-key format invalid'}"))


def test_diagnose_2015():
    assert "-2015" in pf.diagnose_error(Exception("Invalid API-key, IP, or permissions (-2015)"))


def test_diagnose_auth_by_type():
    class AuthenticationError(Exception):
        pass

    assert "Kimlik" in pf.diagnose_error(AuthenticationError("bad signature"))


def test_diagnose_network():
    class NetworkError(Exception):
        pass

    assert "Ag" in pf.diagnose_error(NetworkError("getaddrinfo failed"))


def test_diagnose_permission():
    class PermissionDenied(Exception):
        pass

    assert "Izin" in pf.diagnose_error(PermissionDenied("denied"))


def test_diagnose_unknown():
    assert "Bilinmeyen" in pf.diagnose_error(ValueError("weird"))


# ── probe_testnet (gercek ag yok, handler enjekte) ─────────────────────────


async def test_probe_success():
    ok, reason, usdt = await pf.probe_testnet(
        _LONG, _LONG2, handler_factory=_factory(bal={"total": {"USDT": 1234.5}})
    )
    assert ok is True and usdt == 1234.5


async def test_probe_auth_fail():
    ok, reason, usdt = await pf.probe_testnet(
        _LONG, _LONG2, handler_factory=_factory(exc=Exception("Invalid API-key (-2015)"))
    )
    assert ok is False and "-2015" in reason and usdt is None


async def test_probe_closes_handler():
    h = _FakeHandler(bal={"total": {"USDT": 1.0}})
    await pf.probe_testnet(_LONG, _LONG2, handler_factory=lambda k, s: h)
    assert h.closed is True


# ── run_preflight (uctan uca, env + enjekte handler) ───────────────────────


async def test_run_preflight_no_key(monkeypatch):
    for k in ("SEED_API_KEY", "SEED_API_SECRET", "BINANCE_API_KEY", "BINANCE_API_SECRET"):
        monkeypatch.delenv(k, raising=False)
    res = await pf.run_preflight(from_env=True, handler_factory=_factory(bal={}))
    assert res.ok is False and res.stage == "resolve"


async def test_run_preflight_one_char_bug(monkeypatch):
    monkeypatch.setenv("SEED_API_KEY", "K")
    monkeypatch.setenv("SEED_API_SECRET", "S")
    res = await pf.run_preflight(from_env=True, handler_factory=_factory(bal={}))
    assert res.ok is False and res.stage == "validate" and "COK KISA" in res.reason


async def test_run_preflight_probe_success(monkeypatch):
    monkeypatch.setenv("SEED_API_KEY", _LONG)
    monkeypatch.setenv("SEED_API_SECRET", _LONG2)
    res = await pf.run_preflight(
        from_env=True, handler_factory=_factory(bal={"total": {"USDT": 5000.0}})
    )
    assert res.ok is True and res.stage == "probe" and res.usdt == 5000.0


async def test_run_preflight_probe_auth_fail(monkeypatch):
    monkeypatch.setenv("SEED_API_KEY", _LONG)
    monkeypatch.setenv("SEED_API_SECRET", _LONG2)
    res = await pf.run_preflight(
        from_env=True, handler_factory=_factory(exc=Exception("API-key format invalid (-2014)"))
    )
    assert res.ok is False and res.stage == "probe" and "-2014" in res.reason


async def test_run_preflight_vault_path(monkeypatch):
    # Varsayilan yol: botun KULLANDIGI Vault cozumu (VaultBridge mock'lanir).
    class _VB:
        def __init__(self, *a, **k):
            pass

        def get_secret(self, exchange, key):
            return _LONG if key == "api_key" else _LONG2

    monkeypatch.setattr("super_otonom.infra.vault_bridge.VaultBridge", _VB)
    res = await pf.run_preflight(
        from_env=False, handler_factory=_factory(bal={"total": {"USDT": 7.0}})
    )
    assert res.ok is True and res.usdt == 7.0


def test_result_render_masks_and_formats():
    r = pf.PreflightResult(True, "probe", "ok", key_info="AB…YZ (40 char)", usdt=10.0)
    txt = r.render()
    assert "PASS" in txt and "USDT=10.00" in txt and "AB…YZ" in txt


def test_ensure_vault_token_noop_when_already_set(monkeypatch):
    monkeypatch.setenv("VAULT_TOKEN", "zaten-var")
    pf._ensure_vault_token()
    import os as _os
    assert _os.environ["VAULT_TOKEN"] == "zaten-var"  # mevcut token degismedi


def test_sync_probe_uses_sandbox(monkeypatch):
    # _SyncTestnetProbe set_sandbox_mode(True) cagirmali (testnet'e yonlendir).
    calls = {}

    class _FakeCcxtEx:
        def __init__(self, cfg):
            calls["cfg"] = cfg

        def set_sandbox_mode(self, on):
            calls["sandbox"] = on

    import types
    fake_ccxt = types.SimpleNamespace(binance=lambda cfg: _FakeCcxtEx(cfg))
    monkeypatch.setitem(__import__("sys").modules, "ccxt", fake_ccxt)
    pf._SyncTestnetProbe("K" * 40, "S" * 40)
    assert calls["sandbox"] is True
    assert calls["cfg"]["options"]["adjustForTimeDifference"] is True


def test_main_returns_1_on_no_key(monkeypatch, capsys):
    for k in ("SEED_API_KEY", "SEED_API_SECRET", "BINANCE_API_KEY", "BINANCE_API_SECRET"):
        monkeypatch.delenv(k, raising=False)
    rc = pf.main(["--from-env"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "FAIL" in out and "seed" in out.lower()
