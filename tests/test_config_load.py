"""config modülü: anahtarlar ve tipler (smoke)."""

from __future__ import annotations

import super_otonom.config as cfg


def test_general_core_keys() -> None:
    assert "paper_mode" in cfg.GENERAL
    assert "default_exchange" in cfg.GENERAL
    assert isinstance(cfg.GENERAL["paper_mode"], bool)


def test_risk_and_mtf_struct() -> None:
    assert "max_daily_loss_pct" in cfg.RISK
    assert "timeframe" in cfg.MTF
    assert "enabled" in cfg.MTF
