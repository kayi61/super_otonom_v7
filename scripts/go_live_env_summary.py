#!/usr/bin/env python3
"""Ortam ozeti (sır yok) — fastrun_go_live."""

from __future__ import annotations

import os

from super_otonom.config import EXCHANGES, GENERAL, RISK


def main() -> int:
    ex_id = str(GENERAL.get("default_exchange") or "binance")
    ex = EXCHANGES.get(ex_id, {})
    print("DRY_RUN=", GENERAL.get("dry_run"))
    print("PAPER_MODE=", GENERAL.get("paper_mode"))
    print("LIVE_CONFIRM=", repr(GENERAL.get("live_confirm")))
    print("DEFAULT_EXCHANGE=", ex_id)
    print("venue_testnet=", ex.get("testnet"))
    print("SECRETS_VAULT_ONLY=", os.getenv("SECRETS_VAULT_ONLY", ""))
    print("META_REGIME_MODE=", os.getenv("META_REGIME_MODE", "shadow"))
    print("max_daily_loss_pct=", RISK.get("max_daily_loss_pct"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
