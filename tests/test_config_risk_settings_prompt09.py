"""PROMPT-09 — config lazy init + RiskSettings."""

from __future__ import annotations

import warnings

import pytest

pytestmark = pytest.mark.fastrun


def test_risk_access_triggers_meta_log_once(monkeypatch: pytest.MonkeyPatch) -> None:
    import super_otonom.core.config_meta as cm

    cm.reset_meta_advisory_log_flag()
    monkeypatch.setenv("META_REGIME_MODE", "shadow")

    from super_otonom.config import RISK, get_risk_settings

    _ = RISK["max_daily_loss_pct"]
    assert cm._META_ADVISORY_LOGGED is True
    s1 = get_risk_settings()
    s2 = get_risk_settings()
    assert s1.max_daily_loss_pct == s2.max_daily_loss_pct


def test_risk_settings_frozen_and_accessor() -> None:
    from super_otonom.config import get_risk_settings, risk

    s = get_risk_settings()
    assert s.max_position_pct == risk.max_position_pct
    assert s.min_notional > 0


def test_risk_dict_override_deprecated() -> None:
    from super_otonom.config import RISK, get_risk_settings

    orig = RISK["trailing_stop_pct"]
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        RISK["trailing_stop_pct"] = 0.02
        assert any(issubclass(x.category, DeprecationWarning) for x in w)
    assert get_risk_settings().trailing_stop_pct == pytest.approx(0.02)
    RISK["trailing_stop_pct"] = orig


def test_bot_patch_registry_exports() -> None:
    import super_otonom.bot_patch_registry as reg

    assert callable(reg.enforce_entry_prechecks)
    assert callable(reg.compute_signal_quality)


def test_config_load_smoke() -> None:
    import super_otonom.config as cfg

    assert "max_daily_loss_pct" in cfg.RISK
    assert cfg.get_risk_settings().max_open_positions >= 1
